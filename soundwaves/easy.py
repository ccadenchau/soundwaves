"""Make an easy, playable score out of any recording you already have.

The recording is transcribed, the melody is pulled off the top, snapped to the beat, moved into
one comfortable octave and, at the simplest level, onto the white keys. The result is written as
MusicXML and added to the piece list, so it can be practised on Play live like any other score.

Nothing is downloaded here. A hummed tune, a phone recording of a song, or a piano take all work;
a dense mix comes out approximate, and the page says so.
"""

import hashlib
import json
import math
from pathlib import Path
from statistics import median

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PIECES = Path(__file__).with_name('pieces')
SCORE_CACHE = Path(__file__).with_name('sessions') / 'scores'
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
WHITE = {0, 2, 4, 5, 7, 9, 11}


def _groups(notes, gap=0.05):
    """Notes struck together, oldest first."""
    out, current = [], []
    for n in sorted(notes, key=lambda n: (n['onset'], -n['pitch'])):
        if current and n['onset'] - current[0]['onset'] > gap:
            out.append(current)
            current = []
        current.append(n)
    if current:
        out.append(current)
    return out


def estimate_beat(onsets, *, low_bpm=66, high_bpm=132, prefer_bpm=96):
    """Seconds per beat from the spacing of attacks. The most common spacing is the pulse or a
    simple multiple of it; the multiple that lands in a playable tempo wins."""
    onsets = sorted(set(round(t, 3) for t in onsets))
    gaps = [b - a for a, b in zip(onsets, onsets[1:]) if 0.1 <= b - a <= 2.0]
    if len(gaps) < 3:
        return 60.0 / prefer_bpm, None
    # Histogram with 20 ms bins; take the fullest bin's centre, then refine with the median of its members.
    bins = np.arange(0.1, 2.02, 0.02)
    counts, edges = np.histogram(gaps, bins=bins)
    centre = float(edges[int(np.argmax(counts))] + 0.01)
    members = [g for g in gaps if abs(g - centre) <= 0.03]
    unit = float(median(members)) if members else centre
    best = None
    for factor in (0.25, 0.5, 1.0, 2.0, 4.0):
        beat = unit * factor
        bpm = 60.0 / beat
        if low_bpm <= bpm <= high_bpm:
            score = abs(math.log(bpm / prefer_bpm))
            if best is None or score < best[0]:
                best = (score, beat)
    beat = best[1] if best else min(max(unit, 60.0 / high_bpm), 60.0 / low_bpm)
    return beat, round(60.0 / beat)


def _merge_fragments(notes, gap=0.12):
    """A sung or hummed note wobbles, and the transcriber cuts it into pieces of the same pitch.
    Pieces that follow each other closely are one note again."""
    out = []
    for n in sorted(notes, key=lambda n: (n['onset'], n['pitch'])):
        last = out[-1] if out else None
        if last and last['pitch'] == n['pitch'] and n['onset'] - (last['onset'] + last['duration']) <= gap:
            last['duration'] = max(last['duration'], n['onset'] + n['duration'] - last['onset'])
            last['velocity'] = max(last['velocity'], n['velocity'])
            continue
        out.append(dict(n))
    return out


def _drop_neighbour_blips(notes, *, short=0.15, semitones=2, near=0.1):
    """A voice slides and wobbles, so the transcriber adds short, quieter notes a semitone or two
    from the real one. A short note next to a longer, louder note within two semitones goes."""
    out = []
    for n in notes:
        if n['duration'] < short and any(
                o is not n and 0 < abs(o['pitch'] - n['pitch']) <= semitones and o['velocity'] > n['velocity']
                and o['duration'] >= n['duration']
                and o['onset'] - near <= n['onset'] <= o['onset'] + o['duration'] + near for o in notes):
            continue
        out.append(n)
    return out


def extract_melody(notes, *, low=50, high=88, min_duration=0.07):
    """One note per attack: the top of what is loud enough. Bass and drum-like blips are dropped
    by range and length; among notes struck together the highest of the loud ones is the tune;
    an attack under a melody note that is still sounding is accompaniment and is skipped."""
    in_range = [n for n in notes if low <= n['pitch'] <= high and n['duration'] >= min_duration]
    kept = _merge_fragments(_drop_neighbour_blips(in_range))
    melody = []
    for group in _groups(kept):
        loudest = max(n['velocity'] for n in group)
        candidates = [n for n in group if n['velocity'] >= 0.6 * loudest]
        top = max(candidates, key=lambda n: n['pitch'])
        held = melody[-1] if melody else None
        if (held and top['pitch'] < held['pitch'] and top['onset'] < held['onset'] + held['duration'] - 0.05
                and top['velocity'] <= 1.15 * held['velocity']):
            continue  # a chord or bass note under the tune's held note
        melody.append(dict(top))
    # A note immediately followed by a higher one is a grace note or a smear into the real note,
    # and a note an octave from its neighbour within a blink is the transcriber hearing an overtone.
    cleaned = []
    for i, n in enumerate(melody):
        nxt = melody[i + 1] if i + 1 < len(melody) else None
        prev = cleaned[-1] if cleaned else None
        if nxt and nxt['onset'] - n['onset'] < 0.12 and nxt['pitch'] > n['pitch']:
            continue
        if prev and abs(n['pitch'] - prev['pitch']) in (12, 24) and n['onset'] - prev['onset'] < 0.15 and n['velocity'] <= prev['velocity']:
            continue
        cleaned.append(n)
    return _merge_fragments(cleaned, gap=0.08)


