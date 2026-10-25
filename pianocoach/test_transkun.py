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

    def test_chords_quiet_notes_and_mechanical_clicks(self):
        import numpy as np
        import soundfile as sf
        from transcribe_recording import transcribe_recording
        from testing.render_piano import render
        from testing.datasets.audio_eval import note_f1
        from pianocoach.clean import clean_notes

        events = []
        for i, pitch in enumerate([60, 64, 67, 72, 71, 69, 67, 65, 64, 62, 60, 67]):
            start = .5 + i * .45
            events.append(dict(start_seconds=start, end_seconds=start + .30, pitch=pitch,
                               velocity=55 if i % 3 == 0 else 88))
        for i, pitch in enumerate([48, 53, 55, 48]):
            start = .5 + i * 1.35
            events.append(dict(start_seconds=start, end_seconds=start + 1.05, pitch=pitch, velocity=70))
        backend = TranskunBackend()
        try:
            with tempfile.TemporaryDirectory() as folder:
                wav = Path(folder) / 'clip.wav'
                render(events, wav, noise=.001)
                samples, sr = sf.read(wav)
                rng = np.random.default_rng(8)
                for event in events:
                    start, count = int(event['start_seconds'] * sr), int(.008 * sr)
                    samples[start:start + count] += rng.normal(0, .12, count) * np.hanning(count)
                sf.write(wav, samples, sr)
                result = transcribe_recording(wav, Path(folder) / 'take', backend=backend)
                kept, _ = clean_notes(result.notes, harmonics=False)
                metrics = note_f1([(n['start_seconds'], n['pitch']) for n in events],
                                  [(n['onset'], n['pitch']) for n in kept])
                self.assertGreaterEqual(metrics['precision'], .95, metrics)
                self.assertGreaterEqual(metrics['recall'], .95, metrics)
        finally:
            backend.close()


if __name__ == '__main__':
    unittest.main()
