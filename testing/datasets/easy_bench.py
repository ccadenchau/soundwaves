"""Benchmark for the easy-version maker (pianocoach/easy.py).

Known tunes are rendered three ways and the simplified melody is compared with the truth:
  mix   : the tune on a sampled piano with block chords and a bass line underneath
  voice : a synthetic singing voice (harmonics, vibrato, slides, breath noise), tune only
  song  : the synthetic voice over the piano accompaniment, the closest stand-in for a pop song

Transcriptions are cached per rendered file, so trying different extraction settings is instant.

    .venv/bin/python testing/datasets/easy_bench.py            # score the current settings
    .venv/bin/python testing/datasets/easy_bench.py --grid     # try a small grid and print the best
"""

import argparse
import difflib
import hashlib
import json
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from pianocoach import easy  # noqa: E402

OUT = Path(__file__).with_name('results_easy')
NOTE = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

# (name, eighths) in a reference key; eighths so that 2 = quarter note.
TUNES = {
    'Happy Birthday': [('C4', 1), ('C4', 1), ('D4', 2), ('C4', 2), ('F4', 2), ('E4', 4), ('C4', 1), ('C4', 1), ('D4', 2), ('C4', 2), ('G4', 2), ('F4', 4),
                       ('C4', 1), ('C4', 1), ('C5', 2), ('A4', 2), ('F4', 2), ('E4', 2), ('D4', 2), ('Bb4', 1), ('Bb4', 1), ('A4', 2), ('F4', 2), ('G4', 2), ('F4', 4)],
    'Twinkle Twinkle': [('C4', 2), ('C4', 2), ('G4', 2), ('G4', 2), ('A4', 2), ('A4', 2), ('G4', 4), ('F4', 2), ('F4', 2), ('E4', 2), ('E4', 2), ('D4', 2), ('D4', 2), ('C4', 4),
                        ('G4', 2), ('G4', 2), ('F4', 2), ('F4', 2), ('E4', 2), ('E4', 2), ('D4', 4)],
    'Ode to Joy': [('E4', 2), ('E4', 2), ('F4', 2), ('G4', 2), ('G4', 2), ('F4', 2), ('E4', 2), ('D4', 2), ('C4', 2), ('C4', 2), ('D4', 2), ('E4', 2), ('E4', 3), ('D4', 1), ('D4', 4),
                   ('E4', 2), ('E4', 2), ('F4', 2), ('G4', 2), ('G4', 2), ('F4', 2), ('E4', 2), ('D4', 2), ('C4', 2), ('C4', 2), ('D4', 2), ('E4', 2), ('D4', 3), ('C4', 1), ('C4', 4)],
    'Mary Had a Little Lamb': [('E4', 2), ('D4', 2), ('C4', 2), ('D4', 2), ('E4', 2), ('E4', 2), ('E4', 4), ('D4', 2), ('D4', 2), ('D4', 4), ('E4', 2), ('G4', 2), ('G4', 4),
                               ('E4', 2), ('D4', 2), ('C4', 2), ('D4', 2), ('E4', 2), ('E4', 2), ('E4', 2), ('E4', 2), ('D4', 2), ('D4', 2), ('E4', 2), ('D4', 2), ('C4', 8)],
    'Jingle Bells': [('E4', 2), ('E4', 2), ('E4', 4), ('E4', 2), ('E4', 2), ('E4', 4), ('E4', 2), ('G4', 2), ('C4', 3), ('D4', 1), ('E4', 8),
                     ('F4', 2), ('F4', 2), ('F4', 3), ('F4', 1), ('F4', 2), ('E4', 2), ('E4', 2), ('E4', 1), ('E4', 1), ('E4', 2), ('D4', 2), ('D4', 2), ('E4', 2), ('D4', 4), ('G4', 4)],
    'Amazing Grace': [('G3', 2), ('C4', 4), ('E4', 1), ('C4', 1), ('E4', 4), ('D4', 2), ('C4', 4), ('A3', 2), ('G3', 4), ('G3', 2), ('C4', 4), ('E4', 1), ('C4', 1), ('E4', 4), ('D4', 2), ('G4', 8)],
    'When the Saints': [('C4', 2), ('E4', 2), ('F4', 2), ('G4', 8), ('C4', 2), ('E4', 2), ('F4', 2), ('G4', 8), ('C4', 2), ('E4', 2), ('F4', 2), ('G4', 4), ('E4', 4), ('C4', 4), ('E4', 4), ('D4', 8)],
    'Frere Jacques': [('C4', 2), ('D4', 2), ('E4', 2), ('C4', 2), ('C4', 2), ('D4', 2), ('E4', 2), ('C4', 2), ('E4', 2), ('F4', 2), ('G4', 4), ('E4', 2), ('F4', 2), ('G4', 4),
                      ('G4', 1), ('A4', 1), ('G4', 1), ('F4', 1), ('E4', 2), ('C4', 2), ('G4', 1), ('A4', 1), ('G4', 1), ('F4', 1), ('E4', 2), ('C4', 2)],
}
CHORDS = {  # simple accompaniment per tune: a cycle of (bass, chord tones) per bar, in the reference key
    'default': [('C3', ['E3', 'G3']), ('F3', ['A3', 'C4']), ('G3', ['B3', 'D4']), ('C3', ['E3', 'G3'])],
    'Happy Birthday': [('F3', ['A3', 'C4']), ('C3', ['E3', 'G3']), ('F3', ['A3', 'C4']), ('Bb2', ['D3', 'F3'])],
}


