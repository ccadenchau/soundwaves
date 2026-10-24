# Piano Performance Analyzer — Project Overview & Technical Architecture

**Working title:** PianoCoach  
**Implementation language:** Python  
**Document version:** 1.0 — October 2026  
**Goal:** Analyze a piano performance against written sheet music, identify probable mistakes, and provide specific, useful practice feedback.

---

## 1. Executive summary

PianoCoach accepts (1) a reference score and (2) a recording of someone playing that score. It converts both into a shared representation of musical notes, aligns the performed notes with the intended notes even when the player changes speed, detects discrepancies, and produces measure-level feedback.

**Core principle:** Use proven tools for optical music recognition (OMR) and audio-to-note transcription. Focus original engineering effort on score-to-performance alignment, error detection, confidence estimation, and actionable feedback.

**Recommended development progression:**
1. **MIDI vs. MIDI** to validate the comparison algorithm with perfect note inputs.
2. **MusicXML vs. MIDI** to support notation with explicit measures and beats.
3. **MusicXML vs. recorded audio** via a pretrained piano transcription model.
4. **PDF/image score vs. audio** using OMR.
5. **Interactive analysis UI** with clickable, highlighted measure-level errors.

**Non-goals for the MVP:** real-time feedback, arbitrary orchestral instruments, perfect transcription, fingering inference, advanced interpretation of expressiveness, and guaranteed error-free grading.

---

## 2. User experience and product requirements

### Core user flow
1. User selects a piano score (MVP: MusicXML; later: PDF/image).
2. User uploads a performance recording (MVP: WAV; later: MP3/M4A or MIDI).
3. User indicates optional starting measure or selected passage if they did not perform the whole piece.
4. System parses/transcribes each input, estimates alignment, and computes a report.
5. System shows annotated measures and detailed mistakes, with links to relevant audio timestamps.
6. User receives practice suggestions prioritized by frequency and severity.

### Functional requirements
- Parse note pitch, onset, duration, part/hand where specified, voice, measure, and beat from MusicXML.
- Extract note pitches, onsets, offsets, and approximate velocities from MIDI or transcribed audio.
- Handle tempo differences, count-in silence, extra pauses, and imperfect note onsets.
- Flag **wrong pitches**, **missed notes**, **extra notes**, **early/late attacks**, and **duration anomalies**.
- Report **per-measure** accuracy and a list of errors linked to score coordinates and performance timestamps.
- Treat uncertain transcriptions as **possible errors** rather than definitive mistakes.
- Provide specific, rule-based practice advice; optionally let an LLM phrase the advice later.
- Save a machine-readable JSON analysis report.

### Nonfunctional requirements
- Reproducible, testable offline analysis with versioned models and configuration.
- Robust handling of unsupported or corrupt files.
- Reasonable performance on short excerpts (e.g., 15–60 seconds) before scaling to whole pieces.
- Transparent scoring methodology; don't invent precision or claim certainty when model output is ambiguous.
- Respect recordings' privacy: process locally by default and don't upload to external services without clear notice.

---

## 3. System architecture

```text
                  ┌───────────────────────┐      ┌──────────────────────┐
                  │ Reference score       │      │ Performance          │
                  │ .musicxml / .mxl      │      │ .wav / .mid          │
                  │ (later .pdf / image)  │      │ (later .mp3)         │
                  └───────────┬───────────┘      └──────────┬───────────┘
                              │                             │
                  ┌───────────▼───────────┐      ┌──────────▼───────────┐
                  │ Score ingestion       │      │ Performance ingestion│
                  │ music21               │      │ pretty_midi          │
                  │ (Audiveris → XML)     │      │ or audio transcription│
                  └───────────┬───────────┘      └──────────┬───────────┘
                              │                             │
                  ┌───────────▼───────────┐      ┌──────────▼───────────┐
                  │ Score NoteEvents      │      │ Played NoteEvents    │
                  │ beat / measure / voice│      │ seconds / confidence │
                  └───────────┬───────────┘      └──────────┬───────────┘
                              └──────────────┬──────────────┘
                                             ▼
                                ┌──────────────────────────┐
                                │ Alignment engine         │
                                │ coarse tempo + DTW       │
                                │ + note/chord assignment  │
                                └────────────┬─────────────┘
                                             ▼
                                ┌──────────────────────────┐
                                │ Error classification     │
                                │ pitch / omission / extra │
                                │ timing / duration        │
                                └────────────┬─────────────┘
                                             ▼
                                ┌──────────────────────────┐
                                │ Scores & recommendations │
                                │ JSON + annotated score   │
                                └────────────┬─────────────┘
                                             ▼
                                ┌──────────────────────────┐
                                │ UI / API                 │
                                │ Streamlit (initial)      │
                                │ FastAPI (optional later) │
                                └──────────────────────────┘
```

