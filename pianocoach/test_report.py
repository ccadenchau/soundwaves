"""The adapter must emit exactly what pianocoach-ui/index.html accepts."""

import tempfile
import unittest
from pathlib import Path

from music21 import meter, note, stream, tempo

from alignment import align_performance
from pianocoach.report import build_ui_report, validate_ui_report
from sheet_downloader.reference import build_reference


def two_hand_score():
    score = stream.Score()
    right, left = stream.Part(id='RH'), stream.Part(id='LH')
    for part, bars in ((right, (('C5', 'D5', 'E5'), ('F5', 'G5', 'A5'))),
                       (left, (('C3',), ('F3',)))):
        for number, pitches in enumerate(bars, 1):
            measure = stream.Measure(number=number)
            if number == 1:
                measure.append(meter.TimeSignature('3/4'))
                measure.append(tempo.MetronomeMark(number=120))
            for p in pitches:
                n = note.Note(p)
                n.quarterLength = 3.0 / len(pitches)
                measure.append(n)
            part.append(measure)
    score.insert(0, right)
    score.insert(0, left)
    return score


class UiReportTests(unittest.TestCase):
    def test_right_hand_report_matches_page_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'score.musicxml'
            two_hand_score().write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            reference = root / 'ref' / 'reference.json'

            # 120 bpm = 0.5 s/beat, one second of silence first; bar 2 rushed at 0.4 s/beat.
            def t(beat):
                return 1.0 + (beat * 0.5 if beat < 3 else 1.5 + (beat - 3) * 0.4)
            played = []
            for beat, midi in zip(range(6), (72, 74, 75, 77, 79, 81)):  # E5 -> Eb5
                played.append(dict(id=f'p{beat}', onset=t(beat), duration=0.4, pitch=midi,
                                   velocity=80, model_score=0.9))
            played.append(dict(id='lh1', onset=t(0), duration=1.4, pitch=48, velocity=70, model_score=0.9))
            played.append(dict(id='lh2', onset=t(3), duration=1.1, pitch=53, velocity=70, model_score=0.9))
            played.append(dict(id='ghost', onset=t(0) + 0.01, duration=0.1, pitch=84, velocity=40, model_score=0.3))
            played.append(dict(id='lowextra', onset=t(0) + 0.3, duration=0.2, pitch=41, velocity=60, model_score=0.8))

            alignment = align_performance(reference, played)
            report = build_ui_report(reference, alignment, performance_notes=played,
                                     musicxml=root / 'ref' / 'reference.musicxml',
                                     piece=dict(title='Two bars', composer='Test'), audio_duration=4.0)
            validate_ui_report(report)

            self.assertEqual(report['piece']['measures'], 2)
            self.assertEqual(report['piece']['time_signature'], [3, 4])
            self.assertEqual(report['piece']['marked_bpm'], 120)
            self.assertEqual(report['notes'], [[1, 1.0, 'C5', 1.0], [1, 2.0, 'D5', 1.0], [1, 3.0, 'E5', 1.0],
                                               [2, 1.0, 'F5', 1.0], [2, 2.0, 'G5', 1.0], [2, 3.0, 'A5', 1.0]])
            categories = sorted(e['category'] for e in report['errors'])
            self.assertEqual(categories, ['wrong_pitch'], report['errors'])
            wrong = report['errors'][0]
            self.assertEqual((wrong['measure'], wrong['beat'], wrong['note_id']), (1, 3.0, 'n1-3'))
            self.assertEqual((wrong['expected'], wrong['actual']), ('E5', 'Eb5'))
            self.assertEqual(wrong['tier'], 'confident')
            self.assertTrue(wrong['explanation'] and wrong['tip'])
            self.assertEqual(report['meta']['dropped_harmonics'], 1)
            self.assertGreaterEqual(report['meta']['omitted_findings'], 1)
            self.assertEqual([b['tempo_status'] for b in report['bars']], ['on_target', 'too_fast'])
            self.assertAlmostEqual(report['take']['duration_seconds'], 4.0)

            both = build_ui_report(reference, alignment, performance_notes=played, hands='both',
                                   piece=dict(title='Two bars', composer='Test'))
            self.assertIn('extra', [e['category'] for e in both['errors']])


if __name__ == '__main__':
    unittest.main()


