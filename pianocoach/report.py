"""Build the JSON that pianocoach-ui/index.html renders.

Inputs are the converter's reference.json (score notes with measure and beat),
the alignment report from `alignment.align_performance`, and optionally the
transcriber's notes.json (for per-note model scores) and the score's MusicXML
(for title, composer, key and time signature).

The page draws one staff: the right hand. Left-hand findings are left out by
default (`hands='right'`) because the page has nowhere to draw them; pass
`hands='both'` to keep them in the list anyway.

Nothing here decides correctness. It reshapes, estimates confidence, and
writes plain fallback text that `pianocoach.explain` can replace.
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import median

import numpy as np
from music21 import pitch as m21pitch

CATEGORY_ORDER = {'wrong_pitch': 0, 'missing': 1, 'extra': 2, 'timing': 3, 'duration': 4, 'unsure': 5}
# Partials of a struck piano string that Basic Pitch sometimes reports as notes.
HARMONIC_INTERVALS = {12, 19, 24, 28, 31}


def _read_json(value):
    if isinstance(value, (str, Path)):
        return json.loads(Path(value).read_text(encoding='utf-8'))
    return value


def pitch_name(midi, flats=False, sharps=False):
    """Spell a MIDI pitch the way the page expects: C, C#/Db, ... with octave.
    Flat keys spell black keys as flats, sharp keys as sharps; otherwise music21's default."""
    p = m21pitch.Pitch(midi=int(midi))
    alter = p.accidental.alter if p.accidental is not None else 0
    if (flats and alter > 0) or (sharps and alter < 0):
        p = p.getEnharmonic()
    return p.nameWithOctave.replace('-', 'b')


def score_metadata(musicxml):
    """Title, composer, time signature and key from the score, when available."""
    meta = {}
    if musicxml is None or not Path(musicxml).is_file():
        return meta
    from music21 import converter, key, meter
    score = converter.parse(str(musicxml))
    md = score.metadata
    if md is not None:
        if md.title:
            meta['title'] = str(md.title)
        if md.composer:
            meta['composer'] = str(md.composer)
    ts = score.recurse().getElementsByClass(meter.TimeSignature).first()
    if ts is not None:
        meta['time_signature'] = [int(ts.numerator), int(ts.denominator)]
    ks = score.recurse().getElementsByClass(key.KeySignature).first()
    if ks is not None:
        meta['sharps'] = int(ks.sharps)
    return meta


def _right_hand_part(notes):
    by_part = defaultdict(list)
    for n in notes:
        by_part[n['part']].append(n['pitch'])
    if len(by_part) <= 1:
        return next(iter(by_part), None)
    return max(by_part, key=lambda p: median(by_part[p]))


def _infer_time_signature(bar_beats):
    if abs(bar_beats - round(bar_beats)) < 1e-6:
        return [int(round(bar_beats)), 4]
    return [int(round(bar_beats * 2)), 8]


def _round(value, digits=3):
    return float(round(value + 0.0, digits))


