from math import isfinite

from .models import PlayedNote, TranscriptionConfig


def normalize_notes(events, duration: float, config: TranscriptionConfig):
    notes = []
    seen = set()
    discarded = 0
    clipped = 0
    valid = []
    for event in events:
        if all(isfinite(value) for value in event):
            valid.append(event)
        else:
            discarded += 1
    for start, end, pitch, score in sorted(valid, key=lambda event: (event[0], event[2], event[1])):
        if pitch != int(pitch) or not config.lowest_pitch <= pitch <= config.highest_pitch:
            discarded += 1
            continue
        onset = max(0.0, start)
        offset = min(duration, end)
        if offset <= onset:
            discarded += 1
            continue
        if onset != start or offset != end:
            clipped += 1
        identity = (int(pitch), onset, offset)
        if identity in seen:
            discarded += 1
            continue
        seen.add(identity)
        score = min(1.0, max(0.0, score))
        notes.append(PlayedNote(
            id=f'p{len(notes):06d}', pitch=int(pitch), onset=onset,
            duration=offset - onset, velocity=max(1, round(score * 127)),
            model_score=score,
        ))
    return tuple(notes), {'discarded_events': discarded, 'clipped_events': clipped}
