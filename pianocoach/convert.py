"""Audio in, MIDI out. No sheet music: test the cleaner and the transcriber on any recording.

    .venv/bin/python -m pianocoach.convert ~/Downloads/take.m4a          # prints a summary and a link
    .venv/bin/python -m pianocoach.convert take.wav --no-compare --strength 0.5

Each run transcribes the cleaned audio and, unless --no-compare, the original as well, so the
effect of cleaning is visible. Outputs (cleaned audio, MIDI files, MIDI rendered with the sampled
piano) go to pianocoach/sessions/convert/<id>/ and open at http://127.0.0.1:5001/convert?id=<id>.
"""

import argparse
import json
import shutil
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

CONVERT = Path(__file__).with_name('sessions') / 'convert'
AUDIO_TYPES = {'.wav', '.mp3', '.m4a', '.aac', '.webm', '.ogg', '.oga', '.flac', '.aiff', '.aif', '.mp4', '.caf'}
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def note_name(pitch):
    return f'{NAMES[pitch % 12]}{pitch // 12 - 1}'


def _write_midi(notes, path):
    import pretty_midi
    midi = pretty_midi.PrettyMIDI()
    piano = pretty_midi.Instrument(program=0, name='Piano')
    for n in notes:
        piano.notes.append(pretty_midi.Note(velocity=int(max(1, min(127, n['velocity']))), pitch=int(n['pitch']),
                                            start=float(n['onset']), end=float(n['onset'] + n['duration'])))
    midi.instruments.append(piano)
    midi.write(str(path))


def _stats(notes):
    if not notes:
        return dict(notes=0, chords=0, biggest_chord=0, lowest=None, highest=None)
    onsets = sorted(notes, key=lambda n: n['onset'])
    groups, current = [], [onsets[0]]
    for n in onsets[1:]:
        if n['onset'] - current[0]['onset'] <= 0.05:
            current.append(n)
        else:
            groups.append(current); current = [n]
    groups.append(current)
    sizes = [len({n['pitch'] for n in g}) for g in groups]
    pitches = [n['pitch'] for n in notes]
    return dict(notes=len(notes), chords=sum(s >= 2 for s in sizes), biggest_chord=max(sizes),
                lowest=note_name(min(pitches)), highest=note_name(max(pitches)))


def _room_db(path):
    from audio_cleaner.clean_audio import load_audio, room_snr_db
    data, sr = load_audio(path)
    return round(room_snr_db(data.mean(axis=1), sr), 1)


def convert_audio(audio, out_dir=None, *, compare=True, strength=0.7):
    """Clean and transcribe one recording. Returns a JSON-ready summary; files land in out_dir."""
    from audio_cleaner.clean_audio import CleanConfig, clean_audio
    from transcribe_recording import transcribe_recording
    from testing.render_piano import render
    from .clean import clean_notes
    from .pipeline import transcriber

    audio = Path(audio).expanduser().resolve()
    if audio.suffix.lower() not in AUDIO_TYPES:
        raise ValueError(f'Use an audio file ({", ".join(sorted(AUDIO_TYPES))}).')
    run_id = uuid.uuid4().hex
    out = Path(out_dir) if out_dir else CONVERT / run_id
    out.mkdir(parents=True, exist_ok=True)
    original = out / ('original' + audio.suffix.lower())
    shutil.copy(audio, original)

    started = time.time()
    backend = transcriber()
    engine = backend.name if backend is not None else 'basic-pitch'
    cleaned = out / 'cleaned.wav'
    clean_audio(original, cleaned, mode='piano', strength=strength)
    room_before = _room_db(original)
    skipped = room_before >= CleanConfig().skip_above_snr_db
    result = dict(id=run_id if out_dir is None else None, file=audio.name, engine=engine, strength=strength,
                  room=dict(before_db=room_before, after_db=_room_db(cleaned), cleaner_skipped=skipped),
                  versions={})
    sources = {'cleaned': cleaned}
    if compare:
        sources['original'] = original
    for key, source in sources.items():
        t0 = time.time()
        take = transcribe_recording(source, out / f'take-{key}', backend=backend)
        kept, cleanup = clean_notes(take.notes, harmonics=backend is None)
        kept.sort(key=lambda n: (n['onset'], n['pitch']))
        _write_midi(kept, out / f'{key}.mid')
        if kept:
            render([dict(start_seconds=n['onset'], end_seconds=n['onset'] + n['duration'],
                         pitch=n['pitch'], velocity=n['velocity']) for n in kept], out / f'{key}-as-piano.wav', noise=0)
        result['versions'][key] = dict(
            seconds=round(time.time() - t0, 1), duration=round(take.duration_seconds, 2), stats=_stats(kept),
            removed=dict(duplicates=cleanup.get('duplicates_merged', 0), overtones=cleanup.get('harmonics_removed', 0),
                         split_notes=cleanup.get('reonsets_merged', 0)),
            notes=[dict(t=round(n['onset'], 3), d=round(n['duration'], 3), p=int(n['pitch']), v=int(n['velocity']),
                        name=note_name(int(n['pitch']))) for n in kept],
            warnings=list(take.warnings))
    if compare:
        def keyset(notes):
            return [(round(n['t'] / 0.06), n['p']) for n in notes]
        a, b = result['versions']['cleaned']['notes'], result['versions']['original']['notes']
        ka, kb = keyset(a), keyset(b)
        match = lambda n, other: any(o['p'] == n['p'] and abs(o['t'] - n['t']) <= 0.06 for o in other)
        result['difference'] = dict(only_after_cleaning=[n for n in a if not match(n, b)],
                                    lost_by_cleaning=[n for n in b if not match(n, a)])
    result['seconds'] = round(time.time() - started, 1)
    (out / 'result.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
    return result


def main(argv):
    parser = argparse.ArgumentParser(description='Clean a recording and convert it to MIDI, without sheet music.')
    parser.add_argument('audio', type=Path)
    parser.add_argument('--strength', type=float, default=0.7, help='piano cleaner strength 0-1 (default 0.7)')
    parser.add_argument('--no-compare', action='store_true', help='only transcribe the cleaned audio')
    parser.add_argument('--port', type=int, default=5001, help='port of the running app, for the link')
    args = parser.parse_args(argv[1:])
    r = convert_audio(args.audio, compare=not args.no_compare, strength=args.strength)
    room = r['room']
    print(f"{r['file']}  ·  transcriber: {r['engine']}  ·  {r['seconds']} s")
    print(f"loud-to-quiet spread: {room['before_db']} dB"
          + (' (very quiet room, cleaner left it alone)' if room['cleaner_skipped'] else f" -> {room['after_db']} dB after cleaning"))
    for key, v in r['versions'].items():
        s = v['stats']
        print(f"\n{key:>8}: {s['notes']} notes, {s['chords']} chords (biggest {s['biggest_chord']}), range {s['lowest']} to {s['highest']}")
        print('          ' + ' '.join(f"{n['name']}@{n['t']:.2f}" for n in v['notes'][:24]) + (' …' if len(v['notes']) > 24 else ''))
    if 'difference' in r:
        d = r['difference']
        print(f"\ncleaning added {len(d['only_after_cleaning'])} notes, removed {len(d['lost_by_cleaning'])}: "
              + ', '.join([f"+{n['name']}@{n['t']:.2f}" for n in d['only_after_cleaning']] + [f"-{n['name']}@{n['t']:.2f}" for n in d['lost_by_cleaning']])[:300])
    print(f"\nfiles: {CONVERT / r['id']}\nopen:  http://127.0.0.1:{args.port}/convert?id={r['id']}")
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