def build_ui_report(reference, alignment, *, performance_notes=None, musicxml=None,
                    piece=None, take_number=1, audio_duration=None, hands='right',
                    drop_harmonics=True):
    reference = _read_json(reference)
    alignment = _read_json(alignment)
    if hands not in ('right', 'both'):
        raise ValueError("hands must be 'right' or 'both'")

    played = {}
    if performance_notes is not None:
        data = _read_json(performance_notes)
        records = data['notes'] if isinstance(data, dict) else data
        for raw in records:
            n = raw if isinstance(raw, dict) else raw.__dict__
            played[str(n['id'])] = n

    meta = score_metadata(musicxml)
    piece = dict(piece or {})
    chunks = reference['chunks']
    if not chunks:
        raise ValueError('reference.json has no measure chunks; convert with measures_per_chunk=1.')
    bar_beats = chunks[0]['end_beat'] - chunks[0]['start_beat']
    time_signature = piece.get('time_signature') or meta.get('time_signature') or _infer_time_signature(bar_beats)
    if not all(1 <= int(v) <= 16 for v in time_signature):
        time_signature = _infer_time_signature(bar_beats)
    if not all(1 <= int(v) <= 16 for v in time_signature):
        time_signature = [min(16, max(1, int(round(bar_beats)))), 4]
    bpb, denominator = int(time_signature[0]), int(time_signature[1])
    unit = denominator / 4.0  # quarter-note beats -> beats of the time signature
    key_sharps = piece.pop('sharps', None) if 'sharps' in piece else meta.get('sharps', 0)
    flats, sharps = key_sharps < 0, key_sharps > 0

    ref_notes = {n['id']: n for n in reference['notes']}
    rh_part = _right_hand_part(reference['notes'])

    # Printed measure numbers -> page measure index, in first-occurrence order.
    first_chunk, ui_measure = {}, {}
    for chunk in chunks:
        printed = chunk['measures'][0]
        if printed not in first_chunk:
            first_chunk[printed] = chunk
            ui_measure[printed] = len(ui_measure) + 1
    occurrence_chunk = {chunk['measure_occurrence']: chunk for chunk in chunks}

    def beat_in_bar(onset, chunk):
        return _round(1 + (onset - chunk['start_beat']) * unit)

    # Right-hand notes of each measure's first occurrence, in the page's order.
    ui_notes, slot_of, rh_low = [], {}, {}
    for printed, chunk in first_chunk.items():
        m = ui_measure[printed]
        rows = []
        for entry in chunk['notes']:
            n = ref_notes[entry['note_id']]
            if entry.get('carried_in') or n['part'] != rh_part:
                continue
            rows.append((beat_in_bar(n['onset'], chunk), n['pitch'], n['duration'] * unit))
        rows.sort()
        for index, (beat, midi, dur) in enumerate(rows, 1):
            beat = min(beat, bpb + 1 - 1e-3)
            ui_notes.append([m, beat, pitch_name(midi, flats, sharps), _round(max(dur, 1e-3))])
            slot_of[(m, beat, midi)] = f'n{m}-{index}'
        if rows:
            rh_low[m] = min(r[1] for r in rows)
    if not ui_notes:
        raise ValueError('No right-hand notes found in the reference.')

    def note_slot(score_note_id):
        n = ref_notes.get(score_note_id)
        if n is None or n['part'] != rh_part:
            return None
        chunk = occurrence_chunk.get(_occurrence_of(n, chunks))
        if chunk is None:
            return None
        beat = min(beat_in_bar(n['onset'], chunk), bpb + 1 - 1e-3)
        return slot_of.get((ui_measure[chunk['measures'][0]], beat, n['pitch']))

    anchors = alignment.get('alignment', {}).get('anchors', [])
    anchor_beats = [a['score_beat'] for a in anchors]
    anchor_times = [a['audio_time'] for a in anchors]

    measures_in_order = alignment['measures']
    position = {(b['number'], b['occurrence']): i for i, b in enumerate(measures_in_order)}

    def nearest_fit(bar):
        """The tempo fit of the closest bar that has one, for bars the aligner could not anchor."""
        i = position.get((bar['number'], bar['occurrence']))
        if i is None:
            return None
        for step in range(1, len(measures_in_order)):
            for j in (i - step, i + step):
                if 0 <= j < len(measures_in_order) and measures_in_order[j].get('tempo_fit'):
                    return measures_in_order[j]['tempo_fit']
        return None

    def time_at_beat(score_beat, bar):
        fit = bar.get('tempo_fit') if bar else None
        if fit is None and bar is not None:
            fit = nearest_fit(bar)
        if fit:
            return fit['intercept'] + fit['seconds_per_beat'] * score_beat
        if len(anchor_beats) >= 2:
            if anchor_beats[0] <= score_beat <= anchor_beats[-1]:
                return float(np.interp(score_beat, anchor_beats, anchor_times))
            # extrapolate from the nearest anchor pair instead of clamping
            (b0, t0), (b1, t1) = ((anchor_beats[0], anchor_times[0]), (anchor_beats[1], anchor_times[1])) \
                if score_beat < anchor_beats[0] else ((anchor_beats[-2], anchor_times[-2]), (anchor_beats[-1], anchor_times[-1]))
            slope = (t1 - t0) / (b1 - b0) if b1 != b0 else 0.0
            return t0 + slope * (score_beat - b0)
        return anchor_times[0] if anchor_times else 0.0

    def beat_at_time(audio_time):
        if len(anchor_beats) >= 2:
            return float(np.interp(audio_time, anchor_times, anchor_beats))
        return None

    bars = {(b['number'], b['occurrence']): b for b in alignment['measures']}
    source = alignment.get('performance_source', 'audio')
    matched_played = [m for m in alignment['matches']
                      if m['category'] in ('correct', 'wrong_pitch') and m['audio_time'] is not None]

    def harmonic_of_matched(err):
        """Overtone above a note that was really played, or a false fundamental an
        octave below one (a known Basic Pitch failure on bass notes)."""
        for m in matched_played:
            if abs(m['audio_time'] - err['audio_time']) <= 0.06:
                interval = err['actual_pitch'] - m['actual_pitch']
                if interval in HARMONIC_INTERVALS or interval == -12:
                    return True
        return False

    def tier_of(confidence):
        return 'confident' if confidence >= 0.8 else 'likely' if confidence >= 0.65 else 'possible'

    def place_by_time(audio_time):
        """Bar for a played note the aligner could not place (before the first or
        after the last anchor): the bar whose fitted span contains it, else the
        nearest bar edge."""
        spans = [(b['estimated_start_seconds'], b['estimated_end_seconds'], b) for b in alignment['measures']
                 if b.get('estimated_start_seconds') is not None]
        for start, end, b in spans:
            if start <= audio_time < end:
                return b['number'], b['occurrence']
        if spans:
            start, end, b = min(spans, key=lambda s: min(abs(audio_time - s[0]), abs(audio_time - s[1])))
            return b['number'], b['occurrence']
        first, last = alignment['measures'][0], alignment['measures'][-1]
        edge = first if (not anchor_times or audio_time <= anchor_times[0]) else last
        return edge['number'], edge['occurrence']

    errors, dropped, omitted, placed = [], 0, 0, 0
    for err in alignment['errors']:
        category = err['category']
        if category not in CATEGORY_ORDER:
            omitted += 1
            continue
        if err['measure'] is None:
            if category != 'extra' or err['audio_time'] is None:
                omitted += 1
                continue
            err = dict(err)
            err['measure'], err['measure_occurrence'] = place_by_time(err['audio_time'])
            placed += 1
        bar = bars.get((err['measure'], err['measure_occurrence']))
        chunk = occurrence_chunk.get(err['measure_occurrence'])
        if chunk is None:
            omitted += 1
            continue
        m = ui_measure[err['measure']]
        slot = note_slot(err['score_note_id']) if err['score_note_id'] else None
        # Left-hand findings are decided now but removed only after the repairs
        # below, so a left-hand note can still pair with its own stray extra.
        left_hand = (bool(err['score_note_id']) and slot is None) or \
                    (category == 'extra' and err['actual_pitch'] < rh_low.get(m, 0) - 5)
        if category == 'extra' and drop_harmonics and harmonic_of_matched(err):
            dropped += 1
            continue
        if err['score_beat'] is not None:
            beat = beat_in_bar(err['score_beat'], chunk)
            audio_time = err['audio_time'] if err['audio_time'] is not None else time_at_beat(err['score_beat'], bar)
        else:
            audio_time = err['audio_time']
            absolute = beat_at_time(audio_time)
            beat = beat_in_bar(absolute, chunk) if absolute is not None else 1.0
        beat = float(min(max(beat, 1.0), bpb + 1 - 1e-3))
        audio_time = float(max(0.0, audio_time if audio_time is not None else 0.0))

        played_note = played.get(err['performance_note_id']) if err['performance_note_id'] else None
        model_score = played_note.get('model_score') if played_note else None
        if source == 'midi':
            confidence = 0.95
        elif category == 'wrong_pitch':
            confidence = 0.5 + 0.45 * (model_score if model_score is not None else 0.7)
        elif category == 'extra':
            confidence = 0.45 + 0.4 * (model_score if model_score is not None else 0.5)
        elif category == 'missing':
            confidence = 0.7
        else:
            confidence = 0.8
        entry = dict(id=f'err-{len(errors) + 1}', category=category, measure=m, beat=beat,
                     note_id=slot,
                     expected=pitch_name(err['expected_pitch'], flats, sharps) if err['expected_pitch'] is not None else None,
                     actual=pitch_name(err['actual_pitch'], flats, sharps) if err['actual_pitch'] is not None else None,
                     audio_time=_round(audio_time, 3))
        if category == 'timing':
            delta = err['onset_error_seconds'] or 0.0
            entry['delta_ms'] = int(round(delta * 1000))
            if abs(entry['delta_ms']) < 40:
                confidence -= 0.2
            if entry['delta_ms'] == 0:
                omitted += 1
                continue
        confidence = float(min(0.99, max(0.05, confidence)))
        entry['confidence'] = _round(confidence, 2)
        entry['tier'] = tier_of(confidence)
        entry['_score_beat'] = err['score_beat']
        entry['_left_hand'] = left_hand
        entry['_occurrence'] = err['measure_occurrence']
        errors.append(entry)

    # A partial take (the student stopped early, or started mid-piece) must not
    # bury the page in missing notes for bars that were never attempted.
    played_span = _played_span(alignment, chunks)
    if played_span:
        errors = [e for e in errors if e['category'] != 'missing' or e.get('_occurrence') is None
                  or played_span[0] <= e['_occurrence'] <= played_span[1]]
        # In a partial take the student may have stopped mid-bar: notes after the
        # last one they played were not skipped, they were never reached.
        partial = (played_span[1] - played_span[0] + 1) < 0.8 * len(chunks)
        last_played_beat = max((m['score_beat'] for m in alignment['matches']
                                if m['category'] == 'correct' and m['score_beat'] is not None
                                and m['measure_occurrence'] is not None
                                and played_span[0] <= m['measure_occurrence'] <= played_span[1]), default=None)
        if partial and last_played_beat is not None:
            errors = [e for e in errors if e['category'] != 'missing' or e.get('_score_beat') is None
                      or e['_score_beat'] <= last_played_beat + 1e-6]
    else:
        errors = [e for e in errors if e['category'] != 'missing']
    errors = _repair_same_pitch(errors, bars, ui_measure, occurrence_chunk, time_at_beat, unit)
    errors, reconciled = _reconcile_missing_extra(errors, bars, ui_measure, time_at_beat, unit)
    errors, octaves = _reconcile_octaves(errors, bars, ui_measure, time_at_beat)
    ornaments = _tag_ornaments(errors, matched_played)
    if hands == 'right':
        omitted += sum(1 for e in errors if e.get('_left_hand'))
        errors = [e for e in errors if not e.get('_left_hand')]
    for e in errors:
        e.pop('_score_beat', None)
        e.pop('_left_hand', None)
        e.pop('_occurrence', None)
    errors = _merge_repeat_occurrences(errors)
    if played_span:
        first_bar = ui_measure[occurrence_chunk[played_span[0]]['measures'][0]]
        last_bar = ui_measure[occurrence_chunk[played_span[1]]['measures'][0]]
        played_bars = [first_bar, last_bar]
        coverage = (played_span[1] - played_span[0] + 1) / len(chunks)
    else:
        played_bars, coverage = None, 0.0
    errors.sort(key=lambda e: (e['measure'], e['beat'], CATEGORY_ORDER[e['category']]))
    for index, e in enumerate(errors, 1):
        e['id'] = f'err-{index}'
        e['explanation'], e['tip'] = fallback_text(e, _bar_for(e, bars, ui_measure), time_signature)

    tempi = reference.get('tempo_changes') or [[0, 120]]
    marked_bpm = float(tempi[0][1])
    performed = [b['performed_average_bpm'] for b in alignment['measures'] if b.get('performed_average_bpm')]
    take_bpm = float(median(performed)) if performed else marked_bpm
    pace_rows, rushed, dragged = [], [], []
    for b in alignment['measures']:
        bpm = b.get('performed_average_bpm')
        ratio = (bpm / take_bpm) if (bpm and take_bpm) else None
        status = ('steady' if ratio is None else 'rushed' if ratio > 1.12 else 'dragged' if ratio < 0.88 else 'steady')
        if b['tempo_status'] in ('unassessed', 'irregular'):
            status = b['tempo_status']
        pace_rows.append((ui_measure[b['number']], ratio, status))
        if status == 'rushed':
            rushed.append(ui_measure[b['number']])
        elif status == 'dragged':
            dragged.append(ui_measure[b['number']])
    pace = {m: (ratio, status) for m, ratio, status in pace_rows}
    if audio_duration is None:
        times = [m['audio_time'] for m in alignment['matches'] if m['audio_time'] is not None]
        audio_duration = (max(times) + 1.0) if times else 1.0

    report = dict(
        piece=dict(title=piece.get('title') or meta.get('title') or 'Untitled',
                   catalog=piece.get('catalog') or '',
                   composer=piece.get('composer') or meta.get('composer') or 'Unknown',
                   time_signature=[bpb, denominator],
                   marked_bpm=_round(marked_bpm, 1),
                   measures=len(ui_measure)),
        take=dict(number=int(take_number), source=source, bpm=_round(take_bpm, 1),
                  duration_seconds=_round(float(audio_duration), 2)),
        notes=ui_notes,
        errors=errors,
        bars=[dict(measure=ui_measure[b['number']], printed=b['number'], occurrence=b['occurrence'],
                   tempo_status=b['tempo_status'], tempo_ratio=b['tempo_ratio'],
                   performed_bpm=b['performed_average_bpm'], pitch_recall=b['pitch_recall'],
                   pace_ratio=pace[ui_measure[b['number']]][0], pace=pace[ui_measure[b['number']]][1],
                   start_seconds=b['estimated_start_seconds'], end_seconds=b['estimated_end_seconds'])
              for b in alignment['measures']],
        pace=dict(median_bpm=_round(take_bpm, 1), marked_bpm=_round(marked_bpm, 1),
                  rushed_bars=sorted(set(rushed)), dragged_bars=sorted(set(dragged))),
        meta=dict(alignment_status=alignment['alignment']['status'],
                  pitch_precision=alignment['metrics']['pitch_precision'],
                  pitch_recall=alignment['metrics']['pitch_recall'],
                  hands=hands, dropped_harmonics=dropped, omitted_findings=omitted,
                  reconciled_pairs=reconciled, octave_pairs=octaves, ornament_like=ornaments, placed_extras=placed,
                  played_bars=played_bars, coverage=_round(coverage, 2),
                  warnings=list(alignment.get('warnings', [])),
                  explanations='fallback'),
    )
    if played_bars is None:
        report['coach'] = 'No notes from the score were heard in this take, so nothing is marked.'
    elif coverage < 0.8:
        a, b = played_bars
        report['coach'] = (f'You played bar {a} on its own, so only that bar is marked.' if a == b
                           else f'You played bars {a} to {b}, so only those bars are marked.')
    validate_ui_report(report)
    return report


