"""Waveforms must describe real audio and obey artifact access checks."""
import importlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import soundfile as sf

from soundwaves.web.waveform import waveform_data


class WaveformTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / 'take.wav'
        t = np.arange(8000) / 8000
        signal = np.sin(2*np.pi*440*t) * np.where(t < .5, .05, .5)
        sf.write(self.audio, signal, 8000)

    def tearDown(self):
        self.temp.cleanup()

    def test_envelope_preserves_loudness_changes(self):
        data = waveform_data(self.audio)
        self.assertEqual(len(data['peaks']), 960)
        self.assertAlmostEqual(data['duration'], 1, places=3)
        self.assertGreater(np.mean(data['peaks'][500:]), np.mean(data['peaks'][:450]) * 7)
        self.assertLessEqual(max(data['peaks']), 1)

    def test_silent_audio_has_a_flat_waveform(self):
        sf.write(self.audio, np.zeros(8000), 8000)
        self.assertEqual(max(waveform_data(self.audio)['peaks']), 0)

    def test_artifact_route_is_cached_and_rejects_outside_paths(self):
        web = importlib.import_module('soundwaves.web.app')
        pipeline = importlib.import_module('soundwaves.web.pipeline')
        rid = 'a'*32
        directory = self.root / 'reports' / rid
        directory.mkdir(parents=True)
        (directory / 'report.json').write_text('{}')
        manifest = directory / 'artifacts.json'
        manifest.write_text(json.dumps(dict(audio='take.wav')))
        with patch.object(web, 'CACHE', self.root), patch.object(pipeline, 'CACHE', self.root):
            client = web.app.test_client()
            url = f'/artifact/{rid}/audio/waveform'
            with client.get(url) as first:
                self.assertEqual(first.status_code, 200)
                original = first.json
            with patch('soundwaves.web.waveform.waveform_data', side_effect=AssertionError('Not cached')):
                with client.get(url) as second:
                    self.assertEqual(second.json, original)
            self.assertEqual(client.get(f'/artifact/{rid}/report/waveform').status_code, 404)
            manifest.write_text(json.dumps(dict(audio='../outside.wav')))
            self.assertEqual(client.get(url).status_code, 404)

    def test_convert_audio_uses_the_same_waveform_endpoint(self):
        from soundwaves.web.app import app
        folder = self.root / ('b'*32)
        folder.mkdir()
        self.audio.rename(folder / 'original.wav')
        pipeline = importlib.import_module('soundwaves.web.pipeline')
        with patch('soundwaves.convert.CONVERT', self.root), patch.object(pipeline, 'CACHE', self.root):
            with app.test_client().get(f'/api/convert/{folder.name}/original/waveform') as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.json['peaks']), 960)

    def test_unreadable_audio_reports_an_error(self):
        self.audio.write_bytes(b'not audio')
        with self.assertRaises(ValueError):
            waveform_data(self.audio)
