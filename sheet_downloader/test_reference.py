"""Regression checks for expression playback through repeat expansion."""

import tempfile
import unittest
from pathlib import Path

from music21 import bar, dynamics, note, stream

from sheet_downloader.reference import build_reference


class ReferenceExpressionTests(unittest.TestCase):
    def test_repeated_wedges_preserve_note_velocities(self):
        for wedge_type, expected in (
            (dynamics.Crescendo, [72, 82, 92]),
            (dynamics.Diminuendo, [72, 62, 52]),
        ):
            with self.subTest(wedge=wedge_type.__name__), tempfile.TemporaryDirectory() as directory:
                score = stream.Score()
                part = stream.Part()
                measure = stream.Measure(number=1)
                notes = [note.Note(pitch) for pitch in ('F4', 'G4', 'A4')]
                measure.append(notes)
                measure.leftBarline = bar.Repeat(direction='start')
                measure.rightBarline = bar.Repeat(direction='end')
                part.append(measure)
                part.insert(0, wedge_type(notes[0], notes[-1]))
                score.insert(0, part)
                source = Path(directory) / 'score.musicxml'
                score.write('musicxml', fp=source)

                manifest = build_reference(
                    source, Path(directory) / 'reference', render_audio=False,
                )

                self.assertEqual(
                    [event['velocity'] for event in manifest['notes']],
                    expected * 2,
                )
                self.assertTrue((Path(directory) / 'reference/reference.mid').is_file())


if __name__ == '__main__':
    unittest.main()
