import subprocess
from pathlib import Path

SAMPLE_RATE = 22050


def prepare_audio(source: Path, destination: Path, maximum_duration: float) -> dict:
    import imageio_ffmpeg
    import numpy as np
    import soundfile as sf

    command = [
        imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
        '-i', str(source), '-map', '0:a:0', '-vn', '-ac', '1',
        '-ar', str(SAMPLE_RATE), '-t', str(maximum_duration + 1),
        '-c:a', 'pcm_f32le', str(destination),
    ]
    try:
        process = subprocess.run(command, capture_output=True, check=False, timeout=120)
    except subprocess.TimeoutExpired as error:
        raise ValueError('Audio decoding timed out. Use a shorter recording.') from error
    if process.returncode:
        raise ValueError('Could not decode the recording. Supply a readable audio file.')
    samples, sample_rate = sf.read(destination, dtype='float32')
    if not len(samples) or not np.isfinite(samples).all():
        raise ValueError('The recording is empty or contains invalid samples.')
    duration = len(samples) / sample_rate
    if duration > maximum_duration:
        raise ValueError(f'Recording exceeds the {maximum_duration:g}-second limit.')
    peak = float(np.max(np.abs(samples)))
    return {
        'duration_seconds': duration,
        'sample_rate': sample_rate,
        'channels': 1,
        'silent': peak == 0,
        'peak_amplitude': peak,
        'timing': 'Seconds from the beginning of the supplied audio; no silence trimming.',
        'preprocessing': 'Decode, mono downmix, and resample. No denoising or gain normalization.',
    }
