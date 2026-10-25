"""Render MusicXML to reference audio and measure-indexed alignment data."""

import json
import math
import wave
from pathlib import Path
from xml.etree import ElementTree

import numpy as np
from music21 import chord, converter, instrument, repeat, stream, tempo

from .expression import apply_expression
from .validation import inspect_score
from .repairs import repair_score
from .tuplets import inspect_tuplets, read_xml


def synthesize(events, duration_seconds, sample_rate):
    audio = np.zeros(math.ceil(duration_seconds * sample_rate), dtype=np.float64)
    for event in events:
        start = round(event["start_seconds"] * sample_rate)
        stop = min(len(audio), round(event["end_seconds"] * sample_rate))
        t = np.arange(stop - start) / sample_rate
        frequency = 440 * 2 ** ((event["pitch"] - 69) / 12)
        signal = np.zeros(len(t))
        for harmonic, gain in [(1, 1), (2, 0.35), (3, 0.15), (4, 0.06)]:
            if frequency * harmonic < sample_rate / 2:
                signal += gain * np.sin(2 * np.pi * frequency * harmonic * t)
        envelope = np.minimum(t / 0.005, 1) * np.exp(-1.5 * t)
        envelope *= np.minimum((len(t) / sample_rate - t) / 0.02, 1)
        audio[start:stop] += signal * envelope * (event["velocity"] / 127) ** 2
    peak = np.max(np.abs(audio))
    if peak:
        audio *= 0.9 / peak
    pcm = np.rint(audio * 32767).astype("<i2")
    return pcm


