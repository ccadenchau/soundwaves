"""Pitch comparison and independent robust timing fits for each measure."""

import json
from dataclasses import asdict
from pathlib import Path

import numpy as np

from .inputs import load_performance, load_score
from .matching import assign_chord, onset_groups, sequence_alignment
from .models import AlignmentConfig


def _reference_seconds(beat, tempi):
    total = 0.0
    for index, (start, bpm) in enumerate(tempi):
        stop = tempi[index + 1][0] if index + 1 < len(tempi) else beat
        if beat <= start:
            break
        total += (min(beat, stop) - start) * 60 / bpm
    return total


def _fit_bar(anchors, start, end):
    own = [(b, t) for b, t in anchors if start <= b < end]
    points = own + [(b, t) for b, t in anchors if abs(b - end) < 1e-6]
    # A boundary anchor may measure a one-note bar, but not an empty bar.
    if not own or len(points) < 2 or points[-1][0] - points[0][0] < (end - start) * 0.25:
        return None
    # Bound quadratic fitting work on dense measures, preserving endpoints.
    points = [points[i] for i in np.unique(np.linspace(0, len(points) - 1, min(64, len(points))).astype(int))]
    slopes = [(t2 - t1) / (b2 - b1)
              for i, (b1, t1) in enumerate(points)
              for b2, t2 in points[i + 1:] if b2 > b1 and t2 > t1]
    if not slopes:
        return None
    slope = float(np.median(slopes))
    intercept = float(np.median([t - slope * b for b, t in points]))
    residual = float(np.median([abs(t - (intercept + slope * b)) for b, t in points]))
    return dict(seconds_per_beat=slope, intercept=intercept,
                anchor_count=len(points), median_residual_seconds=residual)


def _merge_split_notes(matches, anchors):
    """A missing note and an extra of the same pitch right next to it are one note.

    The aligner groups attacks into chords with a fixed window, so a chord note that lands a
    little late (or a transcriber that stamps it late) falls into its own group: the score
    note is reported missing and the played note extra. When the extra has the missing note's
    pitch and sounds within about half a beat of where that score note should fall, they are
    merged into one correct match; any real lateness is then judged as timing, not as a
    wrong note."""
    if len(anchors) < 2:
        return matches
    beats, times = [a[0] for a in anchors], [a[1] for a in anchors]
    if beats[-1] <= beats[0] or times[-1] <= times[0]:
        return matches
    seconds_per_beat = (times[-1] - times[0]) / (beats[-1] - beats[0])
    window = max(0.25, 0.5 * seconds_per_beat)
    extras = [m for m in matches if m['category'] == 'extra' and m['audio_time'] is not None]
    drop = set()
    for missing in matches:
        if missing['category'] != 'missing' or missing['score_beat'] is None:
            continue
        predicted = float(np.interp(missing['score_beat'], beats, times))
        near = [x for x in extras if id(x) not in drop and x['actual_pitch'] == missing['expected_pitch']
                and abs(x['audio_time'] - predicted) <= window]
        if not near:
            continue
        extra = min(near, key=lambda x: abs(x['audio_time'] - predicted))
        drop.add(id(extra))
        for key in ('performance_note_id', 'audio_time', 'actual_pitch',
                    'performance_duration_seconds', 'performance_velocity'):
            missing[key] = extra[key]
        missing['category'] = 'correct'
    return [m for m in matches if id(m) not in drop]