**Architectural rule:** All downstream code should consume a normalized note-event schema, not the raw output of a particular library or ML model. This makes it straightforward to swap transcription models.

---

## 4. Recommended tech stack

| Concern | MVP choice | Why / alternatives |
|---|---|---|
| Language | Python 3.11 or a model-compatible supported version | Strong audio/music ecosystem; verify current model dependencies |
| Score parsing | `music21` | Read MusicXML, metadata, measures, pitches, rests, tempo, and voices |
| MIDI I/O | `pretty_midi` | Accessible MIDI note data, timing, velocity |
| Audio loading / DSP | `librosa`, `soundfile`, `numpy`, `scipy` | Loading, waveform processing, onset/pitch features |
| Audio transcription | Piano-specific pretrained model (e.g., `piano-transcription-inference`) | Better starting point for piano polyphony than training from scratch |
| Simple transcription alternative | `basic-pitch` | Useful baseline; compare accuracy on piano chords |
| Alignment | Custom Python + `numpy`/`scipy` | Core project algorithm; optionally `librosa.sequence.dtw` for prototyping |
| Optical music recognition | Audiveris → MusicXML | **Later phase**; OMR is imperfect and requires score correction |
| Backend/API | Local Python functions initially; FastAPI later | Avoid premature service complexity |
| UI | Streamlit first | Fast upload, tables, plots, and audio playback |
| Visualization | Plotly or Matplotlib, later score rendering via Verovio | Interactive piano-roll or notation-linked annotations |
| Testing | `pytest` | Deterministic fixtures and regression testing |
| Packaging / tooling | `venv` and pinned requirements or `pyproject.toml` | Repeatable setup |

Resources (inspect current package compatibility before implementation):
- music21: https://www.music21.org/music21docs/
- pretty_midi: https://github.com/craffel/pretty-midi
- librosa: https://librosa.org/doc/latest/index.html
- Basic Pitch: https://github.com/spotify/basic-pitch
- Piano Transcription Inference: https://github.com/bytedance/piano_transcription
- Audiveris: https://github.com/Audiveris/audiveris
- Streamlit: https://docs.streamlit.io/
- MAESTRO paired piano audio/MIDI dataset: https://magenta.tensorflow.org/datasets/maestro

---

## 5. Canonical data model

### 5.1 Two time systems
The **score** uses *musical beats/quarter lengths*; the **performance** uses *seconds*. Don't compare their raw timestamps directly. Alignment maps score beats to performance seconds.

### 5.2 Note event

```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass(frozen=True)
class NoteEvent:
    id: str
    pitch: int                          # MIDI note number, C4 = 60
    onset: float                       # beats for score; seconds for audio
    duration: float                    # same units as onset
    source: Literal["score", "performance"]
    measure: int | None = None          # score only
    beat_in_measure: float | None = None
    part: str | None = None             # e.g. RH, LH, or part ID
    voice: str | None = None
    velocity: int | None = None         # usually performance only
    confidence: float | None = None     # transcription confidence, if available

@dataclass
class ScoreData:
    notes: list[NoteEvent]
    tempo_changes: list[tuple[float, float]]  # (beat, bpm)
    time_signatures: list[tuple[float, int, int]]
    metadata: dict = field(default_factory=dict)

@dataclass
class PerformanceData:
    notes: list[NoteEvent]
    duration_seconds: float
    source_type: Literal["midi", "audio"]
    metadata: dict = field(default_factory=dict)
```

