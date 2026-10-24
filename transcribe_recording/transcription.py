import hashlib
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from .audio import prepare_audio
from .backend import BasicPitchBackend
from .events import normalize_notes
from .export import note_records, write_json, write_midi, write_raw_notes
from .models import Prediction, TranscriptionBackend, TranscriptionConfig, TranscriptionResult


def transcribe_recording(
    audio_path: str | Path,
    output_directory: str | Path | None = None,
    *,
    config: TranscriptionConfig | None = None,
    backend: TranscriptionBackend | None = None,
) -> TranscriptionResult:
    """Transcribe polyphonic recording audio into MIDI and timed note events."""
    source = Path(audio_path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    config = config or TranscriptionConfig()
    config.validate()
    destination = (
        Path(output_directory).expanduser().resolve() if output_directory is not None
        else Path(__file__).resolve().parent.parent / 'temp_files'
        / f'{source.stem}_transcription_{uuid4().hex[:8]}'
    )
    if destination.exists():
        raise FileExistsError('Choose a new transcription output directory.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = hashlib.sha256()
    with source.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            fingerprint.update(block)
    with TemporaryDirectory(prefix='.transcription-', dir=destination.parent) as temporary:
        workspace = Path(temporary)
        prepared = workspace / 'audio.wav'
        audio = prepare_audio(source, prepared, config.maximum_duration_seconds)
        prediction = (
            Prediction(notes=[], metadata={'name': 'none', 'reason': 'Digital silence; inference skipped.'})
            if audio['silent'] else (backend or BasicPitchBackend()).transcribe(prepared, config)
        )
        notes, cleanup = normalize_notes(prediction.notes, audio['duration_seconds'], config)
        warnings = []
        if audio['silent']:
            warnings.append('The recording is digitally silent.')
        if audio['peak_amplitude'] > 1:
            warnings.append('The decoded recording exceeds full scale; clipping may affect transcription.')
        if not notes:
            warnings.append('No notes were detected. Check the recording and detection thresholds.')
        if cleanup['discarded_events']:
            warnings.append('Invalid, duplicate, or out-of-range model events were discarded; inspect raw_notes.json.')
        output = workspace / 'result'
        output.mkdir()
        write_midi(output / 'performance.mid', notes)
        write_raw_notes(output / 'raw_notes.json', prediction.notes)
        write_json(output / 'notes.json', {
            'schema_version': 1,
            'source': str(source), 'source_type': 'audio',
            'source_sha256': fingerprint.hexdigest(), 'time_unit': 'seconds',
            'duration_seconds': audio['duration_seconds'],
            'notes': note_records(notes), 'model': prediction.metadata,
            'config': asdict(config), 'audio': audio, 'cleanup': cleanup,
            'warnings': warnings,
            'confidence_meaning': 'Confidence is null: model_score is not a calibrated error probability.',
        })
        model_output_path = None
        if config.save_model_output and prediction.model_output is not None:
            import numpy as np

            np.savez_compressed(output / 'model_output.npz', **prediction.model_output)
            model_output_path = destination / 'model_output.npz'
        if destination.exists():
            raise FileExistsError(destination)
        output.rename(destination)
    return TranscriptionResult(
        directory=destination, midi_path=destination / 'performance.mid',
        notes_path=destination / 'notes.json', raw_notes_path=destination / 'raw_notes.json',
        model_output_path=model_output_path, notes=notes,
        duration_seconds=audio['duration_seconds'], warnings=tuple(warnings),
    )
