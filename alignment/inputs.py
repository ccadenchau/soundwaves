"""Adapters for the existing converter and transcriber artifacts."""

import json
from dataclasses import asdict, is_dataclass
from math import isfinite
from pathlib import Path


def read_json(value):
    if isinstance(value, (str, Path)):
        return json.loads(Path(value).read_text(encoding='utf-8'))
    return value


def normalize_notes(records, source):
    result, ids = [], set()
    for index, raw in enumerate(records):
        note = asdict(raw) if is_dataclass(raw) else dict(raw)
        note['id'] = str(note.get('id', f'{source}-{index}'))
        if note['id'] in ids:
            raise ValueError(f'Duplicate {source} note ID: {note["id"]}')
        ids.add(note['id'])
        for key in ('onset', 'duration', 'pitch'):
            note[key] = float(note[key])
            if not isfinite(note[key]):
                raise ValueError(f'{source} note {key} must be finite.')
        if note['onset'] < 0 or note['duration'] <= 0:
            raise ValueError('Note onsets must be nonnegative and durations positive.')
        if note['pitch'] != int(note['pitch']) or not 0 <= note['pitch'] <= 127:
            raise ValueError('Note pitches must be integers in MIDI range 0–127.')
        note['pitch'] = int(note['pitch'])
        note['source'] = source
        result.append(note)
    return sorted(result, key=lambda n: (n['onset'], n['pitch'], n['id']))


def load_score(value):
    data = read_json(value)
    if not isinstance(data, dict) or data.get('time_unit') != 'quarter_note':
        raise ValueError('Use converter reference.json with time_unit="quarter_note".')
    notes = normalize_notes(data['notes'], 'score')
    if not notes:
        raise ValueError('Reference score has no notes.')
    bars = []
    for index, chunk in enumerate(data.get('chunks', [])):
        if len(chunk['measures']) != 1:
            raise ValueError('Reconvert the score with measures_per_chunk=1 for bar-level analysis.')
        start, end = float(chunk['start_beat']), float(chunk['end_beat'])
        if not all(isfinite(v) for v in (start, end)) or start < 0 or end <= start:
            raise ValueError('Measure boundaries must be finite, nonnegative, increasing beats.')
        if bars and abs(start - bars[-1]['end_beat']) > 1e-6:
            raise ValueError('Measure chunks must be contiguous and in playback order.')
        bars.append(dict(number=chunk['measures'][0], occurrence=index,
                         start_beat=start, end_beat=end))
    if not bars:
        raise ValueError('Reference needs one chunk per measure; use convert_score().')
    if any(not bars[0]['start_beat'] <= n['onset'] < bars[-1]['end_beat'] for n in notes):
        raise ValueError('Reference note onset is outside measure boundaries.')
    tempi = sorted((float(beat), float(bpm)) for beat, bpm in data.get('tempo_changes', []))
    if not tempi or tempi[0][0] != 0 or any(
        not isfinite(b) or not isfinite(t) or b < 0 or t <= 0 for b, t in tempi
    ) or len({b for b, _ in tempi}) != len(tempi):
        raise ValueError('Reference needs valid tempo_changes starting at beat zero.')
    return data, notes, bars, tempi


def load_performance(value):
    if isinstance(value, (str, Path)) and Path(value).suffix.lower() in ('.mid', '.midi'):
        import pretty_midi

        midi = pretty_midi.PrettyMIDI(str(value))
        records = [dict(pitch=n.pitch, onset=n.start, duration=n.end - n.start,
                        velocity=n.velocity) for track in midi.instruments if not track.is_drum
                   for n in track.notes]
        return normalize_notes(records, 'performance'), 'midi', []
    data = read_json(value)
    if hasattr(data, 'notes'):
        records, warnings = data.notes, list(getattr(data, 'warnings', ()))
        source_type = 'audio'
    elif isinstance(data, dict):
        if data.get('time_unit', 'seconds') != 'seconds':
            raise ValueError('Performance notes must use seconds.')
        records, warnings = data['notes'], list(data.get('warnings', []))
        source_type = data.get('source_type', 'audio')
    else:
        records, warnings, source_type = data, [], 'audio'
    return normalize_notes(records, 'performance'), source_type, warnings
