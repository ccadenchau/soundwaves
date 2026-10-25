"""Score + performance in, page report out. Reuses a converted score when it is already there."""

import json
import shutil
from pathlib import Path

from alignment import align_performance  # noqa: F401 - re-exported for callers
from sheet_downloader import convert_score

from .clean import clean_notes
from .report import build_ui_report
from .scoreprep import prepare_reference

_TRANSKUN = None
MIN_NOTES = 4


class TooFewNotes(ValueError):
    """The take holds too little to compare with the score. The message is written for the student."""


def _check_enough(count, *, audio):
    if count >= MIN_NOTES:
        return
    if count == 0:
        raise TooFewNotes('No notes were heard in that recording. Check that the browser is allowed to use the '
                          'microphone and that the piano is close to it, then record again.' if audio else
                          'No notes came in from the keyboard. Check the connection and try again.')
    raise TooFewNotes(f'Only {count} note{"s" if count != 1 else ""} came through. Play at least a few bars and try again.')


def transcriber(choice=None):
    """Pick the audio transcriber. PIANOCOACH_TRANSCRIBER=basic|transkun|auto (default auto:
    Transkun when its environment exists, else the bundled Basic Pitch)."""
    import os
    global _TRANSKUN
    choice = (choice or os.environ.get('PIANOCOACH_TRANSCRIBER', 'auto')).lower()
    if choice == 'basic':
        return None
    from .transkun_backend import TranskunBackend
    if choice == 'transkun' or (choice == 'auto' and TranskunBackend.available()):
        if _TRANSKUN is None:
            _TRANSKUN = TranskunBackend()
        return _TRANSKUN
    return None


def prepare_for_transcription(audio, workdir, backend):
    """Piano-safe cleanup before transcription. Returns (path_to_transcribe, cleaning_used).

    PIANOCOACH_CLEAN=auto|on|off (default auto: clean only in front of Basic Pitch, which picks up
    room noise as notes; Transkun does as well on the raw recording). The cleaner keeps the full
    piano range and the exact timeline, and leaves already-quiet recordings untouched."""
    import os
    mode = os.environ.get('PIANOCOACH_CLEAN', 'auto').lower()
    if mode == 'off' or (mode == 'auto' and backend is not None):
        return Path(audio), 'none'
    from audio_cleaner.clean_audio import clean_audio
    target = Path(workdir) / 'cleaned_for_transcription.wav'
    clean_audio(audio, target, mode='piano')
    return target, 'piano'


AUDIO_SUFFIXES = {'.wav', '.mp3', '.m4a', '.aac', '.ogg', '.oga', '.webm', '.flac', '.aiff', '.aif', '.mp4', '.caf'}
MIDI_SUFFIXES = {'.mid', '.midi'}


def convert_once(score_path, directory, *, bpm=120):
    """Run the converter unless this directory already holds its output."""
    directory = Path(directory)
    reference = directory / 'reference'
    paths = dict(notes=reference / 'reference.json', musicxml=reference / 'reference.musicxml',
                 midi=reference / 'reference.mid', repairs=reference / 'repairs.json')
    if all(p.is_file() for p in paths.values()):
        return paths
    if directory.exists():
        shutil.rmtree(directory)
    result = convert_score(score_path, directory, bpm=bpm, measures_per_chunk=1)
    return dict(notes=result.notes, musicxml=result.musicxml, midi=result.midi, repairs=result.repairs)


def _window(reference, first, last):
    """A copy of the reference holding only measure occurrences first..last (inclusive).
    The aligner numbers occurrences by position, so they are renumbered from zero and the
    mapping back to the full score is returned alongside."""
    import copy
    chunks = [c for c in reference['chunks'] if first <= c['measure_occurrence'] <= last]
    start, end = chunks[0]['start_beat'], chunks[-1]['end_beat']
    sub = dict(reference)
    sub['notes'] = [n for n in reference['notes'] if start <= n['onset'] < end]
    sub['chunks'] = []
    mapping = {}
    for index, c in enumerate(chunks):
        c = copy.deepcopy(c)
        mapping[index] = c['measure_occurrence']
        c['measure_occurrence'] = index
        sub['chunks'].append(c)
    return sub, mapping


