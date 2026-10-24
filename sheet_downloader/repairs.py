import copy
from fractions import Fraction
from statistics import median

from music21 import chord, clef, duration, key, note, stream

from .expression import piano_groups


def repair_score(score, source_issues):
    changes = []
    grouped_parts = piano_groups(score)
    broken_tuplets = {
        str(issue['measure']) for issue in source_issues
        if issue['code'] == 'tuplet_notation'
        and ('matching start' in issue['message'] or 'matching end' in issue['message'])
    }
    for part in score.parts:
        measures = list(part.getElementsByClass(stream.Measure))
        for index, measure in enumerate(measures):
            merge_simultaneous_notes(score, part, measure, changes)
            if str(measure.number) in broken_tuplets:
                remove_fragmented_tuplets(part, measure, changes)
            if index not in (0, len(measures) - 1):
                fill_trailing_silence(part, measure, changes)
        if id(part) in grouped_parts:
            restore_chord_clef(part, changes)
    return changes


def record(changes, part, measure, rule, message, before, after):
    changes.append({
        'rule': rule, 'part': str(part.id), 'measure': measure.number,
        'basis': 'inference' if rule == 'inferred_chord_clef' else 'score_structure',
        'message': message, 'before': before, 'after': after,
    })


def merge_simultaneous_notes(score, part, measure, changes):
    for voice in list(measure.voices) or [measure]:
        groups = {}
        for element in voice.notes:
            groups.setdefault((element.offset, element.quarterLength), []).append(element)
        for (offset, length), elements in groups.items():
            if len(elements) < 2 or any(element.duration.isGrace for element in elements):
                continue
            members = []
            for element in elements:
                members.extend(element.notes if element.isChord else [element])
            combined = chord.Chord(copy.deepcopy(members), quarterLength=length)
            combined.articulations = copy.deepcopy(elements[0].articulations)
            combined.expressions = copy.deepcopy(elements[0].expressions)
            for element in elements:
                for spanner in score.spannerBundle:
                    if element in spanner.getSpannedElements():
                        spanner.replaceSpannedElement(element, combined)
                voice.remove(element)
            voice.insert(offset, combined)
            record(changes, part, measure, 'simultaneous_chord',
                   'Combined simultaneous events of equal length in the same voice into a chord.',
                   [str(element) for element in elements], str(combined))


def remove_fragmented_tuplets(part, measure, changes):
    signature = measure.timeSignature or measure.getContextByClass('TimeSignature')
    if signature is None:
        return
    expected = Fraction(signature.barDuration.quarterLength)
    events = sorted(measure.recurse().notesAndRests,
                    key=lambda element: element.getOffsetInHierarchy(measure))
    candidates = [element for element in events if element.duration.tuplets]
    if not candidates or any(len(element.duration.tuplets) != 1 for element in candidates):
        return
    ratios = {(element.duration.tuplets[0].numberNotesActual,
               element.duration.tuplets[0].numberNotesNormal) for element in candidates}
    if len(ratios) != 1:
        return
    actual, _ = next(iter(ratios))
    if len(candidates) != actual:
        return
    onsets = [Fraction(element.getOffsetInHierarchy(measure)) for element in events]
    if len(set(onsets)) != len(onsets):
        return
    replacements = []
    for index, element in enumerate(events):
        if element not in candidates:
            continue
        if element.duration.type in ('complex', 'inexpressible', 'zero'):
            return
        written = duration.Duration(type=element.duration.type, dots=element.duration.dots)
        boundary = onsets[index + 1] if index + 1 < len(events) else expected
        if onsets[index] + Fraction(written.quarterLength) != boundary:
            return
        replacements.append((element, written))
    before = [float(element.quarterLength) for element, _ in replacements]
    for element, written in replacements:
        element.duration = written
    record(changes, part, measure, 'fragmented_tuplet',
           'Removed an unmatched tuplet split across voices: written durations exactly fill the existing onset slots.',
           before, [float(element.quarterLength) for element, _ in replacements])


def fill_trailing_silence(part, measure, changes):
    signature = measure.timeSignature or measure.getContextByClass('TimeSignature')
    if signature is None or measure.paddingLeft or measure.paddingRight:
        return
    end = Fraction(measure.highestTime)
    expected = Fraction(signature.barDuration.quarterLength)
    gap = expected - end
    if end <= 0 or gap <= 0 or gap.denominator > 16:
        return
    rest = note.Rest(quarterLength=gap)
    voices = list(measure.voices)
    target = max(
        voices,
        key=lambda voice: voice.getOffsetInHierarchy(measure) + voice.highestTime,
    ) if voices else measure
    target_offset = Fraction(target.getOffsetInHierarchy(measure)) if voices else 0
    target.insert(end - target_offset, rest)
    record(changes, part, measure, 'trailing_rest',
           'Made the existing trailing silence explicit with a rest; pitches and attacks are unchanged.',
           float(end), float(expected))


def shifted_pitches(element, shift):
    pitches = copy.deepcopy(element.pitches)
    for pitch in pitches:
        pitch.diatonicNoteNum += shift
    return pitches


def restore_chord_clef(part, changes):
    events = list(part.recurse().notes)
    clefs = list(part.recurse().getElementsByClass(clef.PitchClef))
    for upcoming in clefs:
        end = float(upcoming.getOffsetInHierarchy(part))
        after = next((element for element in events
                      if float(element.getOffsetInHierarchy(part)) >= end), None)
        if after is None:
            continue
        candidates = []
        for index, first in enumerate(events):
            start = float(first.getOffsetInHierarchy(part))
            if index == 0 or start >= end or end - start > 16 or not first.isChord:
                continue
            old_clef = first.getContextByClass(clef.PitchClef)
            if old_clef is None or type(old_clef) is type(upcoming):
                continue
            segment = [element for element in events[index:]
                       if float(element.getOffsetInHierarchy(part)) < end]
            if len(segment) < 3 or not all(element.isChord for element in segment):
                continue
            if any(element.getContextByClass(clef.PitchClef) is not old_clef for element in segment):
                continue
            signature = first.getContextByClass(key.KeySignature)
            if signature is not None and signature.sharps != 0:
                continue
            if any(pitch.accidental is not None for element in segment for pitch in element.pitches):
                continue
            shift = upcoming.lowestLine - old_clef.lowestLine
            before = [events[index - 1], *segment, after]
            old_centers = [median(p.midi for p in element.pitches) for element in before]
            new_centers = [old_centers[0], *[
                median(p.midi for p in shifted_pitches(element, shift)) for element in segment
            ], old_centers[-1]]
            improvement = register_cost(old_centers) - register_cost(new_centers)
            if improvement >= 24:
                candidates.append((improvement, start, segment, shift))
        candidates.sort(key=lambda candidate: candidate[0], reverse=True)
        if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 8):
            continue
        _, start, segment, shift = candidates[0]
        first = segment[0]
        measure = first.getContextByClass(stream.Measure)
        before = [[p.nameWithOctave for p in element.pitches] for element in segment]
        for element in segment:
            for pitch in element.pitches:
                pitch.diatonicNoteNum += shift
        replacement = copy.deepcopy(upcoming)
        measure.insert(start - float(measure.offset), replacement)
        record(changes, part, measure, 'inferred_chord_clef',
               'Inferred an earlier clef change from a unique chord-register transition and the later explicit clef. Review this inferred pitch change.',
               before, [[p.nameWithOctave for p in element.pitches] for element in segment])


def register_cost(values):
    return sum(abs(a - b) for a, b in zip(values, values[1:]))
