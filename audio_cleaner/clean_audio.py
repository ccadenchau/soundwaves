#!/usr/bin/env python3
"""AI noise removal and mastering for voice recordings.

Version 3 pipeline: DeepFilterNet neural denoising, high-pass filtering,
presence/air EQ, compression, trimming, and loudness normalization.

Python usage:
    from clean_audio import clean_audio

    clean_audio("recording.webm", "cleaned.wav")
    clean_audio("recording.webm", output_path="cleaned.wav", use_ai=False)
    clean_audio("recording.wav", presence_gain=6.0, target_db=-16.0)

Command-line usage:
    python clean_audio.py recording.wav
    python clean_audio.py recording.webm -o cleaned.wav
    python clean_audio.py recording.wav --no-ai
"""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, replace
from math import gcd
from pathlib import Path

import noisereduce as nr
import numpy as np
import soundfile as sf
from scipy.signal import butter, resample_poly, sosfilt, sosfiltfilt

FRAME_MS = 30
HOP_MS = 10
NOISE_FRAME_MS = 10

AI_SAMPLE_RATE = 48000
AI_VERSION = "0.5.6"
AI_RELEASE = f"https://github.com/Rikorose/DeepFilterNet/releases/download/v{AI_VERSION}"
AI_ASSETS = {
    ("Linux", "x86_64"): "deep-filter-0.5.6-x86_64-unknown-linux-musl",
    ("Linux", "aarch64"): "deep-filter-0.5.6-aarch64-unknown-linux-gnu",
    ("Darwin", "x86_64"): "deep-filter-0.5.6-x86_64-apple-darwin",
    ("Darwin", "arm64"): "deep-filter-0.5.6-aarch64-apple-darwin",
    ("Windows", "AMD64"): "deep-filter-0.5.6-x86_64-pc-windows-msvc.exe",
}
AI_SHA256 = {
    "deep-filter-0.5.6-x86_64-unknown-linux-musl": (
        "70775e251eee44c0f2451a1e833326cf8bcbbe304d3e7cd12851e6fce72ef7da"
    ),
}