def align_performance(reference, performance, output_path=None, *, config=None):
    """Return a JSON-serializable report; optionally save it without overwriting.

    reference: converter reference.json path or parsed dictionary.
    performance: transcription result, notes.json path/dict, played-note
        iterable (seconds), or MIDI path. Supply the complete score passage.
    No transcription, audio cleaning, or score conversion runs here.
    """
    config = config or AlignmentConfig()
    config.validate()
    _, score, bars, tempi = load_score(reference)
    played, source_type, warnings = load_performance(performance)
    sg = onset_groups(score, config.score_chord_window_beats)
    pg = onset_groups(played, config.chord_window_seconds)
    sequence, cost = sequence_alignment(sg, pg, config.maximum_alignment_cells)
    anchors, matches = [], []
    for si, pi in sequence:
        sgroup = sg[si] if si is not None else None
        pgroup = pg[pi] if pi is not None else None
        if sgroup and pgroup and sgroup['pitches'] & pgroup['pitches']:
            anchors.append((sgroup['onset'], pgroup['onset']))
        for s, p in assign_chord(sgroup['notes'] if sgroup else [], pgroup['notes'] if pgroup else []):
            category = ('extra' if s is None else 'missing' if p is None else
                        'correct' if s['pitch'] == p['pitch'] else 'wrong_pitch')
            matches.append(dict(score_note_id=s['id'] if s else None,
                                performance_note_id=p['id'] if p else None,
                                score_beat=s['onset'] if s else None,
                                alignment_beat=sgroup['onset'] if sgroup else None,
                                audio_time=p['onset'] if p else None,
                                expected_pitch=s['pitch'] if s else None,
                                actual_pitch=p['pitch'] if p else None,
                                category=category, onset_error_seconds=None,
                                score_duration_beats=s['duration'] if s else None,
                                performance_duration_seconds=p['duration'] if p else None,
                                score_velocity=s.get('velocity') if s else None,
                                performance_velocity=p.get('velocity') if p else None,
                                duration_ratio=None, relative_dynamics_delta=None,
                                measure=None, measure_occurrence=None))
    # Extras get a score-location estimate from surrounding sequence anchors,
    # never from the reference's absolute timestamps.
    def extra_beat(time):
        if not anchors:
            return None
        if time < anchors[0][1] or time > anchors[-1][1]:
            return None
        return float(np.interp(time, [t for _, t in anchors], [b for b, _ in anchors]))

    matches = _merge_split_notes(matches, anchors)
    correct_total = sum(m['category'] == 'correct' for m in matches)
    recall = correct_total / len(score)
    precision = correct_total / len(played) if played else 0.0
    reliable = (bool(anchors) and recall >= config.minimum_pitch_recall
                and precision >= config.minimum_pitch_recall)
    correct_matches = [m for m in matches if m['category'] == 'correct']
    score_velocities = [m['score_velocity'] for m in correct_matches if m['score_velocity'] is not None]
    played_velocities = [m['performance_velocity'] for m in correct_matches if m['performance_velocity'] is not None]
    # Use the matched notes' average velocity as the recording-level calibration point.
    score_velocity_center = float(np.mean(score_velocities)) if score_velocities else None
    played_velocity_center = float(np.mean(played_velocities)) if played_velocities else None
    dynamics_assessable = (len(score_velocities) >= 4 and len(played_velocities) >= 4
                           and float(np.percentile(score_velocities, 90) - np.percentile(score_velocities, 10)) >= 8)
    for match in correct_matches:
        if dynamics_assessable and match['score_velocity'] is not None and match['performance_velocity'] is not None:
            # Compare each note with its source's average matched-note loudness.
            match['relative_dynamics_delta'] = ((match['performance_velocity'] - played_velocity_center)
                                                - (match['score_velocity'] - score_velocity_center))
    warnings = list(warnings)
    if not reliable:
        warnings.append('Insufficient pitch agreement for reliable alignment; discrepancies are candidates and tempo feedback is withheld.')
    warnings.append('Alignment is monotone and heuristic. Repeated identical passages, skipped/replayed bars, and partial takes can be ambiguous; inspect matches before grading.')
    if source_type != 'midi':
        warnings.append('Audio detections have uncalibrated confidence; discrepancies may come from transcription rather than playing.')
    measure_reports, errors = [], []
    for bar in bars:
        start, end = bar['start_beat'], bar['end_beat']
        local = []
        for match in matches:
            beat = match['score_beat'] if match['score_beat'] is not None else match['alignment_beat']
            if beat is None:
                beat = extra_beat(match['audio_time'])
            if beat is not None and start <= beat < end:
                match['measure'], match['measure_occurrence'] = bar['number'], bar['occurrence']
                local.append(match)
        expected = sum(m['score_note_id'] is not None for m in local)
        correct = sum(m['category'] == 'correct' for m in local)
        local_recall = correct / expected if expected else None
        fit = _fit_bar(anchors, start, end) if reliable and local_recall is not None and local_recall >= config.minimum_pitch_recall else None
        reference_duration = _reference_seconds(end, tempi) - _reference_seconds(start, tempi)
        tempo_status, tempo_ratio = 'unassessed', None
        if fit:
            tempo_ratio = reference_duration / ((end - start) * fit['seconds_per_beat'])
            tempo_status = ('too_fast' if tempo_ratio > 1 + config.tempo_tolerance else
                            'too_slow' if tempo_ratio < 1 - config.tempo_tolerance else 'on_target')
            tolerance = max(config.timing_tolerance_seconds,
                            config.timing_tolerance_beats * fit['seconds_per_beat'])
            if fit['median_residual_seconds'] > tolerance:
                tempo_status = 'irregular'
        for match in local:
            if match['category'] != 'correct':
                errors.append(_error(match['category'], match, source_type))
            if fit and match['category'] == 'correct':
                delta = match['audio_time'] - (fit['intercept'] + fit['seconds_per_beat'] * match['score_beat'])
                match['onset_error_seconds'] = delta
                if abs(delta) > tolerance:
                    errors.append(_error('timing', match, source_type))
                if match['score_duration_beats'] and match['performance_duration_seconds']:
                    expected_seconds = match['score_duration_beats'] * fit['seconds_per_beat']
                    match['duration_ratio'] = match['performance_duration_seconds'] / expected_seconds
        timed = [m for m in local if m['category'] == 'correct' and m['onset_error_seconds'] is not None]
        duration_ratios = [m['duration_ratio'] for m in timed if m['duration_ratio'] is not None]
        dynamic_deltas = [abs(m['relative_dynamics_delta']) for m in local if m['relative_dynamics_delta'] is not None]
        signed_dynamic_deltas = [m['relative_dynamics_delta'] for m in local if m['relative_dynamics_delta'] is not None]
        abs_timing = [abs(m['onset_error_seconds']) for m in timed]
        dynamic_notes = [m for m in local if m['category'] == 'correct'
                         and m['score_velocity'] is not None and m['performance_velocity'] is not None
                         and m['score_beat'] is not None]
        dynamics_trend = None
        score_dynamic_slope = performance_dynamic_slope = None
        if (len(dynamic_notes) >= 4 and
                float(np.percentile([m['score_velocity'] for m in dynamic_notes], 90)
                      - np.percentile([m['score_velocity'] for m in dynamic_notes], 10)) >= 6):
            beats = np.array([m['score_beat'] for m in dynamic_notes], dtype=float)
            score_dynamic_slope = float(np.polyfit(beats, [m['score_velocity'] for m in dynamic_notes], 1)[0])
            performance_dynamic_slope = float(np.polyfit(beats, [m['performance_velocity'] for m in dynamic_notes], 1)[0])
            if score_dynamic_slope >= 1.5:
                dynamics_trend = ('crescendo_needs_more'
                                  if performance_dynamic_slope < score_dynamic_slope * 0.5
                                  else 'crescendo_followed')
            elif score_dynamic_slope <= -1.5:
                dynamics_trend = ('decrescendo_needs_more'
                                  if performance_dynamic_slope > score_dynamic_slope * 0.5
                                  else 'decrescendo_followed')
        summary = dict(bar, expected_notes=expected, correct_notes=correct,
                       missing_notes=sum(m['category'] == 'missing' for m in local),
                       extra_notes=sum(m['category'] == 'extra' for m in local),
                       wrong_pitch_notes=sum(m['category'] == 'wrong_pitch' for m in local),
                       pitch_recall=local_recall, tempo_status=tempo_status,
                       tempo_ratio=tempo_ratio, tempo_fit=fit,
                       median_absolute_timing_error_seconds=float(np.median(abs_timing)) if abs_timing else None,
                       early_notes=sum(m['onset_error_seconds'] < -config.timing_tolerance_seconds for m in timed),
                       late_notes=sum(m['onset_error_seconds'] > config.timing_tolerance_seconds for m in timed),
                       median_duration_ratio=float(np.median(duration_ratios)) if duration_ratios else None,
                       dynamics_note_count=len(dynamic_deltas),
                       median_relative_dynamics_difference=float(np.median(dynamic_deltas)) if dynamic_deltas else None,
                       relative_dynamics_level_difference=float(np.mean(signed_dynamic_deltas)) if signed_dynamic_deltas else None,
                       dynamics_trend=dynamics_trend,
                       score_dynamic_slope=score_dynamic_slope,
                       performance_dynamic_slope=performance_dynamic_slope,
                       reference_average_bpm=60 * (end - start) / reference_duration,
                       performed_average_bpm=60 / fit['seconds_per_beat'] if fit else None,
                       estimated_start_seconds=fit['intercept'] + fit['seconds_per_beat'] * start if fit else None,
                       estimated_end_seconds=fit['intercept'] + fit['seconds_per_beat'] * end if fit else None)
        summary['feedback'] = _feedback(summary)
        measure_reports.append(summary)
    for match in matches:
        if match['measure_occurrence'] is None and match['category'] != 'correct':
            errors.append(_error(match['category'], match, source_type))
    report = dict(schema_version=1, performance_source=source_type, configuration=asdict(config),
                  alignment=dict(status='aligned' if reliable else 'uncertain',
                                 method='monotone onset edit alignment + one-to-one chord assignment + independent robust bar fits',
                                 sequence_cost=cost,
                                 anchors=[dict(score_beat=b, audio_time=t) for b, t in anchors]),
                  metrics=dict(expected_notes=len(score), performed_notes=len(played),
                               correct_notes=correct_total, pitch_precision=precision,
                               pitch_recall=recall,
                               pitch_f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0,
                               tempo_assessed_measures=sum(b['tempo_fit'] is not None for b in measure_reports),
                               dynamics_assessed_notes=sum(m['relative_dynamics_delta'] is not None for m in correct_matches),
                               median_relative_dynamics_difference=float(np.median([abs(m['relative_dynamics_delta']) for m in correct_matches if m['relative_dynamics_delta'] is not None])) if any(m['relative_dynamics_delta'] is not None for m in correct_matches) else None,
                               median_absolute_timing_error_seconds=float(np.median([abs(m['onset_error_seconds']) for m in correct_matches if m['onset_error_seconds'] is not None])) if any(m['onset_error_seconds'] is not None for m in correct_matches) else None,
                               median_duration_ratio=float(np.median([m['duration_ratio'] for m in correct_matches if m['duration_ratio'] is not None])) if any(m['duration_ratio'] is not None for m in correct_matches) else None),
                  measures=measure_reports, matches=matches, errors=errors, warnings=warnings)
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as handle:
            handle.write(json.dumps(report, indent=2, allow_nan=False) + '\n')
    return report


