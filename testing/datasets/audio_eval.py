"""How good is audio -> MIDI, how well does cleaning isolate real background noise, how good is the feedback
against the score, and is it fast enough for real time? Measured on real data.

    .venv/bin/python testing/datasets/audio_eval.py transcribe --pieces 8 --seconds 30
    .venv/bin/python testing/datasets/audio_eval.py feedback  --performances 6
    .venv/bin/python testing/datasets/audio_eval.py live      --pieces 3

Data (outside the repo, see README.md in this folder):
  SMD   ~/Desktop/calhacks/datasets/smd      Yamaha Disklavier recordings with the piano's own MIDI (ground truth)
  DEMAND ~/Desktop/calhacks/datasets/demand  real recorded background noise (living room, kitchen, cafe, office, park)
  ASAP  ~/Desktop/calhacks/datasets/asap-dataset  MusicXML scores + human performance MIDI

Metrics follow the usual transcription convention: a detected note is correct when the pitch matches
exactly and the onset is within 50 ms of a ground-truth onset (each ground-truth note used once).
"""

import argparse
import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

DATA = Path.home() / 'Desktop' / 'calhacks' / 'datasets'
SMD, DEMAND, ASAP, MAESTRO = DATA / 'smd', DATA / 'demand', DATA / 'asap-dataset', DATA / 'maestro'
ENVIRONMENTS = [e for e in ['DLIVING', 'PCAFETER', 'DKITCHEN', 'OOFFICE', 'NPARK'] if (DEMAND / e).is_dir()] or ['DLIVING']
TOL = 0.05


# ------------------------------------------------------------------ helpers

def midi_notes(path, start=0.0, end=None):
    import pretty_midi
    midi = pretty_midi.PrettyMIDI(str(path))
    out = []
    for inst in midi.instruments:
        if inst.is_drum:
            continue
        for n in inst.notes:
            if n.start >= start and (end is None or n.start < end):
                out.append((n.start - start, n.pitch))
    return sorted(out)


def note_f1(truth, detected, tol=TOL):
    """Greedy one-to-one matching by pitch, closest onset first."""
    by_pitch = {}
    for t, p in detected:
        by_pitch.setdefault(p, []).append(t)
    used, hits = set(), 0
    for t, p in sorted(truth):
        best = None
        for i, d in enumerate(by_pitch.get(p, [])):
            if (p, i) in used or abs(d - t) > tol:
                continue
            if best is None or abs(d - t) < abs(by_pitch[p][best] - t):
                best = i
        if best is not None:
            used.add((p, best)); hits += 1
    precision = hits / len(detected) if detected else 0.0
    recall = hits / len(truth) if truth else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return dict(precision=precision, recall=recall, f1=f1, hits=hits, truth=len(truth), detected=len(detected))