class SamePitchRepairTests(unittest.TestCase):
    def test_skipped_repeated_note_is_reported_once_at_the_right_slot(self):
        from music21 import meter, note, stream, tempo
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            part = stream.Part(id='RH')
            for number, pitches in enumerate((('D5', 'G4', 'G4'), ('E5', 'C5', 'D5')), 1):
                measure = stream.Measure(number=number)
                if number == 1:
                    measure.append(meter.TimeSignature('3/4'))
                    measure.append(tempo.MetronomeMark(number=120))
                for p in pitches:
                    measure.append(note.Note(p, quarterLength=1.0))
                part.append(measure)
            score = stream.Score()
            score.insert(0, part)
            source = root / 'score.musicxml'
            score.write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            reference = root / 'ref' / 'reference.json'
            # Play everything at 0.5 s per beat, but skip the second G4 (bar 1, beat 3).
            played = [dict(id=f'p{i}', onset=1.0 + i * 0.5, duration=0.45, pitch=m, velocity=80, model_score=0.9)
                      for i, m in enumerate((74, 67, None, 76, 72, 74)) if m is not None]
            alignment = align_performance(reference, played)
            report = build_ui_report(reference, alignment, performance_notes=played,
                                     piece=dict(title='t', composer='t'), audio_duration=4.5)
            self.assertEqual([(e['category'], e['measure'], e['beat'], e['note_id']) for e in report['errors']],
                             [('missing', 1, 3.0, 'n1-3')])


class SpreadChordTests(unittest.TestCase):
    def test_spread_chord_is_not_a_missing_plus_extra(self):
        from music21 import chord, meter, note, stream, tempo
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            part = stream.Part(id='RH')
            measure = stream.Measure(number=1)
            measure.append(meter.TimeSignature('3/4'))
            measure.append(tempo.MetronomeMark(number=120))
            measure.append(chord.Chord(['C4', 'E4', 'G4'], quarterLength=1.0))
            measure.append(note.Note('A4', quarterLength=1.0))
            measure.append(note.Note('B4', quarterLength=1.0))
            part.append(measure)
            score = stream.Score()
            score.insert(0, part)
            source = root / 'score.musicxml'
            score.write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            reference = root / 'ref' / 'reference.json'
            # Rolled chord: C4 then E4 80 ms later then G4 160 ms later (beyond the 50 ms chord window).
            played = [dict(id='c', onset=1.00, duration=0.45, pitch=60, velocity=80, model_score=0.9),
                      dict(id='e', onset=1.08, duration=0.40, pitch=64, velocity=80, model_score=0.9),
                      dict(id='g', onset=1.16, duration=0.35, pitch=67, velocity=80, model_score=0.9),
                      dict(id='a', onset=1.50, duration=0.45, pitch=69, velocity=80, model_score=0.9),
                      dict(id='b', onset=2.00, duration=0.45, pitch=71, velocity=80, model_score=0.9)]
            alignment = align_performance(reference, played)
            raw = sorted(e['category'] for e in alignment['errors'])
            report = build_ui_report(reference, alignment, performance_notes=played,
                                     piece=dict(title='t', composer='t'), audio_duration=3.0)
            # No note may be called missing or extra; a roll wider than the tolerance may surface as timing.
            self.assertEqual([e['category'] for e in report['errors'] if e['category'] != 'timing'], [], (raw, report['errors']))
            self.assertLessEqual(len(report['errors']), 1)
            self.assertGreaterEqual(report['meta']['reconciled_pairs'], 2 if raw else 0)


class OctaveTests(unittest.TestCase):
    def test_octave_displacement_is_one_wrong_pitch_finding(self):
        from music21 import meter, note, stream, tempo
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            part = stream.Part(id='RH')
            measure = stream.Measure(number=1)
            measure.append(meter.TimeSignature('3/4'))
            measure.append(tempo.MetronomeMark(number=120))
            for p in ('D6', 'E6', 'C6'):
                measure.append(note.Note(p, quarterLength=1.0))
            measure2 = stream.Measure(number=2)
            for p in ('A5', 'B5', 'C6'):
                measure2.append(note.Note(p, quarterLength=1.0))
            part.append([measure, measure2])
            score = stream.Score()
            score.insert(0, part)
            source = root / 'score.musicxml'
            score.write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            reference = root / 'ref' / 'reference.json'
            # Bar 1 played an octave down, bar 2 as written.
            pitches = (74, 76, 72, 81, 83, 84)
            played = [dict(id=f'p{i}', onset=1.0 + i * 0.5, duration=0.45, pitch=m, velocity=80, model_score=0.9)
                      for i, m in enumerate(pitches)]
            alignment = align_performance(reference, played)
            report = build_ui_report(reference, alignment, performance_notes=played,
                                     piece=dict(title='t', composer='t'), audio_duration=4.5)
            findings = [(e['category'], e['measure'], e['beat'], e['expected'], e['actual'], e.get('octave')) for e in report['errors']]
            self.assertEqual(findings, [('wrong_pitch', 1, 1.0, 'D6', 'D5', True),
                                        ('wrong_pitch', 1, 2.0, 'E6', 'E5', True),
                                        ('wrong_pitch', 1, 3.0, 'C6', 'C5', True)], findings)
            self.assertIn('wrong octave', report['errors'][0]['explanation'])