def _error(category, match, source_type):
    return dict(category=category, measure=match['measure'],
                measure_occurrence=match['measure_occurrence'],
                score_note_id=match['score_note_id'],
                performance_note_id=match['performance_note_id'],
                score_beat=match['score_beat'], audio_time=match['audio_time'],
                expected_pitch=match['expected_pitch'], actual_pitch=match['actual_pitch'],
                onset_error_seconds=match['onset_error_seconds'],
                duration_ratio=match['duration_ratio'],
                relative_dynamics_delta=match['relative_dynamics_delta'],
                evidence_confidence=None,
                assessment='candidate' if source_type == 'midi' else 'possible_transcription_or_playing_error')


def _feedback(bar):
    result = []
    if bar['expected_notes'] and bar['correct_notes'] == bar['expected_notes'] and not bar['extra_notes']:
        result.append('All expected pitches matched.')
    if bar['tempo_status'] in ('too_fast', 'too_slow'):
        direction = 'faster' if bar['tempo_ratio'] > 1 else 'slower'
        result.append(f"This bar was approximately {abs(bar['tempo_ratio'] - 1):.0%} {direction} than the score tempo. Pitch accuracy is scored separately.")
    elif bar['tempo_status'] == 'irregular':
        result.append('Timing within this bar was irregular; its average tempo is only an estimate.')
    elif bar['tempo_status'] == 'unassessed':
        result.append('Not enough reliable, separated note anchors to assess this bar’s tempo.')
    if bar['missing_notes'] or bar['wrong_pitch_notes'] or bar['extra_notes']:
        result.append('Review the candidate pitch discrepancies against the recording and score.')
    level_delta = bar.get('relative_dynamics_level_difference')
    if level_delta is not None and level_delta >= 8:
        result.append('This bar’s relative level is stronger than the score suggests; try playing it softer.')
    elif level_delta is not None and level_delta <= -8:
        result.append('This bar’s relative level is softer than the score suggests; bring it out more.')
    if bar.get('dynamics_trend') == 'crescendo_needs_more':
        result.append('The score builds here; increase the volume more gradually through the crescendo.')
    elif bar.get('dynamics_trend') == 'decrescendo_needs_more':
        result.append('The score fades here; decrease the volume more gradually through the decrescendo.')
    return result