def load_mono(path, sr=None):
    data, rate = sf.read(str(path), dtype='float32', always_2d=True)
    x = data.mean(axis=1)
    if sr and rate != sr:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(rate, sr)
        x = resample_poly(x, sr // g, rate // g).astype(np.float32)
        rate = sr
    return x, rate


def active_rms(x, sr):
    frame = int(0.05 * sr)
    frames = x[: len(x) // frame * frame].reshape(-1, frame)
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    loud = rms[rms > np.percentile(rms, 50)]
    return float(np.sqrt((loud ** 2).mean()))


def noise_clip(env, length, sr, rng):
    files = sorted((DEMAND / env).glob('ch*.wav'))
    noise, rate = load_mono(files[rng.integers(0, len(files))], sr)
    if len(noise) < length:
        noise = np.tile(noise, int(np.ceil(length / len(noise))))
    start = int(rng.integers(0, len(noise) - length + 1))
    return noise[start:start + length]


def mix(clean, noise, snr_db, sr):
    if snr_db is None:
        return clean.copy()
    gain = active_rms(clean, sr) / (np.sqrt((noise ** 2).mean()) + 1e-12) / (10 ** (snr_db / 20))
    out = clean + gain * noise
    peak = np.abs(out).max()
    return (out / peak * 0.9).astype(np.float32) if peak > 0.99 else out.astype(np.float32)


def si_snr(reference, estimate):
    """Scale-invariant SNR of an estimate against the clean reference (dB)."""
    n = min(len(reference), len(estimate))
    r, e = reference[:n] - reference[:n].mean(), estimate[:n] - estimate[:n].mean()
    target = (e @ r) / (r @ r + 1e-12) * r
    return float(10 * np.log10((target @ target) / (((e - target) @ (e - target)) + 1e-12)))


def engines(which):
    from transcribe_recording.backend import BasicPitchBackend
    from pianocoach.transkun_backend import TranskunBackend
    out = {}
    if 'transkun' in which and TranskunBackend.available():
        out['transkun'] = TranskunBackend()
    if 'basic-pitch' in which:
        out['basic-pitch'] = BasicPitchBackend()
    return out


def convert(path, backend, workdir):
    """What /convert does: transcribe, then the note cleanup."""
    from transcribe_recording import transcribe_recording
    from pianocoach.clean import clean_notes
    take = transcribe_recording(path, workdir, backend=backend)
    kept, _ = clean_notes(take.notes, harmonics=backend.__class__.__name__ == 'BasicPitchBackend')
    return sorted((n['onset'], n['pitch']) for n in kept)


def smd_pairs():
    """Real recordings with exact MIDI: MAESTRO members fetched by fetch_maestro.py, then SMD if present."""
    pairs = []
    for audio in sorted(MAESTRO.rglob('*.wav')):
        midi = audio.with_suffix('.midi')
        if midi.is_file():
            pairs.append((audio, midi))
    for audio in sorted(list(SMD.rglob('*.wav')) + list(SMD.rglob('*.mp3'))):
        if '__MACOSX' in str(audio) or 'synth' in audio.stem.lower():
            continue
        midi = next((m for m in SMD.rglob(audio.stem + '.mid')), None)
        if midi is not None:
            pairs.append((audio, midi))
    return pairs


# ------------------------------------------------------------------ 1+2: transcription and noise

def run_transcribe(args):
    from audio_cleaner.clean_audio import clean_audio
    pairs = smd_pairs()
    if not pairs:
        sys.exit(f'No SMD audio/MIDI pairs under {SMD}.')
    rng = np.random.default_rng(args.seed)
    random.Random(args.seed).shuffle(pairs)
    pairs = pairs[:args.pieces]
    snrs = [None] + [float(s) for s in args.snr.split(',')]
    eng = engines(args.engines.split(','))
    rows, work = [], Path(tempfile.mkdtemp(prefix='audio-eval-'))
    for audio, midi in pairs:
        clean, sr = load_mono(audio)
        clean = clean[: int(args.seconds * sr)]
        truth = midi_notes(midi, 0.0, args.seconds - 0.2)
        for snr in snrs:
            env = ENVIRONMENTS[int(rng.integers(0, len(ENVIRONMENTS)))]
            noisy = mix(clean, noise_clip(env, len(clean), sr, rng), snr, sr)
            raw_path = work / f'{audio.stem}-{snr}.wav'
            sf.write(raw_path, noisy, sr)
            cleaned_path = work / f'{audio.stem}-{snr}-cleaned.wav'
            t0 = time.time(); clean_audio(raw_path, cleaned_path, mode='piano'); clean_seconds = time.time() - t0
            cleaned, _ = load_mono(cleaned_path)
            isolation = dict(before=si_snr(clean, noisy), after=si_snr(clean, cleaned)) if snr is not None else None
            for version, path in (('raw', raw_path), ('cleaned', cleaned_path)):
                for name, backend in eng.items():
                    t0 = time.time()
                    detected = convert(path, backend, work / f't-{audio.stem}-{snr}-{version}-{name}')
                    seconds = time.time() - t0
                    m = note_f1(truth, detected)
                    rows.append(dict(piece=audio.stem, snr=snr, noise=env if snr is not None else None, version=version,
                                     engine=name, **m, realtime_factor=seconds / args.seconds,
                                     clean_seconds=clean_seconds, isolation=isolation))
                    print(f"{audio.stem[:34]:34} {'clean' if snr is None else f'{snr:>4.0f} dB {env:8}':16} {version:7} {name:11} "
                          f"F1 {m['f1']:.3f}  P {m['precision']:.2f} R {m['recall']:.2f}  ({seconds:.1f} s)", flush=True)
    for b in eng.values():
        getattr(b, 'close', lambda: None)()
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'transcribe.json').write_text(json.dumps(rows, indent=1))
    print('\nSummary (mean over pieces):')
    print(f"{'noise':>9} {'engine':11} {'raw F1':>7} {'cleaned F1':>10} {'raw P/R':>11} {'cleaned P/R':>12} {'SI-SNR before -> after':>24}")
    for snr in snrs:
        for name in eng:
            sel = lambda v: [r for r in rows if r['snr'] == snr and r['engine'] == name and r['version'] == v]
            raw, cln = sel('raw'), sel('cleaned')
            mean = lambda rs, k: statistics.mean(r[k] for r in rs)
            iso = [r['isolation'] for r in raw if r['isolation']]
            iso_text = f"{statistics.mean(i['before'] for i in iso):6.1f} -> {statistics.mean(i['after'] for i in iso):5.1f} dB" if iso else ''
            print(f"{'clean' if snr is None else f'{snr:.0f} dB':>9} {name:11} {mean(raw, 'f1'):7.3f} {mean(cln, 'f1'):10.3f} "
                  f"{mean(raw, 'precision'):5.2f}/{mean(raw, 'recall'):.2f} {mean(cln, 'precision'):6.2f}/{mean(cln, 'recall'):.2f} {iso_text:>24}")
    for name in eng:
        rf = [r['realtime_factor'] for r in rows if r['engine'] == name]
        print(f"{name}: {statistics.median(rf):.3f} s of compute per second of audio (median)")
    print(f"cleaner: {statistics.median(r['clean_seconds'] for r in rows) / args.seconds:.3f} s per second of audio (median)")


# ------------------------------------------------------------------ 3: feedback against the score, through audio

def run_feedback(args):
    import csv
    from alignment import AlignmentConfig
    from music21 import pitch as m21pitch
    from pianocoach.pipeline import align_clean, convert_once
    from testing.datasets.asap_eval import plant_mistakes, score_findings
    from testing.render_piano import render
    import pretty_midi
    rows = list(csv.DictReader((ASAP / 'metadata.csv').open()))
    random.Random(args.seed).shuffle(rows)
    rng = np.random.default_rng(args.seed)
    eng = engines(['transkun'] if 'transkun' in args.engines else ['basic-pitch'])
    backend = next(iter(eng.values()))
    work = Path(tempfile.mkdtemp(prefix='feedback-eval-'))
    config = AlignmentConfig(maximum_alignment_cells=16_000_000)
    results, done = [], 0
    for row in rows:
        if done >= args.performances:
            break
        perf = ASAP / row['midi_performance']
        if not perf.is_file():
            continue
        notes = sum(len(i.notes) for i in pretty_midi.PrettyMIDI(str(perf)).instruments)
        if notes > args.max_notes:
            continue
        key = row['folder'].replace('/', '__')
        try:
            ref = convert_once(ASAP / row['xml_score'], ROOT / 'testing/datasets/results/scores' / key)
        except Exception as error:  # noqa: BLE001
            print(f'skip {key}: {str(error)[:60]}'); continue
        for variant in ('clean', 'planted'):
            midi_path = perf if variant == 'clean' else work / f'{key}-{perf.stem}-planted.mid'
            plants = [] if variant == 'clean' else plant_mistakes(perf, midi_path, args.plant, args.seed + done)
            events = [dict(start_seconds=n.start, end_seconds=n.end, pitch=n.pitch, velocity=n.velocity)
                      for i in pretty_midi.PrettyMIDI(str(midi_path)).instruments for n in i.notes]
            wav = work / f'{key}-{variant}.wav'
            render(events, wav, noise=0)
            clean, sr = load_mono(wav)
            snr = args.feedback_snr
            noisy = mix(clean, noise_clip(ENVIRONMENTS[int(rng.integers(0, len(ENVIRONMENTS)))], len(clean), sr, rng), snr, sr)
            sf.write(wav, noisy, sr)
            t0 = time.time()
            detected_path = work / f't-{key}-{variant}'
            from transcribe_recording import transcribe_recording
            from pianocoach.clean import clean_notes
            take = transcribe_recording(wav, detected_path, backend=backend)
            kept, _ = clean_notes(take.notes, harmonics=False)
            transcribe_seconds = time.time() - t0
            t0 = time.time()
            alignment, report = align_clean(ref['notes'], kept, performance_notes=kept, musicxml=ref['musicxml'],
                                            piece=dict(title=row['title'], composer=row['composer']), hands='both', config=config,
                                            drop_harmonics='octave' if 'transkun' in eng else True)
            align_seconds = time.time() - t0
            findings = [dict(category=e['category'], audio_time=e['audio_time'],
                             expected_pitch=m21pitch.Pitch(e['expected']).midi if e.get('expected') else None,
                             actual_pitch=m21pitch.Pitch(e['actual']).midi if e.get('actual') else None)
                        for e in report['errors'] if e['category'] in ('wrong_pitch', 'missing', 'extra')]
            r = dict(piece=key, performance=perf.stem, variant=variant, notes=notes, seconds=len(clean) / sr,
                     transcribe_seconds=transcribe_seconds, align_seconds=align_seconds, findings=len(findings),
                     timing_findings=sum(e['category'] == 'timing' for e in report['errors']))
            if variant == 'planted':
                hits, misses, alarms = score_findings(plants, findings)
                baseline = next(x['findings'] for x in results if x['piece'] == key and x['variant'] == 'clean')
                r.update(planted=len(plants), hits=hits, new_false_alarms=max(0, alarms - baseline))
            results.append(r)
            print(json.dumps(r), flush=True)
        done += 1
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'feedback.json').write_text(json.dumps(results, indent=1))
    planted = [r for r in results if r['variant'] == 'planted']
    clean_runs = [r for r in results if r['variant'] == 'clean']
    if planted:
        hits, total = sum(r['hits'] for r in planted), sum(r['planted'] for r in planted)
        print(f"\nThrough audio at {args.feedback_snr} dB real background noise ({next(iter(eng))}):")
        print(f"  planted mistakes caught: {hits}/{total} ({hits / total:.0%}), new false alarms: {sum(r['new_false_alarms'] for r in planted)}")
        print(f"  findings on the unaltered performance: {statistics.mean(r['findings'] for r in clean_runs):.1f} per performance "
              f"({statistics.mean(r['findings'] / r['notes'] * 100 for r in clean_runs):.1f} per 100 notes)")
        print(f"  speed: transcription {statistics.median(r['transcribe_seconds'] / r['seconds'] for r in results):.3f} s per s of audio, "
              f"score comparison + feedback {statistics.median(r['align_seconds'] for r in results):.2f} s per take")


