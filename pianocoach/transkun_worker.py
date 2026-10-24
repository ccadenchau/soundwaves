"""Persistent Transkun transcription worker. Run it with the .venv-transkun interpreter (Python 3.12).

    .venv-transkun/bin/python pianocoach/transkun_worker.py [cpu|mps]

Prints one JSON line when the model is loaded, then answers one JSON line per request read
from stdin: {"audio": "<wav path>", "out": "<json path>"} -> {"ok": true, "notes": N, "seconds": T}.
The output file holds [[start, end, pitch, velocity], ...] in seconds and MIDI numbers.
"""

import json
import sys
import time
from importlib.resources import files


def load_model(device):
    import moduleconf
    import torch

    pretrained = files('transkun') / 'pretrained'
    manager = moduleconf.parseFromFile(str(pretrained / '2.0.conf'))
    TransKun = manager['Model'].module.TransKun
    model = TransKun(conf=manager['Model'].config).to(device)
    checkpoint = torch.load(str(pretrained / '2.0.pt'), map_location=device)
    state = checkpoint['best_state_dict'] if 'best_state_dict' in checkpoint else checkpoint['state_dict']
    model.load_state_dict(state, strict=False)
    model.eval()
    return model


def read_audio(path):
    """Float32 (frames, channels) and sample rate. soundfile reads every WAV flavour the
    pipeline writes; pydub (Transkun's own reader) needs ffprobe for some of them."""
    try:
        import soundfile as sf
        audio, fs = sf.read(path, dtype='float32', always_2d=True)
        return fs, audio
    except Exception:  # noqa: BLE001 - fall back to Transkun's reader for non-WAV input
        from transkun.transcribe import readAudio
        return readAudio(path)


def transcribe(model, device, audio_path):
    import torch

    fs, audio = read_audio(audio_path)
    if fs != model.fs:
        import soxr
        audio = soxr.resample(audio, fs, model.fs)
    x = torch.from_numpy(audio).to(device)
    with torch.no_grad():
        notes = model.transcribe(x, stepInSecond=None, segmentSizeInSecond=None, discardSecondHalf=False)
    records = []
    for n in notes:
        start, end = float(n.start), float(n.end)
        if end <= start:
            continue
        records.append([start, end, int(n.pitch), int(getattr(n, 'velocity', 80) or 80)])
    return records


def main(argv):
    import torch
    device = argv[1] if len(argv) > 1 else ('mps' if torch.backends.mps.is_available() else 'cpu')
    started = time.time()
    model = load_model(device)
    print(json.dumps(dict(ready=True, device=device, load_seconds=round(time.time() - started, 1), fs=int(model.fs))), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        request = json.loads(line)
        if request.get('quit'):
            break
        started = time.time()
        try:
            records = transcribe(model, device, request['audio'])
            with open(request['out'], 'w', encoding='utf-8') as handle:
                json.dump(records, handle)
            print(json.dumps(dict(ok=True, notes=len(records), seconds=round(time.time() - started, 2))), flush=True)
        except Exception as error:  # noqa: BLE001 - report to the parent and keep serving
            print(json.dumps(dict(ok=False, error=f'{type(error).__name__}: {error}'[:400])), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
