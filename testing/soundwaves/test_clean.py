import unittest

from soundwaves.clean import remove_harmonics


class HarmonicFilterTests(unittest.TestCase):
    def test_short_octave_ghosts_go_and_real_octaves_stay(self):
        notes = [
            dict(id='a', onset=1.00, duration=0.46, pitch=60, velocity=92, model_score=0.7),
            dict(id='a12', onset=1.00, duration=0.13, pitch=72, velocity=50, model_score=0.3),   # ghost
            dict(id='b', onset=1.50, duration=0.47, pitch=62, velocity=90, model_score=0.7),
            dict(id='b19', onset=1.51, duration=0.14, pitch=81, velocity=40, model_score=0.2),   # ghost (19 = octave + fifth)
            dict(id='c', onset=2.00, duration=0.45, pitch=64, velocity=90, model_score=0.7),
            dict(id='c12real', onset=2.00, duration=0.45, pitch=76, velocity=88, model_score=0.7),  # a real octave doubling
            dict(id='d12late', onset=2.60, duration=0.10, pitch=76, velocity=40, model_score=0.3),  # too late to be an overtone
        ]
        kept, dropped = remove_harmonics(notes)
        self.assertEqual(sorted(n['id'] for n in dropped), ['a12', 'b19'])
        self.assertEqual([n['id'] for n in kept], ['a', 'b', 'c', 'c12real', 'd12late'])


if __name__ == '__main__':
    unittest.main()


class ReonsetTests(unittest.TestCase):
    def test_split_note_is_merged_but_repeated_notes_survive(self):
        from soundwaves.clean import merge_reonsets
        notes = [
            dict(id='b1', onset=27.611, duration=0.163, pitch=71, velocity=97, model_score=0.76),
            dict(id='b1split', onset=27.774, duration=0.119, pitch=71, velocity=67, model_score=0.52),  # restart
            dict(id='a', onset=27.774, duration=0.305, pitch=69, velocity=86, model_score=0.68),
            dict(id='g1', onset=30.0, duration=0.55, pitch=67, velocity=90, model_score=0.7),
            dict(id='g2', onset=30.625, duration=0.55, pitch=67, velocity=88, model_score=0.7),  # real repeat
            # Real repeated quarter notes on a sampled piano: the model ends the first exactly where the
            # second starts and hears the second as slightly quieter. Both are full length, so both stay.
            dict(id='r1', onset=3.501, duration=0.627, pitch=67, velocity=86, model_score=0.67),
            dict(id='r2', onset=4.128, duration=0.755, pitch=67, velocity=81, model_score=0.64),
        ]
        kept, dropped = merge_reonsets(notes)
        self.assertEqual([n['id'] for n in dropped], ['b1split'])
        merged = next(n for n in kept if n['id'] == 'b1')
        self.assertAlmostEqual(merged['duration'], 27.774 + 0.119 - 27.611, places=3)
        self.assertEqual([n['id'] for n in kept], ['r1', 'r2', 'b1', 'a', 'g1', 'g2'])


class DuplicateTests(unittest.TestCase):
    def test_same_pitch_twice_within_30ms_is_one_note(self):
        from soundwaves.clean import merge_duplicates
        notes = [dict(id='a', onset=2.500, duration=0.30, pitch=62, velocity=70, model_score=0.6),
                 dict(id='a2', onset=2.512, duration=0.35, pitch=62, velocity=66, model_score=0.6),
                 dict(id='b', onset=2.900, duration=0.30, pitch=62, velocity=70, model_score=0.6)]
        kept, dropped = merge_duplicates(notes)
        self.assertEqual([n['id'] for n in dropped], ['a'])
        self.assertEqual([n['id'] for n in kept], ['a2', 'b'])
        self.assertAlmostEqual(kept[0]['duration'], 2.512 + 0.35 - 2.512, places=3)


class MidiExportTests(unittest.TestCase):
    def test_export_uses_cleaned_notes_and_preserves_real_repeats(self):
        import tempfile
        from pathlib import Path
        import pretty_midi
        from soundwaves.clean import clean_notes, write_performance_midi

        notes = [
            dict(id='a', onset=1.0, duration=.5, pitch=60, velocity=90, model_score=.8),
            dict(id='ghost', onset=1.0, duration=.1, pitch=72, velocity=35, model_score=.3),
            dict(id='repeat', onset=1.6, duration=.3, pitch=60, velocity=85, model_score=.7),
        ]
        kept, _ = clean_notes(notes)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'performance.mid'
            write_performance_midi(kept, path)
            decoded = pretty_midi.PrettyMIDI(str(path)).instruments[0].notes
        self.assertEqual([n.pitch for n in decoded], [60, 60])
        for actual, expected in zip(decoded, kept):
            self.assertAlmostEqual(actual.start, expected['onset'], delta=.002)
            self.assertAlmostEqual(actual.end, expected['onset'] + expected['duration'], delta=.002)
            self.assertEqual(actual.velocity, expected['velocity'])
