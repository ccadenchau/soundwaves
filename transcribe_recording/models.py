from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class TranscriptionConfig:
    onset_threshold: float = 0.5
    frame_threshold: float = 0.3
    minimum_note_length_ms: float = 50.0
    lowest_pitch: int = 21
    highest_pitch: int = 108
    maximum_duration_seconds: float = 600.0
    save_model_output: bool = False

    def validate(self) -> None:
        for value in (self.onset_threshold, self.frame_threshold):
            if not isfinite(value) or not 0 < value <= 1:
                raise ValueError('Detection thresholds must be between 0 and 1.')
        if not isfinite(self.minimum_note_length_ms) or self.minimum_note_length_ms <= 0:
            raise ValueError('Minimum note length must be positive.')
        if not isfinite(self.maximum_duration_seconds) or self.maximum_duration_seconds <= 0:
            raise ValueError('Maximum recording duration must be positive.')
        if not 21 <= self.lowest_pitch <= self.highest_pitch <= 108:
            raise ValueError('Pitch range must be within the piano range, MIDI 21–108.')


@dataclass(frozen=True)
class PlayedNote:
    id: str
    pitch: int
    onset: float
    duration: float
    velocity: int
    model_score: float
    source: str = 'performance'
    confidence: float | None = None


@dataclass
class Prediction:
    notes: list[tuple[float, float, int, float]]
    metadata: dict[str, Any]
    model_output: dict[str, Any] | None = None


class TranscriptionBackend(Protocol):
    def transcribe(self, audio_path: Path, config: TranscriptionConfig) -> Prediction: ...


@dataclass(frozen=True)
class TranscriptionResult:
    directory: Path
    midi_path: Path
    notes_path: Path
    raw_notes_path: Path
    model_output_path: Path | None
    notes: tuple[PlayedNote, ...]
    duration_seconds: float
    warnings: tuple[str, ...]
