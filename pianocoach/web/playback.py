"""Render actual MIDI note times to a lightweight WAV for browser playback.

This is a harmonic synthesizer, not a sampled piano or a recording. Reading the
MIDI preserves its encoded tempo changes, note durations, and velocities.
"""

import math
import wave

import pretty_midi

from sheet_downloader.reference import synthesize


def render_midi(source, destination):
    midi = pretty_midi.PrettyMIDI(str(source))
    notes = [note for track in midi.instruments if not track.is_drum for note in track.notes]
    duration = max((note.end for note in notes), default=0) + 0.25
    if not math.isfinite(duration) or duration > 1800:
        raise ValueError('MIDI audio previews support pieces up to 30 minutes. Use a shorter score excerpt.')
    events = [dict(start_seconds=n.start, end_seconds=n.end, pitch=n.pitch, velocity=n.velocity)
              for n in notes]
    sample_rate = 16000
    pcm = synthesize(events, duration, sample_rate)
    with wave.open(str(destination), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