def _played_span(alignment, chunks):
    """(first, last) measure occurrence the student actually played, or None.

    Bars where at least half the notes matched are solid. The time of the first
    and last played note, mapped to score beats through a tempo line fitted on
    the solid bars' anchors, extends that range so a bar the student started
    counts even when most of it went wrong. A lone stray pitch match far away
    does not extend it: pitch-only alignment can pin one note to the wrong bar."""
    solid = [b for b in alignment['measures']
             if b['expected_notes'] and b['correct_notes'] / b['expected_notes'] >= 0.5]
    if not solid:
        return None
    first, last = solid[0]['occurrence'], solid[-1]['occurrence']
    span_beats = [(b['start_beat'], b['end_beat']) for b in solid]
    anchors = [(a['score_beat'], a['audio_time']) for a in alignment['alignment']['anchors']
               if any(s <= a['score_beat'] < e for s, e in span_beats)]
    times = [m['audio_time'] for m in alignment['matches'] if m['audio_time'] is not None]
    if len(anchors) >= 2 and times:
        beats = np.array([a[0] for a in anchors]); secs = np.array([a[1] for a in anchors])
        slope, intercept = np.polyfit(secs, beats, 1)  # beats per second over the solid bars
        if slope > 0:
            for t in (min(times), max(times)):
                beat = intercept + slope * t
                for c in chunks:
                    if c['start_beat'] <= beat < c['end_beat']:
                        first, last = min(first, c['measure_occurrence']), max(last, c['measure_occurrence'])
                        break
    return first, last


