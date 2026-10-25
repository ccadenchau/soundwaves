'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const LiveScoreFollower = require('../../frontend/static/live-input/live-matcher.js');

const score = (pitches, beats = pitches.map((_, i) => i)) => pitches.map((pitch, i) => ({
  id: `n${i}`, pitch, beat: beats[i], duration: 1, measure: Math.floor(beats[i] / 4) + 1,
  beatInMeasure: beats[i] % 4 + 1, hand: 'right'
}));
const event = (pitch, time) => ({pitch, time, velocity: 80});
function session(pitches, options = {}, beats) {
  const follower = new LiveScoreFollower(score(pitches, beats), {bpm: 120, ...options});
  const marks = new Map();
  return {follower, marks, play(pitch, time) {
    const result = follower.feed([event(pitch, time)]);
    result.marks.forEach(mark => marks.set(mark.id, mark));
    return result;
  }};
}

test('correct phrase follows attacks, including arbitrarily long pauses', () => {
  const s = session([60, 62, 64, 65]);
  assert.equal(s.play(60, 20).aligned, false);
  assert.equal(s.play(62, 21).aligned, true);
  assert.equal(s.follower.feed([]).positionBeat, 1);
  assert.equal(s.play(64, 70).positionBeat, 2);
  assert.equal(s.play(65, 100).positionBeat, 3);
  assert.equal(s.marks.size, 4);
  assert.ok([...s.marks.values()].every(mark => mark.kind === 'matched'));
});

test('inserted wrong pitch does not consume the expected note', () => {
  const s = session([60, 62, 64, 65]);
  s.play(60, 1);
  assert.equal(s.play(63, 1.2).marks[0].provisional, true);
  assert.equal(s.play(62, 1.5).positionBeat, 1);
  s.play(64, 2);
  s.play(65, 2.5);
  assert.ok([...s.marks.values()].every(mark => mark.kind === 'matched'));
});

test('an inserted note matching a later pitch cannot drag the score ahead', () => {
  const s = session([60, 62, 64, 65]);
  s.play(60, 1);
  const inserted = s.play(65, 1.2);
  assert.equal(inserted.positionBeat, 0);
  assert.equal(inserted.marks.length, 0);
  assert.equal(s.play(62, 1.5).positionBeat, 1);
  s.play(64, 2);
  s.play(65, 2.5);
  assert.ok([...s.marks.values()].every(mark => mark.kind === 'matched'));
});

test('skipped note requires two distinct later pitch anchors', () => {
  const s = session([60, 62, 64, 65, 67]);
  s.play(60, 1);
  assert.equal(s.play(64, 2).marks.length, 0);
  const confirmed = s.play(65, 2.5);
  assert.equal(confirmed.positionBeat, 3);
  assert.deepEqual(s.marks.get('n1'), {id: 'n1', kind: 'missing', provisional: false});
  assert.equal(s.marks.has('n4'), false);
});

test('bounded wrong pitch is provisional until subsequent anchors confirm its slot', () => {
  const s = session([60, 62, 64, 65]);
  s.play(60, 1);
  assert.deepEqual(s.play(63, 1.5).marks, [{id: 'n1', kind: 'pitch', actual: 63, provisional: true}]);
  s.play(64, 2);
  s.play(65, 2.5);
  assert.deepEqual(s.marks.get('n1'), {id: 'n1', kind: 'pitch', actual: 63, provisional: false});
});

test('chords arrive together or in separate calls; chord tones are one anchor', () => {
  const f = new LiveScoreFollower(score([60, 64, 67, 62, 65, 69], [0, 0, 0, 1, 1, 1]));
  const first = f.feed([event(67, 1.02), event(60, 1), event(64, 1.01)]);
  assert.equal(first.marks.length, 3);
  assert.equal(first.aligned, false);
  assert.equal(f.feed([event(62, 1.5)]).aligned, true);
  assert.equal(f.feed([event(69, 1.53)]).positionBeat, 1);
  assert.equal(f.feed([event(65, 1.55)]).marks[0].id, 'n4');
  assert.equal(f.matched.size, 6);
});

