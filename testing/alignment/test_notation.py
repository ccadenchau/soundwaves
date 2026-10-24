import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from music21 import bar, chord, note, stream

from sheet_downloader.reference import build_reference
from testing.alignment.notation import build_notation


class NotationTests(unittest.TestCase):
    def test_chords_repeats_wrong_missing_and_extra_notes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            score = stream.Score()
            part = stream.Part()
            measure = stream.Measure(number=1)
            measure.append([chord.Chord(['C4', 'E4']), note.Note('F4'), note.Note('G4')])
            measure.leftBarline = bar.Repeat(direction='start')
            measure.rightBarline = bar.Repeat(direction='end')
            part.append(measure)
            score.append(part)
            source = root / 'score.musicxml'
            score.write('musicxml', fp=source)
            reference = root / 'reference'
            manifest = build_reference(source, reference, render_audio=False)
            matches, played = [], []
            for index, event in enumerate(manifest['notes']):
                category = 'missing' if index == 2 else 'wrong_pitch' if index == 3 else 'correct'
                actual = None if category == 'missing' else event['pitch'] + (2 if category == 'wrong_pitch' else 0)
                performance_id = None if actual is None else f'p{index}'
                time = None if actual is None else event['onset'] * .6 + 1
                matches.append(dict(score_note_id=event['id'], performance_note_id=performance_id,
                                    score_beat=event['onset'], alignment_beat=event['onset'],
                                    expected_pitch=event['pitch'], actual_pitch=actual,
                                    category=category, audio_time=time,
                                    measure_occurrence=int(event['onset'] // 3)))
                if actual is not None:
                    played.append(dict(id=performance_id, onset=time, duration=.4, pitch=actual))
            for performance_id, occurrence, time in [('extra', 0, 1.2), ('unplaced', None, 20)]:
                played.append(dict(id=performance_id, onset=time, duration=.3, pitch=61))
                matches.append(dict(score_note_id=None, performance_note_id=performance_id,
                                    expected_pitch=None, actual_pitch=61, category='extra',
                                    audio_time=time, measure_occurrence=occurrence))
            performance = root / 'performance.json'
            performance.write_text(json.dumps(dict(notes=played)))
            report = dict(matches=matches)
            data = build_notation(reference / 'reference.musicxml', reference / 'reference.json', performance, report)
            self.assertEqual(len(data['annotations']), len(manifest['notes']) + 1)
            self.assertEqual(len(data['unplaced']), 1)
            self.assertEqual(data['unplaced'][0]['performance_note_id'], 'unplaced')
            normal_ids = [a['xml_id'] for a in data['annotations'] if a['category'] != 'extra']
            self.assertEqual(len(set(normal_ids)), len(manifest['notes']))
            rendered_ids = {el.attrib.get('id') for page in data['pages'] for el in ElementTree.fromstring(page).iter()}
            self.assertTrue(set(normal_ids) <= rendered_ids)
            wrong = next(a for a in data['annotations'] if a['category'] == 'wrong_pitch')
            self.assertEqual(wrong['actual_name'], 'A4')
            self.assertEqual(wrong['staff_steps'], 1)
            self.assertEqual(wrong['duration'], .4)

            # Existing reports gain the overlay lazily, without reconverting audio.
            from testing.alignment import app as web, pipeline
            report_id = 'a' * 32
            directory = root / 'reports' / report_id
            directory.mkdir(parents=True)
            (directory / 'report.json').write_text(json.dumps(report))
            artifacts = dict(musicxml='reference/reference.musicxml',
                             sheet_notes='reference/reference.json', recording_notes='performance.json')
            (directory / 'artifacts.json').write_text(json.dumps(artifacts))
            with patch.object(web, 'CACHE', root), patch.object(pipeline, 'CACHE', root):
                client = web.app.test_client()
                first = client.get(f'/report/{report_id}/notation')
                self.assertEqual(first.status_code, 200)
                with patch('testing.alignment.notation.build_notation', side_effect=AssertionError('Cache was not reused')):
                    second = client.get(f'/report/{report_id}/notation')
                    self.assertEqual(second.status_code, 200)
                    self.assertEqual(first.json, second.json)
                    second.close()
                first.close()
                with client.get('/static/notation.js') as response:
                    self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get('/').status_code, 200)


if __name__ == '__main__':
    unittest.main()
