"""Small, cached waveform envelopes from the actual playback audio."""

from pathlib import Path
import subprocess

import numpy as np


def waveform_data(source, bins=960):
    import imageio_ffmpeg

    command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-v', 'error',
               '-i', str(source), '-vn', '-ac', '1', '-ar', '16000', '-t', '1800',
               '-f', 'f32le', 'pipe:1']
    try:
        decoded = subprocess.run(command, capture_output=True, timeout=120, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        raise ValueError('Could not decode audio for the waveform.') from error
    samples = np.frombuffer(decoded.stdout, dtype='<f4')
    if not samples.size or not np.isfinite(samples).all():
        raise ValueError('No readable audio for the waveform.')
    count = min(bins, len(samples))
    # Every sample belongs to a bin, including the final partial bin.
    starts = np.linspace(0, len(samples), count + 1, dtype=int)[:-1]
    peaks = np.maximum.reduceat(np.abs(samples), starts)
    peak = float(peaks.max())
    if peak > 0:
        peaks = peaks / peak
    return dict(duration=round(len(samples) / 16000, 4), peaks=np.round(peaks, 4).tolist())


def waveform_response(source):
    from flask import send_file
    from soundwaves.web.pipeline import _cached, _hash, _write_json

    signature = 'waveform-16000-960-' + _hash(Path(__file__))
    cached, _ = _cached('waveforms', Path(source), signature,
        lambda stage: _write_json(stage / 'waveform.json', waveform_data(source)),
        dict(data='waveform.json'))
    return send_file(cached['data'], mimetype='application/json')
