"""Plant mistakes into a score and render the result as a piano recording for demos and tests.

    python testing/make_demo_take.py pianocoach/pieces/minuet_in_g.mxl out/minuet-take \\
        --tempo 96 --wrong 3:3.5 --drop 7:2 --rush 5 --late 15:2:150 --lh-wrong 9:1

Mistakes apply to the first time a bar is played (repeats are expanded by the converter).
--wrong M:B[:semitones]  right-hand note at bar M beat B changes pitch (default -1)
--drop M:B               right-hand note is not played
--rush M[:factor]        bar M is played faster (default 0.78 of the beat length)
--late M:B:ms            right-hand note starts late by ms
--lh-wrong M:B[:semi]    left-hand note changes pitch
Writes take.wav, events.json and planted.json into the output directory.
"""

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pianocoach.pipeline import convert_once  # noqa: E402
from testing.render_piano import render  # noqa: E402


def _pair(text, count):
    parts = text.split(':')
    if len(parts) < 2 and count > 1:
        raise argparse.ArgumentTypeError(f'expected bar:beat, got {text}')
    return parts


def build(score, out, *, tempo=96, lead=1.0, wrong=(), drop=(), rush=(), late=(), lh_wrong=()):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    paths = convert_once(score, out / 'score', bpm=tempo)
    ref = json.loads(Path(paths['notes']).read_text(encoding='utf-8'))
    parts = sorted({n['part'] for n in ref['notes']})
    rh = max(parts, key=lambda p: statistics.median(n['pitch'] for n in ref['notes'] if n['part'] == p))
    chunks = ref['chunks']
    first_occurrence = {}
    for c in chunks:
        first_occurrence.setdefault(c['measures'][0], c['measure_occurrence'])
    rush_factor = {int(r.split(':')[0]): float(r.split(':')[1]) if ':' in r else 0.78 for r in rush}
    spb = 60.0 / tempo
    bar_clock, t = {}, lead
    for c in chunks:
        factor = rush_factor.get(c['measures'][0], 1.0) if c['measure_occurrence'] == first_occurrence[c['measures'][0]] else 1.0
        bar_clock[c['measure_occurrence']] = (t, spb * factor)
        t += (c['end_beat'] - c['start_beat']) * spb * factor

    def occurrence(onset):
        for c in chunks:
            if c['start_beat'] <= onset < c['end_beat']:
                return c
        return chunks[-1]

    def hit(spec_list, m, b, part_is_rh):
        for spec in spec_list:
            parts_ = spec.split(':')
            if int(parts_[0]) == m and abs(float(parts_[1]) - b) < 1e-6:
                return parts_
        return None

    events, planted = [], []
    for n in ref['notes']:
        c = occurrence(n['onset'])
        m, occ = c['measures'][0], c['measure_occurrence']
        first = occ == first_occurrence[m]
        b = n['beat_in_measure']
        pitch = n['pitch']
        start, s = bar_clock[occ]
        onset = start + (n['onset'] - c['start_beat']) * s
        is_rh = n['part'] == rh
        if first and is_rh and hit(drop, m, b, True):
            planted.append(dict(kind='missing', bar=m, beat=b, pitch=pitch))
            continue
        spec = hit(wrong, m, b, True) if (first and is_rh) else None
        if spec:
            delta = int(spec[2]) if len(spec) > 2 else -1
            planted.append(dict(kind='wrong_pitch', bar=m, beat=b, expected=pitch, actual=pitch + delta))
            pitch += delta
        spec = hit(lh_wrong, m, b, False) if (first and not is_rh) else None
        if spec:
            delta = int(spec[2]) if len(spec) > 2 else 1
            planted.append(dict(kind='wrong_pitch_left_hand', bar=m, beat=b, expected=pitch, actual=pitch + delta))
            pitch += delta
        spec = hit(late, m, b, True) if (first and is_rh) else None
        if spec:
            onset += int(spec[2]) / 1000.0
            planted.append(dict(kind='timing', bar=m, beat=b, pitch=pitch, delta_ms=int(spec[2])))
        events.append(dict(start_seconds=round(onset, 4), end_seconds=round(onset + n['duration'] * s * 0.9, 4),
                           pitch=pitch, velocity=85 if is_rh else 70))
    for bar, factor in rush_factor.items():
        planted.append(dict(kind='rushed_bar', bar=bar, factor=factor))
    (out / 'events.json').write_text(json.dumps(events), encoding='utf-8')
    (out / 'planted.json').write_text(json.dumps(planted, indent=2), encoding='utf-8')
    duration = render(events, out / 'take.wav')
    return out / 'take.wav', planted, duration


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('score')
    parser.add_argument('out')
    parser.add_argument('--tempo', type=float, default=96)
    parser.add_argument('--lead', type=float, default=1.0)
    parser.add_argument('--wrong', action='append', default=[])
    parser.add_argument('--drop', action='append', default=[])
    parser.add_argument('--rush', action='append', default=[])
    parser.add_argument('--late', action='append', default=[])
    parser.add_argument('--lh-wrong', action='append', default=[])
    args = parser.parse_args(argv[1:])
    wav, planted, duration = build(args.score, args.out, tempo=args.tempo, lead=args.lead, wrong=args.wrong,
                                   drop=args.drop, rush=args.rush, late=args.late, lh_wrong=args.lh_wrong)
    print(f'{wav} {duration:.1f}s')
    for p in planted:
        print('  planted', p)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