def midi(name):
    pc = NOTE[name[0]]
    acc = name[1:-1]
    return 12 * (int(name[-1]) + 1) + pc + (1 if acc == '#' else -1 if acc == 'b' else 0)


def events_for(tune, *, eighth, transpose):
    out, t = [], 0.0
    for name, eighths in TUNES[tune]:
        d = eighths * eighth
        out.append(dict(start_seconds=t, end_seconds=t + d * 0.92, pitch=midi(name) + transpose, velocity=96))
        t += d
    return out, t


def accompaniment(tune, length, *, eighth, transpose, beats_per_bar=4):
    cycle = CHORDS.get(tune, CHORDS['default'])
    bar = beats_per_bar * 2 * eighth
    out, t, i = [], 0.0, 0
    while t < length:
        bass, tones = cycle[i % len(cycle)]
        out.append(dict(start_seconds=t, end_seconds=t + bar * 0.9, pitch=midi(bass) - 12 + transpose, velocity=72))
        for k in range(beats_per_bar):
            at = t + k * 2 * eighth + (eighth if k % 2 else 0)
            for tone in tones:
                out.append(dict(start_seconds=at, end_seconds=at + eighth * 1.6, pitch=midi(tone) + transpose, velocity=58))
        t += bar
        i += 1
    return out


def voice(events, sr=22050, seed=0):
    """A sung line: a few harmonics, 5.5 Hz vibrato of about 20 cents, a short slide into each
    note, a soft attack, and breath noise under it."""
    rng = np.random.default_rng(seed)
    length = int((events[-1]['end_seconds'] + 1.0) * sr)
    y = np.zeros(length)
    phase = 0.0
    for e in events:
        a, b = int(e['start_seconds'] * sr), int(e['end_seconds'] * sr)
        n = b - a
        tt = np.arange(n) / sr
        f0 = 440 * 2 ** ((e['pitch'] - 69) / 12)
        slide = 2 ** ((-1.5 * np.exp(-tt / 0.06) + 0.03 * rng.standard_normal()) / 12)   # starts a bit flat, settles
        vib = 2 ** ((0.20 * np.sin(2 * np.pi * (5.5 + 0.4 * rng.standard_normal()) * tt + rng.uniform(0, 6.28))) / 12)
        f = f0 * slide * vib
        ph = phase + 2 * np.pi * np.cumsum(f) / sr
        env = np.minimum(1, tt / 0.09) * np.minimum(1, (tt[-1] - tt + 1e-9) / 0.12)
        tone = sum((0.5 ** k) * np.sin((k + 1) * ph) for k in range(6))
        y[a:b] += 0.25 * env * tone * (0.9 + 0.1 * rng.standard_normal())
        phase = ph[-1] % (2 * np.pi)
    y += 0.004 * rng.standard_normal(length)
    return y / max(1e-9, np.abs(y).max()) * 0.8


