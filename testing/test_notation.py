import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from music21 import bar, chord, note, stream

from sheet_downloader.reference import build_reference
from pianocoach.web.notation import _extra_anchor, build_notation


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
            from pianocoach.web import app as web, pipeline
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
                with patch('pianocoach.web.notation.build_notation', side_effect=AssertionError('Cache was not reused')):
                    second = client.get(f'/report/{report_id}/notation')
                    self.assertEqual(second.status_code, 200)
                    self.assertEqual(first.json, second.json)
                    second.close()
                first.close()
                with client.get('/static/notation.js') as response:
                    self.assertEqual(response.status_code, 200)
                self.assertEqual(client.get('/').status_code, 200)


class ExtraAnchorTests(unittest.TestCase):
    """An extra note must not be pinned to the other hand's note that merely sounds beside it."""

    def setUp(self):
        notes = [dict(id='L1', pitch=48, onset=0.0, part='P1-Staff2', measure=1),
                 dict(id='L2', pitch=43, onset=1.0, part='P1-Staff2', measure=1),
                 dict(id='R1', pitch=76, onset=0.0, part='P1-Staff1', measure=1),
                 dict(id='R2', pitch=79, onset=1.0, part='P1-Staff1', measure=1)]
        self.notes, self.by_id = notes, {n['id']: n for n in notes}
        self.locations = {n['id']: 'x-' + n['id'] for n in notes}

    def match(self, note_id, category, played, time):
        n = self.by_id[note_id]
        return dict(score_note_id=note_id, category=category, score_beat=n['onset'], measure_occurrence=0,
                    expected_pitch=n['pitch'], actual_pitch=played, audio_time=time)

    def report(self, matches):
        return dict(matches=matches, alignment=dict(anchors=[dict(score_beat=0.0, audio_time=0.0),
                                                              dict(score_beat=2.0, audio_time=2.0)]))

    def anchor(self, matches, extra):
        located = [m for m in matches if m['score_note_id'] in self.locations]
        return _extra_anchor(extra, self.report(matches), located, self.locations, self.notes, self.by_id)

    def test_octave_slip_goes_to_the_missing_right_hand_note(self):
        matches = [self.match('L1', 'correct', 48, 0.0), self.match('R1', 'correct', 76, 0.0),
                   self.match('L2', 'correct', 43, 1.02), self.match('R2', 'missing', None, None)]
        extra = dict(score_note_id=None, category='extra', actual_pitch=67, audio_time=1.0, measure_occurrence=0)
        self.assertEqual(self.anchor(matches, extra)['score_note_id'], 'R2')

    def test_stray_high_note_stays_on_the_right_hand_staff(self):
        matches = [self.match('L1', 'correct', 48, 0.0), self.match('R1', 'correct', 76, 0.0),
                   self.match('L2', 'correct', 43, 1.02), self.match('R2', 'correct', 79, 1.5)]
        extra = dict(score_note_id=None, category='extra', actual_pitch=74, audio_time=1.0, measure_occurrence=0)
        self.assertEqual(self.anchor(matches, extra)['score_note_id'], 'R2')  # right hand, though L2 is nearer in time

    def test_low_extra_still_goes_to_the_left_hand(self):
        matches = [self.match('L1', 'correct', 48, 0.0), self.match('R1', 'correct', 76, 0.0),
                   self.match('L2', 'correct', 43, 1.02), self.match('R2', 'correct', 79, 1.05)]
        extra = dict(score_note_id=None, category='extra', actual_pitch=45, audio_time=1.0, measure_occurrence=0)
        self.assertEqual(self.anchor(matches, extra)['score_note_id'], 'L2')


if __name__ == '__main__':
    unittest.main()