# ------------------------------------------------------------------ 3b: real student mistakes, hand labelled

SCOREINFORMED = DATA / 'scoreinformed-midi'


def _notes_of(path):
    import pretty_midi
    return sorted((n.start, n.end, n.pitch, n.velocity) for i in pretty_midi.PrettyMIDI(str(path)).instruments for n in i.notes)


def _reference_from_notes(notes, bar_seconds=4.0):
    """A reference.json-shaped score from timed notes (1 beat = 1 s, 4/4), so the real score-comparison
    and feedback code runs unchanged on scores that only exist as MIDI."""
    # Printed chords start together; the performance-timed labels spread them by a few ms.
    snapped, group_start = [], None
    for start, end, pitch, velocity in sorted(notes):
        if group_start is None or start - group_start > 0.05:
            group_start = start
        snapped.append((group_start, end, pitch, velocity))
    notes = snapped
    bars = int(max(n[0] for n in notes) // bar_seconds) + 1
    records, chunks = [], []
    for i, (start, end, pitch, velocity) in enumerate(notes):
        bar = int(start // bar_seconds)
        records.append(dict(id=f'n{i:05d}', pitch=pitch, velocity=velocity, tuplets=[], onset=start,
                            duration=max(0.05, end - start), source='score', measure=bar + 1,
                            beat_in_measure=1 + start - bar * bar_seconds, part='RH' if pitch >= 60 else 'LH',
                            voice=None, start_seconds=start, end_seconds=end))
    for b in range(bars):
        lo, hi = b * bar_seconds, (b + 1) * bar_seconds
        chunks.append(dict(id=b, file=None, measure_occurrence=b, measures=[b + 1], start_beat=lo, end_beat=hi,
                           start_seconds=lo, end_seconds=hi,
                           notes=[dict(note_id=r['id'], onset_beat=r['onset'], onset_seconds=r['onset'], carried_in=False)
                                  for r in records if lo <= r['onset'] < hi]))
    return dict(schema_version=1, time_unit='quarter_note', notes=records, chunks=chunks, tempo_changes=[[0.0, 60.0]])


def _score_against_labels(report, missed, extra, tol=0.3, confident_only=False):
    """Match page findings to hand-labelled mistakes. confident_only ignores findings the page marks
    as possible background noise (shown hedged, at low confidence)."""
    from music21 import pitch as m21pitch
    midi = lambda name: m21pitch.Pitch(name).midi if name else None
    found_missed, found_extra, false_alarms = set(), set(), 0
    for e in report['errors']:
        if e['category'] not in ('wrong_pitch', 'missing', 'extra'):
            continue
        if confident_only and e.get('maybe_noise'):
            continue
        score_time = (e['measure'] - 1) * 4.0 + (e['beat'] - 1)
        ok = False
        if e['category'] in ('missing', 'wrong_pitch') and e.get('expected'):
            for i, (t, _, p, _) in enumerate(missed):
                if i not in found_missed and p == midi(e['expected']) and abs(t - score_time) <= tol:
                    found_missed.add(i); ok = True; break
        if e['category'] in ('extra', 'wrong_pitch') and e.get('actual'):
            for i, (t, _, p, _) in enumerate(extra):
                if i not in found_extra and p == midi(e['actual']) and abs(t - e['audio_time']) <= tol:
                    found_extra.add(i); ok = True; break
        false_alarms += not ok
    return dict(missed=len(missed), missed_found=len(found_missed), extra=len(extra), extra_found=len(found_extra),
                false_alarms=false_alarms, timing_findings=sum(e['category'] == 'timing' for e in report['errors']))


def run_real(args):
    from pianocoach.pipeline import align_clean
    from pianocoach.clean import clean_notes
    from testing.render_piano import render
    from transcribe_recording import transcribe_recording
    rng = np.random.default_rng(args.seed)
    eng = engines(['transkun'])
    backend = eng.get('transkun')
    work = Path(tempfile.mkdtemp(prefix='real-mistakes-'))
    rows = []
    for i in range(1, 8):
        stem = next(SCOREINFORMED.glob(f'Disklavier_0{i}_*_correct.mid')).name.replace('_correct.mid', '')
        correct, missed, extra = (_notes_of(SCOREINFORMED / f'{stem}_{k}.mid') for k in ('correct', 'missed', 'fa'))
        reference = _reference_from_notes(sorted(correct + missed))
        snapped = {(round(r['end_seconds'], 4), r['pitch']): r['onset'] for r in reference['notes']}
        missed = [(snapped.get((round(e, 4), p), s), e, p, v) for s, e, p, v in missed]
        played = sorted(correct + extra)
        noise_ready = any((DEMAND / e).is_dir() for e in ENVIRONMENTS)
        modes = [('MIDI keyboard', None)]
        if backend and not args.midi_only:
            modes.append(('audio, quiet room', 'quiet'))
            if noise_ready:
                modes += [(f'audio + {snr:g} dB real room noise', snr) for snr in args.real_snr]
        for mode, snr in modes:
            t0 = time.time()
            if snr is None:
                # Same path as a USB keyboard take in the app: a MIDI file, so no audio-noise logic runs.
                import pretty_midi
                midi = pretty_midi.PrettyMIDI(); inst = pretty_midi.Instrument(program=0)
                inst.notes = [pretty_midi.Note(velocity=int(v), pitch=int(p), start=float(s), end=float(max(e, s + 0.03))) for s, e, p, v in played]
                midi.instruments.append(inst)
                performance = work / f'{stem}-keyboard.mid'
                midi.write(str(performance))
            else:
                wav = work / f'{stem}.wav'
                render([dict(start_seconds=s, end_seconds=e, pitch=p, velocity=v) for s, e, p, v in played], wav, noise=0)
                clean, sr = load_mono(wav)
                if snr != 'quiet':
                    sf.write(wav, mix(clean, noise_clip(ENVIRONMENTS[int(rng.integers(0, len(ENVIRONMENTS)))], len(clean), sr, rng), snr, sr), sr)
                take = transcribe_recording(wav, work / f't-{stem}-{snr}', backend=backend)
                performance, _ = clean_notes(take.notes, harmonics=False)
            alignment, report = align_clean(reference, performance, performance_notes=None if snr is None else performance,
                                            piece=dict(title=stem, composer='ABRSM'), hands='both',
                                            drop_harmonics=False if snr is None else 'octave')
            r = dict(piece=stem, mode=mode, seconds=round(time.time() - t0, 2), **_score_against_labels(report, missed, extra))
            confident = _score_against_labels(report, missed, extra, confident_only=True)
            r.update(confident_found=confident['missed_found'] + confident['extra_found'], confident_false=confident['false_alarms'],
                     hedged=sum(bool(e.get('maybe_noise')) for e in report['errors']))
            rows.append(r)
            print(f"{stem:22} {mode:26} skipped notes found {r['missed_found']:>2}/{r['missed']:<2}  extra notes found {r['extra_found']:>2}/{r['extra']:<2}  "
                  f"false alarms {r['false_alarms']:>2}  timing flags {r['timing_findings']:>2}  ({r['seconds']} s)", flush=True)
    getattr(backend, 'close', lambda: None)() if backend else None
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'real_mistakes.json').write_text(json.dumps(rows, indent=1))
    print()
    for mode in dict.fromkeys(r['mode'] for r in rows):
        sel = [r for r in rows if r['mode'] == mode]
        found = sum(r['missed_found'] + r['extra_found'] for r in sel)
        total = sum(r['missed'] + r['extra'] for r in sel)
        alarms = sum(r['false_alarms'] for r in sel)
        cf, ca = sum(r['confident_found'] for r in sel), sum(r['confident_false'] for r in sel)
        print(f"{mode}: caught {found}/{total} real mistakes ({found / total:.0%}); "
              f"{alarms} false alarms, so {found / max(1, found + alarms):.0%} of reported mistakes were real"
              f"  | confident findings only: caught {cf}/{total} ({cf / total:.0%}), {ca} false alarms, {cf / max(1, cf + ca):.0%} real; "
              f"{sum(r['hedged'] for r in sel)} hedged as possible noise")


# ------------------------------------------------------------------ 4: live

def run_live(args):
    """Stream SMD excerpts the way /practice does: a window of the last 1.5 s every 100 ms."""
    from pianocoach.live import _transcribe_window
    import io
    if args.beginner:
        # Student-level pieces: the labelled ABRSM grade 1-2 performances, rendered with the sampled piano.
        from testing.render_piano import render
        import pretty_midi
        work = Path(tempfile.mkdtemp(prefix='live-beginner-'))
        pairs = []
        for i in range(1, 8):
            stem = next(SCOREINFORMED.glob(f'Disklavier_0{i}_*_correct.mid')).name.replace('_correct.mid', '')
            played = sorted(_notes_of(SCOREINFORMED / f'{stem}_correct.mid') + _notes_of(SCOREINFORMED / f'{stem}_fa.mid'))
            wav, mid = work / f'{stem}.wav', work / f'{stem}.mid'
            render([dict(start_seconds=a, end_seconds=b, pitch=p, velocity=v) for a, b, p, v in played], wav, noise=0)
            pm = pretty_midi.PrettyMIDI(); inst = pretty_midi.Instrument(program=0)
            inst.notes = [pretty_midi.Note(velocity=int(v), pitch=int(p), start=float(a), end=float(b)) for a, b, p, v in played]
            pm.instruments.append(inst); pm.write(str(mid))
            pairs.append((wav, mid))
    else:
        pairs = smd_pairs()
    random.Random(args.seed).shuffle(pairs)
    rng = np.random.default_rng(args.seed)
    rows = []
    for audio, midi in pairs[:args.pieces]:
        clean, sr0 = load_mono(audio, 22050)
        sr = 22050
        clean = clean[: int(args.seconds * sr)]
        truth = midi_notes(midi, 0.0, args.seconds - 1.6)
        for snr in (None, 10.0):
            x = mix(clean, noise_clip('DLIVING', len(clean), sr, rng), snr, sr)
            windows, per_call = [], []
            hop, context = int(0.1 * sr), int(1.5 * sr)
            for end in range(int(0.2 * sr), len(x), hop):
                start = max(0, end - context)
                buf = io.BytesIO(); sf.write(buf, np.clip(x[start:end], -1, 1), sr, format='WAV', subtype='PCM_16')
                t0 = time.time(); res = _transcribe_window(buf.getvalue()); per_call.append(time.time() - t0)
                windows.append(dict(start=start / sr, end=end / sr, received=end / sr + per_call[-1], notes=res['notes']))
            # The browser's own merger decides what becomes a note on screen.
            import subprocess, shutil
            node = shutil.which('node') or str(next(Path.home().glob('.nvm/versions/node/*/bin/node')))
            merged = json.loads(subprocess.run([node, str(Path(__file__).with_name('live_merge.cjs'))], input=json.dumps(windows),
                                               capture_output=True, text=True, check=True).stdout)
            emitted = [(e['time'], e['pitch']) for e in merged]
            latencies = [e['emitted'] - e['time'] for e in merged]
            m = note_f1(truth, [e for e in emitted if e[0] < args.seconds - 1.6], tol=0.08)
            rows.append(dict(piece=audio.stem, snr=snr, **m, median_latency_ms=statistics.median(latencies) * 1000 if latencies else None,
                             p90_latency_ms=float(np.percentile(latencies, 90) * 1000) if latencies else None,
                             median_call_ms=statistics.median(per_call) * 1000))
            print(f"{audio.stem[:34]:34} {'clean' if snr is None else '10 dB':6} live F1 {m['f1']:.3f} P {m['precision']:.2f} R {m['recall']:.2f} "
                  f"latency median {rows[-1]['median_latency_ms']:.0f} ms p90 {rows[-1]['p90_latency_ms']:.0f} ms, model call {rows[-1]['median_call_ms']:.0f} ms", flush=True)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'live.json').write_text(json.dumps(rows, indent=1))


