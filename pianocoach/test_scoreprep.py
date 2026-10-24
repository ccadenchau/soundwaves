import unittest

from pianocoach.scoreprep import prepare_reference


class PrepareReferenceTests(unittest.TestCase):
    def test_unisons_and_overlaps_collapse_to_one_attack(self):
        notes = [
            dict(id='s', onset=0.0, duration=1.0, pitch=60, part='S'),
            dict(id='a', onset=0.0, duration=0.5, pitch=60, part='A'),      # unison with s
            dict(id='t', onset=0.5, duration=1.0, pitch=60, part='T'),      # starts while s still sounds
            dict(id='b', onset=1.5, duration=0.5, pitch=60, part='B'),      # new attack after s/t end? s ends 1.0, t ends 1.5 -> ok
            dict(id='x', onset=0.0, duration=1.0, pitch=64, part='A'),
        ]
        chunks = [dict(measure_occurrence=0, measures=[1], start_beat=0.0, end_beat=2.0,
                       notes=[dict(note_id=i, onset_beat=0, onset_seconds=0, carried_in=False) for i in 'satbx'])]
        ref, dropped = prepare_reference(dict(notes=notes, chunks=chunks))
        self.assertEqual(dropped, {'a', 't'})
        kept = {n['id']: n for n in ref['notes']}
        self.assertEqual(set(kept), {'s', 'b', 'x'})
        self.assertAlmostEqual(kept['s']['duration'], 1.5)  # extended to cover the merged tenor note
        self.assertEqual([e['note_id'] for e in ref['chunks'][0]['notes']], ['s', 'b', 'x'])


if __name__ == '__main__':
    unittest.main()
