# Devpost submission draft

Copy each section into the Devpost form. Fill the bracketed bits. Keep the voice: a student wrote this.

**Project name:** PianoCoach

**Tagline (60 chars):** Play from your sheet music. Every note checked, live.

**Prize categories to opt into:** Cal Hacks First/Second/Third Overall, Most Technically Complex Hack, Most Creative Hack, Best People-First Social Impact Hack, Hacker's Choice, [Best Beginner Hack if everyone on the team qualifies], [Anthropic] Claude for Public Benefit, [MLH] Best Use of Gemini API, [MLH] Commit Fellowship (also submit their supplemental form), [Microsoft] Built for the Real World.

---

## Inspiration

Two of us learned piano without a teacher. You can read the notes, you can hear that something is off, but you can't tell *what* is off, so you play the whole page again and make the same mistake in the same bar. A lesson a week costs more than most students can spend. We wanted the thing a teacher actually does in a lesson: sit next to you, watch the score while you play, and say "bar 9, left hand, you skipped the C".

## What it does

You upload the sheet music you practise from (PDF or MusicXML) and press Start. While you play, the engraved score lights up about two seconds behind your hands: green for right notes, red where you hit a different key (with the key you did play drawn in purple), orange for notes you skipped, purple for extra notes. A list on the side says it in words, a bar table fills in with your tempo against the written one, and if you turn the voice on the coach says it out loud so you can keep your eyes on the keys.

When you stop, the whole take is checked again with the accurate transcriber and you get a review: a one-line summary, teacher's notes with what went well and what to work on by bar, the coloured score you can click to hear any moment, and a keyboard replay. Every focus area has a button that drops you back into live mode from that bar. Play, review, practise the hard bars, play again.

You can also upload a recording from your phone with its sheet music and get the same review.

## How we built it

Sheet music: Audiveris reads the PDF, music21 turns the MusicXML into notes with bars, beats, hands and tempo, and a repair pass fixes grace notes, conflicting tempo marks and broken exports. 235 of 235 scores in our test set convert.

Playing: Transkun v2 (a piano transcription model) runs as a persistent worker on the Mac's GPU and turns audio into notes with onsets and velocities. Basic Pitch is the fallback and the quick layer that moves the cursor.

Comparison: a monotone sequence alignment pairs score notes with played notes, then a set of repairs we wrote by watching real student takes fail: same-pitch re-pairing, split chord notes, runs played a step off, right note in the wrong octave, quiet room noise, partial takes, and finding where a take really ends so unplayed bars aren't marked as skipped. Each bar gets its own robust tempo fit.

Live: the browser streams raw audio to a rolling session that re-transcribes the last six seconds and re-aligns the whole take so far every 1.3 s. A mistake is shown once two passes agree, settled marks are locked, and the player's position is tracked from timing so the aligner can't jump ahead.

Feedback: Claude (Opus) writes the teacher's notes from the structured findings; Gemini writes the per-note explanations on the detailed review and is the fallback for the notes. The models never hear the audio and never decide what was right.

Everything is Python and Flask on the back, plain HTML and JavaScript on the front, Verovio for engraving.

## Challenges we ran into

Audio transcription is good but not perfect, and every transcription slip looks like a student mistake. Most of our time went into telling the two apart: overtones that aren't keys, a left hand played an octave up, chord notes that land a few milliseconds apart and get split. We built an evaluation on hand-labelled student recordings (95 skipped notes, 96 extra notes) and real MAESTRO concert audio with living-room noise mixed in, and only kept a rule when the numbers moved.

Live was its own problem. The fast model that keeps up with playing gets a third of its mistake calls wrong on a microphone, which is useless as feedback. So the fast layer only moves the cursor, and every coloured mark comes from the accurate model re-run on a sliding window, two seconds behind. The first version repainted notes as later passes changed their mind; locking settled marks and requiring two passes to agree fixed that.

A short take of a long piece used to come back covered in orange: the pitch-only aligner would pin a few stray notes to similar bars near the end and everything in between read as skipped. We now find the end of the take from the tempo of its last solid bars.

## Accomplishments that we're proud of

On hand-labelled student recordings, 190 of 191 real mistakes are caught and 98 to 99% of what we flag is real. On expert performances with planted mistakes, 39 of 40 are found with no new false alarms. Live marks on our test clip agree with the final report on 245 of 247 notes. And it works on a PDF someone pulled off the internet ten minutes ago.

## What we learned

Build the evaluation before the feature. Every repair that felt obviously right and wasn't measured made something else worse. And a model's job here is to explain, not to judge: the moment we let a language model decide which notes were wrong, it was confidently wrong.

## What's next for PianoCoach

Fingering hints from the score, hands-separately mode, a history of takes so you can see a bar go from red to green over a week, and running the transcriber in the browser so it works on a phone next to the piano.

## Built with

python, flask, music21, audiveris, transkun, basic-pitch, pytorch, numpy, verovio, web-audio, anthropic, claude, gemini, javascript

---

## Submission checklist (deadline Sun 9:00 AM PDT)

- [ ] Repository public (it is private right now; the owner has to flip it in GitHub settings)
- [ ] Demo video uploaded (3 minutes or less, see `docs/pitch.md` for the shot list)
- [ ] Project image: a screenshot of the live page mid-take with red and green on the score
- [ ] Prize categories ticked (list at the top of this file)
- [ ] Commit Fellowship supplemental form, if opting in
- [ ] Team members added on Devpost
- [ ] Submit by about 8:00 AM, not 8:59