def _key_shift(melody):
    """Semitones to add so as many notes as possible land on white keys (weighted by how long they
    sound), and whether the result reads as C major or A minor. A key detector guesses from a few
    hummed notes; counting white keys does not."""
    if not melody:
        return 0, 'major'
    best = None
    for shift in range(-6, 6):
        weight = sum(n['duration'] for n in melody if (n['pitch'] + shift) % 12 in WHITE)
        if best is None or weight > best[0] + 1e-9 or (abs(weight - best[0]) < 1e-9 and abs(shift) < abs(best[1])):
            best = (weight, shift)
    shift = best[1]
    last = (melody[-1]['pitch'] + shift) % 12
    mode = 'minor' if last in (9, 4) else 'major'
    return shift, mode


def simplify(melody, *, level=3, bars=8, beats_per_bar=4, beat=None):
    """Snap the tune to a grid and make it easy to play.

    level 1: eighth-note grid, original key, range folded to about an octave and a half.
    level 2: quarter-note grid, moved to C major or A minor, one octave.
    level 3: like 2, and every note on a white key.
    Returns (events in beats: [dict(beat, pitch, length)], info)."""
    if not melody:
        return [], dict(bpm_detected=None, key='C major', shift=0)
    beat_seconds, bpm_detected = (beat, round(60 / beat)) if beat else estimate_beat([n['onset'] for n in melody])
    grid = 0.5 if level <= 1 else 1.0
    start = melody[0]['onset']
    # Key first, so the fold happens in the final key.
    shift, mode = _key_shift(melody) if level >= 2 else (0, 'major')
    pitches = [n['pitch'] + shift for n in melody]
    centre = median(pitches)
    # Move the whole tune by octaves so its middle lands around C4 to C5, then fold stragglers in.
    octave_shift = 12 * round((66 - centre) / 12)
    span = 18 if level <= 1 else 12
    folded = []
    for p in pitches:
        p += octave_shift
        middle = centre + octave_shift
        while p > middle + span / 2:
            p -= 12
        while p < middle - span / 2:
            p += 12
        if level >= 3 and p % 12 not in WHITE:
            p -= 1  # a black key becomes the white key just below it
        folded.append(int(p))
    # Each note is placed by its distance from the previous one, rounded to the grid and never
    # less than one grid step. A fixed grid from the first note drifts whenever the pulse estimate
    # is a few percent off; relative placement cannot. At the simplest level every note therefore
    # gets at least a beat, which turns quick repeated notes into plain repeated notes.
    ordered, pos, prev_onset = [], 0.0, None
    for n, p in zip(melody, folded):
        if prev_onset is not None:
            steps = math.floor((n['onset'] - prev_onset) / (beat_seconds * grid) + 0.5) * grid
            pos += max(grid, min(steps, 2 * beats_per_bar))
        prev_onset = n['onset']
        ordered.append(dict(beat=pos, pitch=p, velocity=n['velocity'], onset=n['onset']))
    total = bars * beats_per_bar
    ordered = [e for e in ordered if e['beat'] < total]
    events = []
    for i, e in enumerate(ordered):
        nxt = ordered[i + 1]['beat'] if i + 1 < len(ordered) else min(total, e['beat'] + beats_per_bar)
        length = nxt - e['beat']
        # Easy lengths only: nothing longer than a bar, nothing shorter than the grid.
        length = max(grid, min(beats_per_bar, length))
        if level >= 2:
            length = float(round(length))  # whole beats
            if length < 1:
                length = 1.0
        events.append(dict(beat=float(e['beat']), pitch=e['pitch'], length=float(length)))
    # Drop a trailing fragment that would start a new bar with one note.
    key_name = ('C major' if mode == 'major' else 'A minor') if level >= 2 else 'original'
    return events, dict(bpm_detected=bpm_detected, key=key_name, shift=shift, bars=math.ceil((events[-1]['beat'] + events[-1]['length']) / beats_per_bar) if events else 0)