test('right-hand melody confirms every onset when bass chord tones are unheard', () => {
  const f = new LiveScoreFollower(score([48, 60, 50, 62, 52, 64, 53, 65], [0, 0, 1, 1, 2, 2, 3, 3]), {input: 'mic'});
  for (let i = 0; i < 4; i++) {
    const result = f.feed([event([60, 62, 64, 65][i], 1 + i * .5)]);
    assert.equal(result.positionBeat, i);
    assert.equal(result.played[0].kind, 'matched');
    assert.deepEqual(result.marks.map(mark => mark.kind), ['matched']);
  }
});

test('a partly heard chord still cannot skip a wholly unheard onset immediately', () => {
  const f = new LiveScoreFollower(score([48, 60, 62, 64, 65], [0, 0, 1, 2, 3]), {input: 'mic'});
  f.feed([event(60, 1)]);
  const pending = f.feed([event(64, 2)]);
  assert.equal(pending.positionBeat, 0);
  assert.equal(pending.played[0].kind, 'pending');
  assert.deepEqual(pending.marks, []);
  const recovered = f.feed([event(62, 2.1)]);
  assert.equal(recovered.positionBeat, 1);
  assert.equal(recovered.played[0].kind, 'matched');
});

test('buffered played objects update in place when later anchors confirm them', () => {
  const f = new LiveScoreFollower(score([60, 62, 64, 65]));
  f.feed([event(60, 1)]);
  const pending = f.feed([event(64, 2)]).played[0];
  assert.equal(pending.kind, 'pending');
  f.feed([event(65, 2.5)]);
  assert.equal(pending.kind, 'matched');
  assert.equal(pending.id, 'n2');
  assert.equal(pending.provisional, false);
});

test('two chord tones do not confirm a skipped onset', () => {
  const f = new LiveScoreFollower(score([60, 62, 64, 67, 69], [0, 1, 2, 2, 3]));
  f.feed([event(60, 1)]);
  assert.deepEqual(f.feed([event(64, 2)]).marks, []);
  assert.deepEqual(f.feed([event(67, 2.03)]).marks, []);
  const result = f.feed([event(69, 2.5)]);
  assert.equal(result.marks.filter(mark => mark.kind === 'missing').length, 1);
  assert.equal(result.positionBeat, 3);
});

test('initial silence, empty feeds, and unplayed suffix generate no missing notes', () => {
  const s = session([60, 62, 64, 65, 67]);
  assert.deepEqual(s.follower.feed([]).marks, []);
  s.play(60, 100);
  s.play(62, 200);
  for (let i = 0; i < 20; i++) assert.deepEqual(s.follower.feed([]).marks, []);
  assert.equal(s.marks.size, 2);
  assert.equal(s.follower.positionBeat, 1);
});

test('repeated notes and repeat passages follow sequential score IDs', () => {
  const s = session([60, 60, 62, 60, 60, 62]);
  [60, 60, 62, 60, 60, 62].forEach((pitch, index) => s.play(pitch, 1 + index * .5));
  assert.equal(s.marks.size, 6);
  assert.equal(s.follower.positionBeat, 5);
  assert.deepEqual(s.follower.feed([event(62, 3.5)]).played, []);
});

test('a held note with no new onset does not advance; exact duplicate events are ignored', () => {
  const s = session([60, 60, 62]);
  s.play(60, 1);
  assert.equal(s.play(60, 1).played.length, 0);
  assert.equal(s.follower.feed([]).positionBeat, 0);
  assert.equal(s.play(60, 3).positionBeat, 1);
});

test('mic never emits missing or confirmed wrong-pitch verdicts', () => {
  const s = session([60, 62, 64, 65, 67], {input: 'mic'});
  s.play(60, 1);
  s.play(63, 1.5);
  s.play(64, 2);
  s.play(67, 3);
  assert.ok([...s.marks.values()].every(mark => mark.kind === 'matched' || mark.kind === 'pitch' && mark.provisional));
  assert.equal(s.marks.has('n3'), false);
});

test('unison notes in both hands match one physical key', () => {
  const f = new LiveScoreFollower(score([60, 60, 62], [0, 0, 1]));
  assert.equal(f.feed([event(60, 1)]).marks.length, 2);
  assert.equal(f.feed([event(62, 1.5)]).positionBeat, 1);
});

