"""A short take must be pinned to the stretch of the score it covers before anything is marked."""

import tempfile
import unittest
from pathlib import Path

from music21 import meter, note, stream, tempo

from soundwaves.pipeline import align_clean
from sheet_downloader.reference import build_reference

SCALE = ['C4', 'D4', 'E4', 'F4', 'G4', 'A4', 'B4', 'C5', 'D5', 'E5', 'F5', 'G5', 'A5', 'B5', 'C6', 'D6']


def sixteen_bar_score():
    part = stream.Part(id='RH')
    for number in range(1, 17):
        measure = stream.Measure(number=number)
        if number == 1:
            measure.append(meter.TimeSignature('3/4'))
            measure.append(tempo.MetronomeMark(number=120))
        # 5 is coprime with 16, so every bar starts on a different scale step and no two bars match
        for k in range(3):
            measure.append(note.Note(SCALE[(number * 5 + k) % len(SCALE)], quarterLength=1.0))
        part.append(measure)
    score = stream.Score()
    score.insert(0, part)
    return score


class PartialTakeLocationTests(unittest.TestCase):
    def test_bars_9_to_12_played_correctly_leave_no_marks(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'score.musicxml'
            sixteen_bar_score().write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            import json
            ref = json.loads((root / 'ref' / 'reference.json').read_text())
            played, i = [], 0
            for n in sorted(ref['notes'], key=lambda n: n['onset']):
                if 24.0 <= n['onset'] < 36.0:  # bars 9-12 in quarter beats
                    played.append(dict(id=f'p{i}', onset=1.0 + (n['onset'] - 24.0) * 0.5, duration=0.45,
                                       pitch=n['pitch'], velocity=80, model_score=0.9))
                    i += 1
            alignment, report = align_clean(root / 'ref' / 'reference.json', played,
                                            piece=dict(title='t', composer='t'), audio_duration=8.0)
            self.assertTrue(alignment['preprocessing']['windowed'])
            self.assertEqual(report['meta']['played_bars'], [9, 12])
            self.assertEqual(report['errors'], [], report['errors'])
            self.assertIn('bars 9 to 12', report['coach'])


if __name__ == '__main__':
    unittest.main()


class MidPieceSummaryTests(unittest.TestCase):
    def test_summary_of_a_take_starting_mid_piece_is_reliable(self):
        """Codex's prefix summary must accept the lead-in bar the locator adds before a mid-piece start."""
        import json
        from soundwaves.live import _summary_payload
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'score.musicxml'
            sixteen_bar_score().write('musicxml', fp=source)
            build_reference(source, root / 'ref', render_audio=False)
            ref = json.loads((root / 'ref' / 'reference.json').read_text())
            played, i = [], 0
            for n in sorted(ref['notes'], key=lambda n: n['onset']):
                if 24.0 <= n['onset'] < 36.0:
                    played.append(dict(id=f'p{i}', onset=1.0 + (n['onset'] - 24.0) * 0.5, duration=0.45,
                                       pitch=n['pitch'], velocity=80, model_score=0.9))
                    i += 1
            alignment, report = align_clean(root / 'ref' / 'reference.json', played,
                                            piece=dict(title='t', composer='t'), audio_duration=8.0)
            summary = _summary_payload('a' * 32, report, alignment)
            self.assertEqual(summary['reachedPrintedMeasure'], 12, summary)
            self.assertFalse(summary['completed'])
            self.assertEqual(summary['errors'], [])
