**Testing:** `./run.sh` then open http://127.0.0.1:5001/test, or `./check.sh` for everything. See `TESTING.md`.

# Review of Codex's live practice work + branch push — Claude, 2026-10-24 ~16:00

- **Pushed** `audio-midi-converters` (commit 738dacc) to GitHub: Codex's live stack (`pianocoach/live.py`,
  `benchmark_live.py`, `test_live.py`, `pianocoach-ui/live-*.js`, `practice-demo.js`, `practice.{html,css,js}`
  and their tests) plus what it needs to run: `clean.py`, `scoreprep.py`, `report.py`, `__init__.py`, the
  Transkun backend/worker, `testing/render_piano.py`, the Minuet score, and a new `pianocoach/practice_server.py`
  launcher (serves `/practice`, `/api/practice/*`, `/api/pieces`). Verified on the branch: Python tests OK,
  39/39 browser tests, launcher routes 200. Everything else stays uncommitted here, as asked.
- **Review verdict:** solid. Bounded uploads, one inference at a time, path-safe asset/score/report routes,
  deterministic prefix summary, good tests. Demo exercised in Chrome end to end: "Demo complete · played through
  bar 8 · 3 places to revisit" with exactly the three planted mistakes; no console errors. Benchmark: sampled-piano
  single notes detected with 75 ms of audio, C major chord at 100 ms, warm endpoint ~13 ms; a five-note chord drops
  one tone (Basic Pitch live is provisional, as Codex says; the final review uses Transkun).
- **Integration fixes made on my side after the review:** (1) `pipeline.locate_take` now trims the located window to
  the bars that matched and re-aligns, so Codex's prefix summary (which assumes playing starts at the first listed
  bar) stays correct for mid-piece starts; (2) `live.py` reliability check tolerates one lead-in bar; (3) partial
  takes no longer mark notes after the last played note; (4) accidentals are spelled by key signature (D♯5 in
  G major, not E♭5). Tests: `test_partial.MidPieceSummaryTests` covers (1)+(2).
- **Known:** Finish on mic/MIDI runs the full review with explanations on (Gemini adds ~10 s); demo and on-screen keys
  send `explain=0`. The live page draws both staves; the old `/` report page draws the right hand only.

---

# Demo mode addendum — Codex, 2026-10-24

- Latest request: a piano-free demo for personal testing. Implemented **Play demo** in the practice header, plus Demo piano in input selector.
- Plays a 15.15-second/8-bar sampled piano excerpt. Exact intentional edits: bar2 D5→D#5; bar3 F#5→F5; bar5 firstRH C5 skipped. 49 played notes, both hands, derived from current score, no source mutation.
- AudioBufferSource playback uses AudioContext clock; scheduled note times are retained in ordinary input/follower/MIDI events. No microphone permission, fake verdicts, or explanation-service call. Automatically finishes into actual `/api/analyze` MIDI review with `explain=0` and prefix summary. Stop cancels all scheduled sources; replay resets state. Normal input choice stays available after review.
- Added `pianocoach-ui/practice-demo.js`, `practice-demo.test.cjs`; edited practice HTML/CSS/JS; safe cached sample route `/api/practice/piano/<pitch>` in `pianocoach/live.py` plus2route tests. Bundled sample source/testing assets unchanged; CC BY3.0 attribution visible during demo. README updated.
- Browser full run produced exactly2different-key findings +1skipped note, through bar8. Replay, early stop, switching to on-screen keys, demo disabled during real take, and mobile390px layout verified. No console errors. User IAB remains ready at `/practice` with Play demo visible, no autoplay.
- `node --test pianocoach-ui/*.test.cjs`: **39/39pass**. `.venv/bin/python -m unittest pianocoach.test_live`: **18/18pass**. Syntax check passed.
- Wider Python suite now runs27tests and has2failures in other report work: `OctaveTests.test_octave_displacement_is_one_wrong_pitch_finding` (emptyfindings vs3) and `PartialTakeTests.test_only_played_bars_are_marked` ([1,3] vs[1,2]). Not modified/hidden; user informed. Demo's actual final summary is correct.
- Server restarted for sample route. Current retained exec session **89738**, command `.venv/bin/python -m pianocoach.app 5002`. Earlier session40695 was stopped. Check listener before future restart.
- No commits/push/deployment. Existing team changes preserved. Proof screenshots in this Codex chat outputs: pianocoach-demo-playing.png, pianocoach-demo-summary.png.

---