For chords, represent each constituent pitch as a separate `NoteEvent` with approximately equal onset; optionally also create grouped `OnsetGroup` objects for chord matching. Preserve the original notation's measure, voice, and part mappings.

### 5.3 Matched notes and error records

```python
@dataclass
class NoteMatch:
    score_note_id: str | None
    performance_note_id: str | None
    alignment_cost: float
    onset_error_seconds: float | None
    duration_error_seconds: float | None
    confidence: float

@dataclass
class ErrorEvent:
    category: str                     # wrong_pitch, missing, extra, timing, duration
    severity: str                     # info, warning, high
    score_note_id: str | None
    performance_note_id: str | None
    measure: int | None
    score_beat: float | None
    audio_time: float | None
    expected_pitch: int | None
    actual_pitch: int | None
    evidence_confidence: float
    explanation: str
```

**Implementation note:** Audio transcription tools do not all expose calibrated per-note confidence. Set confidence to `None` when unavailable rather than inventing it; derive any heuristic evidence score separately and label it honestly.

### 5.4 Report shape

```json
{
  "piece": {"title": "Example", "duration_seconds": 34.2},
  "model_versions": {"transcriber": "example-version"},
  "metrics": {"pitch_precision": 0.92, "pitch_recall": 0.89},
  "measures": [{"number": 5, "accuracy": 0.75, "error_ids": ["err-3"]}],
  "errors": [{
    "id": "err-3", "category": "wrong_pitch", "measure": 5,
    "expected_pitch": 64, "actual_pitch": 65, "audio_time": 13.4,
    "evidence_confidence": 0.81,
    "explanation": "Possible F4 played in place of E4"
  }],
  "recommendations": ["Practice measure 5 slowly, hands separately."]
}
```

Values above are **illustrative sample data**, not real analysis results.

---

## 6. Input pipeline A — sheet music

### First version: MusicXML
1. Parse `.musicxml` or `.mxl` with `music21.converter.parse()`.
2. Iterate parts, measures, notes/chords, voices, and tempo/time signature changes.
3. Convert each pitch to MIDI number (`pitch.midi`).
4. Store global offsets in score beats/quarter lengths; preserve measure and beat in measure.
5. Expand chords into note events while retaining grouping metadata.
6. Resolve ties into sustained notes when suitable; preserve articulation and rest information separately.
7. Explicitly handle repeated sections and alternate endings (either expand score playback order or mark unsupported in MVP).

### Later version: PDF / PNG / JPEG
1. Run Audiveris or another OMR engine to produce MusicXML.
2. Validate resulting measures, pitches, clefs, key signatures, accidentals, tuplets, and rhythms.
3. Show the user a preview and allow corrections (especially for scanned scores).
4. Pass the corrected MusicXML through the same parser.

**Important:** PDF-to-MusicXML is its own difficult subproblem. Build the score comparison engine first.

---

## 7. Input pipeline B — recorded performance

### MIDI path (implement first)
1. Load MIDI using `pretty_midi.PrettyMIDI(path)`.
2. Read notes from non-drum instruments.
3. Convert note starts/ends to `NoteEvent` with seconds, pitch, and velocity.
4. Optional: preserve instrument/channel/track to separate hands where available.
5. Use this route as the baseline **ground truth** for testing alignment and grading.

### Audio path (implement second)
1. Decode uploaded WAV (and later MP3) and convert to the transcription model's required sample rate/channels.
2. Normalize safely; avoid aggressive processing that erases quiet piano notes.
3. Transcribe piano audio with a pretrained model to note onsets, offsets, pitches, and optional velocities.
4. Decode model outputs into `NoteEvent`.
5. Run conservative cleanup: merge obvious duplicate detections, remove ultra-short noise notes using configurable thresholds, and retain uncertainties.
6. Keep both the raw transcription and cleaned transcription to aid debugging.

### Main challenges
- Overlapping chord notes and fast runs.
- Sustain pedal causing long tails and ambiguous note offsets.
- Reverberation, background noise, and phone microphone distortion.
- Dynamic range: soft notes may be missed; upper harmonics may create false detections.
- Multiple performances/retakes in one recording.

**Best practical option:** Also offer recording/export from a digital piano as MIDI. This provides reliable note keypress data without relying on audio transcription.