def locate_take(reference, played, *, config=None, full_fraction=0.6):
    """Find the stretch of the score a short take covers. Returns (first, last) measure
    occurrences, or None when the take is long enough to be the whole piece.

    The aligner matches pitch sequences monotonically with no sense of position, so a
    take of four bars against a 64-bar score gets its notes scattered over every bar
    that shares those pitches. Trying every window of about the right length and keeping
    the one that matches the most notes pins the take to one place first. Ties go to the
    earliest window (first pass of a repeat)."""
    from math import ceil
    from alignment.inputs import load_performance
    notes, _, _ = load_performance(played)
    chunks = reference['chunks']
    if not chunks or len(notes) >= full_fraction * len(reference['notes']):
        return None
    per_bar = len(reference['notes']) / len(chunks)
    length = max(2, min(len(chunks), ceil(len(notes) / per_bar * 1.4)))
    best = None
    for first in range(0, len(chunks) - length + 1):
        sub, _ = _window(reference, first, first + length - 1)
        if not sub['notes']:
            continue
        try:
            report = align_performance(sub, notes, config=config)
        except ValueError:
            continue
        metrics = report['metrics']
        score = metrics['correct_notes'] - 0.5 * (metrics['performed_notes'] - metrics['correct_notes'])
        if best is None or score > best[0] + 1e-9:
            best = (score, first, report)
    if best is None:
        return None
    _, first, report = best
    # Trim the window to the bars that actually matched, plus one bar after the
    # last for an ending the student may have started. The summary code assumes
    # playing begins at the window's first bar, so no lead-in bars are kept.
    # Re-align on the trimmed window until it stops shrinking: a wide window lets
    # the pitch-only aligner pin the last notes to identical pitches in later bars.
    window = (first, min(len(chunks) - 1, first + length - 1))
    for _ in range(4):
        hit = [b['occurrence'] for b in report['measures'] if b['correct_notes']]
        if not hit:
            return window
        trimmed = (window[0] + hit[0], min(len(chunks) - 1, window[0] + hit[-1] + 1))
        if trimmed == window:
            return window
        window = trimmed
        sub, _ = _window(reference, *window)
        try:
            report = align_performance(sub, notes, config=config)
        except ValueError:
            return window
    return window


def align_windowed(reference, performance, *, config=None):
    """Prepare the score, locate a short take inside it, align. Returns (alignment, prepared_reference).

    `reference` is a reference.json path or dictionary; `performance` is anything the aligner accepts.
    Occurrence numbers in the result refer to the full score even when only a window was aligned."""
    import json as _json
    data = _json.loads(Path(reference).read_text(encoding='utf-8')) if isinstance(reference, (str, Path)) else reference
    prepared, dropped = prepare_reference(data)
    window = locate_take(prepared, performance, config=config)
    if window is None:
        alignment = align_performance(prepared, performance, config=config)
    else:
        sub, mapping = _window(prepared, *window)
        alignment = align_performance(sub, performance, config=config)
        for m in alignment['matches'] + alignment['errors']:
            if m.get('measure_occurrence') is not None:
                m['measure_occurrence'] = mapping[m['measure_occurrence']]
        for b in alignment['measures']:
            b['occurrence'] = mapping[b['occurrence']]
        alignment['window'] = dict(first_occurrence=window[0], last_occurrence=window[1],
                                   bars=[c['measures'][0] for c in prepared['chunks'] if window[0] <= c['measure_occurrence'] <= window[1]])
    # Notes the student never reached are not "missing": keep a missing note only inside the bars that were played.
    from .report import _played_span
    span = _played_span(alignment, prepared['chunks'])
    if span is not None:
        before = len(alignment['errors'])
        alignment['errors'] = [e for e in alignment['errors'] if e['category'] != 'missing'
                               or e.get('measure_occurrence') is None or span[0] <= e['measure_occurrence'] <= span[1]]
        alignment['played_span'] = dict(first_occurrence=span[0], last_occurrence=span[1],
                                        unreached_missing_dropped=before - len(alignment['errors']))
    alignment['preprocessing'] = dict(alignment.get('preprocessing', {}), score_notes_merged=len(dropped),
                                      windowed=window is not None)
    return alignment, prepared


def align_clean(reference, performance, *, performance_notes=None, musicxml=None, piece=None,
                take_number=1, audio_duration=None, hands='right', config=None, drop_harmonics=False):
    """Prepare the score, locate a partial take, align, build the page report.
    Returns (alignment, ui_report)."""
    alignment, prepared = align_windowed(reference, performance, config=config)
    # Only Basic Pitch reports overtones as notes. A keyboard or Transkun note an octave above
    # another is a key the student really pressed, so it must not be filtered out.
    report = build_ui_report(prepared, alignment, performance_notes=performance_notes, musicxml=musicxml,
                             piece=piece, take_number=take_number, audio_duration=audio_duration, hands=hands,
                             drop_harmonics=drop_harmonics)
    return alignment, report