test('each skipped gap needs its own two following anchors', () => {
  const s = session([60, 62, 64, 65, 67, 69]);
  s.play(60, 1);
  s.play(64, 2);
  s.play(67, 3);
  assert.equal(s.marks.get('n1').kind, 'missing');
  assert.equal(s.marks.has('n3'), false);
  s.play(69, 3.5);
  assert.equal(s.marks.get('n3').kind, 'missing');
});

test('browser global and CommonJS exports both expose the constructor', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve('../../frontend/static/live-input/live-matcher.js'), 'utf8'), context);
  assert.equal(typeof context.LiveScoreFollower, 'function');
  assert.equal(typeof LiveScoreFollower, 'function');
});

test('invalid score and event data fail with a useful error', () => {
  assert.throws(() => new LiveScoreFollower([]), /score note list/);
  assert.throws(() => new LiveScoreFollower(score([60]), {bpm: 0}), /tempo/);
  assert.throws(() => new LiveScoreFollower(score([60]), {input: 'file'}), /Input/);
  const f = new LiveScoreFollower(score([60]));
  assert.throws(() => f.feed([{pitch: 128, time: 0}]), /MIDI pitch/);
  assert.throws(() => f.feed([{pitch: 60, time: -1}]), /nonnegative time/);
});

test('a wrong chord tone does not leave the follower one chord behind', () => {
  // Score: [D4 E4 A3] then [A4 A3 E4 C4] then [C5]. The student plays B3 instead of A3 in the first chord.
  const score = [
    {id: 'd4', pitch: 62, beat: 0, duration: 1}, {id: 'e4', pitch: 64, beat: 0, duration: 1}, {id: 'a3a', pitch: 57, beat: 0, duration: 1},
    {id: 'a4', pitch: 69, beat: 1, duration: 1}, {id: 'a3b', pitch: 57, beat: 1, duration: 1}, {id: 'e4b', pitch: 64, beat: 1, duration: 1}, {id: 'c4', pitch: 60, beat: 1, duration: 1},
    {id: 'c5', pitch: 72, beat: 2, duration: 1}];
  const f = new LiveScoreFollower(score, {bpm: 60, input: 'midi'});
  f.feed([{pitch: 62, time: 0}, {pitch: 64, time: 0.01}, {pitch: 59, time: 0.02}]);
  f.feed([{pitch: 69, time: 1}, {pitch: 57, time: 1.01}, {pitch: 64, time: 1.01}, {pitch: 60, time: 1.02}]);
  f.feed([{pitch: 72, time: 2}]);
  for (const id of ['a4', 'a3b', 'e4b', 'c4', 'c5']) assert.equal(f.marks.get(id)?.kind, 'matched', id);
  assert.equal(f.marks.get('a3a')?.kind, 'pitch');
});

test('a skipped single note does not pull the follower back after a chord-confirmed jump', () => {
  // Score: C5 | [D5 A3 D4 E4] | C5 | D5. The student skips the first C5.
  const score = [
    {id: 'c5a', pitch: 72, beat: 0, duration: 1},
    {id: 'd5', pitch: 74, beat: 1, duration: 1}, {id: 'a3', pitch: 57, beat: 1, duration: 1}, {id: 'd4', pitch: 62, beat: 1, duration: 1}, {id: 'e4', pitch: 64, beat: 1, duration: 1},
    {id: 'c5b', pitch: 72, beat: 2, duration: 1}, {id: 'd5b', pitch: 74, beat: 3, duration: 1}];
  const f = new LiveScoreFollower(score, {bpm: 60, input: 'midi'});
  f.feed([{pitch: 74, time: 1}, {pitch: 57, time: 1.01}, {pitch: 62, time: 1.01}, {pitch: 64, time: 1.02}]);
  f.feed([{pitch: 72, time: 2}]);
  f.feed([{pitch: 74, time: 3}]);
  for (const id of ['d5', 'a3', 'd4', 'e4', 'c5b', 'd5b']) assert.equal(f.marks.get(id)?.kind, 'matched', id);
  assert.equal(f.marks.get('c5a')?.kind, 'missing');
});