---

## 8. Alignment engine — the hardest original component

A performance may begin after silence, move faster/slower than the printed tempo, pause, or intentionally stretch phrases. Fixed-timestamp comparison will be misleading.

### 8.1 Phase 1: simple baseline
For carefully aligned MIDI fixtures with stable tempo:
1. Estimate a constant seconds-per-beat mapping.
2. For each score note, search unmatched performance notes within a small onset window.
3. Match using weighted pitch difference, onset difference, and duration difference.
4. Classify unmatched score notes as omissions and unmatched performance notes as additions.

**Warning:** Greedy matching fails with repeated pitches/chords and shifted notes. Use it as a baseline only.

### 8.2 Phase 2: tempo and start-offset estimation
- Identify first reliable onsets or estimate an initial offset by matching onset patterns.
- Compare onset-to-onset intervals rather than absolute timestamps.
- Estimate global tempo scaling robustly (e.g., regression on candidate onset pairs).
- Use a wider window for coarse alignment, then narrow it for final note matching.

### 8.3 Phase 3: dynamic time warping (DTW)
1. Turn the score into a sequence of pitch-class/chroma features or onset-group pitch sets indexed by score beat.
2. Turn the performance into comparable features indexed by time.
3. Construct a similarity/cost matrix; nearby pitch sets have low cost.
4. Use DTW with constraints on slope, continuity, and allowable tempo to find a monotonic alignment path.
5. Convert the path into `score_beat -> audio_seconds` mapping.
6. Inspect low-confidence paths or alignment collapses; reject implausible matches.

For recordings with transcription errors, consider computing chroma directly from audio as a second alignment signal; chroma can help even when the MIDI transcription misses notes.

### 8.4 Phase 4: local note/chord matching
After mapping score beat to performance time:
- Group near-simultaneous notes on each side into onset groups.
- For each expected chord, solve a one-to-one assignment against nearby played notes (e.g., Hungarian assignment or dynamic programming).
- Use a composite cost for pitch disagreement, time displacement, duration disagreement, and confidence.
- Allow dummy unmatched nodes for omissions/additions; don't force every note to match.
- Handle repeated notes carefully; one played note must never satisfy multiple score notes.
- Analyze left/right hand independently when trustworthy track/part information exists; otherwise match jointly and assign hand labels cautiously.

### Example matching cost

```text
match_cost = w_pitch * pitch_penalty
           + w_time  * abs(played_onset - aligned_expected_onset)
           + w_dur   * duration_penalty
           + w_conf  * uncertainty_penalty
```

Use robust thresholds and normalize units before summing. Tune weights on labeled examples instead of picking them purely by intuition.

---

## 9. Error classification and metrics

### Errors
| Type | Definition | Pitfall |
|---|---|---|
| Wrong pitch | Aligned onset has a confidently detected pitch different from reference | Chords and transcription harmonics |
| Missing note | Reference note has no plausible matching performed note | Quiet note may be missed by model |
| Extra note | Performed note has no corresponding score note | Echo/transcriber false positive |
| Timing | Matched onset is too early or late relative to estimated local tempo | Rubato can be intentional |
| Duration | Note duration deviates substantially after tempo normalization | Sustain pedal and overlap |
| Tempo instability | Local tempo varies unexpectedly | Expressive playing is not automatically a mistake |
| Dynamics (later) | Velocity/volume contrast deviates from indicated expression | Mic loudness ≠ MIDI key velocity |

### Metrics (report with clear denominators)
- **Pitch precision:** matched correct performed notes / all evaluated performed notes.
- **Pitch recall:** matched correct reference notes / all evaluated reference notes.
- **Pitch F1:** harmonic mean of precision and recall.
- **Onset accuracy:** fraction of matched note onsets within defined timing tolerance.
- **Mean absolute timing error:** average absolute difference after alignment.
- **Measure accuracy:** fraction of evaluated notes correct within a measure; account for uncertain/unscored notes explicitly.
- **Coverage:** share of notes/regions for which the system has enough evidence to grade.

Don't collapse all quality into one arbitrary percentage without documenting weights. Consider separate pitch, rhythm, and overall summaries.