def analyze(score, performance, out_dir, *, bpm=120, take_number=1, piece=None, hands='right',
            explain=True, score_cache=None):
    """Return (ui_report, paths). `performance` is audio or a MIDI file.

    score_cache: directory to hold the converted score so repeated takes of the
    same piece skip conversion. Defaults to <out_dir>/score.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    score_paths = convert_once(score, score_cache or out / 'score', bpm=bpm)

    performance = Path(performance)
    suffix = performance.suffix.lower()
    cleaning, warnings = {}, []
    if suffix in MIDI_SUFFIXES:
        import pretty_midi
        midi = pretty_midi.PrettyMIDI(str(performance))
        duration = midi.get_end_time()
        _check_enough(sum(len(i.notes) for i in midi.instruments if not i.is_drum), audio=False)
        played, performance_notes = performance, None
        take_paths = dict(midi=performance)
    elif suffix in AUDIO_SUFFIXES or suffix == '':
        from transcribe_recording import transcribe_recording
        take_dir = out / 'take'
        if take_dir.exists():
            shutil.rmtree(take_dir)
        backend = transcriber()
        source, audio_cleaning = prepare_for_transcription(performance, out, backend)
        take = transcribe_recording(source, take_dir, backend=backend)
        duration = take.duration_seconds
        kept, cleaning = clean_notes(take.notes, harmonics=backend is None)
        _check_enough(len(kept), audio=True)
        cleaning['transcriber'] = backend.name if backend is not None else 'basic-pitch'
        cleaning['audio_cleaning'] = audio_cleaning
        if backend is not None:
            for n in kept:  # Transkun gives velocity, not confidence; treat its notes as sure
                n['model_score'] = 0.9
        warnings = list(take.warnings)
        played, performance_notes = kept, kept
        take_paths = dict(midi=take.midi_path, notes=take.notes_path)
    else:
        raise ValueError(f'Unsupported performance file: {performance.name}')

    alignment, report = align_clean(score_paths['notes'], played, performance_notes=performance_notes,
                                    musicxml=score_paths['musicxml'], piece=piece, take_number=take_number,
                                    audio_duration=duration, hands=hands,
                                    drop_harmonics=(False if suffix in MIDI_SUFFIXES
                                                    else True if cleaning.get('transcriber') == 'basic-pitch' else 'octave'))
    alignment['preprocessing'].update(cleaning)
    alignment.setdefault('warnings', []).extend(warnings)
    if explain:
        from .explain import explain_report
        report = explain_report(report)

    (out / 'alignment.json').write_text(json.dumps(alignment, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    (out / 'report.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    paths = dict(report=out / 'report.json', alignment=out / 'alignment.json', score=score_paths, take=take_paths)
    return report, paths


def main(argv):
    import argparse
    import json as _json
    parser = argparse.ArgumentParser(description='Score + recording (or MIDI) -> report.json for the practice page.')
    parser.add_argument('score', help='PDF, MusicXML, XML or MXL')
    parser.add_argument('performance', help='WAV/MP3/M4A/WebM audio, or a .mid file')
    parser.add_argument('out_dir')
    parser.add_argument('--bpm', type=float, default=120, help='fallback tempo when the score has none')
    parser.add_argument('--title'); parser.add_argument('--composer'); parser.add_argument('--catalog')
    parser.add_argument('--hands', choices=('right', 'both'), default='right')
    parser.add_argument('--no-explain', action='store_true', help='skip the Claude explanations')
    args = parser.parse_args(argv[1:])
    piece = {k: v for k, v in dict(title=args.title, composer=args.composer, catalog=args.catalog).items() if v}
    report, paths = analyze(args.score, args.performance, args.out_dir, bpm=args.bpm, piece=piece,
                            hands=args.hands, explain=not args.no_explain)
    print(f"{paths['report']}  findings={len(report['errors'])}  explanations={report['meta']['explanations']}")
    for e in report['errors']:
        extra = f" {e['delta_ms']:+d} ms" if 'delta_ms' in e else ''
        print(f"  bar {e['measure']:>3} beat {e['beat']:<4} {e['category']:<12} {e.get('expected') or ''}->{e.get('actual') or ''}{extra}  {e['tier']}")
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main(sys.argv))


def trim_to_played(alignment):
    """Cut a comparison down to the bars the student actually played.

    A pitch-only aligner pins a few stray notes to similar bars past the end of a short take, and
    every score note after the last one played then shows as "missed". Where the take ends is
    found from timing instead: the tempo of the last two well-matched bars, projected to the
    last sound in the recording (and the same at the start). Outside that stretch, skipped notes
    are dropped (the student never got there), bars are dropped, and matches are re-labelled as
    the extra notes they are. Changes `alignment` in place and returns it."""
    import numpy as np
    matches, measures = alignment['matches'], alignment['measures']
    solid = [b for b in measures if b['expected_notes'] and b['correct_notes'] / b['expected_notes'] >= 0.5]
    times = [m['audio_time'] for m in matches if m['audio_time'] is not None]
    if not solid or not times:
        return alignment

    def beat_at(bars, t):
        spans = [(b['start_beat'], b['end_beat']) for b in bars]
        pts = [(m['audio_time'], m['score_beat']) for m in matches if m['category'] == 'correct'
               and m['audio_time'] is not None and m['score_beat'] is not None
               and any(s <= m['score_beat'] < e for s, e in spans)]
        if len({p[0] for p in pts}) < 2:
            return None
        slope, intercept = np.polyfit([p[0] for p in pts], [p[1] for p in pts], 1)
        return intercept + slope * t if slope > 0 else None

    by_occ = sorted(measures, key=lambda b: b['occurrence'])
    def occ_at(beat, fallback):
        if beat is None:
            return fallback
        for b in by_occ:
            if b['start_beat'] <= beat < b['end_beat']:
                return b['occurrence']
        return by_occ[0]['occurrence'] if beat < by_occ[0]['start_beat'] else by_occ[-1]['occurrence']

    end_beat = beat_at(solid[-2:], max(times))
    start_beat = beat_at(solid[:2], min(times))
    first = min(solid[0]['occurrence'], occ_at(start_beat, solid[0]['occurrence']))
    last = max(solid[-1]['occurrence'], occ_at(end_beat, solid[-1]['occurrence']))
    last_bar = next(b for b in by_occ if b['occurrence'] == last)
    reached = end_beat if end_beat is not None else last_bar['end_beat']

    kept, dropped, relabelled = [], set(), set()
    for m in matches:
        occ = m.get('measure_occurrence')
        outside = occ is not None and not first <= occ <= last
        if m['category'] == 'missing' and (outside or (m['score_beat'] is not None and m['score_beat'] > reached + 0.25)):
            dropped.add(m.get('score_note_id'))
            continue
        if outside and m['category'] in ('correct', 'wrong_pitch'):
            relabelled.add(m.get('score_note_id'))
            m = dict(m, category='extra', score_note_id=None, expected_pitch=None, score_beat=None,
                     measure=last_bar['number'], measure_occurrence=last, onset_error_seconds=None)
        elif outside and m['category'] == 'extra':
            m = dict(m, measure=last_bar['number'], measure_occurrence=last)
        kept.append(m)
    alignment['matches'] = kept
    removed = dropped | relabelled
    errors = [e for e in alignment['errors'] if e.get('score_note_id') not in removed or e.get('score_note_id') is None]
    for e in errors:
        if e.get('measure_occurrence') is not None and not first <= e['measure_occurrence'] <= last:
            e['measure'], e['measure_occurrence'] = last_bar['number'], last
    errors += [dict(category='extra', measure=m['measure'], measure_occurrence=m['measure_occurrence'],
                    score_note_id=None, performance_note_id=m.get('performance_note_id'), score_beat=None,
                    audio_time=m['audio_time'], expected_pitch=None, actual_pitch=m['actual_pitch'],
                    onset_error_seconds=None, evidence_confidence=None,
                    assessment='possible_transcription_or_playing_error')
               for m in kept if m['category'] == 'extra' and m.get('performance_note_id') and
               not any(e.get('performance_note_id') == m['performance_note_id'] for e in alignment['errors'])]
    alignment['errors'] = errors
    played = [b for b in measures if first <= b['occurrence'] <= last]
    for b in played:
        inside = [m for m in kept if m.get('measure_occurrence') == b['occurrence']]
        b['correct_notes'] = sum(m['category'] == 'correct' for m in inside)
        b['missing_notes'] = sum(m['category'] == 'missing' for m in inside)
        b['wrong_pitch_notes'] = sum(m['category'] == 'wrong_pitch' for m in inside)
        b['extra_notes'] = sum(m['category'] == 'extra' for m in inside)
        b['expected_notes'] = b['correct_notes'] + b['missing_notes'] + b['wrong_pitch_notes']
        b['pitch_recall'] = b['correct_notes'] / b['expected_notes'] if b['expected_notes'] else 0.0
    alignment['measures'] = played
    metrics = alignment['metrics']
    metrics['expected_notes'] = sum(b['expected_notes'] for b in played)
    metrics['correct_notes'] = sum(m['category'] == 'correct' for m in kept)
    metrics['pitch_recall'] = metrics['correct_notes'] / metrics['expected_notes'] if metrics['expected_notes'] else 0.0
    if metrics.get('performed_notes'):
        metrics['pitch_precision'] = metrics['correct_notes'] / metrics['performed_notes']
    p, r = metrics.get('pitch_precision', 0.0), metrics['pitch_recall']
    metrics['pitch_f1'] = 2 * p * r / (p + r) if p + r else 0.0
    metrics['tempo_assessed_measures'] = sum(b.get('tempo_fit') is not None for b in played)
    alignment['played_span'] = dict(alignment.get('played_span') or {}, first_occurrence=first, last_occurrence=last,
                                    unplayed_bars_hidden=len(measures) - len(played))
    return alignment
