"""Render note events to a WAV with the sampled acoustic grand piano bundled in frontend/static/audio.

    python testing/render_piano.py events.json out.wav [--noise 0.0015]

events.json: [{"start_seconds": .., "end_seconds": .., "pitch": 60, "velocity": 85}, ...]
The samples are FluidR3_GM (CC BY 3.0) MP3s decoded through imageio-ffmpeg. A faint noise
floor stands in for a laptop microphone. The result is realistic enough for the transcribers;
the harmonic synthesizer in sheet_downloader is not (Transkun ignores it).
"""

import argparse
import base64
import json
import subprocess
import sys
import tempfile
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / 'frontend' / 'static' / 'audio' / 'piano.json'
NAMES = ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B']
SAMPLE_RATE = 16000


@lru_cache(maxsize=1)
def _bank():
    return json.loads(SAMPLES.read_text(encoding='utf-8'))


@lru_cache(maxsize=128)
def _sample(pitch, sample_rate=SAMPLE_RATE):
    import imageio_ffmpeg
    name = f'{NAMES[pitch % 12]}{pitch // 12 - 1}'
    data = base64.b64decode(_bank()[name].split(',', 1)[1])
    with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        pcm = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-v', 'error', '-i', path, '-f', 's16le',
                              '-ac', '1', '-ar', str(sample_rate), '-'], capture_output=True, check=True).stdout
    finally:
        Path(path).unlink(missing_ok=True)
    return np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0


def render(events, destination, *, noise=0.0015, sample_rate=SAMPLE_RATE, tail=1.5, seed=1):
    duration = max(e['end_seconds'] for e in events) + tail
    mix = np.zeros(int(duration * sample_rate), dtype=np.float32)
    for e in events:
        sample = _sample(int(e['pitch']), sample_rate)
        start = int(e['start_seconds'] * sample_rate)
        length = min(len(sample), int((e['end_seconds'] - e['start_seconds'] + 0.3) * sample_rate), len(mix) - start)
        if length <= 0:
            continue
        segment = sample[:length].copy()
        release = min(length, int(0.25 * sample_rate))
        segment[-release:] *= np.linspace(1, 0, release, dtype=np.float32)
        segment *= (float(e.get('velocity', 85)) / 127.0) ** 1.4
        mix[start:start + length] += segment
    if noise:
        mix += np.random.default_rng(seed).normal(0, noise, len(mix)).astype(np.float32)
    mix *= 0.85 / max(1e-6, float(np.abs(mix).max()))
    with wave.open(str(destination), 'wb') as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes((mix * 32767).astype(np.int16).tobytes())
    return duration


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('events', type=Path)
    parser.add_argument('out', type=Path)
    parser.add_argument('--noise', type=float, default=0.0015)
    args = parser.parse_args(argv[1:])
    events = json.loads(args.events.read_text(encoding='utf-8'))
    duration = render(events, args.out, noise=args.noise)
    print(f'{args.out} {duration:.1f}s {len(events)} notes')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
