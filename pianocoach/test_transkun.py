"""Integration test: the Transkun worker transcribes a short synthesized clip. Skipped without .venv-transkun."""

import tempfile
import unittest
from pathlib import Path

from pianocoach.transkun_backend import TranskunBackend


@unittest.skipUnless(TranskunBackend.available(), 'Transkun environment not installed')
class TranskunWorkerTests(unittest.TestCase):
    def test_two_notes_come_back(self):
        from transcribe_recording.models import TranscriptionConfig
        from testing.render_piano import render
        # Transkun is trained on real pianos and ignores plain harmonic tones, so render with piano samples.
        events = [dict(start_seconds=0.5, end_seconds=1.0, pitch=60, velocity=90),
                  dict(start_seconds=1.2, end_seconds=1.7, pitch=67, velocity=90)]
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / 'clip.wav'
            render(events, wav)
            backend = TranskunBackend()
            try:
                prediction = backend.transcribe(wav, TranscriptionConfig())
            finally:
                backend.close()
        pitches = sorted({p for _, _, p, _ in prediction.notes})
        self.assertTrue({60, 67} <= set(pitches), prediction.notes)
        self.assertEqual(prediction.metadata['name'], 'transkun')


if __name__ == '__main__':
    unittest.main()
