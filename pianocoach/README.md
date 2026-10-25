# pianocoach

Glue between the analysis code and the practice page in `pianocoach-ui/`.

```
pianocoach/
  report.py     alignment report + reference.json  ->  the JSON the page renders
  clean.py      drops Basic Pitch overtone ghosts and merges split notes before alignment
  explain.py    asks Claude for the explanation and tip on each finding; cached; falls back to plain text
  pipeline.py   analyze(score, performance, out_dir) runs convert -> transcribe -> clean -> align -> report
  app.py        Flask: serves the page with real reports, /record for mic or file upload, /api/analyze
  pieces/       scores the record page offers (file + optional .json sidecar with title, composer, catalog, bpm)
  sessions/     one folder per take: recording.*, report.json, alignment.json (gitignored)
  cache/        Claude explanations keyed by content hash (gitignored)
```

## Run it

```sh
.venv/bin/python -m pianocoach.app          # http://127.0.0.1:5002
```

### Live practice

Open **http://127.0.0.1:5002/practice** for the score beside a live view of played notes. Choose Microphone, USB / MIDI, or On-screen keys, then Start. Finish opens the summary in the same screen. There is no spoken feedback.

**Play demo** runs an audible 15-second, eight-bar excerpt with two wrong keys and one skipped note. It needs no microphone or MIDI permission. Sampled piano and timed MIDI events come from the selected score, pass through the normal live follower, then automatically use the existing final review (`explain=0`). Stop cancels scheduled audio; Replay starts a fresh demo. The mode is clearly labeled and is not a microphone-accuracy test. Piano samples are the bundled FluidR3_GM bank (CC BY 3.0, attribution shown during demo).

- Both piano staves remain visible in one horizontal score. Following advances from matched note onsets, never from a timer. Pauses and silence do not generate missing-note errors.
- USB / MIDI updates as key events arrive. On-screen keys exercise the same follower and can be used without an attached instrument.
- Microphone capture uses an AudioWorklet and a separate warm Basic Pitch model on a rolling 1.5-second context, starting after 200 ms and scheduled every 100 ms with at most one request in flight. AudioWorklet batches are 1024 samples (about 46 ms at 22.05 kHz). The stream adapter holds the newest 100 ms, deduplicates overlapping attacks, and never advances on silence. Live microphone marks are provisional; late overlap detections do not move the follower backwards. The recording goes to the existing Transkun/final-analysis pipeline after Finish.
- The comparison shows the song and your playing as matching pitch trails, with green checks and coral higher/lower hints. Expected piano keys are outlined; detected keys light up. The input waveform responds to actual captured audio.
- Local synthetic audio through the complete browser capture/request/render path measured 136–275 ms onset-to-feedback (182 ms median in the final 13-note test), with 12 correct melody notes and the intentional wrong note shown immediately on detection. This is not a physical microphone latency measurement.
- The live follower handles pitch and skipped-note candidates conservatively. It does not grade live rhythm, dynamics, or pedaling. Microphone accuracy depends on the room and instrument; synthetic-audio checks do not establish acoustic-piano accuracy.
- Partial summaries use a bounded prefix alignment so untouched later bars are not called missing. They summarize pitch findings; completed takes retain final timing and coaching. The original report is unchanged and its review link is shown only for complete takes.
- If final analysis fails or times out, the captured take remains available to download. Recordings are not saved across page reloads.

Frontend files (scripts and CSS are also in `pianocoach-ui/practice/`): `pianocoach-ui/practice/index.html`, `practice.css`, `practice.js`, `live-audio-worklet.js`, `live-matcher.js`, `live-stream.js`, and `practice-demo.js`. API routes and provisional audio detection live in `pianocoach/live.py`.

```sh
.venv/bin/python -m unittest pianocoach.test_live
node --test pianocoach-ui/tests/*.test.cjs
.venv/bin/python -m pianocoach.benchmark_live --runs 3
```

- `/record` picks a piece, records from the microphone (or takes a WAV/MP3/M4A/WebM/MIDI upload), posts it, and opens the result.
- `/?report=<id>` opens a saved take. `/?report=latest` opens the newest one.
- `POST /api/analyze` with form fields `piece` (a stem from `pieces/`) or `score` (file), `performance` (audio or MIDI), optional `take`, `hands` (`right` or `both`), `explain` (`0` to skip Claude).

