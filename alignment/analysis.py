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
                                measure=None, measure_occurrence=None))
    # Extras get a score-location estimate from surrounding sequence anchors,
    # never from the reference's absolute timestamps.
    def extra_beat(time):
        if not anchors:
            return None
        if time < anchors[0][1] or time > anchors[-1][1]:
            return None
        return float(np.interp(time, [t for _, t in anchors], [b for b, _ in anchors]))

    correct_total = sum(m['category'] == 'correct' for m in matches)
    recall = correct_total / len(score)
    precision = correct_total / len(played) if played else 0.0
    reliable = (bool(anchors) and recall >= config.minimum_pitch_recall
                and precision >= config.minimum_pitch_recall)
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
        summary = dict(bar, expected_notes=expected, correct_notes=correct,
                       missing_notes=sum(m['category'] == 'missing' for m in local),
                       extra_notes=sum(m['category'] == 'extra' for m in local),
                       wrong_pitch_notes=sum(m['category'] == 'wrong_pitch' for m in local),
                       pitch_recall=local_recall, tempo_status=tempo_status,
                       tempo_ratio=tempo_ratio, tempo_fit=fit,
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
                               tempo_assessed_measures=sum(b['tempo_fit'] is not None for b in measure_reports)),
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
    return result
