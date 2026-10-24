from bisect import bisect_right

from music21 import dynamics, layout

VELOCITIES = {
    "pppp": 16,
    "ppp": 24,
    "pp": 34,
    "p": 46,
    "mp": 58,
    "mf": 72,
    "f": 88,
    "ff": 104,
    "fff": 116,
    "ffff": 124,
}


def piano_groups(score):
    groups = {}
    for group in score.recurse().getElementsByClass(layout.StaffGroup):
        parts = list(group.getSpannedElements())
        if group.symbol == "brace":
            for part in parts:
                groups[id(part)] = parts
    return groups


def expression_for_part(score, part, related_parts):
    marks = []
    ramps = []
    for related in related_parts:
        priority = int(related is part)
        for mark in related.recurse().getElementsByClass(dynamics.Dynamic):
            if mark.value in VELOCITIES:
                marks.append((
                    float(mark.getOffsetInHierarchy(score)),
                    priority,
                    VELOCITIES[mark.value],
                ))
        for wedge in related.recurse().getElementsByClass(dynamics.DynamicWedge):
            endpoints = list(wedge.getSpannedElements())
            if len(endpoints) < 2:
                continue
            start = float(endpoints[0].getOffsetInHierarchy(score))
            end = float(endpoints[-1].getOffsetInHierarchy(score))
            if end <= start:
                continue
            direction = 1 if isinstance(wedge, dynamics.Crescendo) else -1
            ramps.append((start, end, direction))
    marks.sort()
    beats = [mark[0] for mark in marks]

    def marked_velocity(beat):
        index = bisect_right(beats, beat)
        return marks[index - 1] if index else (-1, 0, 72)

    resolved = []
    for start, end, direction in sorted(set(ramps)):
        initial = marked_velocity(start)[2]
        if (
            resolved
            and resolved[-1][1] <= start
            and marked_velocity(start)[0] < resolved[-1][1]
        ):
            initial = resolved[-1][3]
        at_end = marked_velocity(end)
        target = at_end[2] if at_end[0] > start else initial + direction * 20
        target = max(1, min(127, target))
        resolved.append((start, end, initial, target))

    def velocity_at(beat):
        latest, _, value = marked_velocity(beat)
        for start, end, initial, target in resolved:
            if beat < start or latest > start:
                continue
            fraction = min(1, (beat - start) / (end - start))
            value = round(initial + (target - initial) * fraction)
        return value

    return velocity_at


def apply_expression(score):
    groups = piano_groups(score)
    for part in score.parts:
        velocity_at = expression_for_part(score, part, groups.get(id(part), [part]))
        for element in part.recurse().notes:
            beat = float(element.getOffsetInHierarchy(score))
            velocity = velocity_at(beat)
            velocity += round(sum(art.volumeShift for art in element.articulations) * 127)
            element.volume.velocity = max(1, min(127, velocity))
            element.volume.velocityIsRelative = False
            if element.isChord:
                for member in element.notes:
                    member.volume.velocity = element.volume.velocity
                    member.volume.velocityIsRelative = False