From Python:

```python
from pianocoach.pipeline import analyze
report, paths = analyze('score.musicxml', 'take.wav', 'out/take-1', bpm=108,
                        piece=dict(title='Minuet in G major', composer='Christian Petzold'))
```

## Claude explanations

`explain.py` sends the findings plus the notes of each bar to `claude-opus-5-5` with a JSON schema and
writes the result into `explanation` and `tip` on each finding and a two-sentence `coach` summary.
Responses are cached in `cache/explanations/` by content hash, so the demo take costs one request ever.
Without a credential (or when the request fails) the plain fallback wording stays and
`meta.explanations` reads `fallback`.

Keys are read from the environment or from a gitignored `.env` at the repo root:

```
ANTHROPIC_API_KEY=sk-ant-...      # Claude, the default and the Anthropic-track requirement
GEMINI_API_KEY=AIza...            # Gemini fallback (also counts for the MLH Gemini track)
```

`PIANOCOACH_EXPLAINER=claude|gemini|auto` forces a provider (auto: Claude if its key is set, else
Gemini). `GEMINI_MODEL` overrides the default `gemini-2.5-flash`. Precompute for a saved take with:

```sh
.venv/bin/python -m pianocoach.explain pianocoach/sessions/<id>/report.json
```

## Transcriber

Audio goes through **Transkun v2** (MIT, the strongest published piano transcriber) when the
`.venv-transkun` environment exists, otherwise through the bundled Basic Pitch model. Transkun runs as
a worker process on its own Python 3.12 interpreter and loads once per server run (about a second on
Apple Silicon with MPS; a two-minute take transcribes in about eight seconds). Create the environment with:

```sh
uv venv --python 3.12 .venv-transkun
uv pip install --python .venv-transkun/bin/python transkun torch torchaudio "setuptools<80"
```

Force a choice with `PIANOCOACH_TRANSCRIBER=basic|transkun|auto`. On the planted-mistake Minuet take
rendered with sampled piano, Transkun reported exactly the planted mistakes; Basic Pitch missed some
first-beat notes above the bass and added a handful of false extras.

`clean.py` runs on the transcription before alignment: near-simultaneous duplicate detections merge,
short quiet overtone ghosts go (Basic Pitch only), and a short restart of a still-sounding pitch is
folded into the note. Full-length repeated notes are never merged.

## Making test takes

```sh
.venv/bin/python testing/make_demo_take.py pianocoach/pieces/minuet_in_g.mxl out/take \
    --tempo 96 --wrong 3:3.5 --drop 7:2 --rush 5 --late 15:2:150 --lh-wrong 9:1
```

renders `take.wav` with the sampled piano from `testing/web-server` plus a `planted.json` listing what
to expect. `testing/render_piano.py` renders any event list the same way.

## Short, partial and empty takes

- A take with fewer than four notes (a silent microphone, a disconnected keyboard) is refused by
  `/api/analyze` with HTTP 422 and a sentence the record page shows, instead of a page of missing notes.
- A take that covers much less than the piece (under 60 % of the score's notes) is first located:
  every window of about the right length is aligned and the one matching the most notes wins, earliest
  on ties (first pass of a repeat). Only that stretch is aligned and marked, `meta.played_bars` says
  which printed bars, and `coach` says "You played bars 9 to 12, so only those bars are marked."

## What the page gets

Exactly the contract in `pianocoach-ui/README.md`, validated in Python by `validate_ui_report()` which
mirrors the page's own `validateReport()`. Right-hand notes only by default; the right hand is the part
with the higher median pitch. Measures are renumbered 1..N in first-occurrence order so pickup bars and
repeats work. Extra keys the page ignores: `bars` (per-bar tempo verdicts), `meta`, `coach`.

Confidence is a heuristic, not a calibrated probability: MIDI input is `confident`; audio findings use the
transcriber's per-note model score. Timing findings compare a note with the fitted pace of its own bar.

## Tests

```sh
.venv/bin/python -m unittest pianocoach.test_report pianocoach.test_clean
```
