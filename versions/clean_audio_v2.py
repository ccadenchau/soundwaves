#!/usr/bin/env python3
"""Clean up a voice recording.

Steps:
  1. Remove DC offset and low-frequency rumble / hum (high-pass filter).
  2. Detect where speech starts and ends, and trim the blank space outside it.
  3. Build a noise profile from the quietest parts of the recording and remove
     the background noise in two passes (stationary + non-stationary).
  4. Add presence so speech sounds crisp, then gently compress it.
  5. Fade the edges, normalize loudness, and limit peaks.

Usage:
    python clean_audio.py recording.wav
    python clean_audio.py recording.webm -o cleaned.wav --noise-strength 0.8
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

import noisereduce as nr
import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt, sosfiltfilt

FRAME_MS = 30
HOP_MS = 10
NOISE_FRAME_MS = 10


def highpass(x, sr, cutoff):
    sos = butter(4, cutoff, btype="highpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x)


def peaking_eq(x, sr, freq, gain_db, q):
    """Boost a band of frequencies (RBJ peaking EQ)."""
    a = 10 ** (gain_db / 40)
    w0 = 2 * np.pi * freq / sr
    alpha = np.sin(w0) / (2 * q)
    c = np.cos(w0)
    b = np.array([1 + alpha * a, -2 * c, 1 - alpha * a])
    d = np.array([1 + alpha / a, -2 * c, 1 - alpha / a])
    sos = np.array([[b[0] / d[0], b[1] / d[0], b[2] / d[0], 1, d[1] / d[0], d[2] / d[0]]])
    return sosfilt(sos, x)


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


def noise_profile(x, sr, start, end, fraction=0.2):
    """Concatenate the quietest frames from outside the speech as a noise sample."""
    levels, hop, frame = frame_levels_db(x, sr)
    outside = np.ones(len(levels), dtype=bool)
    outside[max(0, start // hop - 3):min(len(levels), end // hop + 4)] = False

    candidates = np.flatnonzero(outside)
    if candidates.size < 5:
        candidates = np.arange(len(levels))

    count = max(1, int(candidates.size * fraction))
    quiet = np.sort(candidates[np.argsort(levels[candidates])[:count]])
    return np.concatenate([x[i * hop:i * hop + frame] for i in quiet])


def reduce_noise(x, sr, profile, noise_strength, residual_strength):
    """Two-pass denoise: remove the profiled noise, then chase what is left."""
    denoised = nr.reduce_noise(
        y=x,
        sr=sr,
        y_noise=profile,
        prop_decrease=noise_strength,
        stationary=True,
        n_fft=1024,
        time_mask_smooth_ms=64,
        freq_mask_smooth_hz=300,
    )
    return nr.reduce_noise(
        y=denoised,
        sr=sr,
        prop_decrease=residual_strength,
        stationary=False,
        n_fft=1024,
        time_mask_smooth_ms=64,
        freq_mask_smooth_hz=300,
    )


def compress(x, sr, threshold_db, ratio, attack_ms, release_ms):
    """Simple downward compressor to even out the speech and raise quiet parts."""
    frame = max(1, int(sr * NOISE_FRAME_MS / 1000))
    n = len(x) // frame
    if n < 2:
        return x

    blocks = x[:n * frame].reshape(n, frame)
    levels = 20 * np.log10(np.sqrt(np.mean(blocks ** 2, axis=1)) + 1e-12)

    over = np.maximum(levels - threshold_db, 0.0)
    reduction = over * (1.0 - 1.0 / ratio)

    attack = np.exp(-frame / (sr * attack_ms / 1000))
    release = np.exp(-frame / (sr * release_ms / 1000))
    smoothed = np.empty_like(reduction)
    current = 0.0
    for i, target in enumerate(reduction):
        coeff = attack if target > current else release
        current = coeff * current + (1 - coeff) * target
        smoothed[i] = current

    gain = 10 ** (-smoothed / 20)
    centers = np.arange(n) * frame + frame / 2
    gain = np.interp(np.arange(len(x)), centers, gain)
    return x * gain


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


def load_audio(path):
    """Read any audio/video file, using ffmpeg for formats libsndfile cannot open."""
    try:
        return sf.read(path, always_2d=True, dtype="float32")
    except Exception:
        try:
            import imageio_ffmpeg
        except ImportError:
            raise SystemExit(
                f"Could not read {path}. Install ffmpeg or `pip install imageio-ffmpeg`."
            )

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            subprocess.run(
                [ffmpeg, "-y", "-i", str(path), "-vn", "-acodec", "pcm_s16le", str(wav)],
                check=True,
                capture_output=True,
            )
            return sf.read(wav, always_2d=True, dtype="float32")


def clean_channel(x, sr, args):
    x = x - np.mean(x)
    x = highpass(x, sr, args.highpass)

    start, end = speech_bounds(x, sr, args.threshold_db)
    profile = noise_profile(x, sr, start, end)

    denoised = reduce_noise(x, sr, profile, args.noise_strength, args.residual_strength)
    denoised = peaking_eq(denoised, sr, args.presence_hz, args.presence_gain, args.presence_q)
    denoised = compress(
        denoised, sr, args.comp_threshold, args.comp_ratio, args.attack_ms, args.release_ms
    )

    pad = int(args.pad * sr)
    return denoised[max(0, start - pad):min(len(denoised), end + pad)]


def main():
    parser = argparse.ArgumentParser(description="Remove background noise and sharpen a voice recording.")
    parser.add_argument("input", type=Path, help="Input audio/video file (wav, flac, ogg, mp3, webm, mp4, ...)")
    parser.add_argument("-o", "--output", type=Path, help="Output file (default: <input>_clean.wav)")
    parser.add_argument("--noise-strength", type=float, default=1.0,
                        help="How hard to remove the profiled noise, 0-1 (default: 1.0)")
    parser.add_argument("--residual-strength", type=float, default=1.0,
                        help="How hard to chase leftover noise, 0-1 (default: 1.0)")
    parser.add_argument("--highpass", type=float, default=100.0,
                        help="High-pass cutoff in Hz to remove rumble/hum (default: 100)")
    parser.add_argument("--threshold-db", type=float, default=None,
                        help="Speech detection level in dBFS. Auto-detected if omitted.")
    parser.add_argument("--presence-hz", type=float, default=3000.0,
                        help="Center of the presence boost in Hz (default: 3000)")
    parser.add_argument("--presence-gain", type=float, default=4.0,
                        help="Presence boost in dB (default: 4)")
    parser.add_argument("--presence-q", type=float, default=0.8,
                        help="Width of the presence boost; higher is narrower (default: 0.8)")
    parser.add_argument("--comp-threshold", type=float, default=-28.0,
                        help="Compressor threshold in dBFS (default: -28)")
    parser.add_argument("--comp-ratio", type=float, default=3.0,
                        help="Compressor ratio (default: 3)")
    parser.add_argument("--attack-ms", type=float, default=5.0,
                        help="Compressor attack in ms (default: 5)")
    parser.add_argument("--release-ms", type=float, default=120.0,
                        help="Compressor release in ms (default: 120)")
    parser.add_argument("--pad", type=float, default=0.15,
                        help="Seconds of silence to keep at each end (default: 0.15)")
    parser.add_argument("--target-db", type=float, default=-20.0,
                        help="Target loudness in dBFS RMS (default: -20)")
    args = parser.parse_args()

    for name in ("noise_strength", "residual_strength"):
        if not 0.0 <= getattr(args, name) <= 1.0:
            parser.error(f"--{name.replace('_', '-')} must be between 0 and 1")

    output = args.output or args.input.with_name(f"{args.input.stem}_clean.wav")

    data, sr = load_audio(args.input)
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
