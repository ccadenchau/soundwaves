"""The piano cleaner must keep the timeline, the whole keyboard, and quiet notes."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audio_cleaner.clean_audio import CleanConfig, clean_audio


def tone(freq, seconds, sr, amp):
    t = np.arange(int(seconds * sr)) / sr
    return amp * np.sin(2 * np.pi * freq * t) * np.exp(-t * 1.5)


class PianoCleanerTests(unittest.TestCase):
    def setUp(self):
        self.sr = 16000
        rng = np.random.default_rng(0)
        x = np.zeros(self.sr * 4)
        x[self.sr:self.sr * 3] += tone(27.5, 2, self.sr, 0.5)      # A0, the lowest piano key
        x[self.sr:self.sr * 3] += tone(440.0, 2, self.sr, 0.05)    # a quiet A4 on top
        x += rng.normal(0, 0.01, len(x))                           # room hiss
        self.folder = tempfile.TemporaryDirectory()
        self.src = Path(self.folder.name) / 'in.wav'
        sf.write(self.src, x, self.sr)

    def tearDown(self):
        self.folder.cleanup()

    def band(self, y, lo, hi):
        spectrum = np.abs(np.fft.rfft(y[self.sr:self.sr * 2]))
        freqs = np.fft.rfftfreq(self.sr, 1 / self.sr)
        return spectrum[(freqs >= lo) & (freqs <= hi)].sum()

    def test_timeline_bass_and_quiet_notes_survive(self):
        out = clean_audio(self.src, Path(self.folder.name) / 'out.wav')
        x, _ = sf.read(self.src)
        y, sr = sf.read(out)
        self.assertEqual(sr, self.sr)
        self.assertEqual(len(y), len(x), 'nothing may be trimmed')
        # Compare shapes, not levels: the output is peak-normalised.
        x, y = x / np.abs(x).max(), y / np.abs(y).max()
        self.assertGreater(self.band(y, 25, 30) / self.band(x, 25, 30), 0.7, 'A0 must survive')
        self.assertGreater(self.band(y, 435, 445) / self.band(x, 435, 445), 0.7, 'a quiet note must survive')
        hiss_before = np.std(x[: self.sr // 2])
        hiss_after = np.std(y[: self.sr // 2])
        self.assertLess(hiss_after, hiss_before * 0.8, 'room noise should drop')

    def test_phone_sample_rates_work(self):
        for rate in (44100, 48000, 96000):
            with self.subTest(rate=rate):
                rng = np.random.default_rng(1)
                x = rng.normal(0, 0.01, rate * 2)
                x[rate // 2: rate // 2 + rate] += tone(261.6, 1, rate, 0.4)
                src = Path(self.folder.name) / f'r{rate}.wav'
                sf.write(src, x, rate)
                y, sr = sf.read(clean_audio(src, Path(self.folder.name) / f'r{rate}-out.wav'))
                self.assertEqual((sr, len(y)), (rate, len(x)))

    def test_piano_is_the_default_and_rejects_bass_cutting_filters(self):
        self.assertEqual(CleanConfig().mode, 'piano')
        with self.assertRaises(ValueError):
            clean_audio(self.src, Path(self.folder.name) / 'bad.wav', highpass=80.0)


if __name__ == '__main__':
    unittest.main()