# HANDOFF — PianoCoach live practice, Sat 2026-10-24 — Codex update

## Goal

The user clarified the core product: read sheet music while playing, see quiet live visual marks beside it, then get a summary after finishing. Both microphone/acoustic piano and USB/MIDI inputs are required. No spoken coaching during playing. Preserve the dark teal/glass aesthetic and concise UI.

## State

- Implemented and running at **http://127.0.0.1:5001/practice**. The existing `/record` and saved report routes remain available.
- Both-hand horizontal score; note-based following (never a nominal-tempo timer); song/you pitch-trail comparison; large Right note / A little higher / A little lower cues; expected-key outlines and played-key flashes; real input waveform; MIDI and provisional mic marks; end-only summary.
- Microphone uses 1024-sample AudioWorklet PCM batches (~46 ms), begins after 200 ms, requests every 100 ms over up to 1.5 seconds of context, with one request in flight and no stale request queue. Full original MediaRecorder capture still goes through existing final Transkun pipeline.
- Latest browser synthetic-audio test exercised actual AudioWorklet→WAV→live endpoint→stream merger→score marks: every one of 12 correct melody notes confirmed as detected; one deliberate F5 instead of F#5 showed a higher hint. Onset-to-feedback was 136–275 ms, median 182 ms, wrong note 200 ms. Physical microphone/room latency was not measured. Test-only input mocks were closed/reloaded.
- Browser simulated MIDI port exercised the MIDI handler, score marks, MIDI encoding, analysis, and summary: 17 matched notes, then expected 2 findings (one omitted A3 and F5 instead of F#5). Physical USB hardware still needs testing.
- Partial summaries now realign saved events against a score prefix. Untouched later bars are not called missing. A reproduced half-length repeated-passage bug is covered by a regression test.
- Everything remains uncommitted. Existing dirty `.gitignore`, all earlier Claude work, and the user's sessions were preserved. No keys were printed or changed.

## Files touched by Codex in this update

- `pianocoach/app.py`: import/register the new practice blueprint only.
- `pianocoach/live.py`: score/asset/live-note/partial-summary routes, bounded inference and prefix alignment.
- `pianocoach/test_live.py`: 16 endpoint, input-bound, score, and summary tests, including real-model short-window onset detection.
- `pianocoach-ui/practice.html`, `practice.css`, `practice.js`: new practice view and capture/finish flow.
- `pianocoach-ui/live-audio-worklet.js`: silent PCM capture; never routes mic audio to speakers.
- `pianocoach-ui/live-matcher.js`, `live-matcher.test.cjs`: event follower; 18 tests. Exact next onset after a partially heard chord can advance immediately; completely skipped groups still need two anchors.
- `pianocoach-ui/live-stream.js`, `live-stream.test.cjs`: overlap adapter, 13 tests; one-to-one dedup, right-edge hold, left-edge sustain suppression, chronological late-note separation.
- `pianocoach/benchmark_live.py`: repeatable generated/sampled-piano causal detection benchmark; no external calls.
- `pianocoach/README.md`: run/test instructions and current limits.
- `HANDOFF.md`: this section prepended; prior handoff retained below.

## How to run / verify

From `~/Desktop/calhacks/soundwaves`:

```sh
.venv/bin/python -m pianocoach.app 5002
node --check pianocoach-ui/practice.js
node --test pianocoach-ui/*.test.cjs
.venv/bin/python -m pianocoach.benchmark_live --runs 3
.venv/bin/python -m unittest pianocoach.test_live pianocoach.test_report pianocoach.test_clean pianocoach.test_scoreprep
```

Latest results: JS parses; 31 matcher/stream tests pass; 24 Python tests pass. Desktop 1280×900 and mobile 390×844 verified, no horizontal page overflow; end-of-take summary exercised with synthetic mic and on-screen keys. `pianocoach.test_transkun` also passed earlier in the session but emitted existing unclosed-pipe ResourceWarnings. No tests were removed or weakened.

Codex's currently running server is retained in exec session 40695; it binds loopback 5002. Check the listening PID before starting another. The user-facing page should be left at `/practice`, ready to start with a real input. Test-only browser input mocks are cleared by reload and were never added to source.

## Decisions / gotchas

- Basic Pitch live detection is provisional, especially for acoustic polyphony. Actual model check on sampled piano: C4/C6 detected with 75 ms of captured sound, A2 with 50 ms, C major chord with 100 ms; warm Flask endpoint ~13 ms. Five-note dense chord missed one tone; octave ghosts still possible. This is not an acoustic accuracy guarantee.
- Incoming microphone windows use live-stream.js with 0.10 s right-edge hold, 0.12 s left-edge rejection, 0.09 s onset dedup tolerance, and 0.06 s late-chord grace. Only emitted attacks advance chronology; silent/empty replies do not. Late rediscovered notes render neutrally instead of moving the follower backwards.
- MIDI marks can be immediate; skipped-note candidates require subsequent pitch anchors. Mic never confirms missing notes or timing. Silence and pauses generate no verdicts.
- Final summary uses only confidently covered prefix. Complete takes can retain final timing/coach text. Partial takes currently summarize pitch only and hide the old full-review link because the old full report still assumes the whole passage.
- Original full review still draws only right hand. New practice view draws both staves. Do not confuse sequential unfolded measures (64 here) with 32 printed bars/repeats.
- Existing `/api/analyze` remains the final-analysis endpoint. No spoken output was added. On-screen-key testing sets `explain=0`; real microphone/MIDI final reviews keep configured explanation behavior.
- Final requests have bounded timeouts; failures retain a download link for the captured take. Reloading still discards unsaved recordings.
- MIDI sustain-controller data is not captured; rhythmic/dynamic/pedal grading is outside the live follower.
- Previous isolated frontend at `~/Desktop/calhacks/pianocoach-ui` on 8765 is only the earlier report prototype. The new integrated work is in this repository.

## Next steps

1. User test on a real acoustic piano and USB keyboard. Check microphone device, room noise, wrong-note marks, pauses, and Finish summary. No physical instrument was available for automated verification.
2. If needed tune the live detector's onset/dedup thresholds using actual piano recordings. Keep uncertain mic marks provisional.
3. Team decides how to consolidate `/record` and `/practice` entry points; no old route was removed.
4. Commit in logical groups when the user asks; do not commit `.env`, recordings, or runtime caches.

## Resume prompt

> Read HANDOFF.md. The live practice screen is at http://127.0.0.1:5001/practice. Preserve the existing pipeline and plain UI; continue from real-instrument verification in Next steps.

---

# Earlier Claude handoff — Sat 2026-10-24 ~14:00 PDT

Written by Claude Code for whoever picks this up (Codex, a teammate, or a fresh session).
Devpost hard deadline: **Sun 2026-10-25 09:00 PDT**. Repo must be public by then.

## Where things are

- Repo clone: `~/Desktop/calhacks/soundwaves` (branch main, **everything below is uncommitted**; the user has not asked for commits).
- Python: `.venv` (3.14, uv) for everything; `.venv-transkun` (3.12) only for the Transkun transcriber worker. Both gitignored.
- Datasets (outside the repo, untrusted downloads): `~/Desktop/calhacks/datasets/{asap-dataset, scores, expert-novice, scoreinformed-midi, en-augmented}`.
- Planning handoff from the design session: `~/Downloads/CLAUDE_CODE_CONTEXT.md`. Spec: `overview.md`.
- Finished front end: `pianocoach-ui/index.html` (now at repo root; also still at `~/Desktop/calhacks/pianocoach-ui`). Do not redesign it.

## What was built today (new, uncommitted)

```
pianocoach/            adapter + server (see pianocoach/README.md)
  report.py            alignment report + reference.json -> the page's JSON; mirrors the page's validator
  clean.py             duplicate merge, overtone-ghost filter (Basic Pitch only), split-note merge
  scoreprep.py         merges unison/overlapping same-pitch score notes before alignment
  explain.py           Claude (claude-opus-5-5, structured output) explanation + tip per finding; cached; plain fallback
  pipeline.py          analyze(score, audio|midi, out) and align_clean(); CLI: python -m pianocoach.pipeline
  transkun_worker.py   persistent Transkun model process (runs on .venv-transkun)
  transkun_backend.py  TranscriptionBackend wrapper; pipeline picks it automatically when .venv-transkun exists
  app.py               Flask :5002 — serves the page with real reports, /record (mic, file, USB MIDI keyboard), /api/analyze
  pieces/minuet_in_g.mxl (+ .json)  public-domain two-staff score, 32 bars (MuseTrainer library)
  sessions/, cache/    gitignored runtime data
  test_*.py            11 unit/integration tests (plus the teammates' 2; all 13 pass)
testing/datasets/asap_eval.py + README.md   evaluation on real performances + dataset/model catalog
testing/make_demo_take.py                    plant mistakes into any score and render a sampled-piano WAV
testing/render_piano.py                      event list -> WAV with the FluidR3 piano samples already in the repo
```

## Verified (commands and results)

```sh
.venv/bin/python -m unittest pianocoach.test_report pianocoach.test_clean pianocoach.test_scoreprep pianocoach.test_transkun
# Ran 11 tests ... OK
.venv/bin/python -m unittest sheet_downloader.test_reference testing.alignment.test_notation   # teammates' tests, OK
.venv/bin/python testing/make_demo_take.py pianocoach/pieces/minuet_in_g.mxl out/take --wrong 3:3.5 --drop 7:2 --rush 5 --late 15:2:150 --lh-wrong 9:1
.venv/bin/python -m pianocoach.pipeline pianocoach/pieces/minuet_in_g.mxl out/take/take.wav out/take/report --no-explain
# -> exactly: wrong F#5->F5 bar 3, missing G4 bar 7, B4 +150 ms bar 15, pace.rushed_bars=[5]; P 0.98 R 0.99 (Transkun)
```

- Server: `.venv/bin/python -m pianocoach.app` then `http://127.0.0.1:5001/?report=d3b07384d113edec49eaa6238ad5ff00` shows that take in the finished page (checked in Chrome). `/record` records from the mic (WebM upload tested), takes file uploads, and listens to a USB MIDI keyboard (Web MIDI; encoder tested end to end from the browser; no keyboard was attached to test hardware).
- ASAP dataset (expert MIDI performances vs MusicXML): planted mistakes caught 39/40 with 0 new false alarms; ~30 findings per error-free expert Bach performance remain (ornaments, edition differences). See `testing/datasets/README.md`.
- Transkun vs Basic Pitch on the same sampled-piano take: Transkun exactly the planted mistakes; Basic Pitch 12 findings incl. 8 false. Transkun loads in ~1 s on MPS, ~8 s per 2 min of audio.

## Not done / needs a human

1. **Explanations: Gemini is live, Claude is not yet.** A Gemini key sits in `.env` (gitignored) with `GEMINI_MODEL=gemini-3.5-flash`; the demo take's explanations are generated and cached. The Anthropic track needs Claude doing the explaining: add `ANTHROPIC_API_KEY=...` to `.env` (credits link in #cohost-anthropic), rerun
   `.venv/bin/python -m pianocoach.explain pianocoach/sessions/d3b07384d113edec49eaa6238ad5ff00/report.json`
   and read the wording (style rules live in the system prompt in explain.py). The server reads `.env` on its next request; no restart needed for the saved take.
2. **Apify Actor** (priority 3 in the plan): not started.
3. ~~Real amateur audio test~~ done: four Expert-Novice *The Entertainer* takes analysed in 4.5–6.9 s each, 9–10 findings per take, P/R ≈ 0.96; octave displacement is now reported as "right note, wrong octave". Results and caveats in `testing/datasets/README.md`.
4. **Commit.** Nothing is committed. Suggested split: `pianocoach-ui/` ; `pianocoach/` (+ .gitignore) ; `testing/datasets`, `testing/make_demo_take.py`, `testing/render_piano.py` ; `HANDOFF.md`.
5. The page has no slot for `report.coach` (Claude's two-sentence summary) or per-bar pace; both are in the JSON if someone wants to surface them.
6. Known converter limits (teammates' code): grace notes rejected; the aligner is O(n·m) in pure Python (fine under ~2000 notes).
7. Live-demo advice: a USB MIDI keyboard makes the demo deterministic (no transcription); with a mic, give one second of silence before the first note and keep the room quiet. Keep the saved demo session as the fallback.

## Style rules in force
Plain human wording in anything user-facing; no AI-sounding filler; never put the UCLA student ID anywhere; max ~3 sponsor integrations; never touch /etc/hosts.

## Added after the first handoff (14:30–15:30)

- Your test takes from the record page showed two gaps, both fixed: silent microphone recordings (−91 dB, the
  browser captured nothing) now get a clear 422 message instead of 204 missing notes; short keyboard takes are
  now located within the score (`pipeline.locate_take`) and only the bars played are marked.
- Explanations: Gemini key in `.env`, `GEMINI_MODEL=gemini-3.5-flash`; demo take explained and cached.
- If the mic stays silent on the demo machine: check Chrome's microphone permission for 127.0.0.1 and the
  input device in macOS Sound settings; the level bar on `/record` should move while you play.
