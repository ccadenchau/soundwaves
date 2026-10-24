# Soundwaves

The PDF-to-MIDI code lives in `soundwaves/`. Flask, score previews, templates, JavaScript, CSS, piano samples, and web uploads live separately in `web-server/`.

## Convert a PDF

Install the core dependencies:

```sh
python3 -m pip install -r requirements.txt
```

From Python code with this repository on its import path:

```python
from soundwaves import pdf_to_midi

midi_path = pdf_to_midi("/path/to/score.pdf")
```

The function takes one argument: the PDF path. It writes `/path/to/score.mid` beside that PDF and returns its absolute `pathlib.Path`. It refuses to overwrite an existing MIDI file; remove or rename that file before converting again. Recognition runs fresh on every call, automatic repairs and dynamics are applied, and temporary recognition files are removed afterward.

PDF recognition requires [Audiveris](https://github.com/Audiveris/audiveris/releases), installed separately. Set `AUDIVERIS_PATH` to its executable or add it to PATH. macOS installations in `~/Applications/Audiveris.app` and `/Applications/Audiveris.app` are detected automatically. The macOS app includes Java.

Core conversion does not import Flask or Verovio and does not start a server. There is no package installation/build configuration; copy the `soundwaves/` folder alongside your other Python code, or add this repository to your Python import path.

## Full conversion artifacts

For repaired MusicXML, reference notes, and a repair log:

```python
from soundwaves import convert_score

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
python3 -m venv venv
venv/bin/python -m pip install -r web-server/requirements.txt
venv/bin/python web-server/app.py
```

Open http://127.0.0.1:5000. Stop with Ctrl+C.

The server calls `soundwaves.convert_score`, then uses `web-server/preview.py` to render notation and highlighting data. It shows the original PDF beside the score, plays local piano samples, and offers MIDI, repaired MusicXML, original recognition, and repair-log downloads.

Every upload reruns recognition and conversion. No previous score or output is reused; HTTP caching is disabled. Uploads are limited to 20 MB and recognition to five minutes. Generated sessions are stored in `web-server/instance/uploads`; delete that directory to clear them.

## Structure

| Location | Responsibility |
| --- | --- |
| `soundwaves/conversion.py` | Callable conversion functions and result paths |
| `soundwaves/recognition.py` | Local Audiveris PDF recognition |
| `soundwaves/reference.py` | Parsing, repeat expansion, MIDI/WAV export, measure/note data |
| `soundwaves/repairs.py` | Automatic repairs and before/after records |
| `soundwaves/validation.py`, `soundwaves/tuplets.py` | Score and tuplet checks |
| `soundwaves/expression.py` | Dynamics and hairpin velocities |
| `web-server/app.py` | Flask upload/download interface |
| `web-server/preview.py` | Verovio notation rendering and highlighting timeline |
| `web-server/templates/` | HTML |
| `web-server/static/styles/` | CSS |
| `web-server/static/scripts/` | JavaScript |
| `web-server/static/audio/` | Piano samples and attribution |

## Musical behavior and limits

Voices retain independent rhythms, ties retain one attack, and clefs determine pitches. Dynamics from `pppp` to `ffff` map to MIDI velocities. Hairpins interpolate toward their endpoint dynamic, or change velocity by 20 when no endpoint dynamic exists. Encoded brace groups share dynamics. Browser playback uses sampled piano with gain changes, rather than multiple sampled velocity layers.

Automatic repairs combine equal-length simultaneous events within a voice into chords, repair fragmented unmatched tuplets when written durations exactly fit the existing onset slots, and add rests to trailing silence in internal metered measures. A restricted heuristic can infer an earlier clef change in a braced staff group when a later explicit clef and a uniquely better chord-register transition support it. Inferred pitch changes are labeled for review. Repairs contain no score fingerprints or fixed measure numbers.

The repair log retains original findings, before/after changes, and remaining warnings. Unsupported or ambiguous errors stay flagged. A bracketed `6` is a sextuplet rhythm, not a sixfold repeat. Recognized tuplet ratios are preserved; ordinary repeat barlines are expanded separately.

Audiveris has [documented recognition limitations](https://audiveris.github.io/audiveris/_pages/reference/limitations/). Structural repair cannot guarantee correct interpretation of every PDF. Missing notes, incorrect staff assignments, and ambiguous notation may still require correction in a notation editor. Grace notes, microtones, pedal realization, and expressive rubato are not implemented.

Reference JSON preserves notes, score beats, and measure boundaries for future performance comparison. A future comparator must align played notes to score beats before comparing local timing; fixed timestamp slicing would accumulate tempo drift.