def _bar_for(e, bars, ui_measure):
    for (printed, occurrence), bar in bars.items():
        if ui_measure.get(printed) == e['measure']:
            return bar
    return None


def _repair_same_pitch(errors, bars, ui_measure, occurrence_chunk, time_at_beat, unit):
    """The aligner matches by pitch sequence only. When a bar repeats a pitch and
    one of them was not played, it can pair the played note with the wrong slot
    and report a missing note plus a large timing error on its twin. A student
    would say one of the two was skipped, so re-pair by time: the played note
    takes the slot it is closest to and the other slot becomes the missing one."""
    by_bar = {}
    for e in errors:
        by_bar.setdefault(e['measure'], []).append(e)
    repaired = []
    for measure, group in by_bar.items():
        drop = set()
        missing = [e for e in group if e['category'] == 'missing']
        timing = [e for e in group if e['category'] == 'timing' and e['_score_beat'] is not None]
        for t in timing:
            for m in missing:
                if m['expected'] != t['expected'] or id(m) in drop or id(t) in drop or m['_score_beat'] is None:
                    continue
                bar = _bar_for(t, bars, ui_measure)
                predicted = time_at_beat(m['_score_beat'], bar)
                residual_if_swapped = abs(t['audio_time'] - predicted)
                if residual_if_swapped < abs(t['delta_ms']) / 1000.0:
                    # the played note really belongs to the missing slot; the timing slot is the one unplayed
                    m['beat'], m['note_id'], m['_score_beat'] = t['beat'], t['note_id'], t['_score_beat']
                    m['audio_time'] = _round(max(0.0, time_at_beat(t['_score_beat'], bar)), 3)
                    drop.add(id(t))
                    break
        repaired.extend(e for e in group if id(e) not in drop)
    return repaired


