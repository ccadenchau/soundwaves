# Pitch, demo video and demo-day checklist

Format from the Devpost page: 3 minutes to pitch, 2 minutes of questions, live or recorded demo required. Judging criteria, in their words: Application, Intentionality, Functionality, Creativity, Technical Complexity. The live demo is most of the score. Rehearse it twice before judging opens.

## The 3-minute pitch

**0:00 – 0:20. The problem, one person.**
"I taught myself piano. I could read the notes and I could hear something was wrong, but I couldn't tell *what*, so I'd play the page again and make the same mistake in the same bar. A teacher fixes that in ten seconds. A teacher is also sixty dollars an hour."

**0:20 – 0:35. The sentence.**
"PianoCoach is the teacher sitting next to you. You play from your own sheet music, and every note turns green or red on the score while you play. When you stop, it writes you the notes a teacher would."

**0:35 – 2:05. Live demo. Talk over it, don't narrate the UI.**
1. Piece is already selected, Start at bar 1, microphone. Press Start.
2. Teammate plays the first 8 to 12 bars of the Mozart. Make one deliberate mistake around bar 4 or 5 (a wrong key is best: red note plus the purple key you played). Keep playing.
3. Point at: the cursor following, notes going green, the red note with the purple "what you played", the line that appears on the right ("Bar 5 · wrong key. The score has F4; you played E4."). If the voice is on with headphones, let the judges hear one line.
4. Press Stop. "Now the whole take gets checked again with the accurate model." The review opens in about ten seconds.
5. Point at: the one-line summary, the teacher's notes (read one focus area aloud, it names the bar and gives a drill), the coloured score, the "Practise from bar 9 live" button. Click it. "Play, review, practise the hard bars, play again. That's the loop."

**2:05 – 2:40. Why it's hard, in two breaths.**
"Audio transcription is never perfect, and every slip looks like a student mistake. We built an evaluation on hand-labelled student recordings and real concert audio with living-room noise, and wrote the repairs that tell a transcription slip from a wrong key: overtones, an octave-up left hand, split chords, where the take actually ends. 190 of 191 real mistakes caught, 98% of flags real. Live, the fast model only moves the cursor; every coloured mark comes from the accurate model re-run on a sliding window, and a mark is only shown when two passes agree."

**2:40 – 3:00. Who it's for, and close.**
"Anyone with sheet music and a laptop. No teacher, no special keyboard, a PDF off the internet works. We'd love you to play something."

## Likely questions, short answers

- *Does it work on a real piano or only MIDI?* Microphone, real piano. MIDI is also accepted on the review path. (Be honest: tested most on recordings and Disklavier audio; demo it on the real thing.)
- *How accurate is it?* Numbers above; the detail is in `testing/datasets/README.md`. Live is about two seconds behind by design.
- *What's the AI doing?* Two things only: Transkun turns sound into notes, and Claude writes the teacher's notes from the structured comparison (Gemini explains single notes). The comparison itself is our alignment and repair code. The model never decides what was wrong.
- *What about a noisy room?* Quiet room 98 to 99% real flags; with conversation at 20 dB still 95%; it degrades past that and the review says so.
- *Why not a MIDI keyboard?* Most learners have an acoustic or a cheap digital piano and a phone. Audio is the hard, useful version.
- *Can I use my own sheet music?* Yes, Add a piece takes PDF or MusicXML. PDFs take a minute the first time.
- *What breaks?* Repeats and jumps in the score, very fast ornaments, a second instrument in the room.

## Demo video (3 minutes or less)

Record with QuickTime or Loom at 1440 × 900 or larger, system audio on, one take if possible. No slides. Captions over the footage are fine.

| Time | Shot | Say |
| --- | --- | --- |
| 0:00 | Someone at the piano with a printed score, phone or laptop on the stand | the problem, two sentences |
| 0:15 | Home page, click Play live | "You play from your own sheet music." |
| 0:25 | Live page: press Start, play 8 bars with one wrong key | let it run, point out green, red, purple, the feed line |
| 1:15 | Press Stop, the review opens | summary line, teacher notes, one focus area read aloud |
| 1:50 | Click a red note on the score, hear that moment; scroll the bar table | "Every mark is clickable." |
| 2:10 | Click "Practise from bar N live", it opens at that bar | "That's the loop." |
| 2:25 | Add a piece: drop a PDF, it converts, pick it | "Any sheet music." |
| 2:45 | Repo and numbers on screen for five seconds | one line on accuracy, team names |

If the microphone take in the video is messy, record that section with "A recording, played as if live" and say so in a caption. Don't fake it.

## Demo-day checklist

**Tonight**
- Repo public. Devpost filled (`docs/devpost.md`). Video uploaded. Submit by 8:00.
- `.env` has `ANTHROPIC_API_KEY` (teacher notes by Claude) and `GEMINI_API_KEY` (explanations, fallback).
- Open `/live` once with the demo piece so the score and Transkun are warm. Open `/report/<last id>` once so the teacher notes are cached.
- Charge the laptop. Download nothing new.

**At the table**
- Keyboard or piano close to the laptop microphone, lid mic facing the keys. Room check: play four bars, confirm green.
- Headphones plugged in if the spoken coach is on; otherwise leave it off in microphone mode (the voice would be heard as notes).
- The fallback is one click away: "A recording, played as if live" with `betteraudio.mp3`. Same pipeline, no microphone. Use it if the room is loud.
- Start at bar 1. If the player wants to show the loop, "Practise from bar 9 live" is the second demo.
- Hacker's Choice is a vote by other hackers: invite people to play. A piano at a table draws a crowd.
- One person talks, one person plays, one person watches the screen for the moment to point at.
