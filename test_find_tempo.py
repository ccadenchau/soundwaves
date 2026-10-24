#!/usr/bin/env python3
"""Tests for the tempo detector."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from find_tempo import find_tempo


def write_click_track(path, bpm, seconds=8.0, sr=22050):
    interval = 60.0 / bpm
    audio = np.zeros(int(seconds * sr), dtype=np.float32)
    click_len = int(0.02 * sr)
    t = np.arange(click_len) / sr
    click = (0.6 * np.sin(2 * np.pi * 1000 * t) * np.exp(-t * 80)).astype(np.float32)
    for onset in np.arange(0.0, seconds - 0.1, interval):
        start = int(onset * sr)
        audio[start:start + click_len] += click
    sf.write(path, audio, sr)


class TempoTest(unittest.TestCase):
    def test_120_bpm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "click_120.wav"
            write_click_track(path, 120)

            result = find_tempo(path)

            self.assertGreaterEqual(result.bpm, 116)
            self.assertLessEqual(result.bpm, 124)
            self.assertGreater(result.confidence, 0.6)
            self.assertGreaterEqual(len(result.beat_times), 8)

    def test_90_bpm(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "click_90.wav"
            write_click_track(path, 90)

            result = find_tempo(path)

            self.assertGreaterEqual(result.bpm, 87)
            self.assertLessEqual(result.bpm, 93)

    def test_trims_leading_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "padded.wav"
            write_click_track(path, 100)
            audio, sr = sf.read(path, dtype="float32")
            padded = np.concatenate([np.zeros(sr * 3, dtype=np.float32), audio])
            sf.write(path, padded, sr)

            result = find_tempo(path)

            self.assertGreaterEqual(result.bpm, 97)
            self.assertLessEqual(result.bpm, 103)

    def test_rejects_silence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "silence.wav"
            sf.write(path, np.zeros(22050 * 4, dtype=np.float32), 22050)

            with self.assertRaises(ValueError):
                find_tempo(path)

    def test_rejects_short_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "short.wav"
            sf.write(path, np.zeros(2205, dtype=np.float32), 22050)

            with self.assertRaisesRegex(ValueError, "too short"):
                find_tempo(path)


if __name__ == "__main__":
    unittest.main()