def render_all(folder, seed=11):
    """Make the audio once. Returns a list of (condition, tune, wav, truth events)."""
    from testing.render_piano import render
    folder.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    cases = []
    for tune in TUNES:
        bpm = rng.choice([76, 88, 100, 112])
        transpose = rng.choice([-3, -2, 0, 2, 4, 5])
        eighth = 30.0 / bpm
        mel, length = events_for(tune, eighth=eighth, transpose=transpose)
        acc = accompaniment(tune, length, eighth=eighth, transpose=transpose)
        stem = tune.lower().replace(' ', '_')
        mix = folder / f'{stem}_mix.wav'
        if not mix.is_file():
            render(mel + acc, mix, noise=0)
        v = voice(mel, seed=rng.randint(0, 999))
        voice_wav = folder / f'{stem}_voice.wav'
        if not voice_wav.is_file():
            sf.write(voice_wav, v, 22050)
        song = folder / f'{stem}_song.wav'
        if not song.is_file():
            accomp = folder / f'{stem}_acc.wav'
            render(acc, accomp, noise=0)
            a, sr = sf.read(accomp, always_2d=True)
            a = a.mean(axis=1)
            if sr != 22050:
                from scipy.signal import resample_poly
                a = resample_poly(a, 22050, sr)
            n = max(len(a), len(v))
            y = np.zeros(n)
            y[:len(v)] += v * 0.9
            y[:len(a)] += a * 0.6
            sf.write(song, y / max(1e-9, np.abs(y).max()) * 0.9, 22050)
        for condition, wav in (('mix', mix), ('voice', voice_wav), ('song', song)):
            cases.append(dict(condition=condition, tune=tune, wav=wav, truth=mel, bpm=bpm))
    return cases


_TRANSCRIPTIONS = {}


def transcribed(wav, *, solo_piano, separate):
    """Cleaned transcription of one file, cached on disk under a key of file + settings."""
    from transcribe_recording import transcribe_recording
    from pianocoach.clean import clean_notes
    from pianocoach.pipeline import transcriber
    key = (str(wav), solo_piano, separate)
    if key in _TRANSCRIPTIONS:
        return _TRANSCRIPTIONS[key]
    digest = hashlib.sha256(f'{wav}|{solo_piano}|{separate}|{wav.stat().st_mtime_ns}'.encode()).hexdigest()[:12]
    cache = OUT / 'cache' / f'{digest}.json'
    if cache.is_file():
        notes = json.loads(cache.read_text(encoding='utf-8'))
    else:
        work = OUT / 'work' / digest
        work.mkdir(parents=True, exist_ok=True)
        source = wav
        if separate:
            stem = easy.separate_voice(wav, work)
            source = stem or wav
        backend = transcriber() if solo_piano else None
        take = transcribe_recording(source, work / 'take', backend=backend)
        notes, _ = clean_notes(take.notes, harmonics=backend is None)
        notes = [dict(pitch=int(n['pitch']), onset=float(n['onset']), duration=float(n['duration']), velocity=int(n['velocity'])) for n in notes]
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(notes), encoding='utf-8')
    _TRANSCRIPTIONS[key] = notes
    return notes


def similarity(events, truth):
    """Pitch-class sequence similarity after the best transposition, and a rhythm score: the share
    of successive note gaps that match the truth to the nearest half beat."""
    got = [e['pitch'] for e in events]
    want = [t['pitch'] for t in truth][:len(got) + 4]
    best = max((difflib.SequenceMatcher(None, [(g - s) % 12 for g in got], [w % 12 for w in want]).ratio(), s) for s in range(12))
    # rhythm: compare the pattern of relative gaps on the aligned prefix
    gw = [round((b['start_seconds'] - a['start_seconds']) / (truth[1]['start_seconds'] - truth[0]['start_seconds']) * 2) / 2 for a, b in zip(truth, truth[1:])]
    gg = [b['beat'] - a['beat'] for a, b in zip(events, events[1:])]
    if gw and gg:
        unit = min(x for x in gw if x > 0)
        gw = [x / unit for x in gw]
        unit_g = min(x for x in gg if x > 0) or 1
        gg = [x / unit_g for x in gg]
        rhythm = difflib.SequenceMatcher(None, [round(x * 2) for x in gg], [round(x * 2) for x in gw]).ratio()
    else:
        rhythm = 0.0
    return best[0], rhythm


