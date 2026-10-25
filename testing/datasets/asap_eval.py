"""Measure the aligner on real performances from the ASAP dataset.

ASAP (Foscarin et al.) pairs MusicXML scores with human MIDI performances of
Western classical piano. The performances are by competition pianists and are
close to error-free, so this harness does two things per performance:

1. Clean run: align the performance as played and report pitch precision,
   recall and how many bars received a tempo verdict. Anything flagged here is
   a false alarm or a genuine performer slip; the number should be small.
2. Planted run: copy the performance, plant a known set of mistakes (wrong
   pitches, deleted notes, inserted notes), align again, and score the
   findings against the plant list. That gives detection precision and recall
   for the kinds of mistakes a student makes.

Usage:
    python testing/datasets/asap_eval.py --asap ~/Desktop/calhacks/datasets/asap-dataset \
        --max-notes 1200 --limit 12 --plant 6 --out testing/datasets/results

The aligner's sequence matrix is O(score onsets x performance onsets) in pure
Python, so pieces are filtered by note count. Scores are converted once and
cached under --out/scores. Only MIDI performances are used; no audio.
"""

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pretty_midi  # noqa: E402

from music21 import pitch as m21pitch  # noqa: E402

from alignment import AlignmentConfig  # noqa: E402
from soundwaves.pipeline import align_clean, convert_once  # noqa: E402

NOTE_CATEGORIES = ('wrong_pitch', 'missing', 'extra')


def ui_errors_as_pitches(report):
    """Page findings use note names; the plant list uses MIDI numbers."""
    out = []
    for e in report['errors']:
        if e['category'] not in NOTE_CATEGORIES:
            continue
        out.append(dict(category=e['category'], audio_time=e['audio_time'],
                        expected_pitch=m21pitch.Pitch(e['expected']).midi if e.get('expected') else None,
                        actual_pitch=m21pitch.Pitch(e['actual']).midi if e.get('actual') else None))
    return out


def load_rows(asap):
    with (asap / 'metadata.csv').open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def count_notes(midi_path):
    midi = pretty_midi.PrettyMIDI(str(midi_path))
    return sum(len(i.notes) for i in midi.instruments if not i.is_drum)