def build_reference(
    source,
    output,
    *,
    bpm=120.0,
    measures_per_chunk=1,
    sample_rate=22050,
    render_audio=True,
):
    if (
        not math.isfinite(bpm)
        or bpm <= 0
        or measures_per_chunk < 1
        or sample_rate < 8000
    ):
        raise ValueError(
            "Use positive BPM, at least one measure per chunk, and sample rate >= 8000."
        )
    source, output = Path(source), Path(output)
    if source.suffix.lower() not in {".musicxml", ".xml", ".mxl"}:
        raise ValueError(
            "Input must be MusicXML (.musicxml, .xml, .mxl). Convert PDF/images with OMR first."
        )
    score = converter.parse(source, forceSource=True)
    source_issues = inspect_tuplets(source)
    original_issues = inspect_score(score)["issues"] + source_issues
    fixes = repair_score(score, source_issues)
    review = inspect_score(score)
    repaired_tuplets = {
        (fix["part"].split("-Staff")[0], str(fix["measure"]))
        for fix in fixes if fix["rule"] == "fragmented_tuplet"
    }
    review["issues"].extend(
        issue for issue in source_issues
        if (issue["part"], str(issue["measure"])) not in repaired_tuplets
    )
    review["applied_fixes"] = fixes
    review["original_issues"] = original_issues
    # Resolve wedges against the original hierarchy. Repeat expansion copies
    # notes and can leave spanner endpoints referring to detached originals.
    # The calculated note velocities are copied into each repeated measure.
    apply_expression(score)
    try:
        score = score.expandRepeats()
    except repeat.ExpanderException as error:
        raise ValueError(
            "The recognized score has incomplete repeat markings. Try a complete piece."
        ) from error
    parts = list(score.parts)
    if not parts:
        raise ValueError("Score must contain measured parts.")
    measures = list(parts[0].getElementsByClass(stream.Measure))
    if not measures:
        raise ValueError("Score has no measures.")
    end = float(score.highestTime)
    changes = {0.0: bpm}
    for mark in score.recurse().getElementsByClass(tempo.MetronomeMark):
        value = mark.getQuarterBPM()
        if value is not None:
            beat = float(mark.getOffsetInHierarchy(score))
            if not math.isfinite(value) or value <= 0:
                raise ValueError("Score contains invalid tempo.")
            if beat in changes and beat != 0 and changes[beat] != value:
                continue  # parts disagree; keep the mark seen first (the top staff)
            changes[beat] = value
    tempi = sorted(changes.items())
    if not any(
        float(mark.getOffsetInHierarchy(score)) == 0
        for mark in score.recurse().getElementsByClass(tempo.MetronomeMark)
    ):
        score.insert(0, tempo.MetronomeMark(number=bpm))

    def seconds(beat):
        result = 0.0
        for i, (start, rate) in enumerate(tempi):
            stop = tempi[i + 1][0] if i + 1 < len(tempi) else beat
            if beat <= start:
                break
            result += (min(beat, stop) - start) * 60 / rate
        return result

    events = []
    # Grace notes take no time in the notation, so they are not timed reference events. They are
    # kept as ornaments (the onset of the note they decorate, and their pitches) so a comparison
    # can recognise them in a performance instead of calling them wrong or extra notes.
    ornaments = []
    for pi, part in enumerate(parts):
        tied = part.stripTies()
        for element in tied.recurse().notes:
            onset = float(element.getOffsetInHierarchy(tied)) + float(part.offset)
            duration = float(element.quarterLength)
            if duration <= 0:
                pitches = element.pitches if isinstance(element, chord.Chord) else [element.pitch]
                ornaments.extend({"onset": onset, "pitch": p.midi, "part": str(part.id or pi)}
                                 for p in pitches if p.ps == p.midi)
                continue
            pitches = (
                element.pitches if isinstance(element, chord.Chord) else [element.pitch]
            )
            measure = element.getContextByClass(stream.Measure)
            voice = element.getContextByClass(stream.Voice)
            for pitch in pitches:
                if pitch.ps != pitch.midi:
                    raise ValueError("Microtonal pitches are unsupported.")
                events.append(
                    {
                        "id": f"n{len(events):06d}",
                        "pitch": pitch.midi,
                        "velocity": element.volume.velocity or 72,
                        "tuplets": [
                            {"actual": t.numberNotesActual, "normal": t.numberNotesNormal}
                            for t in element.duration.tuplets
                        ],
                        "onset": onset,
                        "duration": duration,
                        "source": "score",
                        "measure": measure.number if measure else None,
                        "beat_in_measure": float(element.beat),
                        "part": str(part.id or pi),
                        "voice": str(voice.id) if voice else None,
                        "start_seconds": seconds(onset),
                        "end_seconds": seconds(onset + duration),
                    }
                )
    if not events:
        raise ValueError("Score contains no sounding notes.")
    events.sort(key=lambda n: (n["onset"], n["pitch"], n["id"]))
    sample_count = math.ceil(seconds(end) * sample_rate)
    pcm = synthesize(events, seconds(end), sample_rate) if render_audio else None
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty.")

    def write_wav(path, samples):
        with wave.open(str(path), "wb") as handle:
            handle.setparams((1, 2, sample_rate, 0, "NONE", "not compressed"))
            handle.writeframes(samples.tobytes())

    if render_audio:
        write_wav(output / "reference.wav", pcm)
    for part in parts:
        for existing in list(part.recurse().getElementsByClass(instrument.Instrument)):
            existing.midiProgram = 0
        part.insert(0, instrument.Piano())
    ElementTree.ElementTree(read_xml(source)).write(
        output / "original.musicxml", encoding="utf-8", xml_declaration=True
    )
    (output / "repairs.json").write_text(json.dumps(review, indent=2) + "\n")
    score.write("midi", fp=output / "reference.mid")
    try:
        score.write("musicxml", fp=output / "reference.musicxml", makeNotation=False)
    except Exception:  # complex durations left by repairs; let music21 re-notate them
        try:
            score.write("musicxml", fp=output / "reference.musicxml", makeNotation=True)
        except Exception:
            # The notation file is only drawn on screen and read for title, key and metre. If the
            # repaired score cannot be written out, show the original notation rather than fail.
            import shutil
            shutil.copyfile(output / "original.musicxml", output / "reference.musicxml")
            review.setdefault("notes", []).append("Notation shown as uploaded: the repaired score could not be exported.")
            (output / "repairs.json").write_text(json.dumps(review, indent=2) + "\n")
    chunks = []
    for index in range(0, len(measures), measures_per_chunk):
        group = measures[index : index + measures_per_chunk]
        start = float(group[0].offset) + float(parts[0].offset)
        next_index = index + measures_per_chunk
        stop = (
            float(measures[next_index].offset) + float(parts[0].offset)
            if next_index < len(measures)
            else end
        )
        a = round(seconds(start) * sample_rate)
        b = (
            round(seconds(stop) * sample_rate)
            if next_index < len(measures)
            else sample_count
        )
        filename = f"chunk_{len(chunks):04d}.wav"
        if render_audio:
            write_wav(output / filename, pcm[a:b])
        active = [
            n
            for n in events
            if n["onset"] < stop and n["onset"] + n["duration"] > start
        ]
        chunks.append(
            {
                "id": len(chunks),
                "file": filename if render_audio else None,
                "measure_occurrence": index,
                "measures": [m.number for m in group],
                "start_beat": start,
                "end_beat": stop,
                "start_sample": a,
                "end_sample": b,
                "start_seconds": a / sample_rate,
                "end_seconds": b / sample_rate,
                "notes": [
                    {
                        "note_id": n["id"],
                        "onset_beat": n["onset"] - start,
                        "onset_seconds": n["start_seconds"] - a / sample_rate,
                        "carried_in": n["onset"] < start,
                    }
                    for n in active
                ],
            }
        )
    manifest = {
        "schema_version": 3,
        "review": review,
        "source": str(source.resolve()),
        "time_unit": "quarter_note",
        "sample_rate": sample_rate,
        "audio": "reference.wav" if render_audio else None,
        "synthesis": "deterministic harmonic reference; no pedal",
        "duration_seconds": sample_count / sample_rate,
        "tempo_changes": tempi,
        "notes": events,
        "ornaments": [dict(o, start_seconds=seconds(o["onset"])) for o in ornaments],
        "chunks": chunks,
        "alignment_hint": "Align onset/pitch sequences monotonically with DTW or score following; fit local beat-to-second maps. Do not slice performance at reference timestamps.",
    }
    (output / "reference.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
