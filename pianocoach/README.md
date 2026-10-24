# pianocoach — audio ↔ MIDI converters and the live practice screen

This branch holds the conversion code only. The full practice product (record page,
final review, explanations) lives elsewhere.

## What converts what

| Direction | Where | Notes |
| --- | --- | --- |
| Microphone audio → notes, live | `pianocoach/live.py` (`POST /api/practice/notes`) | Bounded 16-bit WAV windows through the bundled Basic Pitch model, one inference at a time, then `clean.py` |
| Browser detections → ordered attacks | `pianocoach-ui/live-stream.js` | Merges overlapping windows into one-to-one note attacks |
| Attacks → score position | `pianocoach-ui/live-matcher.js` | Conservative online score follower, never grades timing |
| Recording audio → MIDI, offline | `pianocoach/transkun_backend.py`, `transkun_worker.py` | Transkun v2 in its own Python 3.12 environment; see below |
| Score / notes → piano audio | `GET /api/practice/piano/<pitch>`, `pianocoach-ui/practice-demo.js`, `testing/render_piano.py` | FluidR3 sampled grand (CC BY 3.0) already bundled in `testing/web-server` |
| Keyboard events → MIDI file | `encodeMidi` in `pianocoach-ui/practice.js` | Web MIDI or on-screen keys to a type-0 SMF |

`scoreprep.py` merges unison and overlapping same-pitch score notes before anything is compared,
and `report.py` supplies note spelling, score metadata and plain fallback wording.

## Run the live screen

```sh
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pianocoach.practice_server        # http://127.0.0.1:5002/practice
```

Pick the piece, start, play. "Play demo" plays a sampled-piano excerpt with a few deliberate wrong
notes so the screen can be tried without an instrument. The end-of-take final review calls
`/api/analyze`, which is not on this branch; the page then offers the captured take as a download.

## Transkun (optional, better offline audio → MIDI)

```sh
uv venv --python 3.12 .venv-transkun
uv pip install --python .venv-transkun/bin/python transkun torch torchaudio soundfile "setuptools<80"
```

`TranskunBackend` implements the `transcribe_recording` backend protocol and keeps the model loaded
in a worker process (about a second to load on Apple Silicon, roughly eight seconds per two minutes
of audio). Use it as `transcribe_recording(audio, out, backend=TranskunBackend())`.

## Tests

```sh
.venv/bin/python -m unittest pianocoach.test_live pianocoach.test_clean pianocoach.test_scoreprep pianocoach.test_report pianocoach.test_transkun
node --test pianocoach-ui/*.test.cjs
.venv/bin/python -m pianocoach.benchmark_live --runs 3
```
