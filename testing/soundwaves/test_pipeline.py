"""An empty take must be refused with a message for the student, not analysed into 200 missing notes."""

import os
import tempfile
import unittest
import wave
from pathlib import Path

from soundwaves.pipeline import TooFewNotes, analyze

ROOT = Path(__file__).resolve().parents[2]


class EmptyTakeTests(unittest.TestCase):
    def test_silent_recording_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            wav = Path(folder) / 'silence.wav'
            with wave.open(str(wav), 'wb') as h:
                h.setnchannels(1); h.setsampwidth(2); h.setframerate(16000); h.writeframes(b'\x00\x00' * 16000 * 3)
            os.environ['SOUNDWAVES_TRANSCRIBER'] = 'basic'
            try:
                with self.assertRaises(TooFewNotes) as caught:
                    analyze(ROOT / 'soundwaves' / 'pieces' / 'minuet_in_g.mxl', wav, Path(folder) / 'out',
                            explain=False, score_cache=ROOT / 'soundwaves' / 'sessions' / 'scores' / 'minuet_in_g')
            finally:
                os.environ.pop('SOUNDWAVES_TRANSCRIBER', None)
            self.assertIn('No notes were heard', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