### Confidence and user-facing language
- **High confidence:** “Wrong note: F4 instead of E4.”
- **Medium confidence:** “Possible pitch mistake: check the third note in measure 5.”
- **Low confidence:** “Unable to assess this note reliably.”

A model-detected discrepancy should not automatically be framed as a musician's mistake.

---

## 10. Feedback and recommendations

Start with **deterministic rules**, not an LLM:
- Repeated errors in one measure → recommend isolating that measure.
- Many right-hand wrong pitches → practice right hand separately.
- Timing consistently ahead of beat → use metronome at a reduced BPM.
- Missed notes within dense chords → practice chord voicings and broken-chord drills.
- Passage improves over attempts → recognize the improvement using tracked metrics.

Example feedback:
> “Measure 12 has three likely pitch errors and four rushed attacks. Practice the right-hand run at 70% tempo, then increase speed by 5 BPM after two clean repetitions.”

Only claim which hand is responsible when the score part or performance track supports that attribution. Optionally send structured findings to an LLM to turn them into natural-language explanations; never let it invent score locations or errors. Keep generated text anchored to machine-readable evidence.

---

## 11. Repository structure

```text
piano-coach/
├── README.md
├── pyproject.toml
├── .gitignore
├── config/
│   └── defaults.yaml
├── src/
│   └── piano_coach/
│       ├── __init__.py
│       ├── cli.py                 # command-line entry point
│       ├── models.py              # canonical dataclasses / schemas
│       ├── pipeline.py            # orchestration
│       ├── score/
│       │   ├── parser.py          # MusicXML -> NoteEvent
│       │   ├── midi_loader.py     # reference MIDI -> NoteEvent
│       │   └── omr.py             # PDF -> MusicXML (later)
│       ├── performance/
│       │   ├── midi_loader.py     # performance MIDI -> NoteEvent
│       │   ├── audio.py           # sample rate/decoding
│       │   ├── transcription.py   # model adapter
│       │   └── postprocess.py     # clean note candidates
│       ├── alignment/
│       │   ├── coarse.py          # initial offset/tempo
│       │   ├── dtw.py             # flexible time map
│       │   └── matching.py        # local note assignment
│       ├── evaluation/
│       │   ├── errors.py          # classify discrepancies
│       │   ├── metrics.py         # accuracy/coverage
│       │   └── feedback.py        # rules-based suggestions
│       ├── reporting/
│       │   ├── schema.py          # report JSON structure
│       │   └── export.py          # save reports
│       └── ui/
│           └── streamlit_app.py
├── tests/
│   ├── test_musicxml_parser.py
│   ├── test_note_matching.py
│   ├── test_tempo_alignment.py
│   ├── test_error_classification.py
│   └── fixtures/
│       ├── reference.mid
│       ├── perfect.mid
│       ├── wrong_pitch.mid
│       ├── missing_note.mid
│       └── shifted_tempo.mid
├── scripts/
│   ├── generate_fixtures.py
│   └── benchmark_transcription.py
├── examples/
│   └── sample_report.json
└── docs/
    └── evaluation_methodology.md
```

### Module contracts

```python
parse_score(path: str) -> ScoreData
load_midi_performance(path: str) -> PerformanceData
transcribe_audio(path: str, model_config: dict) -> PerformanceData
align(score: ScoreData, performance: PerformanceData) -> tuple[list[NoteMatch], dict]
evaluate(score: ScoreData, performance: PerformanceData, matches: list[NoteMatch]) -> list[ErrorEvent]
compute_metrics(score, performance, matches, errors) -> dict
recommend_practice(errors: list[ErrorEvent], metrics: dict) -> list[str]
analyze(score_path: str, performance_path: str, config: dict) -> dict
```

Use these as interface designs; implement and type-check the actual signatures once the data model stabilizes.

---

## 12. Example end-to-end CLI

```bash
piano-coach analyze \
  --score samples/score.musicxml \
  --performance samples/performance.wav \
  --output reports/session-001.json
```

