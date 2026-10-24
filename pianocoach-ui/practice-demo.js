/* A deterministic, audible example derived from the selected score.
 * beat/duration use quarter notes; time/length and the top-level duration use
 * seconds. Changes describe the authored example, not microphone detections.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PracticeDemo = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const sameBeat = (a, b) => Math.abs(a - b) < 1e-5;
  const BPM = 104, LEAD_IN = .7, TAIL = .6;

  function build(score) {
    if (!score || !Array.isArray(score.notes) || !score.notes.length) throw new TypeError('Choose a score with notes to play the demo.');
    const ids = new Set();
    const source = score.notes.map(note => {
      if (!note || typeof note.id !== 'string' || !note.id || ids.has(note.id) ||
          !Number.isInteger(note.pitch) || note.pitch < 0 || note.pitch > 127 ||
          !finite(note.beat) || note.beat < 0 || !finite(note.duration) || note.duration <= 0 ||
          !Number.isInteger(note.measure) || note.measure < 1) {
        throw new TypeError('Demo score notes need unique IDs, valid pitches, beats, durations, and measures.');
      }
      ids.add(note.id);
      return {...note};
    }).sort((a, b) => a.beat - b.beat || a.pitch - b.pitch);

    let startBeat, endBeat, measures;
    if (score.bars !== undefined) {
      if (!Array.isArray(score.bars) || !score.bars.length) throw new TypeError('Score bars must be a nonempty list.');
      const bars = score.bars.slice().sort((a, b) => a.startBeat - b.startBeat);
      for (let index = 0; index < bars.length; index++) {
        const bar = bars[index];
        if (!bar || !finite(bar.startBeat) || bar.startBeat < 0 || !finite(bar.endBeat) || bar.endBeat <= bar.startBeat ||
            !Number.isInteger(bar.measure) || bar.measure < 1 || index > 0 && bar.startBeat < bars[index - 1].endBeat - 1e-5) {
          throw new TypeError('Score bars need ordered, nonoverlapping beat ranges and measure numbers.');
        }
      }
      const first = bars.slice(0, 8);
      startBeat = first[0].startBeat;
      endBeat = first[first.length - 1].endBeat;
      measures = new Set(first.map(bar => bar.measure));
    } else {
      const ordered = [...new Set(source.map(note => note.measure))];
      measures = new Set(ordered.slice(0, 8));
      const chosen = source.filter(note => measures.has(note.measure));
      startBeat = chosen[0].beat;
      const following = source.find(note => !measures.has(note.measure));
      endBeat = following ? following.beat : Math.max(...chosen.map(note => note.beat + note.duration));
    }
    const phrase = source.filter(note => measures.has(note.measure) && note.beat >= startBeat && note.beat < endBeat);
    if (!phrase.length) throw new TypeError('The opening bars contain no playable notes.');
    const changes = [];
    const onsets = [...new Set(phrase.map(note => note.beat))];
    const supported = note => onsets.filter(beat => beat > note.beat + 1e-5).length >= 2;
    const right = measure => phrase.filter(note => note.hand === 'right' && note.measure === measure && supported(note))
      .sort((a, b) => a.beat - b.beat || b.pitch - a.pitch);
    const pitchChange = (measure, delta, preferredPitch) => {
      const candidates = right(measure);
      if (preferredPitch !== undefined) candidates.sort((a, b) => Number(b.pitch === preferredPitch) - Number(a.pitch === preferredPitch));
      for (const note of candidates) {
        const actual = note.pitch + delta;
        if (actual < 0 || actual > 127) continue;
        // A substituted pitch that belongs to a nearby real onset is ambiguous
        // to an online follower. Pick another eligible note, not a fake verdict.
        const next = onsets.filter(beat => beat >= note.beat - 1e-5).slice(0, 6);
        if (phrase.some(other => other.id !== note.id && next.some(beat => sameBeat(beat, other.beat)) && other.pitch === actual)) continue;
        changes.push({id: note.id, expected: note.pitch, actual, kind: 'pitch', measure: note.measure,
          beat: note.beat, beatInMeasure: note.beatInMeasure});
        return;
      }
    };
    pitchChange(2, 1);
    pitchChange(3, -1, 78); // Prefer the Minuet's F♯5 → F5 when present.
    const omitted = right(5).find(note => !phrase.some(other => other.id !== note.id && sameBeat(other.beat, note.beat) && other.pitch === note.pitch));
    if (omitted) changes.push({id: omitted.id, expected: omitted.pitch, kind: 'missing', measure: omitted.measure,
      beat: omitted.beat, beatInMeasure: omitted.beatInMeasure});
    changes.sort((a, b) => a.beat - b.beat);
    const alterations = new Map(changes.map(change => [change.id, change]));
    const secondsPerBeat = 60 / BPM;
    const notes = phrase.filter(note => alterations.get(note.id)?.kind !== 'missing').map(note => {
      const duration = Math.min(note.duration, endBeat - note.beat);
      return {...note, pitch: alterations.get(note.id)?.actual ?? note.pitch, duration,
        velocity: note.hand === 'left' ? 65 : 92,
        time: LEAD_IN + (note.beat - startBeat) * secondsPerBeat,
        length: duration * secondsPerBeat * .95};
    });
    return {notes, duration: LEAD_IN + (endBeat - startBeat) * secondsPerBeat + TAIL,
      changes, bpm: BPM, leadIn: LEAD_IN, tail: TAIL, startBeat, endBeat};
  }
  return {build};
});
