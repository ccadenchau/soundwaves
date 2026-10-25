/* A conservative online score follower. Times are seconds; score beats are quarter notes.
 * feed() returns incremental score-mark updates and this call's played notes.
 * It does not grade timing, infer notes from silence, or replace the final alignment.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.LiveScoreFollower = factory();
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';

  const finite = value => typeof value === 'number' && Number.isFinite(value);
  const midi = value => Number.isInteger(value) && value >= 0 && value <= 127;

  class LiveScoreFollower {
    constructor(scoreNotes, options = {}) {
      if (!Array.isArray(scoreNotes) || !scoreNotes.length) throw new TypeError('A nonempty score note list is required.');
      const bpm = options.bpm === undefined ? 120 : options.bpm;
      if (!finite(bpm) || bpm <= 0) throw new TypeError('Score tempo must be positive.');
      this.input = options.input || 'midi';
      // How many onsets ahead a skip may land. Microphone detections include stray notes that can
      // match a later onset by chance, so the microphone looks less far ahead than a keyboard.
      this.lookahead = options.lookahead ?? (this.input === 'mic' ? 2 : 5);
      if (!['midi', 'mic'].includes(this.input)) throw new TypeError('Input must be midi or mic.');
      const ids = new Set();
      this.notes = scoreNotes.map(note => {
        if (!note || typeof note.id !== 'string' || !note.id || ids.has(note.id) || !midi(note.pitch) ||
            !finite(note.beat) || note.beat < 0 || !finite(note.duration) || note.duration <= 0) {
          throw new TypeError('Score notes need unique IDs, MIDI pitches, nonnegative beats, and positive durations.');
        }
        ids.add(note.id);
        return {...note};
      }).sort((a, b) => a.beat - b.beat || a.pitch - b.pitch);
      this.groups = [];
      for (const note of this.notes) {
        let group = this.groups[this.groups.length - 1];
        if (!group || Math.abs(group.beat - note.beat) > 1e-5) {
          group = {beat: note.beat, notes: []};
          this.groups.push(group);
        }
        group.notes.push(note);
      }
      this.cursor = 0;
      this.positionBeat = this.groups[0].beat;
      this.anchorCount = 0;
      this.lastAnchor = -1;
      this.matched = new Set();
      this.marks = new Map();
      this.proposals = new Map();
      this.gaps = new Map();
      this.jump = null;
      this.seen = new Set();
      this.attackWindow = Math.min(.08, 60 / bpm * .16);
      this.updates = new Map();
    }

    feed(events) {
      if (!Array.isArray(events)) throw new TypeError('feed expects an array of played notes.');
      this.updates = new Map();
      const played = [];
      for (const event of events) {
        if (!event || !midi(event.pitch) || !finite(event.time) || event.time < 0 ||
            (event.velocity !== undefined && (!finite(event.velocity) || event.velocity < 0 || event.velocity > 127))) {
          throw new TypeError('Played notes need a MIDI pitch, nonnegative time, and valid velocity.');
        }
        // Re-delivering the same attack is not another key press. Sustained mic
        // windows still need onset detection/deduplication in the input adapter.
        const key = `${event.pitch}:${event.time}`;
        if (event.velocity === 0 || this.seen.has(key)) continue;
        this.seen.add(key);
        played.push({...event, kind: 'unplaced', provisional: true});
      }
      played.sort((a, b) => a.time - b.time);
      const attacks = [];
      for (const event of played) {
        let attack = attacks[attacks.length - 1];
        // Two presses of the same key are separate attacks even at fast tempi.
        if (!attack || event.time - attack[0].time > this.attackWindow || attack.some(n => n.pitch === event.pitch)) {
          attack = [];
          attacks.push(attack);
        }
        attack.push(event);
      }
      for (const attack of attacks) this.process(attack);
      return {positionBeat: this.positionBeat, marks: [...this.updates.values()], played, aligned: this.anchorCount >= 2};
    }

    available(index) {
      return this.groups[index] ? this.groups[index].notes.filter(note => !this.matched.has(note.id)) : [];
    }

    matches(attack, index) {
      const pitches = new Set(attack.map(note => note.pitch));
      return this.available(index).some(note => pitches.has(note.pitch));
    }

    overlap(attack, index) {
      const pitches = new Set(attack.map(note => note.pitch));
      return new Set(this.available(index).filter(note => pitches.has(note.pitch)).map(note => note.pitch)).size;
    }

    findAhead(attack, start) {
      if (!this.groups[start]) return -1;
      const firstBeat = this.groups[start].beat;
      for (let index = start; index < Math.min(this.groups.length, start + this.lookahead); index++) {
        if (this.groups[index].beat - firstBeat > 8) break;
        if (this.matches(attack, index)) return index;
      }
      return -1;
    }

    process(attack) {
      if (this.cursor >= this.groups.length) return;
      // A lookahead backed by a chord (two or more matching tones) is strong evidence the student
      // skipped ahead. A following note that fits right after it confirms the jump, even if the same
      // pitch also fits the skipped onset; otherwise the follower falls one onset behind for good.
      if (this.jump && this.jump.strength >= 2 && !this.matches(attack, this.jump.index)) {
        const next = this.findAhead(attack, this.jump.index + 1);
        if (next !== -1) {
          const jump = this.jump;
          this.jump = null;
          for (const buffered of jump.attacks) this.commit(buffered, jump.index);
          this.commit(attack, next);
          return;
        }
      }
      // The next expected onset always wins over an unconfirmed lookahead.
      // C, (inserted F), D must not skip D/E just because F exists later.
      if (this.matches(attack, this.cursor)) {
        // A chord already partly heard keeps a leftover slot open (a wrong or missed tone). If the new
        // attack fits the next onset better than that leftover, it is the next chord: giving its
        // shared pitch to the old slot would leave the follower one chord behind from then on.
        const partly = this.groups[this.cursor].notes.some(note => this.matched.has(note.id));
        if (partly && this.cursor + 1 < this.groups.length &&
            this.overlap(attack, this.cursor + 1) > this.overlap(attack, this.cursor)) {
          this.jump = null;
          this.commit(attack, this.cursor + 1);
          return;
        }
        this.jump = null;
        this.commit(attack, this.cursor);
        return;
      }
      // One heard chord tone already anchors this onset. Moving to its immediate
      // successor does not skip an unheard onset; a quiet bass note must not make
      // every following melody note wait for a second confirmation. Residual
      // chord tones still follow the normal, conservative missing-note policy.
      const partlyHeard = this.groups[this.cursor].notes.some(note => this.matched.has(note.id));
      if (partlyHeard && this.matches(attack, this.cursor + 1)) {
        this.jump = null;
        this.commit(attack, this.cursor + 1);
        return;
      }
      if (this.jump) {
        if (this.matches(attack, this.jump.index)) {
          this.jump.attacks.push(attack);
          attack.forEach(note => { note.kind = 'pending'; });
          return;
        }
        const next = this.findAhead(attack, this.jump.index + 1);
        if (next !== -1) {
          const jump = this.jump;
          this.jump = null;
          for (const buffered of jump.attacks) this.commit(buffered, jump.index);
          this.commit(attack, next);
          return;
        }
      }
      const ahead = this.findAhead(attack, this.cursor + 1);
      if (ahead !== -1) {
        this.jump = {index: ahead, attacks: [attack], strength: this.overlap(attack, ahead)};
        attack.forEach(note => { note.kind = 'pending'; });
      } else {
        this.propose(attack, this.cursor);
      }
    }

    publish(mark) {
      const previous = this.marks.get(mark.id);
      if (previous && previous.kind === mark.kind && previous.actual === mark.actual && previous.provisional === mark.provisional) return;
      this.marks.set(mark.id, mark);
      this.updates.set(mark.id, mark);
    }

    commit(attack, index) {
      // A skipped region is only a candidate until two separate later score
      // onsets support it. Chord tones at one onset count as one anchor.
      if (index > this.lastAnchor) {
        this.anchorCount++;
        this.lastAnchor = index;
      }
      for (let skipped = this.cursor; skipped < index; skipped++) {
        for (const note of this.available(skipped)) {
          const proposal = this.proposals.get(note.id);
          if (!this.gaps.has(note.id)) {
            this.gaps.set(note.id, {id: note.id, kind: proposal ? 'pitch' : 'missing',
              ...(proposal ? {actual: proposal.actual} : {}), anchor: this.anchorCount});
          }
          this.proposals.delete(note.id);
        }
      }
      this.cursor = Math.max(this.cursor, index);
      const unmatched = [];
      for (const event of attack) {
        const targets = this.available(index).filter(note => note.pitch === event.pitch);
        if (!targets.length) { unmatched.push(event); continue; }
        event.kind = 'matched';
        event.id = targets[0].id;
        event.provisional = false;
        // Unisons written for both hands are one physical piano key press.
        for (const note of targets) {
          this.matched.add(note.id);
          this.proposals.delete(note.id);
          this.gaps.delete(note.id);
          this.publish({id: note.id, kind: 'matched', actual: event.pitch, provisional: false});
        }
      }
      this.positionBeat = Math.max(this.positionBeat, this.groups[index].beat);
      // Additional tones in this attack belong to this chord, not the next bar.
      this.propose(unmatched, index);
      while (this.cursor < this.groups.length && !this.available(this.cursor).length) this.cursor++;
      if (this.input === 'midi') {
        for (const [id, gap] of this.gaps) {
          if (this.anchorCount - gap.anchor < 1) continue;
          this.publish({id, kind: gap.kind, ...(gap.actual !== undefined ? {actual: gap.actual} : {}), provisional: false});
          this.gaps.delete(id);
        }
      }
    }

    propose(attack, index) {
      const candidates = this.available(index);
      const used = new Set();
      for (const event of attack) {
        const nearest = candidates.filter(note => !used.has(note.id)).sort((a, b) =>
          Math.abs(a.pitch - event.pitch) - Math.abs(b.pitch - event.pitch))[0];
        const distance = nearest ? Math.abs(nearest.pitch - event.pitch) : Infinity;
        // Large outliers and off-score notes stay unplaced. Microphone pitch
        // guesses are deliberately narrower and never become final verdicts.
        if (distance > (this.input === 'mic' ? 2 : 5)) continue;
        used.add(nearest.id);
        const old = this.proposals.get(nearest.id);
        if (old && old.distance < distance) continue;
        this.proposals.set(nearest.id, {actual: event.pitch, distance});
        event.kind = 'pitch';
        event.id = nearest.id;
        this.publish({id: nearest.id, kind: 'pitch', actual: event.pitch, provisional: true});
      }
    }
  }
  return LiveScoreFollower;
});
