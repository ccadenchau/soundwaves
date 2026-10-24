import hashlib
from pathlib import Path
from threading import Lock

from .decoding import decode_notes
from .inference import infer_frames
from .models import Prediction, TranscriptionConfig


class BasicPitchBackend:
    def __init__(self) -> None:
        self._model = None
        self._model_path = Path(__file__).with_name('model') / 'basic_pitch.onnx'
        self._lock = Lock()

    def transcribe(self, audio_path: Path, config: TranscriptionConfig) -> Prediction:
        try:
            import onnxruntime
        except ImportError as error:
            raise RuntimeError('Install the root requirements.txt with your Python interpreter.') from error
        onnxruntime.disable_telemetry_events()
        with self._lock:
            if self._model is None:
                if not self._model_path.is_file():
                    raise RuntimeError('The bundled Basic Pitch ONNX model is missing.')
                self._model = onnxruntime.InferenceSession(
                    str(self._model_path), providers=['CPUExecutionProvider'],
                )
            features = infer_frames(self._model, audio_path, config.save_model_output)
            import soundfile as sf

            duration = sf.info(audio_path).duration
            events = decode_notes(features, duration, config)
            model_hash = hashlib.sha256(self._model_path.read_bytes()).hexdigest()
        return Prediction(
            notes=events,
            metadata={
                'name': 'basic-pitch',
                'weights_version': '0.4.0',
                'decoder': 'soundwaves-onset-frame-v1',
                'runtime': 'onnx',
                'runtime_version': onnxruntime.__version__,
                'model_sha256': model_hash,
                'score_meaning': 'Mean note activation, not calibrated correctness probability.',
                'velocity_meaning': 'Model activation scaled to MIDI velocity, not measured piano dynamics.',
            },
            model_output=features if config.save_model_output else None,
        )
