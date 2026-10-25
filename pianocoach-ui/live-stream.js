/* Merge overlapping microphone detections into ordered note attacks.
 * Input onsets/durations and window start/end are seconds. Only actual emitted
 * attacks advance the frontier; a quiet or inconclusive window never does.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LiveNoteStream = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const finite = value => typeof value === 'number' && Number.isFinite(value);

  // Maximize one-to-one matches, then minimize onset drift. Independent nearest
  // neighbors can merge two fast repetitions into one old attack.
  function pairDetections(records, detections, tolerance) {
    const rows = records.length + 1, cols = detections.length + 1;
    const cells = Array.from({length: rows}, () => Array.from({length: cols}, () => ({count: 0, cost: 0, move: ''})));
    const better = (a, b) => a.count > b.count || a.count === b.count && a.cost < b.cost;
    for (let i = 1; i < rows; i++) for (let j = 1; j < cols; j++) {
      let best = {...cells[i - 1][j], move: 'record'};
      const skip = {...cells[i][j - 1], move: 'detection'};
      if (better(skip, best)) best = skip;
      const distance = Math.abs(records[i - 1].matchTime - detections[j - 1].time);
      if (distance <= tolerance + 1e-8) {
        const prior = cells[i - 1][j - 1];
        const match = {count: prior.count + 1, cost: prior.cost + distance, move: 'pair'};
        if (better(match, best)) best = match;
      }
      cells[i][j] = best;
    }
    const pairs = new Map();
    let i = rows - 1, j = cols - 1;
    while (i && j) {
      const move = cells[i][j].move;
      if (move === 'pair') { pairs.set(detections[j - 1], records[i - 1]); i--; j--; }
      else if (move === 'record') i--;
      else j--;
    }
    return pairs;
  }

  class LiveNoteStream {
    constructor(options = {}) {
      this.edgeHold = options.edgeHold ?? .10;
      this.leftEdge = options.leftEdge ?? .12;
      this.dedupTolerance = options.dedupTolerance ?? .09;
      this.chordGrace = options.chordGrace ?? .06;
      for (const value of [this.edgeHold, this.leftEdge, this.dedupTolerance, this.chordGrace]) {
        if (!finite(value) || value < 0) throw new TypeError('Stream tolerances must be nonnegative seconds.');
      }
      this.history = [];
      this.lastDelivered = -Infinity;
      this.lastWindowEnd = -Infinity;
    }

    ingest(notes, window) {
      if (!Array.isArray(notes) || !window || !finite(window.start) || !finite(window.end) || window.start < 0 || window.end <= window.start) {
        throw new TypeError('ingest requires notes and a valid start/end window in seconds.');
      }
      const {start, end} = window;
      const stale = end < this.lastWindowEnd - 1e-8;
      const detections = notes.map(note => {
        const duration = note?.duration ?? .08;
        if (!note || !Number.isInteger(note.pitch) || note.pitch < 0 || note.pitch > 127 ||
            !finite(note.onset) || note.onset < 0 || !finite(duration) || duration <= 0 ||
            (note.velocity !== undefined && (!finite(note.velocity) || note.velocity < 0 || note.velocity > 127))) {
          throw new TypeError('Detections need a MIDI pitch, nonnegative onset, positive duration, and valid velocity.');
        }
        return {pitch: note.pitch, time: start + note.onset, duration, velocity: note.velocity ?? 80};
      }).filter(note => note.time < end && note.velocity > 0).sort((a, b) => a.time - b.time || a.pitch - b.pitch);
      const events = [], late = [], candidates = [];
      for (const detection of detections) {
        // A held key may look like a new attack where a rolling window begins.
        // Boundary fragments can extend an existing sustain, but never emit.
        if (start > 0 && detection.time - start < this.leftEdge) {
          const sustain = this.history.filter(record => record.pitch === detection.pitch &&
            record.time <= detection.time && record.end >= start - this.dedupTolerance)
            .sort((a, b) => b.time - a.time)[0];
          if (sustain) {
            sustain.end = Math.max(sustain.end, detection.time + detection.duration);
            sustain.lastSeen = Math.max(sustain.lastSeen, end);
          }
          continue;
        }
        // Ignore byte-for-byte duplicate rows within a response, but retain
        // separate onsets of the same pitch, even when less than .09 s apart.
        if (candidates.some(note => note.pitch === detection.pitch && Math.abs(note.time - detection.time) < 1e-7)) continue;
        candidates.push(detection);
      }
      const assignments = new Map();
      for (const pitch of new Set(candidates.map(note => note.pitch))) {
        const records = this.history.filter(record => record.pitch === pitch).sort((a, b) => a.matchTime - b.matchTime);
        const samePitch = candidates.filter(note => note.pitch === pitch);
        for (const [detection, record] of pairDetections(records, samePitch, this.dedupTolerance)) assignments.set(detection, record);
      }
      const frontier = this.lastDelivered;
      for (const detection of candidates) {
        let record = assignments.get(detection);
        if (record) {
          record.matchTime = record.matchTime * .5 + detection.time * .5;
          record.end = Math.max(record.end, detection.time + detection.duration);
          record.lastSeen = Math.max(record.lastSeen, end);
          if (record.state !== 'pending') continue;
        } else {
          record = {pitch: detection.pitch, time: detection.time, matchTime: detection.time,
            end: detection.time + detection.duration, velocity: detection.velocity,
            lastSeen: end, state: 'pending'};
          this.history.push(record);
        }
        // A right-edge detection stays pending until it is observed with enough
        // following audio. Do not flush it merely because a later window is empty.
        if (detection.time > end - this.edgeHold + 1e-8) continue;
        const event = {pitch: record.pitch, time: record.time,
          velocity: detection.velocity, duration: Math.max(detection.duration, record.end - record.time)};
        if (stale || event.time < frontier - this.chordGrace - 1e-8) {
          record.state = 'late';
          late.push(event);
        } else {
          record.state = 'delivered';
          events.push(event);
          this.lastDelivered = Math.max(this.lastDelivered, event.time);
        }
      }
      this.lastWindowEnd = Math.max(this.lastWindowEnd, end);
      this.history = this.history.filter(record => record.lastSeen >= this.lastWindowEnd - 6);
      events.sort((a, b) => a.time - b.time || a.pitch - b.pitch);
      late.sort((a, b) => a.time - b.time || a.pitch - b.pitch);
      return {events, late};
    }
  }
  return LiveNoteStream;
});
