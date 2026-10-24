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

## Bar-by-bar performance alignment

`alignment/` compares reference score notes against transcribed notes or a performed
MIDI. Pitch matching follows musical sequence rather than fixed timestamps. Each
bar then gets its own robust tempo and start-offset estimate. A fast bar can have
perfect pitch accuracy and `tempo_status="too_fast"`; the following bar is fitted
independently, so it is not marked late or early just because the prior bar changed
the recording timeline. Leading silence does not shift the pitch comparison.

The module uses NumPy, SciPy, and (for MIDI inputs) pretty_midi from the root
`requirements.txt`. There is no separate requirements file or installation step.
It does not call the cleaner, recognition engine, or transcription model.

### Call it

Keep the converter's `reference.json`: MIDI alone does not preserve the reference
measure boundaries needed by this API. Generate one chunk per bar (the default):

```python
from alignment import align_performance
from sheet_downloader import convert_score
from transcribe_recording import transcribe_recording

score = convert_score("score.pdf", "output/score-001", measures_per_chunk=1)
take = transcribe_recording("recording.wav", "output/take-001")

report = align_performance(
    score.notes,             # Path to reference.json
    take,                    # Or take.notes, take.notes_path, or a MIDI path
    "output/analysis-001.json",
)

for bar in report["measures"]:
    print(bar["number"], bar["pitch_recall"], bar["tempo_status"], bar["feedback"])
```

`reference` accepts a converter reference JSON path or its parsed dictionary.
`performance` accepts a transcription result, performance JSON path/dictionary,
an iterable of played-note dictionaries/dataclasses, or a `.mid`/`.midi` path.
Score onsets/durations are quarter-note beats; performance times are seconds.
Pass the full performance of the supplied reference passage. For an excerpt,
convert the corresponding score excerpt first. Multi-bar chunks are rejected;
reconvert with `measures_per_chunk=1`.

The optional output path is created with its parents and refuses to overwrite an
existing report. Omitting it returns the report without writing files.

### Matching and feedback

- Nearby performance onsets are grouped into chords (default 50 ms). A monotone
  sequence alignment compares pitch multisets, allowing inserted/deleted onset
  groups. Within paired chords, one-to-one assignment identifies correct, wrong,
  missing, and extra pitches. No played note can satisfy two score notes.
- Pitch-overlapping onset groups provide beat-to-second anchors. Each bar uses
  its own robust slope/intercept fit, optionally including an anchor exactly at
  its ending boundary. Timing residuals are measured against that local fit.
- `tempo_ratio` compares the fitted bar speed with the score's average tempo for
  that bar, including encoded tempo changes. A ratio of `1.5` means 50% faster.
  The default tempo tolerance is 12%; pitch accuracy remains a separate metric.
- Bars without enough separated anchors, or with poor pitch agreement, have
  `tempo_status="unassessed"`. Irregular fits are labeled `irregular`. An entirely
  empty performance returns an uncertain report with candidate missing notes.
- Reports include global pitch precision/recall/F1, per-bar counts and feedback,
  note matches, candidate pitch/timing errors, recording timestamps, alignment
  anchors, settings, and warnings. `measure_occurrence` is a zero-based playback
  index, so repeated printed measure numbers can be distinguished. Extras outside
  the anchor span remain unassigned to a bar and are still included in the report.

Customize tolerances if needed:

```python
from alignment import AlignmentConfig, align_performance

report = align_performance(
    "output/score-001/reference/reference.json",
    "output/take-001/notes.json",
    config=AlignmentConfig(tempo_tolerance=0.15, chord_window_seconds=0.04),
)
```

The alignment costs and evidence checks are heuristics, not calibrated confidence
scores. Audio discrepancies are possible transcription or playing errors.
Repeated identical passages, rolled chords spanning the grouping window, long
pauses within a bar, skipped/replayed bars, and missing attacks can make the path
ambiguous. The matcher assumes forward playback and does not follow jumps or
automatically locate a partial take. Inspect the reported matches and warnings;
a good pitch score alone does not prove the location is correct. Timing compares
against the bar's fitted pace and does not grade fine expressive rubato, duration,
pedal, or dynamics. The default sequence-matrix limit targets short excerpts and
rejects oversized inputs rather than allocating without a bound.

### Simple manual runner

From the repository root, using the environment with root dependencies installed:

```sh
python alignment/test.py
```

With no file arguments, this starts the upload server. Open
http://127.0.0.1:5001 and choose your sheet music and MP3 in the browser, then
click **Compare performance**. Use `--port 5002` to choose another port. Press
Ctrl+C in the terminal to stop the server.

For optional command-line comparison instead:

```sh
python alignment/test.py path/to/score.pdf path/to/recording.mp3
python alignment/test.py "https://example.com/score.pdf" path/to/recording.mp3
python alignment/test.py path/to/score.musicxml path/to/recording.mp3 --bpm 100 --output output/report-001.json
```

