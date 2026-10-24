#!/usr/bin/env python3
"""Clean up a voice recording.

Steps:
  1. Remove DC offset and low-frequency rumble (high-pass filter).
  2. Detect where speech starts and ends, and trim the blank space outside it.
  3. Reduce background noise, using the leading silence as the noise profile.
  4. Fade the edges, normalize loudness, and limit peaks.

Usage:
    python clean_audio.py recording.wav
    python clean_audio.py recording.mp3 -o cleaned.wav --noise-strength 0.8
"""

import argparse
from pathlib import Path

import noisereduce as nr
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfiltfilt

FRAME_MS = 30
HOP_MS = 10
MIN_NOISE_CLIP_S = 0.3  # shortest silence we trust as a noise profile


def highpass(x, sr, cutoff):
    sos = butter(4, cutoff, btype="highpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x)


def frame_levels_db(x, sr):
    """Return the RMS level in dB of each short frame."""
    frame = int(sr * FRAME_MS / 1000)
    hop = int(sr * HOP_MS / 1000)
    if len(x) < frame:
        x = np.pad(x, (0, frame - len(x)))
    n = 1 + (len(x) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(x[idx] ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms), hop, frame


def speech_bounds(x, sr, threshold_db=None):
    """Return (start, end) sample indexes of the speech in x."""
    levels, hop, frame = frame_levels_db(x, sr)
    if threshold_db is None:
        # Sit just above the noise floor, but never more than 40 dB below the loudest frame.
        noise_floor = np.percentile(levels, 10)
        threshold_db = max(noise_floor + 12, levels.max() - 40)
    active = np.flatnonzero(levels > threshold_db)
    if active.size == 0:
        return 0, len(x)  # nothing stands out from the noise; keep everything
    start = active[0] * hop
    end = min(len(x), active[-1] * hop + frame)
    return start, end


def pick_noise_clip(x, sr, start, end):
    """Use the leading silence (or trailing if leading is too short) as the noise profile."""
    min_len = int(MIN_NOISE_CLIP_S * sr)
    if start >= min_len:
        return x[:start]
    if len(x) - end >= min_len:
        return x[end:]
    return None


def clean_channel(x, sr, args):
    x = x - np.mean(x)
    x = highpass(x, sr, args.highpass)

    start, end = speech_bounds(x, sr, args.threshold_db)
    noise_clip = pick_noise_clip(x, sr, start, end)

    denoised = nr.reduce_noise(
        y=x,
        sr=sr,
        y_noise=noise_clip,
        prop_decrease=args.noise_strength,
        stationary=False,
    )

    pad = int(args.pad * sr)
    return denoised[max(0, start - pad):min(len(denoised), end + pad)]


def fade_edges(x, sr, fade_ms=10):
    n = min(int(sr * fade_ms / 1000), len(x) // 2)
    if n == 0:
        return x
    ramp = np.linspace(0.0, 1.0, n).reshape(-1, *([1] * (x.ndim - 1)))
    x = x.copy()
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


def normalize(x, target_db, peak_db=-1.0):
    """Scale to the target RMS level without letting peaks go above peak_db."""
    rms = np.sqrt(np.mean(x ** 2) + 1e-12)
    gain = 10 ** (target_db / 20) / rms
    peak = np.max(np.abs(x)) + 1e-12
    gain = min(gain, 10 ** (peak_db / 20) / peak)
    return x * gain


def main():
    parser = argparse.ArgumentParser(description="Remove background noise and silence from a recording.")
    parser.add_argument("input", type=Path, help="Input audio file (wav, flac, ogg, mp3, ...)")
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: <input>_clean.wav)")
    parser.add_argument("--noise-strength", type=float, default=0.9,
                        help="How hard to reduce noise, 0-1 (default: 0.9)")
    parser.add_argument("--highpass", type=float, default=80.0,
                        help="High-pass cutoff in Hz to remove rumble (default: 80)")
    parser.add_argument("--threshold-db", type=float, default=None,
                        help="Speech detection level in dBFS. Auto-detected if omitted.")
    parser.add_argument("--pad", type=float, default=0.15,
                        help="Seconds of silence to keep at each end (default: 0.15)")
    parser.add_argument("--target-db", type=float, default=-20.0,
                        help="Target loudness in dBFS RMS (default: -20)")
    args = parser.parse_args()

    if not 0.0 <= args.noise_strength <= 1.0:
        parser.error("--noise-strength must be between 0 and 1")

    output = args.output or args.input.with_name(f"{args.input.stem}_clean.wav")

    data, sr = sf.read(args.input, always_2d=True)
    print(f"Loaded {args.input} ({data.shape[1]} ch, {sr} Hz, {len(data) / sr:.2f} s)")

    channels = [clean_channel(data[:, c], sr, args) for c in range(data.shape[1])]
    length = min(len(c) for c in channels)
    audio = np.column_stack([c[:length] for c in channels])

    audio = fade_edges(audio, sr)
    audio = normalize(audio, args.target_db)

    sf.write(output, audio, sr)
    print(f"Wrote {output} ({len(audio) / sr:.2f} s)")


if __name__ == "__main__":
    main()