def _reconcile_missing_extra(errors, bars, ui_measure, time_at_beat, unit):
    """A missing note and an extra of the same pitch a few tens of milliseconds
    apart is one note the aligner split across two onset groups (a spread chord,
    a slightly early or late attack). Pair them: within the timing tolerance
    they cancel; beyond it the pair becomes a single timing finding."""
    missing = [e for e in errors if e['category'] == 'missing' and e.get('_score_beat') is not None]
    extras = [e for e in errors if e['category'] == 'extra']
    drop, reconciled = set(), 0
    for m in missing:
        bar = _bar_for(m, bars, ui_measure)
        fit = bar.get('tempo_fit') if bar else None
        spb = fit['seconds_per_beat'] if fit else 0.5
        predicted = time_at_beat(m['_score_beat'], bar)
        window = max(0.25, 0.5 * spb)
        tolerance = max(0.10, 0.20 * spb)
        best = None
        for x in extras:
            if id(x) in drop or x['actual'] != m['expected'] or abs(x['measure'] - m['measure']) > 1:
                continue
            if bool(x.get('_left_hand')) != bool(m.get('_left_hand')) and m.get('note_id') is not None:
                continue
            gap = x['audio_time'] - predicted
            if abs(gap) <= window and (best is None or abs(gap) < abs(best[0])):
                best = (gap, x)
        if best is None:
            continue
        gap, x = best
        drop.add(id(x))
        reconciled += 1
        if abs(gap) <= tolerance:
            drop.add(id(m))
        else:
            m['category'] = 'timing'
            m['actual'] = m['expected']
            m['audio_time'] = x['audio_time']
            m['delta_ms'] = int(round(gap * 1000))
            m['confidence'] = _round(min(0.99, x['confidence']), 2)
            m['tier'] = 'confident' if m['confidence'] >= 0.8 else 'likely' if m['confidence'] >= 0.65 else 'possible'
    return [e for e in errors if id(e) not in drop], reconciled