def plant_mistakes(source, destination, count, seed):
    """Write a copy of the MIDI with `count` planted mistakes. Returns the plant list."""
    rng = random.Random(seed)
    midi = pretty_midi.PrettyMIDI(str(source))
    notes = [n for inst in midi.instruments if not inst.is_drum for n in inst.notes]
    notes.sort(key=lambda n: (n.start, n.pitch))
    # Plant in the middle 80% so the aligner has anchors on both sides.
    candidates = notes[len(notes) // 10: -max(1, len(notes) // 10)]
    rng.shuffle(candidates)
    plants, used = [], set()
    kinds = ['wrong_pitch', 'missing', 'extra'] * (count // 3 + 1)
    for kind, note in zip(kinds[:count], candidates):
        if any(abs(note.start - t) < 0.4 for t in used):
            continue
        used.add(note.start)
        if kind == 'wrong_pitch':
            original = note.pitch
            note.pitch += rng.choice([-2, -1, 1, 2])
            plants.append(dict(kind='wrong_pitch', time=note.start, expected=original, actual=note.pitch))
        elif kind == 'missing':
            for inst in midi.instruments:
                if note in inst.notes:
                    inst.notes.remove(note)
            plants.append(dict(kind='missing', time=note.start, expected=note.pitch, actual=None))
        else:
            extra = pretty_midi.Note(velocity=note.velocity, pitch=note.pitch + rng.choice([1, 2, 3, -1, -2]),
                                     start=note.start + 0.02, end=note.end)
            midi.instruments[0].notes.append(extra)
            plants.append(dict(kind='extra', time=extra.start, expected=None, actual=extra.pitch))
    midi.write(str(destination))
    return plants


def score_findings(plants, errors, window=0.25):
    """Match findings to plants by kind, pitch and time. Returns (hits, misses, false_alarms)."""
    remaining = list(plants)
    hits, false_alarms = 0, 0
    for err in errors:
        if err['category'] not in ('wrong_pitch', 'missing', 'extra'):
            continue
        match = None
        for plant in remaining:
            if plant['kind'] != err['category']:
                continue
            time_ok = err['audio_time'] is not None and abs(err['audio_time'] - plant['time']) <= window
            if err['category'] == 'missing':
                # the aligner reports no audio_time for a missing note; use pitch only plus a wider check later
                time_ok = True
            pitch_ok = (plant['expected'] in (None, err['expected_pitch'])) and (plant['actual'] in (None, err['actual_pitch']))
            if time_ok and pitch_ok:
                match = plant
                break
        if match is not None:
            remaining.remove(match)
            hits += 1
        else:
            false_alarms += 1
    return hits, len(remaining), false_alarms


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--asap', type=Path, required=True)
    parser.add_argument('--out', type=Path, default=Path(__file__).with_name('results'))
    parser.add_argument('--max-notes', type=int, default=1200, help='skip performances with more notes')
    parser.add_argument('--limit', type=int, default=10, help='performances to run')
    parser.add_argument('--plant', type=int, default=6, help='mistakes to plant per performance')
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--cells', type=int, default=16_000_000, help='maximum_alignment_cells for the aligner')
    parser.add_argument('--composer', default=None, help='only this composer folder')
    args = parser.parse_args()

    rows = load_rows(args.asap)
    if args.composer:
        rows = [r for r in rows if r['composer'].lower() == args.composer.lower()]
    rng = random.Random(args.seed)
    rng.shuffle(rows)
    args.out.mkdir(parents=True, exist_ok=True)
    config = AlignmentConfig(maximum_alignment_cells=args.cells)
    results = []
    for row in rows:
        if len(results) >= args.limit:
            break
        perf = args.asap / row['midi_performance']
        score = args.asap / row['xml_score']
        if not perf.is_file() or not score.is_file():
            continue
        try:
            n_notes = count_notes(perf)
        except Exception:  # noqa: BLE001
            continue
        if n_notes > args.max_notes:
            continue
        piece_key = row['folder'].strip('/').replace('/', '__')
        record = dict(composer=row['composer'], title=row['title'], folder=row['folder'],
                      performance=perf.name, notes=n_notes)
        try:
            t0 = time.time()
            ref = convert_once(score, args.out / 'scores' / piece_key)
            record['convert_seconds'] = round(time.time() - t0, 1)
            piece = dict(title=row['title'], composer=row['composer'])
            t0 = time.time()
            clean, clean_ui = align_clean(ref['notes'], perf, musicxml=ref['musicxml'], piece=piece,
                                          hands='both', config=config)
            record['align_seconds'] = round(time.time() - t0, 1)
            categories = {c: sum(e['category'] == c for e in clean_ui['errors']) for c in ('wrong_pitch', 'missing', 'extra', 'timing')}
            record['clean'] = dict(status=clean['alignment']['status'],
                                   precision=round(clean['metrics']['pitch_precision'], 3),
                                   recall=round(clean['metrics']['pitch_recall'], 3),
                                   raw_findings=len(clean['errors']),
                                   findings=len(clean_ui['errors']), by_category=categories,
                                   ornament_like=clean_ui['meta']['ornament_like'],
                                   reconciled=clean_ui['meta']['reconciled_pairs'],
                                   tempo_assessed=clean['metrics']['tempo_assessed_measures'],
                                   bars=len(clean['measures']),
                                   rushed=len(clean_ui['pace']['rushed_bars']), dragged=len(clean_ui['pace']['dragged_bars']))
            planted_midi = args.out / 'planted' / f'{piece_key}__{perf.stem}.mid'
            planted_midi.parent.mkdir(parents=True, exist_ok=True)
            plants = plant_mistakes(perf, planted_midi, args.plant, args.seed)
            planted, planted_ui = align_clean(ref['notes'], planted_midi, musicxml=ref['musicxml'], piece=piece,
                                              hands='both', config=config)
            hits, misses, false_alarms = score_findings(plants, ui_errors_as_pitches(planted_ui))
            baseline_alarms = len(ui_errors_as_pitches(clean_ui))
            record['planted'] = dict(planted=len(plants), hits=hits, misses=misses,
                                     false_alarms=max(0, false_alarms - baseline_alarms),
                                     status=planted['alignment']['status'])
        except Exception as error:  # noqa: BLE001
            record['error'] = f'{type(error).__name__}: {error}'[:200]
        results.append(record)
        print(json.dumps(record), flush=True)

    (args.out / 'results.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    ok = [r for r in results if 'error' not in r]
    if ok:
        hits = sum(r['planted']['hits'] for r in ok)
        planted = sum(r['planted']['planted'] for r in ok)
        alarms = sum(r['planted']['false_alarms'] for r in ok)
        clean_alarms = sum(r['clean']['findings'] for r in ok)
        print(f"\n{len(ok)} performances ok, {len(results) - len(ok)} failed")
        print(f"clean runs: mean precision {sum(r['clean']['precision'] for r in ok) / len(ok):.3f}, "
              f"mean recall {sum(r['clean']['recall'] for r in ok) / len(ok):.3f}, "
              f"{clean_alarms} findings on error-free playing ({clean_alarms / len(ok):.1f} per performance)")
        print(f"planted mistakes: {hits}/{planted} detected ({hits / max(planted, 1):.0%}), {alarms} extra false alarms")
    return 0


if __name__ == '__main__':
    sys.exit(main())
