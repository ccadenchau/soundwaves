# Testing on real performances

`asap_eval.py` runs the whole PianoCoach path (score preparation, alignment, the page adapter with
its repairs) on the [ASAP dataset](https://github.com/fosfrancesco/asap-dataset): MusicXML scores
paired with MIDI performances by competition pianists. The dataset is cloned outside the repo at
`~/Desktop/calhacks/datasets/asap-dataset` (shallow clone, no audio).

Two measurements per performance:

1. **Clean run.** The performance exactly as played. These pianists make very few mistakes, so almost
   everything reported here is a false alarm, a score-edition difference (ASAP scores and
   performances come from different sources), or an ornament the score writes as a symbol.
2. **Planted run.** The same performance with known mistakes planted in the middle 80% (wrong
   pitches a step or two off, deleted notes, inserted neighbouring notes). Findings are scored
   against the plant list by kind, pitch and time. New false alarms are findings beyond those the
   clean run already produced.

```sh
.venv/bin/python testing/datasets/asap_eval.py --asap ~/Desktop/calhacks/datasets/asap-dataset \
    --max-notes 1000 --limit 8 --plant 6 --out testing/datasets/results
```

## Results, 2026-10-24 (seed 7, performances under 1000 notes, final adapter)

| Piece | Performance | Notes | Convert | Align | Raw findings | Page findings | Planted caught | New false alarms |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Bach Fugue bwv 880 | LeungR01M.mid | 984 | 0.0 s | 0.5 s | 59 | 33 | 6/6 | 0 |
| Bach Prelude bwv 885 | JeonH01M.mid | 516 | 0.0 s | 0.2 s | 61 | 45 | 6/6 | 0 |
| Bach Prelude bwv 860 | Tetzloff04M.mid | 612 | 0.0 s | 0.2 s | 21 | 8 | 6/6 | 0 |
| Bach Prelude bwv 854 | Ozaki01M.mid | 443 | 0.0 s | 0.1 s | 46 | 34 | 5/5 | 0 |
| Bach Prelude bwv 860 | ZhangH04M.mid | 608 | 0.0 s | 0.2 s | 12 | 8 | 4/5 | 0 |
| Bach Prelude bwv 889 | YangY02M.mid | 789 | 0.0 s | 0.4 s | 33 | 29 | 6/6 | 0 |
| Bach Prelude bwv 870 | MaximovI01M.mid | 833 | 0.0 s | 0.4 s | 95 | 56 | 6/6 | 0 |

Failed: 1 (Prelude_bwv_876: ValueError: Grace notes are unsupported; resolve their playb).

- Planted mistakes caught: **39/40 (98%)**, **0** new false alarms.
- Findings on error-free playing: 327 raw from the aligner, **213** after the adapter
  (30.4 per performance, down from 46.7). The adapter's repairs that
  earned their place, in order of effect: merging unison and overlapping same-pitch score notes
  (a piano cannot sound one key twice at once), pairing a missing note with a same-pitch extra a few
  tens of milliseconds away (spread chords), re-pairing repeated pitches within a bar by time, tagging
  extras a step away from a correct note as likely ornaments, and collapsing identical findings from
  repeated passes of a bar into one.
- What remains on expert playing is mostly extras between beats (trills written as symbols, re-struck
  pedal notes) and notes where the performer's edition differs from the score. A student playing from
  the exact score shown on the page sees far less of this: on the planted-mistake Minuet take, the
  page shows exactly the planted mistakes.
- Alignment itself takes well under a second for pieces up to about 1000 notes and about 2 s at
  2200 notes; `--max-notes` and `--cells` bound the pure-Python sequence matrix. A second run on
  longer pieces (`results_long/`, seed 11, up to 2500 notes) caught 36/39 planted mistakes with 6
  new false alarms; dense Chopin études produced 150+ clean-run findings, so this tool is for
  beginner and intermediate repertoire.

Known converter limits hit here: scores with grace notes are rejected (`sheet_downloader`), and the
page cannot show time signatures above 16 (24/16 is shown as 6/4).

## Real amateur recordings (Expert-Novice dataset), 2026-10-24

Four amateur takes of *The Entertainer* (42 to 56 s each, laptop-class recordings from Jiang's
Expert-Novice set) through the full audio path: Transkun transcription, cleaning, alignment, adapter,
both hands. Each take analysed in 4.5 to 6.9 s on this MacBook.

| Take | Transcribed notes | Pitch P / R | Page findings | Mix |
| --- | ---: | ---: | ---: | --- |
| 01 | 171 | 0.96 / 0.98 | 9 | 2 missing, 4 extra (an added chord in bar 24), 1 timing, 2 wrong |
| 02 | 167 | 0.95 / 0.94 | 10 | 5 wrong (bass-note substitutions), 5 missing |
| 03 | 169 | 0.96 / 0.96 | 10 | 6 wrong **flagged as octave displacement** (intro played an octave down), 4 timing |
| 04 | 169 | 0.98 / 0.99 | 9 | 8 timing, 1 wrong |

Caveats: the dataset's MusicXML is a simplified arrangement written by the researchers, and the
players clearly used their own arrangements in places (added chords, different bass notes), so some
"wrong" findings are arrangement differences rather than slips. The nominal tempo in those scores is
meaningless (takes read 190 to 270 "quarter notes" per minute); pace is judged against the take's own
median, never the printed tempo. The EN-augmented mistake-region annotations did not line up with the
WAV timeline well enough to score against (they appear to follow the dataset's MIDI, not the audio),
so that comparison is inconclusive.

## Dataset catalog (researched 2026-10-24)

Verified links are ones that answered HTTP 200 during the research pass. NC licences are fine for a
hackathon demo and would matter only if the project were productised.

### Score plus performance, with alignment ground truth

| Dataset | What it has | Alignment labels | Licence | Get it |
| --- | --- | --- | --- | --- |
| [ASAP v1.1](https://github.com/fosfrancesco/asap-dataset) | 236 scores (MusicXML + MIDI), 1067 performance MIDIs, 519 with MAESTRO audio | beat and downbeat only | CC BY-NC-SA 4.0 | `git clone --depth 1` (about 80 MB, no audio). Used by `asap_eval.py`. |
| [(n)ASAP v2.1](https://github.com/CPJKU/asap-dataset) | same pieces plus a `.match` file and `note_alignment.tsv` per performance | **note level** (834 of 1066 marked robust) | CC BY-NC-SA 4.0 | clone (about 333 MB) or fetch single files by raw URL, e.g. `Bach/Prelude/bwv_856/LuoJ01M_note_alignments/note_alignment.tsv`. Parse `.match` with `partitura.load_match`. Best ground truth for the aligner's note matching. |
| [Vienna 4x22](https://github.com/CPJKU/vienna4x22) ([audio at mdw](https://datasets.mdw.ac.at/datasets/dataset/98ea25fa-2468-43ff-929b-3c926e163583)) | 22 pianists × 4 short excerpts (Mozart K331/I bars 1–36, Schubert D783/15, Chopin Op.10/3 and Op.38) with MusicXML, MIDI, match, audio | **note level** | **CC BY 4.0** | raw URLs under `musicxml/`, `midi/`, `match/`. 22 interpretations of one short piece: ideal for rushed/dragged-bar testing. |
| [Batik plays Mozart](https://github.com/huispaty/batik_plays_mozart) | 12 Mozart sonatas, performance MIDI, MusicXML, match files; no audio | note level | CC BY-NC-SA 4.0 | clone with submodules; movements are long (thousands of notes). |
| [MAESTRO v3](https://magenta.tensorflow.org/datasets/maestro) | 1276 expert performances, paired WAV + MIDI, no scores | audio–MIDI synchronous | CC BY-NC-SA 4.0 | [MIDI-only zip, 58 MB](https://storage.googleapis.com/magentadata/datasets/maestro/v3.0.0/maestro-v3.0.0-midi.zip); full audio is one 101 GB zip, **individual files are not fetchable**. |
| [MusicNet](https://zenodo.org/records/5120004) | 330 classical recordings (mostly chamber), note labels from DTW (about 4 % error) | note level | CC BY 4.0 | 11 GB tarball. |
| MAPS | piano audio + MIDI, no scores | audio–MIDI | CC BY-NC-SA 2.0 FR | official page now redirects to a dead URL; effectively unavailable. |

### Amateur playing and labelled mistakes

| Resource | What it has | Mistake labels | Licence | Get it |
| --- | --- | --- | --- | --- |
| [Expert-Novice piano evaluations (Jiang, ISMIR 2023)](https://zenodo.org/records/8392772) | 83 amateur WAV recordings of 7 short pieces, 7 MusicXML scores, 83 audio-to-score alignments, instructor ratings | quality ratings | CC BY-NC-SA 4.0 | 587 MB zip + 30 kB scores. Downloaded to `~/Desktop/calhacks/datasets/expert-novice`. **The only real amateur audio with scores we can get in minutes.** |
| [EN-augmented-data (Hugging Face)](https://huggingface.co/datasets/anusfoil/EN-augmented-data) | the same 7 songs as MIDI, 83 performances + 34 `-annot.mid` | mistake **regions** as pitch-0 notes | CC BY 4.0 | 183 kB. *The Entertainer* has all 8 performances annotated. |
| [scoreinformed-midi (Hugging Face)](https://huggingface.co/datasets/anusfoil/scoreinformed-midi) | 7 Disklavier performances of ABRSM grade 1–2 pieces as `_correct`, `_missed`, `_fa` MIDI triples | **exact wrong / missing / extra notes** | CC BY 4.0 | tiny. Exact-label test of the aligner. Original QMUL WAVs were unreachable. |
| [Burgmüller set, Morsi et al. ISMIR 2023](https://sites.google.com/view/ismir2023-conspicuous-error) | 50 performances of Burgmüller Op.100 études with conspicuous-mistake regions | regions | CC BY-NC-SA 4.0 | Google Drive folder (needs login). Scores for Op.100 Nos. 1–18 are on Mutopia. |
| [SynMist (SMC 2024)](https://github.com/Alia-morsi/piano-synmist) | scripts that inject taxonomic mistakes (insertion, mistouch, pitch change, drag) into clean MIDI | known injections | see repo | use git tag `smc_2024`; a richer version of what `plant_mistakes()` does here. |
| [MAESTRO-E / LadderSym](https://huggingface.co/datasets/ben2002chou/MAESTRO-E) | synthetic errors on MAESTRO audio | note level | CC BY 4.0 | 199 GB; use the published numbers as a yardstick instead (LadderSym F1: correct 90, missed 56, extra 86). |

### Public-domain scores for beginner pieces

- **Minuet in G, BWV Anh. 114**: [MuseTrainer MXL](https://musetrainer.github.io/library/scores/Bach_Minuet_in_G_Major_BWV_Anh._114.mxl) (public domain, 32 bars, 2 staves) — now `pianocoach/pieces/minuet_in_g.mxl`. Mutopia has only `.ly/.mid/.pdf` ([dir](https://www.mutopiaproject.org/ftp/BachJS/BWVAnh114/anna-magdalena-04/)); IMSLP has PDFs and no MusicXML; the music21 corpus has nothing from the Anna Magdalena notebook.
- Für Elise: [Mutopia MIDI](https://www.mutopiaproject.org/ftp/BeethovenLv/WoO59/fur_Elise_WoO59/fur_Elise_WoO59.mid); MuseTrainer lists `Fur_Elise.mxl`.
- Clementi Sonatina Op.36/1: [Mutopia MIDI zip](https://www.mutopiaproject.org/ftp/ClementiM/O36/sonatina-1/sonatina-1-mids.zip).
- Burgmüller Op.100 Nos. 1–18: [Mutopia](https://www.mutopiaproject.org/ftp/BurgmullerJFF/O100/25EF-01/25EF-01.mid) (one dir per étude).
- Bach Prelude in C BWV 846: music21 corpus `bach/bwv846` (local), [Mutopia MIDI](https://www.mutopiaproject.org/ftp/BachJS/BWV846/wtk1-prelude1/wtk1-prelude1.mid).
- Satie Gymnopédie 1: [Mutopia MIDI](https://www.mutopiaproject.org/ftp/SatieE/gymnopedie_1/gymnopedie_1.mid); MuseTrainer `Erik_Satie_-_Gymnopedie_No.1.mxl`.

### Transcription models (upgrade path from Basic Pitch)

| Model | Licence / framework | MAESTRO note F1 (onset / onset+offset) | On this Mac (60 s of audio) | Notes |
| --- | --- | --- | --- | --- |
| Basic Pitch 0.4 (current) | Apache-2.0, ONNX | 0.71 / 0.11 (paper) | 1.0 s | octave ghosts on synthetic tones (P 0.41); clean on sampled piano in our test |
| [Transkun v2](https://github.com/Yujia-Yan/Transkun) | MIT, PyTorch, `pip install transkun` | **0.983 / 0.935** | **9.5 s on MPS**, 27 s CPU | highest published; weights in the wheel; needs Python 3.12 and `setuptools<80`. Installed in `.venv-transkun`. |
| [ByteDance high-res CRNN](https://github.com/bytedance/piano_transcription) | Apache-2.0, PyTorch | 0.967 / 0.825 | 14.6 s CPU, 22.8 s MPS | 172 MB checkpoint; hosted on [Replicate](https://replicate.com/bytedance/piano-transcription) at about $0.08 per run |
| [hFT-Transformer](https://github.com/sony/hFT-Transformer) | MIT, PyTorch | 0.974 / 0.905 | not measured | no simple CLI |
| Onsets and Frames | Apache-2.0, TF1 | 0.953 / 0.805 | not practical on Python 3.14 | archived Jan 2026 |

GPU rental is only worth it for batch evaluation (Modal T4 $0.59/h, RunPod 4090 from $0.34/h, Lambda A10 $1.29/h); the demo should stay local.