def _reconcile_octaves(errors, bars, ui_measure, time_at_beat):
    """A missing note and an extra exactly one or two octaves away at the same
    moment is the right key in the wrong octave, which the aligner cannot say
    because it caps pitch substitutions at an octave. Report it as a wrong
    pitch so the page shows "D6 came out as D5" instead of two findings."""
    missing = [e for e in errors if e['category'] == 'missing' and e.get('_score_beat') is not None]
    extras = [e for e in errors if e['category'] == 'extra']
    drop, paired = set(), 0
    for m in missing:
        bar = _bar_for(m, bars, ui_measure)
        fit = bar.get('tempo_fit') if bar else None
        spb = fit['seconds_per_beat'] if fit else 0.5
        predicted = time_at_beat(m['_score_beat'], bar)
        window = max(0.25, 0.5 * spb)
        expected_midi = m21pitch.Pitch(m['expected']).midi
        best = None
        for x in extras:
            if id(x) in drop or abs(x['measure'] - m['measure']) > 1:
                continue
            if abs(m21pitch.Pitch(x['actual']).midi - expected_midi) not in (12, 24):
                continue
            gap = abs(x['audio_time'] - predicted)
            if gap <= window and (best is None or gap < best[0]):
                best = (gap, x)
        if best is None:
            continue
        _, x = best
        drop.add(id(x))
        paired += 1
        m['category'] = 'wrong_pitch'
        m['actual'] = x['actual']
        m['audio_time'] = x['audio_time']
        m['octave'] = True
        m['confidence'] = _round(min(0.99, max(m['confidence'], x['confidence'])), 2)
        m['tier'] = 'confident' if m['confidence'] >= 0.8 else 'likely' if m['confidence'] >= 0.65 else 'possible'
    return [e for e in errors if id(e) not in drop], paired