def score_cases(cases, *, level=3, separate_song=False, verbose=False):
    rows = []
    for c in cases:
        solo = c['condition'] == 'mix'
        notes = transcribed(c['wav'], solo_piano=solo, separate=(separate_song and c['condition'] == 'song'))
        try:
            melody = easy.extract_melody(notes)
            events, info = easy.simplify(melody, level=level, bars=16)
            pitch, rhythm = similarity(events, c['truth']) if events else (0.0, 0.0)
        except Exception as error:  # noqa: BLE001
            events, pitch, rhythm = [], 0.0, 0.0
            info = dict(error=str(error))
        rows.append(dict(condition=c['condition'], tune=c['tune'], pitch=pitch, rhythm=rhythm, notes=len(events), truth=len(c['truth'])))
        if verbose:
            print(f"  {c['condition']:5} {c['tune']:24} pitch {pitch:4.0%} rhythm {rhythm:4.0%} notes {len(events):3}/{len(c['truth'])}")
    summary = {}
    for cond in ('mix', 'voice', 'song'):
        sub = [r for r in rows if r['condition'] == cond]
        summary[cond] = dict(pitch=float(np.mean([r['pitch'] for r in sub])), rhythm=float(np.mean([r['rhythm'] for r in sub])))
    summary['all'] = dict(pitch=float(np.mean([r['pitch'] for r in rows])), rhythm=float(np.mean([r['rhythm'] for r in rows])))
    return rows, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--grid', action='store_true', help='try a small grid of extraction settings')
    parser.add_argument('--separate', action='store_true', help='run Demucs voice separation on the song condition')
    parser.add_argument('--level', type=int, default=3)
    args = parser.parse_args()
    cases = render_all(OUT / 'audio')
    if not args.grid:
        rows, summary = score_cases(cases, level=args.level, separate_song=args.separate, verbose=True)
        for cond, v in summary.items():
            print(f"{cond:5} pitch {v['pitch']:.0%}  rhythm {v['rhythm']:.0%}")
        (OUT / 'latest.json').write_text(json.dumps(dict(rows=rows, summary=summary, params=easy.PARAMS), indent=1), encoding='utf-8')
        return
    base = dict(easy.PARAMS)
    import itertools
    grid = [dict(zip(('loud_ratio', 'held_ratio', 'blip_short', 'fragment_gap', 'restrike_ratio', 'drop_quiet', 'drop_below'), combo))
            for combo in itertools.product((0.5, 0.6, 0.7), (1.0, 1.15, 1.3), (0.12, 0.15, 0.2), (0.08, 0.12), (0.7, 0.85, 1.0), (0.8, 1.0, 1.2), (5, 7, 9))]
    results = []
    for g in grid:
        easy.PARAMS.update(base)
        easy.PARAMS.update(g)
        _, summary = score_cases(cases, level=args.level, separate_song=args.separate)
        results.append((summary['all']['pitch'] + 0.5 * summary['all']['rhythm'], g, summary))
    results.sort(key=lambda r: -r[0])
    easy.PARAMS.update(base)
    print('best settings:')
    for score, g, summary in results[:5]:
        print(f"  score {score:.3f}  {g}  mix {summary['mix']['pitch']:.0%} voice {summary['voice']['pitch']:.0%} song {summary['song']['pitch']:.0%}")
    print('current:', {k: base[k] for k in ('loud_ratio', 'held_ratio', 'blip_short', 'fragment_gap', 'restrike_ratio', 'drop_quiet', 'drop_below')})


if __name__ == '__main__':
    main()
