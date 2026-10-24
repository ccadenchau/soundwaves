import json
from dataclasses import asdict
from math import isfinite
from pathlib import Path

from .models import PlayedNote


def write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n')


def write_raw_notes(path: Path, events) -> None:
    records = [
        {
            'onset': start if isfinite(start) else None,
            'offset': end if isfinite(end) else None,
            'pitch': pitch if isfinite(pitch) else None,
            'model_score': score if isfinite(score) else None,
        }
        for start, end, pitch, score in events
    ]
    write_json(path, {'time_unit': 'seconds', 'notes': records})


def write_midi(path: Path, notes: tuple[PlayedNote, ...]) -> None:
    import pretty_midi

    midi = pretty_midi.PrettyMIDI(initial_tempo=120, resolution=960)
    piano = pretty_midi.Instrument(program=0)
    for note in notes:
        piano.notes.append(pretty_midi.Note(
            velocity=note.velocity, pitch=note.pitch,
            start=note.onset, end=note.onset + note.duration,
        ))
    midi.instruments.append(piano)
    midi.write(str(path))


def note_records(notes: tuple[PlayedNote, ...]) -> list[dict]:
    return [asdict(note) for note in notes]
