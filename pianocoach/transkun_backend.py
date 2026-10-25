"""Transkun v2 (Yan & Duan, ISMIR 2024) as a drop-in backend for `transcribe_recording`.

Transkun needs PyTorch on Python 3.12, so it lives in its own environment
(`.venv-transkun`) and runs as a long-lived worker process that loads the model
once. This class speaks to that worker. If the environment is missing the
pipeline falls back to the bundled Basic Pitch model.
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path
from threading import Lock

from transcribe_recording.models import Prediction

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / '.venv-transkun' / 'bin' / 'python'
WORKER = Path(__file__).with_name('transkun_worker.py')


class TranskunBackend:
    name = 'transkun'

    def __init__(self, python=PYTHON, device=None):
        self.python = Path(python)
        self.device = device
        self.info = None
        self._process = None
        self._lock = Lock()

    @staticmethod
    def available(python=PYTHON):
        return Path(python).is_file() and WORKER.is_file()

    def start(self, timeout=240):
        """Launch the worker and wait for the model to load (first call only)."""
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                return self.info
            command = [str(self.python), str(WORKER)] + ([self.device] if self.device else [])
            self._process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                             stderr=subprocess.DEVNULL, text=True, bufsize=1, cwd=str(ROOT))
            deadline = time.time() + timeout
            line = self._process.stdout.readline()
            while line and not line.startswith('{'):
                if time.time() > deadline:
                    break
                line = self._process.stdout.readline()
            if not line.startswith('{'):
                self.close()
                raise RuntimeError('Transkun worker did not start.')
            self.info = json.loads(line)
            return self.info

    def transcribe(self, audio_path, config):
        self.start()
        with self._lock:
            if self._process.poll() is not None:
                self._process = None
                raise RuntimeError('Transkun worker exited.')
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as handle:
                out = Path(handle.name)
            try:
                self._process.stdin.write(json.dumps(dict(audio=str(Path(audio_path).resolve()), out=str(out))) + '\n')
                self._process.stdin.flush()
                reply = json.loads(self._process.stdout.readline() or '{}')
                if not reply.get('ok'):
                    raise RuntimeError(reply.get('error', 'Transkun worker gave no answer.'))
                records = json.loads(out.read_text(encoding='utf-8'))
            finally:
                out.unlink(missing_ok=True)
        # The team's normaliser derives MIDI velocity from the score, so pass velocity/127.
        events = [(start, end, pitch, min(1.0, max(0.05, velocity / 127.0))) for start, end, pitch, velocity in records]
        return Prediction(notes=events, metadata={
            'name': 'transkun', 'weights_version': '2.0', 'runtime': f"torch/{self.info.get('device')}",
            'worker_seconds': reply.get('seconds'),
            'score_meaning': 'MIDI velocity divided by 127; Transkun reports no per-note confidence.',
            'velocity_meaning': 'Estimated MIDI velocity from the model.',
        })

    def close(self):
        if self._process is not None:
            try:
                self._process.stdin.write(json.dumps(dict(quit=True)) + '\n')
                self._process.stdin.flush()
            except Exception:  # noqa: BLE001
                pass
            try:
                self._process.wait(timeout=5)
            except Exception:  # noqa: BLE001
                self._process.kill()
            self._process = None