class PartialTakeTests(unittest.TestCase):
    def test_only_played_bars_are_marked(self):
        from music21 import meter, note, stream, tempo
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            part = stream.Part(id='RH')
            bars = (('C5', 'D5', 'E5'), ('F5', 'G5', 'A5'), ('B5', 'A5', 'G5'), ('F5', 'E5', 'D5'))
            for number, pitches in enumerate(bars, 1):
                measure = stream.Measure(number=number)
                if number == 1:
                    measure.append(meter.TimeSignature('3/4'))
                    measure.append(tempo.MetronomeMark(number=120))
                for p in pitches:
                    measure.append(note.Note(p, quarterLength=1.0))
                part.append(measure)
            score = stream.Score()
            score.insert(0, part)
            source = root / 'score.musicxml'
            score.write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            reference = root / 'ref' / 'reference.json'
            # The student plays bars 1 and 2 only, with one wrong note in bar 2.
            pitches = (72, 74, 76, 77, 80, 81)  # G5 -> G#5
            played = [dict(id=f'p{i}', onset=1.0 + i * 0.5, duration=0.45, pitch=m, velocity=80, model_score=0.9)
                      for i, m in enumerate(pitches)]
            alignment = align_performance(reference, played)
            report = build_ui_report(reference, alignment, performance_notes=played,
                                     piece=dict(title='t', composer='t'), audio_duration=4.5)
            self.assertEqual(report['meta']['played_bars'], [1, 2])
            # Bars 3 and 4 were never attempted, so nothing may be marked there.
            self.assertTrue(all(e['measure'] <= 2 for e in report['errors']), report['errors'])
            self.assertIn(('wrong_pitch', 2, 'G#5'), [(e['category'], e['measure'], e['actual']) for e in report['errors']])
            self.assertIn('bars 1 to 2', report['coach'])


class ShiftedRunTests(unittest.TestCase):
    def test_run_played_a_step_low_is_four_wrong_notes(self):
        self._check(slice(8, 12), ['B4', 'A4', 'G4', 'F4'],
                    [('wrong_pitch', 3, 1.0, 'C5', 'B4'), ('wrong_pitch', 3, 2.0, 'B4', 'A4'),
                     ('wrong_pitch', 3, 3.0, 'A4', 'G4'), ('wrong_pitch', 3, 4.0, 'G4', 'F4')])

    def test_part_of_a_bar_played_a_step_low(self):
        self._check(slice(9, 12), ['A4', 'G4', 'F4'],
                    [('wrong_pitch', 3, 2.0, 'B4', 'A4'), ('wrong_pitch', 3, 3.0, 'A4', 'G4'), ('wrong_pitch', 3, 4.0, 'G4', 'F4')])

    def _check(self, where, shifted, expected):
        from music21 import meter, note, stream, tempo
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            part = stream.Part(id='RH')
            bars = (('E5', 'D5', 'C5', 'B4'), ('A4', 'G4', 'F4', 'E4'), ('C5', 'B4', 'A4', 'G4'), ('E5', 'D5', 'C5', 'B4'), ('A4', 'G4', 'F4', 'E4'))
            for number, pitches in enumerate(bars, 1):
                measure = stream.Measure(number=number)
                if number == 1:
                    measure.append(meter.TimeSignature('4/4'))
                    measure.append(tempo.MetronomeMark(number=120))
                for name in pitches:
                    measure.append(note.Note(name, quarterLength=1.0))
                part.append(measure)
            score = stream.Score()
            score.insert(0, part)
            source = root / 'score.musicxml'
            score.write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            reference = root / 'ref' / 'reference.json'
            from music21 import pitch as m21pitch
            played_names = [n for bar in bars for n in bar]
            played_names[where] = shifted                            # played a step low, in time
            played = [dict(id=f'p{i}', onset=1.0 + i * 0.5, duration=0.45, pitch=m21pitch.Pitch(n).midi,
                           velocity=80, model_score=0.9) for i, n in enumerate(played_names)]
            alignment = align_performance(reference, played)
            report = build_ui_report(reference, alignment, performance_notes=played,
                                     piece=dict(title='t', composer='t'), audio_duration=12.0)
            findings = sorted((e['category'], e['measure'], e['beat'], e['expected'], e['actual']) for e in report['errors'])
            self.assertEqual(findings, sorted(expected), findings)