def _tag_ornaments(errors, matched_played):
    """An extra a step or two away from a correctly played note at nearly the
    same instant is more likely a trill, mordent or brush than a wrong key.
    Keep it, but as a low-confidence possibility the text can hedge on."""
    count = 0
    for e in errors:
        if e['category'] != 'extra':
            continue
        actual = m21pitch.Pitch(e['actual']).midi
        for m in matched_played:
            if abs(m['audio_time'] - e['audio_time']) <= 0.12 and 0 < abs(m['actual_pitch'] - actual) <= 2:
                e['maybe_ornament'] = True
                e['confidence'] = _round(min(e['confidence'], 0.45), 2)
                e['tier'] = 'possible'
                count += 1
                break
    return count


def _merge_repeat_occurrences(errors):
    """With repeats expanded, the same printed bar is played more than once. The
    page draws each printed bar once, so identical findings from different passes
    collapse into one that says how many times it happened."""
    merged, index = [], {}
    for e in errors:
        key = (e['measure'], round(e['beat'], 2), e['category'], e.get('expected'), e.get('actual'))
        if key in index:
            first = merged[index[key]]
            first['occurrences'] = first.get('occurrences', 1) + 1
            first['confidence'] = _round(min(0.99, max(first['confidence'], e['confidence']) + 0.05), 2)
            first['tier'] = 'confident' if first['confidence'] >= 0.8 else 'likely' if first['confidence'] >= 0.65 else 'possible'
            first.setdefault('audio_times', [first['audio_time']]).append(e['audio_time'])
            continue
        index[key] = len(merged)
        merged.append(e)
    return merged


def _occurrence_of(note, chunks):
    for chunk in chunks:
        if chunk['start_beat'] <= note['onset'] < chunk['end_beat']:
            return chunk['measure_occurrence']
    return None


def fallback_text(e, bar, time_signature):
    """Plain wording used until Claude writes the real explanation and tip."""
    m, beat = e['measure'], e['beat']
    beat_text = str(int(beat)) if float(beat).is_integer() else str(beat)
    explanation, tip = _fallback_body(e, bar, m, beat_text)
    if e.get('occurrences', 1) > 1:
        explanation += ' It happened both times through the repeat.' if e['occurrences'] == 2 else f" It happened {e['occurrences']} times through."
    return explanation, tip


