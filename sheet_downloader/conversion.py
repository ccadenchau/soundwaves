import shutil
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import RLock

from .recognition import convert_pdf
from .reference import build_reference

_conversion_lock = RLock()


@dataclass(frozen=True)
class ConversionResult:
    directory: Path
    midi: Path
    musicxml: Path
    original_musicxml: Path
    notes: Path
    repairs: Path


def convert_score(
    source: str | Path,
    output_directory: str | Path,
    *,
    render_audio: bool = False,
    bpm: float = 120.0,
    measures_per_chunk: int = 1,
    audiveris_path: str | Path | None = None,
    timeout: float = 300,
) -> ConversionResult:
    """Convert PDF/MusicXML into repaired MIDI and reference artifacts, without caching.

    output_directory/reference and output_directory/recognition must not exist.
    Audiveris is required only for PDFs.
    """
    source = Path(source).expanduser().resolve()
    output_directory = Path(output_directory).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if source.suffix.lower() not in {'.pdf', '.xml', '.musicxml', '.mxl'}:
        raise ValueError('Choose a PDF or MusicXML file.')
    if timeout <= 0:
        raise ValueError('Recognition timeout must be positive.')
    if source.suffix.lower() == '.pdf':
        with source.open('rb') as handle:
            if not handle.read(1024).lstrip().startswith(b'%PDF-'):
                raise ValueError('This file is not a PDF.')
    recognition = output_directory / 'recognition'
    reference = output_directory / 'reference'
    with _conversion_lock:
        if recognition.exists() or reference.exists():
            raise FileExistsError('Use a fresh output directory for each conversion.')
        output_directory.mkdir(parents=True, exist_ok=True)
        try:
            score = (
                convert_pdf(source, recognition, executable=audiveris_path, timeout=timeout)
                if source.suffix.lower() == '.pdf'
                else source
            )
            build_reference(
                score, reference, bpm=bpm,
                measures_per_chunk=measures_per_chunk, render_audio=render_audio,
            )
        except Exception:
            shutil.rmtree(recognition, ignore_errors=True)
            shutil.rmtree(reference, ignore_errors=True)
            raise
    return ConversionResult(
        directory=output_directory,
        midi=reference / 'reference.mid',
        musicxml=reference / 'reference.musicxml',
        original_musicxml=reference / 'original.musicxml',
        notes=reference / 'reference.json',
        repairs=reference / 'repairs.json',
    )


def pdf_to_midi(pdf_path: str | Path) -> Path:
    """Convert a PDF to a sibling .mid file and return its absolute path.

    Applies automatic repairs and dynamics. Existing MIDI files are not
    overwritten. Intermediate recognition files are deleted after conversion.
    """
    source = Path(pdf_path).expanduser().resolve()
    if source.suffix.lower() != '.pdf':
        raise ValueError('pdf_to_midi expects a PDF. Use convert_score for MusicXML.')
    destination = source.with_suffix('.mid')
    if destination.exists():
        raise FileExistsError(destination)
    with TemporaryDirectory(prefix='soundwaves-') as temporary:
        result = convert_score(source, temporary)
        with result.midi.open('rb') as source_file, destination.open('xb') as output_file:
            shutil.copyfileobj(source_file, output_file)
    return destination