```python
# Simplified orchestration pseudocode; adapters below are implemented by you.

def analyze(score_path, performance_path, config):
    score = parse_score(score_path)

    if performance_path.lower().endswith((".mid", ".midi")):
        performance = load_midi_performance(performance_path)
    else:
        performance = transcribe_audio(performance_path, config["model"])

    matches, alignment_metadata = align(score, performance)
    errors = evaluate(score, performance, matches)
    metrics = compute_metrics(score, performance, matches, errors)
    recommendations = recommend_practice(errors, metrics)

    return {
        "alignment": alignment_metadata,
        "metrics": metrics,
        "errors": errors,
        "recommendations": recommendations,
    }
```

`ErrorEvent` objects should be serialized as dictionaries before writing JSON. This example illustrates orchestration rather than drop-in executable code.

---

## 13. Concrete MVP plan and acceptance criteria

### Milestone 0 — setup and fixtures
**Build:** repo, environment, test suite, generator for synthetic MIDI fixtures.  
**Done when:** tests run in one command; fixture generator creates reference, clean, wrong-pitch, missing-note, extra-note, and shifted-tempo performances.

### Milestone 1 — MIDI vs. MIDI comparison
**Build:** MIDI loaders, canonical NoteEvent, baseline match engine, JSON reports.  
**Done when:** synthetic wrong/missing/extra notes are classified correctly; a perfect performance yields no pitch errors; repeated notes cannot be double-matched.

### Milestone 2 — robust temporal alignment
**Build:** start-offset and tempo estimates; DTW or a score-following method.  
**Done when:** changing global playback speed or inserting a moderate pause doesn't create spurious pitch errors on basic test pieces.

### Milestone 3 — MusicXML score support
**Build:** measure-aware parser, chords, tempo changes, ties; mapping to score coordinates.  
**Done when:** a known score aligns with its exported MIDI playback; each detected error maps to a measure and beat.

### Milestone 4 — audio transcription
**Build:** audio loader, pretrained piano-model adapter, note-event postprocessing, uncertainty handling.  
**Done when:** short, clean piano recordings can be graded against a known score, and false positives are explicitly measured against paired ground-truth MIDI.

### Milestone 5 — interactive demo
**Build:** Streamlit uploads, analysis report, per-measure table, piano-roll or score graphic, seekable audio player if feasible.  
**Done when:** another person can run a full analysis without editing Python code.

### Milestone 6 — PDFs and richer feedback
**Build:** OMR adapter with user-visible correction path, more nuanced practice advice.  
**Done when:** at least several clear sheet-music scans are recognized and validated; failed scans produce useful warnings instead of silent grading errors.

---

## 14. Testing and evaluation strategy

### Deterministic synthetic tests
Generate a clean MIDI piece and transform it systematically:
- Substitute C4 with C#4 at a known beat.
- Delete one of four chord notes.
- Add a note that isn't in the score.
- Shift one onset by +250 ms.
- Speed up all note timing by 20%.
- Insert silence at the beginning or pause in the middle.
- Repeat the same pitch several times in a row.
- Create simultaneous notes in both hands.

Each test should assert **which note** is flagged, **which error type**, and **which measure**; not only total accuracy.

### Real piano evaluation
Use a dataset with aligned piano audio and MIDI, such as MAESTRO, plus your own clean and noisy recordings. Evaluate the transcription module separately from the evaluator:
1. Audio transcription vs. paired MIDI note ground truth: note-level precision/recall/F1, onset and offset tolerance.
2. Alignment vs. known score/performance pairs: measure location error, beat-to-second mapping error.
3. Error detector vs. intentional synthetic edits: error type precision/recall and false alert rate.
4. End-to-end: are the user-facing annotations and recommendations actually correct?

**Dataset caution:** paired audio/MIDI performance data do not automatically contain the original printed sheet music; converting a performance MIDI to a reference score may require quantization and manual validation.

### Edge-case test matrix
| Scenario | Expected behavior |
|---|---|
| Recording starts with 3 seconds of silence | Align to first actual notes |
| Player is 25% slower | Do not mark all notes late |
| Player repeats a measure | Warn/handle repeated passage, don't force wrong mapping |
| Sustain pedal held | Avoid overconfident duration errors |
| Three-note chord contains one quiet note | Surface transcription uncertainty |
| PDF OMR misreads a sharp | Allow score correction before grading |
| Missing recording / unreadable audio | Explain failure clearly |
| Very long audio uploaded | Impose file and computation limits |

