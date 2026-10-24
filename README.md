# Soundwaves

The PDF-to-MIDI code lives in `sheet_downloader/`. Flask, score previews, templates, JavaScript, CSS, piano samples, and web uploads live separately in `testing/web-server/`.

## Convert a PDF

Use Python 3.14 for the combined cleaner, sheet converter, and transcription dependencies:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

From Python code with this repository on its import path:

```python
from sheet_downloader import pdf_to_midi

midi_path = pdf_to_midi("/path/to/score.pdf")
```

The function takes one argument: the PDF path. It writes `/path/to/score.mid` beside that PDF and returns its absolute `pathlib.Path`. It refuses to overwrite an existing MIDI file; remove or rename that file before converting again. Recognition runs fresh on every call, automatic repairs and dynamics are applied, and temporary recognition files are removed afterward.

PDF recognition requires [Audiveris](https://github.com/Audiveris/audiveris/releases), installed separately. Set `AUDIVERIS_PATH` to its executable or add it to PATH. macOS installations in `~/Applications/Audiveris.app` and `/Applications/Audiveris.app` are detected automatically. The macOS app includes Java.

Core conversion does not import Flask or Verovio and does not start a server. There is no package installation/build configuration; copy the `sheet_downloader/` folder alongside your other Python code, or add this repository to your Python import path.

## Full conversion artifacts

For repaired MusicXML, reference notes, and a repair log:

```python
from sheet_downloader import convert_score

result = convert_score("score.pdf", "output/session-001")

midi_path = result.midi
musicxml_path = result.musicxml
original_score_path = result.original_musicxml
notes_path = result.notes
repairs_path = result.repairs
```

This function also accepts `.xml`, `.musicxml`, and `.mxl`, skipping PDF recognition. Use a fresh output directory for each call. An existing directory is allowed if it contains no `reference` or `recognition` subdirectory. Partial conversion directories are removed on failure; exceptions are raised to the caller.

Optional arguments to `convert_score` are `bpm=120`, `audiveris_path=None`, `timeout=300`, `render_audio=False`, and `measures_per_chunk=1`. WAV generation is optional; MIDI conversion does not need it. Calls within one Python process are serialized because the music libraries maintain shared state.

## Web server

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r testing/web-server/requirements.txt
.venv/bin/python testing/web-server/app.py
```

Open http://127.0.0.1:5000. Stop with Ctrl+C.

The server calls `sheet_downloader.convert_score`, then uses `testing/web-server/preview.py` to render notation and highlighting data. It shows the original PDF beside the score, plays local piano samples, and offers MIDI, repaired MusicXML, original recognition, and repair-log downloads.

Every upload reruns recognition and conversion. No previous score or output is reused; HTTP caching is disabled. Uploads are limited to 20 MB and recognition to five minutes. Generated sessions are stored in `testing/web-server/instance/uploads`; delete that directory to clear them.

## Structure

| Location | Responsibility |
| --- | --- |
| `sheet_downloader/conversion.py` | Callable conversion functions and result paths |
| `sheet_downloader/recognition.py` | Local Audiveris PDF recognition |
| `sheet_downloader/reference.py` | Parsing, repeat expansion, MIDI/WAV export, measure/note data |
| `sheet_downloader/repairs.py` | Automatic repairs and before/after records |
| `sheet_downloader/validation.py`, `sheet_downloader/tuplets.py` | Score and tuplet checks |
| `sheet_downloader/expression.py` | Dynamics and hairpin velocities |
| `testing/web-server/app.py` | Flask upload/download interface |
| `testing/web-server/preview.py` | Verovio notation rendering and highlighting timeline |
| `testing/web-server/templates/` | HTML |
| `testing/web-server/static/styles/` | CSS |
| `testing/web-server/static/scripts/` | JavaScript |
| `testing/web-server/static/audio/` | Piano samples and attribution |

## Musical behavior and limits

Voices retain independent rhythms, ties retain one attack, and clefs determine pitches. Dynamics from `pppp` to `ffff` map to MIDI velocities. Hairpins interpolate toward their endpoint dynamic, or change velocity by 20 when no endpoint dynamic exists. Encoded brace groups share dynamics. Browser playback uses sampled piano with gain changes, rather than multiple sampled velocity layers.

Automatic repairs combine equal-length simultaneous events within a voice into chords, repair fragmented unmatched tuplets when written durations exactly fit the existing onset slots, and add rests to trailing silence in internal metered measures. A restricted heuristic can infer an earlier clef change in a braced staff group when a later explicit clef and a uniquely better chord-register transition support it. Inferred pitch changes are labeled for review. Repairs contain no score fingerprints or fixed measure numbers.

The repair log retains original findings, before/after changes, and remaining warnings. Unsupported or ambiguous errors stay flagged. A bracketed `6` is a sextuplet rhythm, not a sixfold repeat. Recognized tuplet ratios are preserved; ordinary repeat barlines are expanded separately.

Audiveris has [documented recognition limitations](https://audiveris.github.io/audiveris/_pages/reference/limitations/). Structural repair cannot guarantee correct interpretation of every PDF. Missing notes, incorrect staff assignments, and ambiguous notation may still require correction in a notation editor. Grace notes, microtones, pedal realization, and expressive rubato are not implemented.

Reference JSON preserves notes, score beats, and measure boundaries for future performance comparison. A future comparator must align played notes to score beats before comparing local timing; fixed timestamp slicing would accumulate tempo drift.

## Recording transcription

Callable audio-to-note transcription for a single polyphonic piano performance. This is independent of the sheet-music converter, cleaner, and web server.

### Setup

Install the combined root dependencies with Python 3.14:

```sh
python3.14 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

The transcription backend runs the bundled Basic Pitch ONNX model directly, using NumPy and SciPy for windowing and note decoding. It does not depend on the `basic-pitch` Python package, TensorFlow, CoreML, librosa, resampy, or scikit-learn. Python 3.14 and NumPy 2 are supported. Model weights from Basic Pitch 0.4.0, plus their Apache-2.0 license and notice, are bundled in `transcribe_recording/model/`; no model download is required during transcription. The older Python 3.11 environment is no longer needed.

#### Manual runner

Edit `AUDIO_PATH` in `transcribe_recording/test.py`, or place `recording.wav` in that directory, then run:

```sh
.venv/bin/python transcribe_recording/test.py
```

This is a runnable example, not an automated test suite. It prints the absolute path of the generated MIDI. It has not been run as part of this change.

For `/music/take.wav`, the default MIDI location is:

```text
<repository>/temp_files/take_transcription_<unique-id>/performance.mid
```

The unique output directory is created inside the repository’s root `temp_files/` directory, independent of the input recording’s location. `result.midi_path` holds the full path.

### Call it

Run your calling script with the Python environment above, from the repository root or with the repository on its Python import path:

```python
from transcribe_recording import transcribe_recording

result = transcribe_recording("recording.wav")

midi_path = result.midi_path
notes_path = result.notes_path
played_notes = result.notes
```

By default, each call saves MIDI, note JSON, raw detections, and optional model output in `temp_files/<recording>_transcription_<id>/`. Temporary decoded audio is also staged under `temp_files/` and removed after processing. To choose a directory:

```python
result = transcribe_recording("cleaned.wav", "output/take-001")
```

The explicit directory must not already exist. Each call processes the recording again; output files are never reused. The source is read-only. Failed conversions clean up staged files.

Outputs:

- `performance.mid`: polyphonic piano MIDI with estimated note starts, ends, and velocities. MIDI tempo 120 is only a seconds-to-ticks encoding convention; note times are not snapped to beats.
- `notes.json`: canonical played-note events, source hash, audio duration, model/runtime versions, model hash, settings, cleanup counts, and warnings.
- `raw_notes.json`: decoded model note events before validation, boundary clipping, range filtering, and exact-duplicate removal.
- `model_output.npz`: optional frame, onset, and contour activations, enabled with `save_model_output=True`.

Each note contains `id`, `pitch` (MIDI number), `onset`, `duration`, `source="performance"`, estimated `velocity`, `model_score`, and `confidence`. Times are **seconds from the start of the supplied file**, including leading silence and internal pauses. The transcription stage does not infer score measures, quantize rhythm, or align to sheet music.

`model_score` is the model's mean note activation. It is not a calibrated likelihood of correctness, so `confidence` stays `null`. MIDI velocity is derived from that activation and must not be treated as measured piano dynamics.

### Settings

```python
from transcribe_recording import TranscriptionConfig, transcribe_recording

config = TranscriptionConfig(
    onset_threshold=0.5,
    frame_threshold=0.3,
    minimum_note_length_ms=50,
    lowest_pitch=21,
    highest_pitch=108,
    maximum_duration_seconds=600,
    save_model_output=True,
)
result = transcribe_recording("recording.wav", "output/take-002", config=config)
```

The default pitch range is the full 88-key piano. Lower thresholds can detect quieter notes but also introduce false detections. Minimum note lengths are approximate because inference uses an audio frame grid. The local decoder finds onset peaks and positive frame-activation rises, splits repeated strikes at their next onset, and releases a note after three inactive frames. Pitch bends are not generated. This decoder differs from Spotify's original Python post-processing, so detections may differ from that package.

Audio is decoded locally with FFmpeg, downmixed to mono, and resampled to the model's 22,050 Hz rate. No silence trimming, denoising, EQ, or gain normalization is applied. WAV, FLAC, MP3, M4A, OGG, and WebM inputs work when supported by the bundled FFmpeg decoder. Empty/invalid audio and recordings above the configured duration limit are rejected. Digitally silent input produces an empty transcription and a warning without running the model. A recording with no detections also produces a valid empty result, not an invented note.

### Cleaner integration

The current `audio_cleaner` pipeline is designed for speech: it trims silence, applies speech-focused filters, and can use a speech denoiser. That can erase piano bass, quiet notes, sustained tails, or change the timing origin. Start with the **original recording**, and compare transcription quality against a cleaned copy before choosing one. The transcriber does not automatically call the cleaner or reconstruct silence already removed from a cleaned file. Timestamps always refer to the file actually passed in.

### Replacing the model

Basic Pitch is an instrument-agnostic polyphonic baseline, not a specialized piano evaluator. Dense chords, repeated strikes under pedal, background instruments, and reverberation can produce wrong notes or unreliable offsets. Do not grade a player directly from these predictions without alignment and uncertainty handling.

Model loading is in `backend.py`, overlap-aware inference is in `inference.py`, and note decoding is in `decoding.py`. Frame timestamps are derived from each window’s actual sample offset to avoid accumulating timing drift across windows. For repeated calls, reuse an instance so the model loads once:

```python
from transcribe_recording import BasicPitchBackend, transcribe_recording

backend = BasicPitchBackend()
first = transcribe_recording("take-1.wav", backend=backend)
second = transcribe_recording("take-2.wav", backend=backend)
```

A replacement backend implements `transcribe(audio_path, config) -> Prediction`. It receives prepared mono 22,050 Hz WAV audio and returns `(start_seconds, end_seconds, midi_pitch, model_score)` tuples, metadata, and optional activations. Keeping this contract separate makes a piano-specific transcription model a later swap rather than a rewrite of file handling or comparison inputs. Backend calls on a reused Basic Pitch instance are serialized.

### Files

| File | Responsibility |
| --- | --- |
| `transcription.py` | Public callable and staged output orchestration |
| `audio.py` | Audio decoding and duration validation |
| `backend.py` | ONNX model loading and metadata |
| `inference.py` | Overlapped inference and sample-based frame timestamps |
| `decoding.py` | Polyphonic note onset/offset decoding |
| `events.py` | Canonical events and conservative cleanup |
| `export.py` | MIDI and JSON export |
| `models.py` | Configuration, result types, backend contract |

References: [Basic Pitch](https://github.com/spotify/basic-pitch), [upstream dependency configuration](https://github.com/spotify/basic-pitch/blob/main/pyproject.toml), [inference API](https://github.com/spotify/basic-pitch/blob/main/basic_pitch/inference.py).
