"""Practice endpoints: bounded audio, real score shape, and incomplete takes."""

import io
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask

from pianocoach import live
from transcribe_recording.models import Prediction


def wav_bytes(seconds=0.1, rate=22050, channels=1, width=2, value=0):
    out = io.BytesIO()
    with wave.open(out, 'wb') as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(bytes([value]) * int(seconds * rate) * channels * width)
    return out.getvalue()


def reference():
    return dict(time_unit='quarter_note', tempo_changes=[[0, 108]], notes=[
        dict(id='bass', pitch=48, onset=0, duration=1, part='lower'),
        dict(id='first', pitch=72, onset=0, duration=1, part='upper'),
        dict(id='repeat', pitch=74, onset=3, duration=1, part='upper')], chunks=[
            dict(measures=[1], start_beat=0, end_beat=3, notes=[], measure_occurrence=0),
            dict(measures=[1], start_beat=3, end_beat=6, notes=[], measure_occurrence=1)])


def summary_fixture(last=4, detected=6):
    matches = []
    for beat, pitch in ((0, 60), (0.5, 61), (1, 62), (2, 64), (3, 65), (4, 67), (5, 69)):
        played = beat <= last and beat != 1 and bool(detected)
        actual = 66 if beat == 3 else pitch
        matches.append(dict(score_note_id=f's{beat}', expected_pitch=pitch, score_beat=beat,
                            performance_note_id=f'p{beat}' if played else None,
                            actual_pitch=actual if played else None, audio_time=beat / 2 if played else None,
                            category='missing' if not played else 'correct' if actual == pitch else 'wrong_pitch'))
    report = dict(piece=dict(title='Test piece', time_signature=[3, 4]), coach='Final coaching.', errors=[
        dict(id='covered', category='missing', measure=1, beat=2, expected='D4', actual=None),
        dict(id='current', category='wrong_pitch', measure=2, beat=1, expected='F4', actual='F#4'),
        dict(id='suffix', category='missing', measure=2, beat=3, expected='A4', actual=None)])
    alignment = dict(matches=matches, errors=[],
                     metrics=dict(performed_notes=detected, pitch_precision=0.9),
                     alignment=dict(status='aligned', anchors=[dict(score_beat=m['score_beat'], audio_time=m['audio_time'])
                                                               for m in matches if m['category'] == 'correct']),
                     measures=[dict(number=1, occurrence=0, start_beat=0, end_beat=3),
                               dict(number=2, occurrence=1, start_beat=3, end_beat=6)])
    return report, alignment


class PracticeTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.register_blueprint(live.practice)
        self.client = app.test_client()

    def post(self, data):
        response = self.client.post('/api/practice/notes', data={'audio': (io.BytesIO(data), 'window.wav')})
        self.addCleanup(response.close)
        self.addCleanup(response.request.input_stream.close)
        return response

    def test_score_preserves_repeat_occurrences_and_hands(self):
        with patch.object(live, 'score_metadata', return_value={'time_signature': [3, 4]}):
            data = live._score_payload('test', {'title': 'Test'}, reference())
        self.assertEqual(data['piece']['measures'], 2)
        self.assertEqual(data['piece']['printedMeasures'], 1)
        self.assertEqual(data['totalBeats'], 6)
        self.assertEqual({n['hand'] for n in data['notes']}, {'left', 'right'})
        self.assertEqual(data['notes'][-1]['measure'], 2)
        self.assertEqual(data['notes'][-1]['printedMeasure'], 1)
        self.assertEqual(data['notes'][-1]['beatInMeasure'], 1)

    def test_known_piece_route_and_no_directory_traversal(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'test.mxl').write_bytes(b'fixture')
            with patch.object(live, 'PIECES', root), patch.object(live, '_read_score', return_value={'notes': []}):
                self.assertEqual(self.client.get('/api/practice/score/test').status_code, 200)
                self.assertEqual(self.client.get('/api/practice/score/unknown').status_code, 404)
                self.assertEqual(self.client.get('/api/practice/score/..').status_code, 404)

    def test_incomplete_shared_cache_is_never_removed_or_replaced(self):
        def convert(source, destination, **kwargs):
            destination.mkdir()
            notes = destination / 'reference.json'
            notes.write_text(json.dumps(reference()))
            return SimpleNamespace(notes=notes, musicxml=destination / 'reference.musicxml')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'test.mxl'
            source.write_bytes(b'fixture')
            cache = root / 'scores'
            pending = cache / 'test'
            pending.mkdir(parents=True)
            sentinel = pending / 'conversion-in-progress'
            sentinel.write_text('owned by another request')
            with patch.object(live, 'SCORE_CACHE', cache), patch.object(live, '_prepared_scores', {}), \
                 patch.object(live, 'convert_score', side_effect=convert), \
                 patch.object(live, 'score_metadata', return_value={'time_signature': [3, 4]}):
                self.assertEqual(live._read_score('test', source, {})['totalBeats'], 6)
            self.assertEqual(sentinel.read_text(), 'owned by another request')
            self.assertEqual(list(cache.iterdir()), [pending])

    def test_asset_route_allows_frontend_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'practice.js').write_text('test')
            (root / 'report.json').write_text('{}')
            with patch.object(live, 'UI', root):
                with self.client.get('/practice-assets/practice.js') as response:
                    self.assertEqual(response.status_code, 200)
                self.assertEqual(self.client.get('/practice-assets/report.json').status_code, 404)
                self.assertEqual(self.client.get('/practice-assets/../practice.js').status_code, 404)

    def test_piano_route_accepts_only_piano_midi_numbers(self):
        for value in ('20', '109', '-1', '60.5', 'C4', '..'):
            with self.subTest(value=value):
                self.assertEqual(self.client.get('/api/practice/piano/' + value).status_code, 404)

    @unittest.skipUnless(live.PIANO_BANK.is_file(), 'Bundled piano sample bank unavailable')
    def test_piano_samples_are_playable_mp3_with_attribution(self):
        import numpy as np
        import soundfile as sf

        for pitch in (21, 60, 108):
            with self.subTest(pitch=pitch), self.client.get(f'/api/practice/piano/{pitch}') as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, 'audio/mpeg')
                self.assertIn('Frank Wen', response.headers['X-Audio-Attribution'])
                self.assertIn('creativecommons.org/licenses/by/3.0', response.headers['Link'])
                audio, rate = sf.read(io.BytesIO(response.data))
                self.assertGreater(rate, 8000)
                self.assertGreater(len(audio), rate / 4)
                self.assertTrue(np.isfinite(audio).all())
                self.assertGreater(float(np.max(np.abs(audio))), 0.001)

    def test_audio_rejects_missing_invalid_long_oversized_and_truncated(self):
        self.assertEqual(self.client.post('/api/practice/notes').status_code, 400)
        for data in (b'not wav', wav_bytes(12.1), wav_bytes(width=1), wav_bytes()[:-10]):
            with self.subTest(size=len(data)):
                self.assertEqual(self.post(data).status_code, 400)
        self.assertEqual(self.post(b'x' * (live.MAX_AUDIO_BYTES + 1)).status_code, 413)

    def test_silence_returns_no_notes_without_model(self):
        with patch.object(live._backend, 'transcribe') as model:
            result = self.post(wav_bytes())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json['notes'], [])
        model.assert_not_called()

    def test_inference_normalizes_relative_notes_and_removes_own_temp_file(self):
        paths = []
        def predict(path, config):
            paths.append(path)
            self.assertTrue(path.is_file())
            self.assertEqual(config.maximum_duration_seconds, 12)
            return Prediction(notes=[(0.02, 0.09, 60, 0.8)], metadata={'name': 'basic-pitch'})
        with patch.object(live._backend, 'transcribe', side_effect=predict):
            result = self.post(wav_bytes(value=1))
        self.assertEqual(result.status_code, 200, result.json)
        self.assertEqual(result.json['notes'][0]['pitch'], 60)
        self.assertEqual(result.json['notes'][0]['onset'], 0.02)
        self.assertFalse(paths[0].exists())

    @unittest.skipUnless((live.ROOT / 'transcribe_recording/model/basic_pitch.onnx').is_file(),
                         'Bundled Basic Pitch model unavailable')
    def test_short_causal_windows_detect_new_attacks_before_note_release(self):
        import soundfile as sf
        from testing.render_piano import render

        # Only samples already captured are sent: the note continues well after
        # this window ends. No future release or full 2-second context is needed.
        model = live.BasicPitchBackend()
        with tempfile.TemporaryDirectory() as folder, patch.object(live, '_backend', model):
            for pitches, heard in (([60], 0.075), ([60, 64, 67], 0.100)):
                with self.subTest(pitches=pitches, heard_seconds=heard):
                    source = Path(folder) / 'sampled-piano.wav'
                    render([dict(start_seconds=0.65, end_seconds=1.5, pitch=pitch, velocity=90)
                            for pitch in pitches], source, tail=0.5)
                    samples, rate = sf.read(source)
                    window = io.BytesIO()
                    sf.write(window, samples[:round((0.65 + heard) * rate)], rate,
                             format='WAV', subtype='PCM_16')
                    response = self.post(window.getvalue())
                    self.assertEqual(response.status_code, 200, response.json)
                    notes = response.json['notes']
                    self.assertEqual({note['pitch'] for note in notes}, set(pitches))
                    self.assertTrue(all(abs(note['onset'] - 0.65) < 0.03 for note in notes))
                    self.assertTrue(all(1 <= note['velocity'] <= 127 for note in notes))

    def test_busy_requests_do_not_queue(self):
        live._inference_slot.acquire()
        try:
            with patch.object(live, '_transcribe_window') as inference:
                response = self.post(wav_bytes())
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers['Retry-After'], '1')
            inference.assert_not_called()
        finally:
            live._inference_slot.release()

    def test_timeout_keeps_slot_until_worker_finishes(self):
        finish = threading.Event()
        done = threading.Event()
        def slow(data):
            finish.wait(2)
            done.set()
            return {'notes': []}
        with patch.object(live, 'INFERENCE_TIMEOUT_SECONDS', 0.01), patch.object(live, '_transcribe_window', side_effect=slow):
            try:
                self.assertEqual(self.post(wav_bytes()).status_code, 504)
                self.assertEqual(self.post(wav_bytes()).status_code, 503)
            finally:
                finish.set()
                self.assertTrue(done.wait(2))
        # Await worker's finally block, not just the mock's final instruction.
        self.assertTrue(live._inference_slot.acquire(timeout=2))
        live._inference_slot.release()

    def test_zero_note_summary_is_not_all_missing(self):
        report, alignment = summary_fixture(detected=0)
        summary = live._summary_payload('a' * 32, report, alignment)
        self.assertEqual(summary['errors'], [])
        self.assertFalse(summary['completed'])
        self.assertIsNone(summary['reachedMeasure'])
        self.assertIsNone(summary['coach'])

    def test_partial_summary_keeps_passed_and_current_wrong_notes_only(self):
        report, alignment = summary_fixture(last=4)
        summary = live._summary_payload('a' * 32, report, alignment)
        self.assertEqual([(e['category'], e['measure']) for e in summary['errors']], [('missing', 1), ('wrong_pitch', 2)])
        self.assertFalse(summary['completed'])
        self.assertEqual(summary['reachedMeasure'], 2)
        self.assertIsNone(summary['coach'])

    def test_complete_summary_keeps_final_coaching(self):
        report, alignment = summary_fixture(last=5)
        summary = live._summary_payload('a' * 32, report, alignment)
        self.assertTrue(summary['completed'])
        self.assertEqual(summary['coach'], 'Final coaching.')
        self.assertEqual(summary['errors'], report['errors'])

    def test_late_repeat_alignment_is_not_claimed_as_completion(self):
        report, alignment = summary_fixture(last=5)
        for match in alignment['matches']:
            if match['score_beat'] < 3:
                match.update(performance_note_id=None, actual_pitch=None, audio_time=None, category='missing')
        summary = live._summary_payload('a' * 32, report, alignment)
        self.assertFalse(summary['completed'])
        self.assertEqual(summary['errors'], [])

    def test_half_length_repeat_is_realigned_to_prefix_without_suffix_errors(self):
        # Simulate the batch traceback placing six heard notes at the start and
        # end of twelve expected notes. Global recall is .5, yet it is half a take.
        matches = []
        for beat in range(12):
            pitch = (60, 62, 64)[beat % 3]
            heard = beat < 3 or beat >= 9
            time = beat if beat < 3 else beat - 6
            matches.append(dict(score_note_id=f's{beat}', expected_pitch=pitch, score_beat=beat,
                                performance_note_id=f'p{time}' if heard else None,
                                actual_pitch=pitch if heard else None, audio_time=time if heard else None,
                                category='correct' if heard else 'missing'))
        report = dict(piece=dict(title='Repeats', time_signature=[3, 4]), errors=[], coach='A full take!')
        alignment = dict(matches=matches, errors=[], metrics=dict(performed_notes=6, pitch_precision=1),
                         alignment=dict(status='aligned', anchors=[dict(score_beat=b, audio_time=b if b < 3 else b - 6)
                                                                   for b in (0, 1, 2, 9, 10, 11)]),
                         measures=[dict(number=i % 2 + 1, occurrence=i, start_beat=i * 3, end_beat=(i + 1) * 3)
                                   for i in range(4)])
        summary = live._summary_payload('a' * 32, report, alignment)
        self.assertFalse(summary['completed'])
        self.assertEqual(summary['reachedMeasure'], 2)
        self.assertEqual(summary['errors'], [])
        self.assertIsNone(summary['coach'])

    def test_summary_endpoint_reads_only_known_report(self):
        with tempfile.TemporaryDirectory() as folder:
            report, alignment = summary_fixture(detected=0)
            directory = Path(folder) / ('a' * 32)
            directory.mkdir()
            (directory / 'report.json').write_text(json.dumps(report))
            (directory / 'alignment.json').write_text(json.dumps(alignment))
            with patch.object(live, 'SESSIONS', Path(folder)):
                result = self.client.get('/api/practice/summary/' + 'a' * 32)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json['detectedNotes'], 0)
                self.assertEqual(self.client.get('/api/practice/summary/..').status_code, 404)


if __name__ == '__main__':
    unittest.main()
