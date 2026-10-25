# Testing PianoCoach

Two commands. Both work from a fresh clone of this branch.

```sh
./run.sh            # sets everything up, starts the app, opens the test page
./check.sh          # runs every test and prints ALL CHECKS PASSED or what failed
```

Prerequisites: [uv](https://docs.astral.sh/uv/) (`brew install uv`). Node is optional (browser logic tests).
`./run.sh --fast` skips Transkun (a 1 GB install) and uses the bundled Basic Pitch model instead.

## The test page

`./run.sh` opens the original upload page at **http://127.0.0.1:5001** (it now has the new transcriber, cleaning and partial-take detection). The
new pages are on the same server: **http://127.0.0.1:5001/test**. Click **Run all checks**. Each card renders a piano
recording of the Minuet in G with mistakes planted at known places, runs the real converters, and tells you
whether what came out matches what went in:

| Case | What it proves |
| --- | --- |
| Four mistakes | audio → MIDI → score comparison finds a wrong note, a skipped note, a late note and a rushed bar |
| No mistakes | a correct performance is not flagged |
| MIDI keyboard take | the keyboard path (no transcription) gives the same answer |
| First four bars only | a take that stops early is only marked where it was played |
| Silent recording | a dead microphone is refused with a clear message |

Green ✓ is a pass, red ✗ is a failure, and an orange ! is a warning (for example, Basic Pitch adds false notes that
Transkun does not). The first run takes about a minute because it renders the piano audio; later runs are cached.
The top of the page shows which transcriber is active and whether a microphone or MIDI keyboard is connected.

## Test only the audio → MIDI conversion (no sheet music)

Open **http://127.0.0.1:5001/convert** and drop in any piano recording (an iPhone voice memo `.m4a` works). You get
the original and cleaned audio side by side, a piano roll of the notes found, the MIDI played back on a sampled
piano so you can hear what the converter heard, the MIDI file to download, and what the cleaner changed. Or from the
terminal: `.venv/bin/python -m pianocoach.convert ~/Downloads/take.m4a` (prints the notes and a link to the page).

## Try it by hand

- **http://127.0.0.1:5001/practice** — the live screen. Press **Play demo** for a sampled-piano example with three
  deliberate mistakes, or pick Microphone, USB / MIDI or On-screen keys and play.
- **http://127.0.0.1:5001/record** — record or upload a whole take and get the full review.
- The bottom of `/test` takes any WAV/MP3/M4A/MIDI file of the Minuet in G.

If the microphone hears nothing: Chrome → the lock icon next to the address → allow Microphone, and check the input
device in macOS Sound settings. The level bar moves while you play.

## Explanations (optional)

The wording on each finding comes from Claude or Gemini when a key is present. Put it in a file named `.env` next to
this one (it is gitignored):

```
GEMINI_API_KEY=...
ANTHROPIC_API_KEY=...
```

Without a key the app uses plain built-in wording and every test still runs.

## Other checks

```sh
.venv/bin/python -m pianocoach.selftest mistakes     # one end-to-end case from the terminal
.venv/bin/python -m pianocoach.benchmark_live        # live-listening latency
.venv/bin/python testing/make_demo_take.py pianocoach/pieces/minuet_in_g.mxl out/take --wrong 3:3.5 --drop 7:2
```
