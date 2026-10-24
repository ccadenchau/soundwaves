#!/usr/bin/env python3
"""Tempo detection for recorded music.

Python usage:
    from find_tempo import find_tempo

    result = find_tempo("recording.wav")
    print(result.bpm, result.confidence)

Command-line usage:
    python find_tempo.py recording.wav
    python find_tempo.py recording.wav --json
    python find_tempo.py recording.wav --min-bpm 50 --max-bpm 200
"""

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import librosa
import numpy as np

DEFAULT_MIN_BPM = 40.0
DEFAULT_MAX_BPM = 240.0
DEFAULT_START_BPM = 120.0
MIN_DURATION_SECONDS = 1.0


@dataclass(frozen=True)
class TempoEstimate:
    """Result of tempo detection.

    ``confidence`` is a heuristic frame-agreement score in [0, 1], not a
    calibrated probability.
    """

    bpm: float
    confidence: float
    candidates: tuple[float, ...]
    beat_times: tuple[float, ...]
    duration_seconds: float

    def to_dict(self):
        return {
            "bpm": self.bpm,
            "confidence": self.confidence,
            "candidates": list(self.candidates),
            "beat_times": list(self.beat_times),
            "duration_seconds": self.duration_seconds,
        }


def find_tempo(
    path,
    *,
    min_bpm=DEFAULT_MIN_BPM,
    max_bpm=DEFAULT_MAX_BPM,
    start_bpm=DEFAULT_START_BPM,
    sample_rate=22050,
    hop_length=512,
    trim_top_db=40.0,
):
    """Estimate a recording's global tempo in beats per minute.

    The recording is trimmed of leading/trailing silence, onset strength is
    computed, and per-frame tempo candidates are folded into
    ``[min_bpm, max_bpm)`` to resolve octave (half/double) ambiguity. Beats
    are tracked with the chosen tempo as the prior.

    Raises:
        ValueError: if the file is empty, too short, or contains no detectable
            onsets.
    """
    if not 0 < min_bpm < max_bpm:
        raise ValueError("min_bpm must be positive and less than max_bpm")
    if not 0 < start_bpm:
        raise ValueError("start_bpm must be positive")

    audio, sr = librosa.load(str(path), sr=sample_rate, mono=True)
    duration = float(librosa.get_duration(y=audio, sr=sr))
    if duration < MIN_DURATION_SECONDS:
        raise ValueError(
            f"Recording is too short ({duration:.2f}s); "
            f"need at least {MIN_DURATION_SECONDS:.0f}s"
        )

    audio, _ = librosa.effects.trim(audio, top_db=trim_top_db)
    if audio.size < sr * MIN_DURATION_SECONDS:
        raise ValueError("Recording contains no sustained audio after trimming silence")

    onset_envelope = librosa.onset.onset_strength(
        y=audio, sr=sr, hop_length=hop_length
    )
    if not np.any(onset_envelope > 0):
        raise ValueError("No onsets detected; cannot estimate tempo")

    raw_candidates = np.asarray(
        librosa.feature.tempo(
            onset_envelope=onset_envelope,
            sr=sr,
            hop_length=hop_length,
            start_bpm=start_bpm,
            aggregate=None,
        ),
        dtype=float,
    )
    candidates = _fold_tempo(raw_candidates, min_bpm, max_bpm)
    candidates = candidates[np.isfinite(candidates)]
    if candidates.size == 0:
        raise ValueError("Tempo estimation failed; no valid candidates")

    bpm = _dominant_tempo(candidates, min_bpm, max_bpm)
    _, beats = librosa.beat.beat_track(
        onset_envelope=onset_envelope,
        sr=sr,
        hop_length=hop_length,
        start_bpm=bpm,
        units="time",
        trim=False,
    )

    agreement = float(np.mean(np.abs(candidates - bpm) <= 0.04 * bpm))
    regularity = _beat_regularity(np.asarray(beats, dtype=float))
    confidence = float(np.clip(0.5 * agreement + 0.5 * regularity, 0.0, 1.0))

    return TempoEstimate(
        bpm=round(bpm, 2),
        confidence=round(confidence, 3),
        candidates=_top_candidates(candidates, min_bpm, max_bpm),
        beat_times=tuple(float(t) for t in beats),
        duration_seconds=round(duration, 3),
    )


def _fold_tempo(bpm, min_bpm, max_bpm):
    folded = np.where(np.isfinite(bpm) & (bpm > 0), bpm, np.nan)
    for _ in range(8):
        low = folded < min_bpm
        high = folded >= max_bpm
        if not (np.any(low) or np.any(high)):
            break
        folded = np.where(low, folded * 2.0, folded)
        folded = np.where(high, folded / 2.0, folded)
    return np.where((folded >= min_bpm) & (folded < max_bpm), folded, np.nan)


def _tempo_histogram(candidates, min_bpm, max_bpm):
    bin_width = 1.0
    edges = np.arange(min_bpm, max_bpm + bin_width, bin_width)
    hist, edges = np.histogram(candidates, bins=edges)
    return hist, edges


def _dominant_tempo(candidates, min_bpm, max_bpm):
    hist, edges = _tempo_histogram(candidates, min_bpm, max_bpm)
    if not np.any(hist):
        return float(np.median(candidates))
    peak = int(np.argmax(hist))
    center = 0.5 * (edges[peak] + edges[peak + 1])
    near = candidates[np.abs(candidates - center) <= 0.04 * center]
    return float(np.median(near)) if near.size else center


def _top_candidates(candidates, min_bpm, max_bpm, limit=3):
    hist, edges = _tempo_histogram(candidates, min_bpm, max_bpm)
    order = np.argsort(hist)[::-1]
    chosen = []
    for idx in order:
        if hist[idx] == 0:
            break
        center = 0.5 * (edges[idx] + edges[idx + 1])
        if any(abs(center - existing) <= 0.08 * existing for existing in chosen):
            continue
        chosen.append(round(float(center), 2))
        if len(chosen) == limit:
            break
    return tuple(chosen)


def _beat_regularity(beats):
    if beats.size < 2:
        return 0.0
    intervals = np.diff(beats)
    median_interval = float(np.median(intervals))
    if median_interval <= 0:
        return 0.0
    return float(np.mean(np.abs(intervals - median_interval) <= 0.25 * median_interval))


def build_parser():
    parser = argparse.ArgumentParser(
        description="Detect the tempo of an audio recording."
    )
    parser.add_argument(
        "input", type=Path,
        help="Input audio file (wav, flac, ogg, mp3, ...)",
    )
    parser.add_argument(
        "--min-bpm", type=float, default=DEFAULT_MIN_BPM,
        help="Lowest plausible tempo (default: 40)",
    )
    parser.add_argument(
        "--max-bpm", type=float, default=DEFAULT_MAX_BPM,
        help="Highest plausible tempo (default: 240)",
    )
    parser.add_argument(
        "--start-bpm", type=float, default=DEFAULT_START_BPM,
        help="Tempo prior for beat tracking (default: 120)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Print the full result as JSON",
    )
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        result = find_tempo(
            args.input,
            min_bpm=args.min_bpm,
            max_bpm=args.max_bpm,
            start_bpm=args.start_bpm,
        )
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    candidates = ", ".join(f"{bpm:g}" for bpm in result.candidates)
    print(
        f"{result.bpm:.2f} BPM "
        f"(confidence {result.confidence:.2f}, candidates: {candidates})"
    )
    print(f"{len(result.beat_times)} beats over {result.duration_seconds:.2f} s")


if __name__ == "__main__":
    main()
