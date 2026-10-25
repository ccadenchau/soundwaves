import unittest

from alignment.analysis import align_performance


def score(chords):
    notes, chunks = [], []
    for beat, pitches in enumerate(chords):
        for pitch in pitches:
            notes.append(dict(id=f's{beat}-{pitch}', pitch=pitch, onset=float(beat), duration=1.0))
    for bar in range(len(chords) // 2):
        chunks.append(dict(measures=[bar + 1], start_beat=2.0 * bar, end_beat=2.0 * bar + 2))
    return dict(time_unit='quarter_note', notes=notes, chunks=chunks, tempo_changes=[[0, 120]])


class SplitNoteTests(unittest.TestCase):
    def compare(self, played):
        notes = [dict(id=f'p{i}', pitch=p, onset=t, duration=0.4) for i, (p, t) in enumerate(played)]
        return align_performance(score([[60, 64], [67], [72], [71]]), dict(notes=notes))

    def test_late_chord_note_merges_into_one_correct_note(self):
        # E4 of the first chord lands 0.2 s after C4, outside the chord window: it used to be
        # missing at its score position and extra beside it.
        report = self.compare([(60, 0.0), (64, 0.2), (67, 0.5), (72, 1.0), (71, 1.5)])
        self.assertEqual([m for m in report['matches'] if m['category'] in ('missing', 'extra')], [])
        self.assertEqual(report['metrics']['correct_notes'], 5)

    def test_same_pitch_far_from_the_slot_is_not_merged(self):
        report = self.compare([(60, 0.0), (67, 0.5), (72, 1.0), (71, 1.5), (64, 9.0)])
        self.assertIn('missing', {m['category'] for m in report['matches']})
        self.assertIn('extra', {m['category'] for m in report['matches']})


if __name__ == '__main__':
    unittest.main()