# ------------------------------------------------------------------ 4b: live feedback marks vs labelled mistakes

def run_livefeedback(args):
    """What the practice screen paints while a student plays, scored against hand-labelled mistakes."""
    import io, subprocess, shutil
    from pianocoach.live import _transcribe_window
    from testing.render_piano import render
    node = shutil.which('node') or str(next(Path.home().glob('.nvm/versions/node/*/bin/node')))
    rng = np.random.default_rng(args.seed)
    work = Path(tempfile.mkdtemp(prefix='live-feedback-'))
    totals = {}
    for i in range(1, 8):
        stem = next(SCOREINFORMED.glob(f'Disklavier_0{i}_*_correct.mid')).name.replace('_correct.mid', '')
        correct, missed, extra = (_notes_of(SCOREINFORMED / f'{stem}_{k}.mid') for k in ('correct', 'missed', 'fa'))
        reference = _reference_from_notes(sorted(correct + missed))
        score = [dict(id=r['id'], pitch=r['pitch'], beat=r['onset'], duration=r['duration']) for r in reference['notes']]
        label = {}
        for r in reference['notes']:
            is_missed = any(p == r['pitch'] and abs(e - r['end_seconds']) < 1e-3 for s, e, p, v in missed)
            label[r['id']] = 'missed' if is_missed else 'correct'
        played = sorted(correct + extra)
        wav = work / f'{stem}.wav'
        render([dict(start_seconds=a, end_seconds=b, pitch=p, velocity=v) for a, b, p, v in played], wav, noise=0)
        clean, sr0 = load_mono(wav, 22050)
        for mode, snr in (('keyboard (MIDI)', 'midi'), ('mic, quiet room', None), ('mic, 10 dB conversation', 10.0)):
            if snr == 'midi':
                # Keyboard: every key press arrives as it happens, in 35 ms groups like practice.js.
                windows, group = [], []
                for a, b, p, v in played:
                    if group and a - group[0]['time'] > 0.035:
                        windows.append(dict(received=group[0]['time'] + 0.035, events=group)); group = []
                    group.append(dict(pitch=p, time=a, velocity=v))
                if group:
                    windows.append(dict(received=group[0]['time'] + 0.035, events=group))
                job = dict(score=score, bpm=60, input='midi', windows=windows)
            else:
                x = mix(clean, noise_clip('DLIVING', len(clean), sr0, rng), snr, sr0) if snr else clean
                windows, hop, context = [], int(0.1 * sr0), int(1.5 * sr0)
                for end in range(int(0.2 * sr0), len(x), hop):
                    start = max(0, end - context)
                    buf = io.BytesIO(); sf.write(buf, np.clip(x[start:end], -1, 1), sr0, format='WAV', subtype='PCM_16')
                    res = _transcribe_window(buf.getvalue())
                    windows.append(dict(start=start / sr0, end=end / sr0, received=end / sr0 + 0.012, notes=res['notes']))
                job = dict(score=score, bpm=60, input='mic', windows=windows)
            out = json.loads(subprocess.run([node, str(Path(__file__).with_name('live_follow.cjs'))], input=json.dumps(job),
                                            capture_output=True, text=True, check=True).stdout)
            marks = out['marks']
            c = dict(correct_total=sum(v == 'correct' for v in label.values()), missed_total=sum(v == 'missed' for v in label.values()))
            c['correct_confirmed'] = sum(1 for k, m in marks.items() if label.get(k) == 'correct' and m['kind'] == 'matched')
            c['correct_flagged'] = sum(1 for k, m in marks.items() if label.get(k) == 'correct' and m['kind'] in ('pitch', 'missing'))
            c['mistake_flagged'] = sum(1 for k, m in marks.items() if label.get(k) == 'missed' and m['kind'] in ('pitch', 'missing'))
            c['mistake_confirmed_wrongly'] = sum(1 for k, m in marks.items() if label.get(k) == 'missed' and m['kind'] == 'matched')
            for k, v in c.items():
                totals.setdefault(mode, {}).setdefault(k, 0)
                totals[mode][k] += v
            print(f"{stem:22} {mode:24} confirmed {c['correct_confirmed']}/{c['correct_total']} correct notes, "
                  f"flagged {c['mistake_flagged']}/{c['missed_total']} mistakes live, {c['correct_flagged']} correct notes flagged by mistake", flush=True)
    print()
    for mode, t in totals.items():
        flagged = t['mistake_flagged'] + t['correct_flagged']
        print(f"{mode}: lights up {t['correct_confirmed'] / t['correct_total']:.0%} of correctly played notes; flags {t['mistake_flagged'] / t['missed_total']:.0%} "
              f"of mistakes as they happen; {t['mistake_flagged'] / max(1, flagged):.0%} of live flags are real mistakes "
              f"({t['correct_flagged']} false flags over {t['correct_total']} correct notes)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('test', choices=('transcribe', 'feedback', 'real', 'live', 'livefeedback'))
    parser.add_argument('--pieces', type=int, default=8)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--snr', default='20,10,5,0', help='noise levels in dB (lower = louder noise)')
    parser.add_argument('--engines', default='transkun,basic-pitch')
    parser.add_argument('--performances', type=int, default=6)
    parser.add_argument('--max-notes', type=int, default=700)
    parser.add_argument('--plant', type=int, default=6)
    parser.add_argument('--feedback-snr', type=float, default=10.0)
    parser.add_argument('--seed', type=int, default=5)
    parser.add_argument('--midi-only', action='store_true')
    parser.add_argument('--beginner', action='store_true', help='live test on student-level pieces')
    parser.add_argument('--noise', help='use only this DEMAND environment, e.g. DLIVING')
    parser.add_argument('--real-snr', type=lambda v: [float(x) for x in v.split(',')], default=[20.0, 10.0, 5.0])
    parser.add_argument('--out', default=str(Path(__file__).with_name('results_audio')))
    args = parser.parse_args()
    if args.noise:
        ENVIRONMENTS[:] = [args.noise]
    dict(transcribe=run_transcribe, feedback=run_feedback, real=run_real, live=run_live, livefeedback=run_livefeedback)[args.test](args)


if __name__ == '__main__':
    main()
