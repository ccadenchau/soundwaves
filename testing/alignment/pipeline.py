"""Shared content-addressed conversion cache for the CLI and local web UI."""

import hashlib
import json
import math
import os
from dataclasses import asdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
CACHE = Path(__file__).with_name('cache')
MAX_SHEET_BYTES = 20 * 1024 * 1024
MAX_RECORDING_BYTES = 80 * 1024 * 1024
SHEET_SUFFIXES = {'.pdf', '.musicxml', '.xml', '.mxl'}
RECORDING_SUFFIXES = {'.mp3', '.wav', '.m4a', '.webm', '.ogg', '.flac'}
_lock = RLock()


def _hash(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _write_json(path, data):
    path.write_text(json.dumps(data, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def _signature(package, settings):
    digest = hashlib.sha256(json.dumps(settings, sort_keys=True).encode())
    paths = sorted((ROOT / package).rglob('*.py'))
    if package == 'transcribe_recording':
        paths.append(ROOT / package / 'model' / 'basic_pitch.onnx')
    for path in paths:
        digest.update(str(path.relative_to(ROOT)).encode())
        digest.update(_hash(path).encode())
    for name in ('music21', 'numpy', 'scipy', 'pretty_midi', 'onnxruntime', 'imageio-ffmpeg', 'soundfile', 'noisereduce'):
        try:
            digest.update(f'{name}={version(name)}'.encode())
        except PackageNotFoundError:
            digest.update(f'{name}=missing'.encode())
    return digest.hexdigest()


def _stage_stream(stream, suffix, limit):
    """Persist input bytes by hash; filenames never control the stored path."""
    inputs = CACHE / 'inputs'
    inputs.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.input-', dir=inputs) as temporary:
        staged = Path(temporary) / ('input' + suffix)
        size, digest = 0, hashlib.sha256()
        with staged.open('wb') as handle:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                size += len(block)
                if size > limit:
                    raise ValueError(f'Input exceeds the {limit // (1024 * 1024)} MB limit.')
                handle.write(block)
                digest.update(block)
        if not size:
            raise ValueError('The supplied file is empty.')
        target = inputs / (digest.hexdigest() + suffix)
        with _lock:
            if target.exists():
                if not target.is_file() or _hash(target) != digest.hexdigest():
                    raise ValueError(f'Cached input is damaged. Remove it and retry: {target}')
            else:
                try:
                    staged.rename(target)
                except OSError:
                    if not target.is_file() or _hash(target) != digest.hexdigest():
                        raise
        return target


def store_upload(upload, *, recording=False):
    suffix = Path(upload.filename or '').suffix.lower()
    if suffix not in (RECORDING_SUFFIXES if recording else SHEET_SUFFIXES):
        raise ValueError('Choose an MP3, WAV, M4A, WebM, OGG or FLAC recording.' if recording else 'Choose PDF, MusicXML, XML, or MXL sheet music.')
    return _stage_stream(upload.stream, suffix, MAX_RECORDING_BYTES if recording else MAX_SHEET_BYTES)


def _sheet_source(source):
    text = str(source)
    if text.lower().startswith(('http://', 'https://')):
        suffix = Path(unquote(urlsplit(text).path)).suffix.lower()
        with urlopen(Request(text, headers={'User-Agent': 'Soundwaves-local-alignment/1.0'}), timeout=45) as response:
            if urlsplit(response.geturl()).scheme not in ('http', 'https'):
                raise ValueError('Sheet downloads must use HTTP or HTTPS.')
            if suffix not in SHEET_SUFFIXES:
                suffix = Path(unquote(urlsplit(response.geturl()).path)).suffix.lower()
            if suffix not in SHEET_SUFFIXES:
                suffix = {'application/pdf': '.pdf', 'application/vnd.recordare.musicxml': '.mxl',
                          'application/vnd.recordare.musicxml+xml': '.musicxml'}.get(response.headers.get_content_type())
            if suffix not in SHEET_SUFFIXES:
                raise ValueError('Use a direct PDF/MusicXML download URL, not a webpage.')
            return _stage_stream(response, suffix, MAX_SHEET_BYTES)
    path = Path(source).expanduser().resolve()
    if path.suffix.lower() not in SHEET_SUFFIXES:
        raise ValueError('Sheet must be PDF, MusicXML, XML, or MXL.')
    with path.open('rb') as handle:
        return _stage_stream(handle, path.suffix.lower(), MAX_SHEET_BYTES)


def _cached(kind, source, signature, build, artifacts):
    key = hashlib.sha256((_hash(source) + source.suffix + signature).encode()).hexdigest()
    parent = CACHE / kind
    parent.mkdir(parents=True, exist_ok=True)
    destination = parent / key

    def complete():
        try:
            manifest = json.loads((destination / 'manifest.json').read_text(encoding='utf-8'))
            return manifest['signature'] == signature and all(
                (destination / relative).is_file() and
                _hash(destination / relative) == manifest['hashes'][relative]
                for relative in artifacts.values())
        except (OSError, ValueError, KeyError, TypeError):
            return False

    with _lock:
        if destination.exists():
            if not complete():
                raise ValueError(f'Cache entry is damaged. Remove this entry and retry: {destination}')
            return {name: destination / relative for name, relative in artifacts.items()}, True
        # Publish only complete output directories. Failed builds are discarded.
        with TemporaryDirectory(prefix='.build-', dir=parent) as temporary:
            stage = Path(temporary) / 'entry'
            stage.mkdir()
            build(stage)
            hashes = {relative: _hash(stage / relative) for relative in artifacts.values()}
            _write_json(stage / 'manifest.json', dict(signature=signature, source_sha256=_hash(source), hashes=hashes))
            try:
                stage.rename(destination)
            except OSError:
                if not complete():
                    raise
        return {name: destination / relative for name, relative in artifacts.items()}, False


def compare_files(sheet, recording, *, bpm=120):
    """Reuse conversions, rerun alignment, and save a uniquely identified report."""
    if not math.isfinite(bpm) or not 20 <= bpm <= 400:
        raise ValueError('Fallback BPM must be between 20 and 400.')
    sheet_path = _sheet_source(sheet)
    recording = Path(recording).expanduser().resolve()
    if recording.suffix.lower() not in RECORDING_SUFFIXES:
        raise ValueError('Choose an MP3, WAV, M4A, WebM, OGG or FLAC recording.')
    with recording.open('rb') as handle:
        audio_path = _stage_stream(handle, recording.suffix.lower(), MAX_RECORDING_BYTES)

    from sheet_downloader import convert_score
    from transcribe_recording import transcribe_recording
    from transcribe_recording.models import TranscriptionConfig
    from pianocoach.clean import clean_notes
    from pianocoach.pipeline import align_windowed, prepare_for_transcription, transcriber
    from testing.alignment.playback import render_midi

    sheet_signature = _signature('sheet_downloader', dict(bpm=bpm, measures_per_chunk=1,
                                                        audiveris_path=os.environ.get('AUDIVERIS_PATH')))
    score, sheet_hit = _cached('sheets', sheet_path, sheet_signature,
        lambda stage: convert_score(sheet_path, stage / 'converted', bpm=bpm, measures_per_chunk=1),
        dict(midi='converted/reference/reference.mid', notes='converted/reference/reference.json',
             musicxml='converted/reference/reference.musicxml', repairs='converted/reference/repairs.json'))
    # Transkun when its environment exists (best accuracy), else the bundled Basic Pitch.
    backend = transcriber()
    transcriber_name = backend.name if backend is not None else 'basic-pitch'
    clean_mode = os.environ.get('PIANOCOACH_CLEAN', 'auto').lower()
    audio_cleaning = 'none' if clean_mode == 'off' or (clean_mode == 'auto' and backend is not None) else 'piano'
    cleaner_version = _hash(ROOT / 'audio_cleaner' / 'clean_audio.py') if audio_cleaning == 'piano' else None
    recording_signature = _signature('transcribe_recording', dict(
        config=asdict(TranscriptionConfig()), audio_cleaning=audio_cleaning, cleaner=cleaner_version,
        input_audio='original', transcriber=transcriber_name))

    def transcribe(stage):
        source, _ = prepare_for_transcription(audio_path, stage, backend) if audio_cleaning == 'piano' else (audio_path, 'none')
        return transcribe_recording(source, stage / 'converted', backend=backend)

    take, recording_hit = _cached('recordings', audio_path, recording_signature, transcribe,
        dict(midi='converted/performance.mid', notes='converted/notes.json'))
    # Clean the detections, merge unison score notes, and pin a short take to the bars it covers.
    heard = json.loads(Path(take['notes']).read_text(encoding='utf-8'))['notes']
    kept, cleaning = clean_notes(heard, harmonics=backend is None)
    report, _ = align_windowed(score['notes'], kept)
    report['preprocessing'] = dict(report.get('preprocessing', {}), audio_cleaning=audio_cleaning,
                                   timestamp_origin='original_audio', transcriber=transcriber_name, **cleaning)

    playback_signature = _signature('sheet_downloader', dict(
        renderer_sha256=_hash(Path(__file__).with_name('playback.py')), sample_rate=16000))
    previews = {}
    for name, midi in (('sheet_midi_audio', score['midi']), ('recording_midi_audio', take['midi'])):
        preview, _ = _cached('playback', midi, playback_signature,
                             lambda stage, midi=midi: render_midi(midi, stage / 'preview.wav'),
                             dict(audio='preview.wav'))
        previews[name] = preview['audio']
    report_id = uuid4().hex
    directory = CACHE / 'reports' / report_id
    directory.mkdir(parents=True)
    report_path = directory / 'report.json'
    _write_json(report_path, report)
    artifacts = dict(report=report_path, sheet_midi=score['midi'], recording_midi=take['midi'],
                     sheet_notes=score['notes'], recording_notes=take['notes'],
                     musicxml=score['musicxml'], repairs=score['repairs'],
                     audio=audio_path, original_audio=audio_path, sheet=sheet_path,
                     **previews)
    _write_json(directory / 'artifacts.json', {k: str(v.relative_to(CACHE)) for k, v in artifacts.items()})
    return dict(report=report, report_id=report_id, report_path=report_path,
                cache=dict(sheet_hit=sheet_hit, recording_hit=recording_hit))