def to_musicxml(events, path, *, title, bpm=72, beats_per_bar=4, key_name='C major'):
    """Write the events as a one-staff score music21 and our converter both like."""
    from music21 import instrument, key as m21key, metadata, meter, note as m21note, stream, tempo
    score = stream.Score()
    score.metadata = metadata.Metadata(title=title, composer='easy version')
    part = stream.Part()
    part.insert(0, instrument.Piano())
    part.insert(0, meter.TimeSignature(f'{beats_per_bar}/4'))
    part.insert(0, m21key.Key('C' if key_name != 'A minor' else 'a'))
    part.insert(0, tempo.MetronomeMark(number=bpm))
    for e in events:
        n = m21note.Note(int(e['pitch']), quarterLength=e['length'])
        part.insert(e['beat'], n)
    part.makeRests(fillGaps=True, inPlace=True)
    part.makeMeasures(inPlace=True)
    # Let music21 decide which accidentals to print; raw MIDI pitches otherwise come out with a
    # natural sign on every note.
    for n in part.recurse().notes:
        if n.pitch.accidental is not None and n.pitch.accidental.alter == 0:
            n.pitch.accidental = None
    part.makeAccidentals(inPlace=True, overrideStatus=True)
    score.insert(0, part)
    score.write('musicxml', fp=str(path))
    return path


def _load_clip(audio, start_seconds, seconds):
    """Decode the recording and keep one stretch of it as a WAV the transcriber can read."""
    import soundfile as sf
    from audio_cleaner.clean_audio import load_audio
    data, sr = load_audio(audio)
    mono = data.mean(axis=1) if data.ndim > 1 else data
    a = int(max(0.0, start_seconds) * sr)
    b = min(len(mono), a + int(seconds * sr))
    if b - a < sr:
        raise ValueError('That start time is past the end of the recording.')
    return mono[a:b], sr


def make_easy(audio, *, title, level=3, bars=8, start_seconds=0.0, seconds=60.0, bpm=72,
              solo_piano=False, workdir=None):
    """Recording in, an easy piece in the list out. Returns a JSON-ready summary."""
    import tempfile
    import soundfile as sf
    from transcribe_recording import transcribe_recording
    from .clean import clean_notes
    from .pipeline import convert_once, transcriber

    audio = Path(audio)
    title = (title or audio.stem.replace('_', ' ').replace('-', ' ').strip().title() or 'Easy tune')[:80]
    level = int(min(3, max(1, level)))
    bars = int(min(32, max(4, bars)))
    work = Path(workdir) if workdir else Path(tempfile.mkdtemp(prefix='easy-'))
    work.mkdir(parents=True, exist_ok=True)
    clip, sr = _load_clip(audio, start_seconds, seconds)
    wav = work / 'clip.wav'
    sf.write(wav, clip, sr)
    # Transkun hears piano very well and everything else as if it were piano; Basic Pitch is the
    # general model. Solo piano recordings get Transkun, anything else Basic Pitch.
    backend = transcriber() if solo_piano else None
    take = transcribe_recording(wav, work / 'take', backend=backend)
    notes, _ = clean_notes(take.notes, harmonics=backend is None)
    if len(notes) < 4:
        raise ValueError('Too few notes were heard in that stretch. Try a different start time, or a clearer recording.')
    melody = extract_melody(notes)
    if len(melody) < 4:
        raise ValueError('No clear tune was found in that stretch. Try a different start time.')
    events, info = simplify(melody, level=level, bars=bars)
    if len(events) < 3:
        raise ValueError('The tune came out too short to practise. Try more bars or a different start time.')
    xml = work / 'easy.musicxml'
    to_musicxml(events, xml, title=f'{title} (easy)', bpm=bpm, key_name=info['key'])
    data = xml.read_bytes()
    piece_id = 'easy-' + hashlib.sha256(data).hexdigest()[:10]
    PIECES.mkdir(exist_ok=True)
    target = PIECES / f'{piece_id}.musicxml'
    target.write_bytes(data)
    paths = convert_once(target, SCORE_CACHE / piece_id, bpm=bpm)
    (PIECES / f'{piece_id}.json').write_text(json.dumps(dict(
        title=f'{title} (easy)', composer=None, bpm=bpm, uploaded=True, easy=True, level=level,
        source=audio.name, start_seconds=start_seconds, key=info['key'], bpm_detected=info['bpm_detected'])), encoding='utf-8')
    reference = json.loads(Path(paths['notes']).read_text(encoding='utf-8'))
    return dict(id=piece_id, title=f'{title} (easy)', level=level, bars=len(reference['chunks']),
                notes=len(reference['notes']), bpm=bpm, bpm_detected=info['bpm_detected'], key=info['key'],
                heard_notes=len(notes), melody_notes=len(melody), transcriber=backend.name if backend else 'basic-pitch',
                tune=[dict(beat=e['beat'], name=f"{NAMES[e['pitch'] % 12]}{e['pitch'] // 12 - 1}", length=e['length']) for e in events])
