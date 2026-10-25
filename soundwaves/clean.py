"""Remove transcription artefacts before alignment.

Basic Pitch sometimes reports a short, quiet note an octave (or another
partial) above a real note that starts at the same instant. Those are
overtones of the struck string, not keys the student pressed. Dropping them
before alignment keeps pitch precision honest, which the aligner needs
before it will judge tempo at all.
"""

from dataclasses import asdict, is_dataclass

HARMONIC_INTERVALS = (12, 19, 24, 28, 31, 34, 36)


def _as_dict(note):
    return asdict(note) if is_dataclass(note) else dict(note)


def remove_harmonics(notes, *, window_seconds=0.035, intervals=HARMONIC_INTERVALS):
    """Return (kept, dropped). A note is dropped when a lower note starts within
    `window_seconds`, sits a harmonic interval below it, and is the stronger of
    the two by duration, velocity or model score."""
    records = sorted((_as_dict(n) for n in notes), key=lambda n: (n['onset'], n['pitch']))
    kept, dropped = [], []
    for index, note in enumerate(records):
        ghost = False
        j = index - 1
        while j >= 0 and note['onset'] - records[j]['onset'] <= window_seconds:
            lower = records[j]
            if (note['pitch'] - lower['pitch']) in intervals and _weaker(note, lower):
                ghost = True
                break
            j -= 1
        if not ghost:
            j = index + 1
            while j < len(records) and records[j]['onset'] - note['onset'] <= window_seconds:
                lower = records[j]
                if (note['pitch'] - lower['pitch']) in intervals and _weaker(note, lower):
                    ghost = True
                    break
                j += 1
        (dropped if ghost else kept).append(note)
    return kept, dropped


def _weaker(note, lower, *, max_ghost_seconds=0.25):
    """A real note doubled at the octave or twelfth (right hand over left hand)
    is full length and about as loud as its partner. An overtone ghost is short,
    clearly quieter and less certain. All three must hold before a note goes."""
    short = note['duration'] <= max_ghost_seconds and note['duration'] < 0.6 * lower['duration']
    quieter = (note.get('velocity') is not None and lower.get('velocity') is not None
               and note['velocity'] < 0.7 * lower['velocity'])
    less_sure = (note.get('model_score') is not None and lower.get('model_score') is not None
                 and note['model_score'] < lower['model_score'])
    return short and quieter and less_sure


def merge_reonsets(notes, *, gap_seconds=0.03, max_tail_seconds=0.15):
    """Return (kept, dropped). When the transcriber restarts a pitch the instant
    the previous detection of that pitch ended, and the restart is a short tail
    (under `max_tail_seconds`) that is quieter and less certain, it is the same
    key still sounding. A full-length second note is a real repeat and stays."""
    records = sorted((_as_dict(n) for n in notes), key=lambda n: (n['onset'], n['pitch']))
    last_by_pitch, kept, dropped = {}, [], []
    for note in records:
        previous = last_by_pitch.get(note['pitch'])
        if previous is not None:
            gap = note['onset'] - (previous['onset'] + previous['duration'])
            quieter = (note.get('velocity') or 0) < (previous.get('velocity') or 0)
            less_sure = (note.get('model_score') or 0) < (previous.get('model_score') or 0)
            short_tail = note['duration'] <= max_tail_seconds
            if -gap_seconds <= gap <= gap_seconds and short_tail and quieter and less_sure:
                previous['duration'] = max(previous['duration'], note['onset'] + note['duration'] - previous['onset'])
                dropped.append(note)
                continue
        kept.append(note)
        last_by_pitch[note['pitch']] = note
    return kept, dropped


def merge_duplicates(notes, *, window_seconds=0.03):
    """Return (kept, dropped). Two detections of one pitch starting within
    `window_seconds` of each other are one key press reported twice (a frame
    boundary artefact). The longer one stays and is extended if needed."""
    records = sorted((_as_dict(n) for n in notes), key=lambda n: (n['pitch'], n['onset']))
    kept, dropped = [], []
    for note in records:
        last = kept[-1] if kept and kept[-1]['pitch'] == note['pitch'] else None
        if last is not None and note['onset'] - last['onset'] <= window_seconds:
            end = max(last['onset'] + last['duration'], note['onset'] + note['duration'])
            if note['duration'] > last['duration']:
                note['duration'] = end - note['onset']
                dropped.append(kept.pop())
                kept.append(note)
            else:
                last['duration'] = end - last['onset']
                dropped.append(note)
            continue
        kept.append(note)
    kept.sort(key=lambda n: (n['onset'], n['pitch']))
    return kept, dropped


def clean_notes(notes, *, harmonics=True):
    """All passes. Returns (kept, report) where report counts what went.
    `harmonics=False` skips the overtone filter for transcribers that do not ghost."""
    kept, duplicates = merge_duplicates(notes)
    kept, dropped = remove_harmonics(kept) if harmonics else (kept, [])
    kept, reonsets = merge_reonsets(kept)
    harmonics = dropped
    return kept, dict(duplicates_merged=len(duplicates), harmonics_removed=len(harmonics),
                      reonsets_merged=len(reonsets), notes_kept=len(kept))


def write_performance_midi(notes, destination):
    """Export the same cleaned detections used by alignment and score overlays."""
    from types import SimpleNamespace
    from transcribe_recording.export import write_midi

    write_midi(destination, [SimpleNamespace(**_as_dict(note)) for note in notes])
