# Soundwaves

Play from your sheet music and Soundwaves marks every note.

It is for people teaching themselves piano. You read music, you practise alone, and nobody tells you that the left hand in bar 11 was an octave too high or that you rush every time the semiquavers start. Soundwaves listens while you play, turns the score green, red, orange and purple as you go, and when you stop it writes you the notes a teacher would.

Built at Cal Hacks 13.0 (October 2026).

## What it does

- **Play live.** Pick a piece, press Start, play into the microphone. About two seconds behind your hands, each note on the engraved score turns green (right), red (wrong key, with the key you actually played drawn in purple), orange (skipped) or gets a purple extra note. A list on the right says what went wrong in plain words, a bar-by-bar table fills in with tempo and timing, and the coach can say it aloud so you never have to look up from the keys.
- **Your review.** Press Stop and the whole take is checked again with the accurate transcriber. You get a one-line summary, teacher's notes (what went well, what to work on by bar, a plan for the next session), the coloured score you can click to hear any moment, the bar table, and a keyboard replay. Each focus area has a button that sends you back to Play live from that bar.
- **Check a recording.** Already recorded yourself on your phone? Upload the recording and the sheet music and get the same review.
- **Add a piece.** Upload a PDF or MusicXML once; it is read into notes and shows up in the piece list for everyone on that computer.

## How it works

Sheet music goes through Audiveris (optical music recognition) into MusicXML, then music21 into a note list with bars, beats, hands, tempo and dynamics. Grace notes, conflicting tempo marks and odd exports are repaired on the way in; 235 of 235 public-domain scores in our test set convert.

Your playing goes through Transkun v2 (a piano transcription model, PyTorch on Apple silicon) into notes with onsets, lengths and velocities. Basic Pitch is the fallback when Transkun's environment isn't installed, and the quick layer that moves the cursor live.

Before Basic Pitch transcription, the piano cleaner reduces short broadband key clicks separately from steady room noise. It preserves the recording timeline and protects sustained pitch components. This is conservative attenuation, not guaranteed separation of keyboard mechanics from piano attacks. Transkun still uses the original audio by default; `SOUNDWAVES_CLEAN=on` enables cleaning for it too.

The two note lists are lined up by a monotone sequence alignment, then repaired by rules we wrote from watching real takes fail: same-pitch re-pairing, split chord notes, runs played a step off, right note in the wrong octave, quiet background noise, grace notes, partial takes and where a take actually ends. Each bar gets a robust tempo fit, so timing is judged against your own pace in that bar, not a metronome.

Live mode streams the take to a rolling session on the server that re-transcribes the last six seconds and re-aligns the take so far about every 1.3 s. A mistake is shown only when two passes agree on it, and a mark that has settled stays put, so nothing flickers. The player's position is tracked from timing, so the aligner can't pin a stray note three bars ahead.

The written feedback is drafted by Claude (Anthropic) from the structured findings, or by Gemini when only a Gemini key is set. Per-note explanations on the older review page use Gemini. The models only ever see the comparison, never the audio, and never decide what was right or wrong.

The score on screen is engraved by Verovio from the recognised MusicXML; marks are painted onto the actual noteheads.

## How well it works

Measured on real data, details in `testing/datasets/README.md`:

| Test | Result |
| --- | --- |
| Audio to notes, Transkun, quiet room (note F1) | 0.98 |
| Hand-labelled student mistakes caught, MIDI | 190 of 191 |
| Hand-labelled student mistakes caught, audio, quiet room | 190 of 191, 98% of flags real |
| Planted mistakes in expert ASAP performances | 39 of 40, no new false alarms |
| Live marks agreeing with the final report, test clip | 245 of 247 notes |

Those rows were measured on the comparison adapter in `soundwaves/report.py`, which the older review page uses. The review and live pages in `soundwaves/web` run a lighter path: the same aligner with the split-note merge, end-of-take trimming and the room-noise rules, without the adapter's other repairs. On the same hand-labelled student set that path catches 86 to 88% of mistakes, and 94% of its flags are real in a quiet room, 79% with someone talking at 10 dB. Bringing the remaining repairs across is the next job.

The self-checks at `/test` run five end-to-end cases (planted mistakes, a clean take, a MIDI take, a partial take, silence) in about 30 seconds.

## Run it

Use Python 3.14. The launcher installs requirements into the existing `venv/`, or creates `.venv/`. Open the URL below after starting it.

```sh
cp .env.example .env            # optional: add AI feedback keys
python3 run.py                        # http://127.0.0.1:5001
python3 check.py                      # unit tests, browser tests, end-to-end cases
```

Optional but recommended:

- **Transkun** for piano-specific transcription: a Python 3.12 environment at `.venv-transkun` with `transkun` and PyTorch installed. Without it the bundled Basic Pitch model is used. The review page names the active transcriber. MIDI playback and downloads use the same cleaned detections as the comparison.
- **Audiveris** for PDF scores: install the app (macOS: `/Applications/Audiveris.app`) or set `AUDIVERIS_PATH`. MusicXML and MXL work without it.

Pages: `/` opens Play, `/live` play live, `/check` review a recording, `/learn` learn a piece, `/easy` simplify a recording, and `/test` self-checks. Add scores through **New piece** in the piece dropdown.

## Repository map

- `sheet_downloader/` score reading and repair (Audiveris, music21)
- `transcribe_recording/`, `soundwaves/transkun_*` audio to notes
- `alignment/` the aligner and per-bar analysis
- `soundwaves/` report adapter, repairs, teacher notes, pages
- `soundwaves/web/` the main Flask app, report/playback routes, score rendering, and comparison cache
- `testing/` test cases, demo audio generation, and dataset evaluation tools
- `frontend/` current app templates, scripts, styles, and shared piano samples
- `ipad_keys/` independent iPad falling-keyboard page
- `testing/datasets/` real-data evaluation scripts and results

## Built with

Python, Flask, music21, Audiveris, Transkun, Basic Pitch, PyTorch, NumPy, Verovio, Web Audio, the Anthropic API (Claude), the Gemini API.

Application tests: `venv/bin/python -m unittest discover -s testing/soundwaves -t .`. Browser tests: `node --test testing/frontend/*.test.cjs`.

Frontend layout and removed legacy interfaces are documented in [frontend/README.md](frontend/README.md) and [frontend/CLEANUP.md](frontend/CLEANUP.md). The iPad page is independent; see [ipad_keys/README.md](ipad_keys/README.md).