@dataclass(frozen=True)
class CleanConfig:
    """Settings for :func:`clean_audio`. ``None`` means "pick a sensible default"."""

    use_ai: bool = True
    ai_binary: Path | None = None
    noise_strength: float = 1.0
    residual_strength: float = 1.0
    highpass: float | None = None
    threshold_db: float | None = None
    presence_hz: float = 3200.0
    presence_gain: float | None = None
    presence_q: float = 0.7
    air_hz: float = 6500.0
    air_gain: float = 4.0
    air_q: float = 0.6
    comp_threshold: float = -26.0
    comp_ratio: float = 2.5
    attack_ms: float = 5.0
    release_ms: float = 150.0
    pad: float = 0.15
    target_db: float = -18.0

    def resolved(self) -> "CleanConfig":
        return replace(
            self,
            highpass=(
                self.highpass if self.highpass is not None
                else (60.0 if self.use_ai else 100.0)
            ),
            presence_gain=self.presence_gain if self.presence_gain is not None else 5.0,
        )

    def validate(self) -> None:
        for name in ("noise_strength", "residual_strength"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{name.replace('_', ' ')} must be between 0 and 1")


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
        noise_floor = np.percentile(levels, 10)
        threshold_db = max(noise_floor + 12, levels.max() - 40)
    active = np.flatnonzero(levels > threshold_db)
    if active.size == 0:
        return 0, len(x)
    start = active[0] * hop
    end = min(len(x), active[-1] * hop + frame)
    return start, end


def noise_profile(x, sr, start, end, fraction=0.2):
    """Concatenate quiet frames from outside the speech as a noise sample."""
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
    """Two-pass spectral denoise used when AI is disabled."""
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
    """Simple downward compressor to even out speech and raise quiet parts."""
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
            raise RuntimeError(
                f"Could not read {path}. Install ffmpeg or `pip install imageio-ffmpeg`."
            ) from None

        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "audio.wav"
            try:
                subprocess.run(
                    [ffmpeg, "-y", "-i", str(path), "-vn", "-acodec", "pcm_s16le", str(wav)],
                    check=True,
                    capture_output=True,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(f"ffmpeg could not decode {path}") from exc
            return sf.read(wav, always_2d=True, dtype="float32")


def resample(x, sr_in, sr_out):
    if sr_in == sr_out:
        return x
    factor = gcd(int(sr_in), int(sr_out))
    return resample_poly(x, int(sr_out) // factor, int(sr_in) // factor)


def ai_asset_name():
    system = platform.system()
    machine = platform.machine()
    if system == "Windows":
        machine = "AMD64" if machine.upper() in ("AMD64", "X86_64") else machine
    return AI_ASSETS.get((system, machine))


def find_deep_filter(explicit=None):
    """Return the DeepFilterNet CLI, downloading the official binary if needed."""
    if explicit:
        binary = Path(explicit).expanduser()
        if not binary.exists():
            raise RuntimeError(f"AI binary does not exist: {binary}")
        return binary

    found = shutil.which("deep-filter")
    if found:
        return Path(found)

    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "soundwaves"
    target = cache / f"deep-filter-{AI_VERSION}"
    if target.exists():
        return target

    asset = ai_asset_name()
    if asset is None:
        raise RuntimeError(
            f"No prebuilt DeepFilterNet for {platform.system()} {platform.machine()}. "
            "Install `deep-filter` or disable AI."
        )

    cache.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(".part")
    part.unlink(missing_ok=True)
    try:
        with urllib.request.urlopen(f"{AI_RELEASE}/{asset}", timeout=180) as response:
            with open(part, "wb") as out:
                shutil.copyfileobj(response, out)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"Could not download the AI denoiser: {exc}") from exc

    expected = AI_SHA256.get(asset)
    if expected and hashlib.sha256(part.read_bytes()).hexdigest() != expected:
        part.unlink(missing_ok=True)
        raise RuntimeError("Downloaded AI denoiser failed its checksum.")

    part.chmod(0o755)
    part.replace(target)
    return target


def fit_length(x, length):
    if len(x) >= length:
        return x[:length]
    return np.pad(x, (0, length - len(x)))


def ai_denoise_channel(x, sr, binary):
    """Run DeepFilterNet on one channel, returning audio aligned to x."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        source = tmp / "input.wav"
        outdir = tmp / "out"
        sf.write(source, x, sr, subtype="PCM_16")

        result = subprocess.run(
            [str(binary), "-D", str(source), "-o", str(outdir)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"DeepFilterNet failed:\n{result.stderr.strip()}")

        enhanced = outdir / source.name
        data, out_sr = sf.read(enhanced, always_2d=True, dtype="float32")
        if out_sr != sr:
            raise RuntimeError(f"DeepFilterNet returned {out_sr} Hz, expected {sr} Hz")
        return fit_length(data[:, 0], len(x))


def polish(x, sr, config):
    """Apply the mastering chain shared by the AI and fallback pipelines."""
    x = highpass(x, sr, config.highpass)
    if config.presence_gain:
        x = peaking_eq(x, sr, config.presence_hz, config.presence_gain, config.presence_q)
    if config.air_gain:
        x = peaking_eq(x, sr, config.air_hz, config.air_gain, config.air_q)
    return compress(
        x, sr, config.comp_threshold, config.comp_ratio, config.attack_ms, config.release_ms
    )


def clean_channel_ai(x, sr, config, binary):
    x48 = resample(x - np.mean(x), sr, AI_SAMPLE_RATE)
    enhanced = ai_denoise_channel(x48, AI_SAMPLE_RATE, binary)
    enhanced = fit_length(resample(enhanced, AI_SAMPLE_RATE, sr), len(x))

    start, end = speech_bounds(enhanced, sr, config.threshold_db)
    enhanced = polish(enhanced, sr, config)

    pad = int(config.pad * sr)
    return enhanced[max(0, start - pad):min(len(enhanced), end + pad)]


def clean_channel_dsp(x, sr, config):
    x = x - np.mean(x)
    x = highpass(x, sr, config.highpass)

    start, end = speech_bounds(x, sr, config.threshold_db)
    profile = noise_profile(x, sr, start, end)

    denoised = reduce_noise(x, sr, profile, config.noise_strength, config.residual_strength)
    denoised = polish(denoised, sr, config)

    pad = int(config.pad * sr)
    return denoised[max(0, start - pad):min(len(denoised), end + pad)]


def clean_audio(
    input_path,
    output_path=None,
    config: CleanConfig | None = None,
    *,
    verbose: bool = False,
    **overrides,
) -> Path:
    """Clean a voice recording and return the output path.

    ``output_path`` defaults to ``<input>_clean.wav``. Settings can be passed as a
    :class:`CleanConfig` or as keyword overrides, for example::

        clean_audio("talk.webm", use_ai=False, presence_gain=6.0)
    """
    config = config or CleanConfig()
    if overrides:
        config = replace(config, **overrides)
    config = config.resolved()
    config.validate()

    input_path = Path(input_path)
    output_path = (
        Path(output_path)
        if output_path is not None
        else input_path.with_name(f"{input_path.stem}_clean.wav")
    )

    data, sr = load_audio(input_path)
    if verbose:
        print(f"Loaded {input_path} ({data.shape[1]} ch, {sr} Hz, {len(data) / sr:.2f} s)")

    if config.use_ai:
        binary = find_deep_filter(config.ai_binary)
        if verbose:
            print(f"Denoising with DeepFilterNet {AI_VERSION} ...")
        channels = [
            clean_channel_ai(data[:, c], sr, config, binary)
            for c in range(data.shape[1])
        ]
    else:
        channels = [
            clean_channel_dsp(data[:, c], sr, config)
            for c in range(data.shape[1])
        ]

    length = min(len(channel) for channel in channels)
    audio = np.column_stack([channel[:length] for channel in channels])
    audio = fade_edges(audio, sr)
    audio = normalize(audio, config.target_db)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(output_path, audio, sr)
    if verbose:
        print(f"Wrote {output_path} ({len(audio) / sr:.2f} s)")
    return output_path


def build_parser():
    parser = argparse.ArgumentParser(
        description="AI noise removal and mastering for voice recordings."
    )
    parser.add_argument(
        "input", type=Path,
        help="Input audio/video file (wav, flac, ogg, mp3, webm, mp4, ...)",
    )
    parser.add_argument(
        "-o", "--output", type=Path,
        help="Output file (default: <input>_clean.wav)",
    )
    parser.add_argument("--no-ai", action="store_true",
                        help="Use the version 2 spectral denoiser instead of DeepFilterNet")
    parser.add_argument("--ai-binary", type=Path,
                        help="Path to an existing deep-filter executable")
    parser.add_argument("--noise-strength", type=float, default=1.0,
                        help="(no-ai) how hard to remove the profiled noise, 0-1 (default: 1.0)")
    parser.add_argument("--residual-strength", type=float, default=1.0,
                        help="(no-ai) how hard to chase leftover noise, 0-1 (default: 1.0)")
    parser.add_argument("--highpass", type=float, default=None,
                        help="High-pass cutoff in Hz (default: 60 with AI, 100 without)")
    parser.add_argument("--threshold-db", type=float, default=None,
                        help="Speech detection level in dBFS. Auto-detected if omitted.")
    parser.add_argument("--presence-hz", type=float, default=3200.0,
                        help="Center of the presence boost in Hz (default: 3200)")
    parser.add_argument("--presence-gain", type=float, default=None,
                        help="Presence boost in dB (default: 5)")
    parser.add_argument("--presence-q", type=float, default=0.7,
                        help="Width of the presence boost; higher is narrower (default: 0.7)")
    parser.add_argument("--air-hz", type=float, default=6500.0,
                        help="Center of the air boost in Hz (default: 6500)")
    parser.add_argument("--air-gain", type=float, default=4.0,
                        help="Air boost in dB (default: 4)")
    parser.add_argument("--air-q", type=float, default=0.6,
                        help="Width of the air boost (default: 0.6)")
    parser.add_argument("--comp-threshold", type=float, default=-26.0,
                        help="Compressor threshold in dBFS (default: -26)")
    parser.add_argument("--comp-ratio", type=float, default=2.5,
                        help="Compressor ratio (default: 2.5)")
    parser.add_argument("--attack-ms", type=float, default=5.0,
                        help="Compressor attack in ms (default: 5)")
    parser.add_argument("--release-ms", type=float, default=150.0,
                        help="Compressor release in ms (default: 150)")
    parser.add_argument("--pad", type=float, default=0.15,
                        help="Seconds of silence to keep at each end (default: 0.15)")
    parser.add_argument("--target-db", type=float, default=-18.0,
                        help="Target loudness in dBFS RMS (default: -18)")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    config = CleanConfig(
        use_ai=not args.no_ai,
        ai_binary=args.ai_binary,
        noise_strength=args.noise_strength,
        residual_strength=args.residual_strength,
        highpass=args.highpass,
        threshold_db=args.threshold_db,
        presence_hz=args.presence_hz,
        presence_gain=args.presence_gain,
        presence_q=args.presence_q,
        air_hz=args.air_hz,
        air_gain=args.air_gain,
        air_q=args.air_q,
        comp_threshold=args.comp_threshold,
        comp_ratio=args.comp_ratio,
        attack_ms=args.attack_ms,
        release_ms=args.release_ms,
        pad=args.pad,
        target_db=args.target_db,
    )

    try:
        clean_audio(args.input, args.output, config, verbose=True)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