---

## 15. Known risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Piano transcription hallucinates or misses pitches | Incorrectly accuses user of mistakes | Offer MIDI input, confidence/coverage flags, compare models and evaluate ground truth |
| Complex chords make one-to-one matching ambiguous | Wrong substitutions/additions | Chord-aware alignment and bipartite matching |
| Rubato or tempo drift | Excessive timing errors | DTW and local tempo normalization |
| Printed score has repeats / pickups / alternate endings | Incorrect measure mapping | Track playback order; initially limit support or require excerpt selection |
| OMR misreads notation | False score baseline | Human review/edit MusicXML before grading |
| Sustain pedal alters note offsets | False duration errors | Emphasize onset/pitch for MVP; assess pedaling separately |
| Recording environment impacts dynamics | Poor dynamics scoring | Defer dynamics or use MIDI velocities where available |
| Model packages have platform/version conflicts | Hard setup | Pin versions and test OS/Python combinations; isolate ML adapters |
| Expensive models on laptops | Slow processing | Cache results, analyze short excerpts, allow CPU-friendly model, optional GPU |

---

## 16. Priorities: what NOT to build first

Avoid starting with:
- Training a piano transcription neural network from scratch.
- OCR for arbitrary photographs of crumpled sheet music.
- Live microphone grading with sub-100-ms latency.
- A chat interface before objective comparisons work.
- A single “97% accuracy” metric without labeled tests.
- Fingering/hand identification from audio alone.

All of these are possible later but create unnecessary uncertainty at the start.

---

## 17. Stretch goals

1. **Annotated score view:** render MusicXML using a notation renderer and highlight mistaken noteheads by stable IDs.
2. **Automatic loops:** tap an error and play two bars around the mistake at reduced speed.
3. **Practice-history analytics:** compare multiple takes and detect which measures improved.
4. **Difficulty-aware recommendations:** generate exercises for intervals, arpeggios, or rhythmic patterns that recur as errors.
5. **Pedal analysis:** evaluate pedal-on/off control from MIDI CC64 or specialized audio estimates.
6. **Digital piano MIDI input:** live USB-MIDI sessions; near-perfect keypress logging.
7. **Real-time score following:** rolling note estimation and low-latency alignment.
8. **Teacher dashboard:** share annotated practice reports with a coach, subject to user consent.

---

## 18. First week: exact next actions

1. Create a Python project and install `music21`, `pretty_midi`, `numpy`, `scipy`, `librosa`, `pytest`.
2. Implement `NoteEvent` and `get_notes_from_midi(path)`.
3. Generate two 8–16-note MIDI examples programmatically using `pretty_midi`.
4. Create three intentional mistakes (one substituted note, one removed note, one extra note).
5. Implement a **baseline** note matcher and verify the three mistakes in tests.
6. Add a test where the exact same notes are played 20% slower; improve alignment until this passes.
7. Add MusicXML parsing and verify a score exported from the same reference MIDI.
8. Only then integrate a piano audio transcription model.

### Minimal setup commands

```bash
mkdir piano-coach && cd piano-coach
python3 -m venv .venv
source .venv/bin/activate  # macOS/Linux
python -m pip install --upgrade pip
pip install music21 pretty_midi numpy scipy librosa soundfile pytest streamlit
```

Install transcription packages separately once their Python/platform compatibility is confirmed.

### What makes this project compelling
The project is more than an API wrapper: its technical depth comes from a canonical musical event model, tempo-robust sequence alignment, polyphonic note matching, traceable errors, uncertainty-aware grading, and feedback grounded in measurable mistakes. Building the MIDI-only correctness harness first will make the later ML pipeline significantly more reliable.

---

## 19. Definition of a successful v1

A user can submit **MusicXML + a short solo piano WAV file**, receive a credible **measure-by-measure pitch/rhythm report**, inspect each likely error, and see **specific practice suggestions**. The tool identifies when a judgment is uncertain, and its behavior is validated against known MIDI fixtures and at least one set of real recordings.

**Recommended project strategy:** Quality and explainability first; input formats and visual polish second.
