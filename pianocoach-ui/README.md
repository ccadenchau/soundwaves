# PianoCoach frontend

A local practice screen with an annotated score, one finding at a time, and playback controls. One HTML file; no build step or external assets.

## File layout

```text
pianocoach-ui/
  index.html                 Standalone report viewer (embedded CSS, JS, and sample report)
  practice/                  Live practice page, styles, audio worklet, matching, and demo
  replay/                    Falling-note keyboard replay page
  shared/                    Site-wide stylesheet
  fixtures/                  Sample report JSON
  tests/                     Node tests for matching, streaming, and demo behavior
```

The Flask backend serves `/practice`, `/practice-assets/<filename>`, `/falling`, and `/site.css` from these folders. Live practice requires Flask; the static server below serves the standalone report viewer.

Run frontend tests from the repository root with `node --test pianocoach-ui/tests/*.test.cjs`.

## Run

From this directory:

```sh
python3 -m http.server 8765 --bind 127.0.0.1
```

Open http://127.0.0.1:8765. The default is explicitly labeled **Sample take · synthesized playback**. Its notes and findings come from the embedded report. Playback is synthesized from those notes; it is not a recording or a live analysis.

Click a marked note or a numbered finding. Loop its bar, switch between the take and the score, or slow playback to 0.7×. Dismissing a finding changes the local review count; it does not change the performance audio. Space plays or pauses; arrows move through findings; Escape closes the finding. The playback slider supports arrows, Home, and End.

The score is one continuous horizontal staff on every screen size. It follows the playhead during playback and stays still when paused, allowing manual scrolling. Selecting a finding pauses playback and reveals its note; looping its bar resumes following. Focus the score and use arrows, Home, or End to browse. On a narrow screen, selecting a note also scrolls to its feedback.

## Connect the team's report

The existing `fixtures/sample_report.json` contract is unchanged. The frontend does not determine correctness.

Reports can also include an optional `dynamics` object and a `note_detail` array from the backend. When velocity data is available, the page shows bar-level feedback for relative loudness and whether a marked crescendo or decrescendo was followed. The baseline is the average velocity of correctly matched notes in the take, so feedback describes relative dynamics within the performance; audio velocity estimates are not calibrated sound-pressure measurements. `note_detail` adds onset offsets, played-to-score note lengths, and relative dynamics for each matched note. Older reports without these fields continue to load unchanged.

The report includes a five-part pianist’s musicality guide: tone and touch, voicing, phrasing, articulation, and active listening. Timing, dynamics, and note-length measurements appear where the performance data supports them. Green note rings mark matched notes without a flagged issue; red marks show places to review. When available, printed `p`/`f` marks and crescendo/decrescendo wedges appear below the score staff, with followed shapes in green and flagged dynamics in red. The other prompts help the player listen for tone color, hand balance, decay, and pedal use, which the current transcription does not reliably score.

- Replace the JSON inside `<script id="report">` for a server-rendered initial report.
- Or call `window.PianoCoach.loadReport(report, optionalAudioFile)` after fetching a report. The second argument is an optional browser `File` or `Blob` containing playable audio.
- Or use **Open report** to select a JSON report and an optional WAV/MP3 recording. Files stay in the browser. Nothing is uploaded by this page.

```js
const response = await fetch('/api/report');
if (!response.ok) throw new Error('Could not load the report');
window.PianoCoach.loadReport(await response.json());
```

`loadReport` validates the report before replacing the current session and throws an error for invalid input. The file picker shows that error inline. Reloading returns to the embedded sample; imports and dismissed findings are not saved.

## Current limits

The page uses the original small SVG engraver for the supplied right-hand notes. Full notation, multiple staves, and variable time signatures need the team's MusicXML/Verovio integration. There is no recording capture, transcription, analysis request, or Claude call here.

A supplied recording plays as real audio. The current recording playhead and bar loops use proportional time across the score, so rubato or lead-in silence needs an alignment map from the backend for precise loops. Synthesized playback uses the report's tempo and note-level differences.

## Design references

The redesign uses a dark teal music stage, bold system type, and smoked-glass transport controls. The score remains a solid, readable content surface. The header contains only the piece title and report import. The C4–C6 keyboard plays synthesized notes and lights up during synthesized playback; it does not claim to detect pitches from an uploaded recording.

Glass is limited to controls and finding navigation, with defined edges, subtle pointer highlights, restrained press motion, and reduced-transparency/reduced-motion support. This is a CSS interpretation of Apple’s guidance, not Apple’s native Liquid Glass renderer.

- [Apple Materials HIG](https://developer.apple.com/design/human-interface-guidelines/materials) and [Meet Liquid Glass, WWDC25](https://developer.apple.com/videos/play/wwdc2025/219/): functional layer above content, legibility, responsive highlights, and no stacked glass.
- [Apple Logic Pro](https://www.apple.com/logic-pro/) and [Teenage Engineering OP–1](https://teenage.engineering/products/op-1): music-first work areas and compact instrument controls.
- [Duet, Cal Hacks 11.0](https://devpost.com/software/duet-0tbkxe) and [FaceTimeOS, Cal Hacks 12.0](https://devpost.com/software/facetime-macos-ai-agent): focused, visible core interactions.
- [No AI Slop](https://github.com/petergyang/no-ai-slop): plain, specific copy.

This folder remains separate from the shared backend repository. No new dependencies are required.