def _fallback_body(e, bar, m, beat_text):
    if e['category'] == 'wrong_pitch' and e.get('octave'):
        direction = 'lower' if m21pitch.Pitch(e['actual']).midi < m21pitch.Pitch(e['expected']).midi else 'higher'
        return (f"Bar {m}, beat {beat_text}: right note, wrong octave. The score has {e['expected']} and you played {e['actual']}, an octave {direction}.",
                f"Find the {e['expected']} on the keyboard before you start bar {m}, then play the bar once with just that hand.")
    if e['category'] == 'wrong_pitch':
        return (f"Bar {m}, beat {beat_text}: the score has {e['expected']} and you played {e['actual']}.",
                f"Play bar {m} slowly and stop on the {e['expected']}. Say its name before you press it.")
    if e['category'] == 'missing':
        return (f"The {e['expected']} on beat {beat_text} of bar {m} didn't come through. It may have been too soft, or skipped.",
                f"Play bar {m} on its own and make that {e['expected']} the loudest note in the bar until it stops disappearing.")
    if e['category'] == 'extra':
        if e.get('maybe_ornament'):
            return (f"A {e['actual']} sounded in bar {m} right next to a correct note. That could be a brushed key, or an ornament, or the recording.",
                    f"Play bar {m} slowly once and listen for the {e['actual']}. If it isn't there, mark this as fine.")
        return (f"There is a {e['actual']} in bar {m} that isn't in the score.",
                f"Slow bar {m} right down and watch which finger lands on the {e['actual']}.")
    if e['category'] == 'timing':
        direction = 'early' if e['delta_ms'] < 0 else 'late'
        pace = ''
        if bar and bar.get('performed_average_bpm'):
            pace = f" You were playing this bar at about {round(bar['performed_average_bpm'])} bpm."
        return (f"The {e['expected']} landed {abs(e['delta_ms'])} ms {direction} against the pace of the rest of bar {m}.{pace}",
                f"Count out loud through bar {m} with a metronome and let the click arrive before the {e['expected']}.")
    return ('', '')


def validate_ui_report(r):
    """Mirror of validateReport() in pianocoach-ui/index.html, so a bad report fails here first."""
    import re
    finite = lambda n: isinstance(n, (int, float)) and not isinstance(n, bool) and math.isfinite(n)
    is_pitch = lambda p: isinstance(p, str) and re.fullmatch(r'[A-G](#|b)?[0-8]', p) is not None
    if not isinstance(r.get('piece'), dict) or not isinstance(r.get('take'), dict) \
            or not isinstance(r.get('notes'), list) or not isinstance(r.get('errors'), list):
        raise ValueError('report needs piece, take, notes, errors')
    p, t = r['piece'], r['take']
    if not isinstance(p.get('title'), str) or not isinstance(p.get('composer'), str) \
            or not isinstance(p.get('measures'), int) or not 1 <= p['measures'] <= 200:
        raise ValueError('piece needs title, composer and 1-200 measures')
    ts = p.get('time_signature')
    if not isinstance(ts, list) or len(ts) != 2 or any(not isinstance(n, int) or not 1 <= n <= 16 for n in ts):
        raise ValueError('invalid time signature')
    if not all(finite(n) and n > 0 for n in (t.get('bpm'), p.get('marked_bpm'), t.get('duration_seconds'))) \
            or not isinstance(t.get('number'), int) or t['number'] < 1:
        raise ValueError('take needs number, bpm, duration')
    if not r['notes'] or len(r['notes']) > 5000:
        raise ValueError('notes empty or too many')
    for n in r['notes']:
        if not isinstance(n, list) or len(n) != 4 or not isinstance(n[0], int) or not 1 <= n[0] <= p['measures'] \
                or not finite(n[1]) or not 1 <= n[1] < ts[0] + 1 or not is_pitch(n[2]) or not finite(n[3]) or n[3] <= 0:
            raise ValueError(f'invalid score note {n}')
    ids = set()
    for e in r['errors']:
        ok = isinstance(e.get('id'), str) and re.fullmatch(r'[a-zA-Z0-9_-]+', e['id']) and e['id'] not in ids \
            and e.get('category') in CATEGORY_ORDER and isinstance(e.get('measure'), int) \
            and 1 <= e['measure'] <= p['measures'] and finite(e.get('beat')) and 1 <= e['beat'] < ts[0] + 1 \
            and finite(e.get('confidence')) and 0 <= e['confidence'] <= 1 and finite(e.get('audio_time')) \
            and e['audio_time'] >= 0 and (e.get('expected') is None or is_pitch(e['expected'])) \
            and (e.get('actual') is None or is_pitch(e['actual']))
        if not ok:
            raise ValueError(f'invalid finding {e}')
        if (e['category'] != 'extra' and not is_pitch(e.get('expected'))) \
                or (e['category'] in ('wrong_pitch', 'extra') and not is_pitch(e.get('actual'))) \
                or (e['category'] == 'timing' and not finite(e.get('delta_ms'))) \
                or (e['category'] == 'duration' and (not finite(e.get('held_beats')) or e['held_beats'] < 0)):
            raise ValueError(f'finding missing pitch or timing info {e}')
        ids.add(e['id'])
    return r
