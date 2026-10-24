from dataclasses import dataclass
from math import isfinite


@dataclass(frozen=True)
class AlignmentConfig:
    # Performance onsets this close form one chord. No quantization is applied.
    chord_window_seconds: float = 0.05
    score_chord_window_beats: float = 0.0001
    tempo_tolerance: float = 0.12
    timing_tolerance_seconds: float = 0.10
    timing_tolerance_beats: float = 0.20
    minimum_pitch_recall: float = 0.50
    maximum_alignment_cells: int = 4_000_000

    def validate(self):
        for value in (self.chord_window_seconds, self.score_chord_window_beats,
                      self.tempo_tolerance, self.timing_tolerance_seconds,
                      self.timing_tolerance_beats):
            if not isfinite(value) or value <= 0:
                raise ValueError('Alignment windows and tolerances must be positive and finite.')
        if not 0 < self.minimum_pitch_recall <= 1:
            raise ValueError('minimum_pitch_recall must be in (0, 1].')
        if not isinstance(self.maximum_alignment_cells, int) or self.maximum_alignment_cells < 1:
            raise ValueError('maximum_alignment_cells must be a positive integer.')