The runner downloads a direct sheet URL (or reads a local sheet), converts the
sheet and MP3, and prints per-bar pitch matches and tempo feedback. URLs must
return PDF/MusicXML content rather than a score-library webpage; downloading
requires internet access. PDF conversion requires the existing local Audiveris
installation (`AUDIVERIS_PATH`); MusicXML bypasses recognition. The fallback BPM
only applies where the score does not supply tempo. Recordings are limited to ten
minutes and should cover the same passage as the reference. This remains a manual
runner, not an automated test suite.

### Simple alignment web server

Install the root requirements, then start the server:

```sh
python -m pip install -r requirements.txt
python testing/alignment/app.py
```

Open http://127.0.0.1:5001. Upload sheet music (PDF/MusicXML/XML/MXL) or supply a
direct sheet download URL, then upload an MP3. The page shows pitch recall and
precision, per-bar pitch counts, tempo compared with the score, candidate note
discrepancies, and assessment warnings. Listen buttons seek to the estimated bar
or note in the recording. Both MIDIs, recognized MusicXML, the score repair log,
and the JSON report can be downloaded. Pitch accuracy is separate from tempo:
a fast bar can still have every expected pitch matched.

Uploaded recordings are transcribed directly from the original MP3 without audio
cleaning, denoising, mastering, or silence trimming. Transcription only decodes,
downmixes to mono, and resamples the audio. Bar/note seek buttons and recording
timestamps refer to the original recording. Reports record that cleaning is disabled.

The results page includes the original MP3 and cached harmonic WAV previews of
the sheet and recording MIDI note times and velocities. Preview length is limited
to 30 minutes. Only one player plays at a time.

The results page renders the recognized sheet music with a performance overlay:
green matched notes, orange missing notes, red expected notes for pitch mismatches,
and purple detected pitches. Play the original recording to follow sounding notes,
or click a colored played note to seek. Extra notes are placed beside the nearest
matched note in their bar; notes without a reliable location are listed separately.
The score uses expanded repeats and any conversion repairs. These are estimated
transcription/alignment results, not a definitive assessment of playing errors.

Notation is rendered locally with Verovio and cached separately; opening an existing
report can generate its overlay without redoing transcription. Install the root
`requirements.txt` to include the renderer. HTML and CSS are in
`testing/alignment/app.py`; overlay controls are in
`testing/alignment/static/notation.js`. This is a synchronous local development
server. The first conversion can take several minutes. Limits are 20 MB per sheet
and 80 MB per MP3, with a ten-minute decoded audio limit. It binds to loopback on
port 5001, leaving the existing score-preview server on port 5000 available.

### Shared conversion cache

The CLI and server share `testing/alignment/pipeline.py` and write under:

```text
testing/alignment/cache/
  inputs/<sha256>.<extension>          # Downloaded/uploaded sheet and MP3 bytes
  sheets/<cache-key>/converted/reference/
    reference.mid                    # Cached sheet MIDI
    reference.json                   # Score beats and bar boundaries
    reference.musicxml
    repairs.json
  recordings/<cache-key>/converted/
    performance.mid                  # Cached recording MIDI
    notes.json                       # Performance times in seconds
    raw_notes.json
  notation/<cache-key>/notation.json  # Rendered score and performance overlays
  playback/<cache-key>/preview.wav    # Browser-playable MIDI audio previews
  reports/<unique-id>/report.json
```

Old cleaned audio and its transcription cache entries are bypassed. New recording
cache keys explicitly identify the original, uncleaned MP3 input.

Conversions are reused by file contents, input type, settings, converter source,
model weights, and installed dependency versions. A changed recording does not
invalidate an unchanged sheet conversion. Renaming the same file does not trigger
conversion again. URLs are fetched on each request, then their downloaded bytes
determine cache reuse. Alignment runs again on every comparison so edits to the
alignment engine take effect without retranscribing.

Completed conversions are published atomically and required artifacts are
hash-checked before reuse. Interrupted builds are discarded; a damaged published
entry raises an error naming the directory to remove. Changing the external
Audiveris executable without changing `AUDIVERIS_PATH` is not automatically
detected: clear the corresponding sheet cache when upgrading Audiveris. Cached
artifacts are gitignored. Delete cached entries to regenerate them, or the cache
contents to clear stored recordings, scores, and reports (stop the server first).
The original converter/transcriber APIs still run fresh when called directly;
caching belongs to this testing harness. Cleaning is cached separately using the
original recording, cleaner code, and settings. Transcription uses the cleaned
WAV and its own cache key, so old uncleaned transcriptions are not reused for the
new pipeline. MIDI previews are also cached independently.

These runners and conversions have not been executed as part of this change.
