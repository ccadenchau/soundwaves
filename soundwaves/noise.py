"""Two room-noise rules for audio takes, shared by every path that shows findings.

They were written and measured in `soundwaves.report` (the older review page) and are copied
here unchanged so the review page's comparison and the live session behave the same way:

- An extra note far quieter than the playing around it is background sound the transcriber
  turned into a note (above all, people talking). It is dropped. Measured on real student
  mistakes under real living-room noise, a cutoff of 0.6 x the local loudness removed about
  half of the noise notes and none of the real extra notes.
- An extra note that does not fit the music (no score note near it in time, or far from every
  nearby score note in pitch and no louder than its neighbours, or a short blip that is no
  louder) is kept but marked `maybe_noise`, so pages can draw it faded and count it apart.

MIDI takes never go through this: a key press is a key press.
"""

import bisect

import numpy as np


def quieter_than_neighbours(note, by_time, times, window=2.0, ratio=0.6):
    lo, hi = bisect.bisect_left(times, note['onset'] - window), bisect.bisect_right(times, note['onset'] + window)
    near = sorted(v for t, v in by_time[lo:hi] if abs(t - note['onset']) > 1e-6)
    if len(near) < 4 or not note.get('velocity'):
        return False
    return note['velocity'] < ratio * near[len(near) // 2]


def sounds_like_room(note, score_onsets, score_pitches, by_time, times):
    t, pitch = float(note['onset']), int(note['pitch'])
    lo, hi = bisect.bisect_left(score_onsets, t - 0.4), bisect.bisect_right(score_onsets, t + 0.4)
    nearby = score_pitches[lo:hi]
    if not nearby:
        return True
    a, b = bisect.bisect_left(times, t - 2.0), bisect.bisect_right(times, t + 2.0)
    neighbours = sorted(v for tt, v in by_time[a:b] if abs(tt - t) > 1e-6)
    louder = bool(neighbours) and (note.get('velocity') or 0) >= neighbours[len(neighbours) // 2]
    far = min(abs(p - pitch) for p in nearby) > 7
    blip = float(note.get('duration') or 1.0) < 0.1
    return (far or blip) and not louder


def _score_timeline(alignment, reference_notes):
    """Each score note's expected moment in the recording, from the alignment's anchors."""
    anchors = alignment.get('alignment', {}).get('anchors') or []
    beats = [a['score_beat'] for a in anchors]
    times = [a['audio_time'] for a in anchors]

    def at(beat):
        if len(beats) >= 2:
            if beats[0] <= beat <= beats[-1]:
                return float(np.interp(beat, beats, times))
            (b0, t0), (b1, t1) = ((beats[0], times[0]), (beats[1], times[1])) if beat < beats[0] \
                else ((beats[-2], times[-2]), (beats[-1], times[-1]))
            slope = (t1 - t0) / (b1 - b0) if b1 != b0 else 0.0
            return t0 + slope * (beat - b0)
        return times[0] if times else 0.0

    onsets, pitches = [], []
    for n in sorted(reference_notes, key=lambda n: n['onset']):
        onsets.append(at(float(n['onset'])) if beats else 0.0)
        pitches.append(int(n['pitch']))
    return onsets, pitches


def apply_noise_rules(alignment, played_notes, reference_notes):
    """Drop quiet-noise extras and tag room-like extras, in place. Returns the counts.

    `played_notes` are the cleaned detections the aligner saw (dicts with id, pitch, onset,
    duration, velocity); `reference_notes` is the score's note list (onset in beats, pitch)."""
    played = {n['id']: n for n in played_notes if n.get('id')}
    by_time = sorted((float(n['onset']), float(n.get('velocity') or 0)) for n in played_notes)
    times = [t for t, _ in by_time]
    score_onsets, score_pitches = _score_timeline(alignment, reference_notes)
    drop, maybe = set(), set()
    for m in alignment['matches']:
        if m['category'] != 'extra':
            continue
        heard = played.get(m.get('performance_note_id'))
        if heard is None:
            continue
        if quieter_than_neighbours(heard, by_time, times):
            drop.add(m['performance_note_id'])
        elif sounds_like_room(heard, score_onsets, score_pitches, by_time, times):
            maybe.add(m['performance_note_id'])
    if drop:
        alignment['matches'] = [m for m in alignment['matches']
                                if not (m['category'] == 'extra' and m.get('performance_note_id') in drop)]
        alignment['errors'] = [e for e in alignment['errors']
                               if not (e['category'] == 'extra' and e.get('performance_note_id') in drop)]
        for b in alignment['measures']:
            b['extra_notes'] = sum(1 for m in alignment['matches']
                                   if m['category'] == 'extra' and m.get('measure_occurrence') == b['occurrence'])
        metrics = alignment.get('metrics') or {}
        if metrics.get('performed_notes'):
            metrics['performed_notes'] = max(0, metrics['performed_notes'] - len(drop))
            p = metrics['correct_notes'] / metrics['performed_notes'] if metrics['performed_notes'] else 0.0
            r = metrics.get('pitch_recall', 0.0)
            metrics['pitch_precision'] = p
            metrics['pitch_f1'] = 2 * p * r / (p + r) if p + r else 0.0
    for m in list(alignment['matches']) + list(alignment['errors']):
        if m['category'] == 'extra' and m.get('performance_note_id') in maybe:
            m['maybe_noise'] = True
    return dict(quiet_noise_dropped=len(drop), maybe_noise=len(maybe))
