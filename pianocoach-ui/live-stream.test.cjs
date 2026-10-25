'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const LiveNoteStream = require('./live-stream.js');
const note = (pitch, onset, duration = .12) => ({pitch, onset, duration, velocity: 80});

test('overlapping windows and onset drift emit one physical attack', () => {
  const stream = new LiveNoteStream();
  assert.equal(stream.ingest([note(60, .3)], {start: 0, end: .7}).events.length, 1);
  assert.deepEqual(stream.ingest([note(60, .22)], {start: .12, end: .82}), {events: [], late: []});
  assert.deepEqual(stream.ingest([note(60, .15)], {start: .24, end: .94}), {events: [], late: []});
});

test('one-to-one matching preserves fast same-pitch repeats amid drift', () => {
  const stream = new LiveNoteStream();
  const initial = stream.ingest([note(60, .2, .05), note(60, .28, .05)], {start: 0, end: .7});
  assert.equal(initial.events.length, 2);
  const next = stream.ingest([note(60, .25, .05), note(60, .33, .05), note(60, .41, .05)], {start: 0, end: .82});
  assert.equal(next.events.length, 1);
  assert.equal(next.events[0].time, .41);
  assert.equal(next.late.length, 0);
});

test('a new repeated attack can be closer than the dedup tolerance', () => {
  const stream = new LiveNoteStream();
  stream.ingest([note(60, .4, .04)], {start: 0, end: .7});
  const next = stream.ingest([note(60, .41, .04), note(60, .47, .04)], {start: 0, end: .82});
  assert.deepEqual(next.events.map(event => event.time), [.47]);
});

test('empty responses never move the note-delivery frontier', () => {
  const stream = new LiveNoteStream();
  stream.ingest([], {start: 0, end: .7});
  stream.ingest([], {start: 0, end: .82});
  assert.equal(stream.lastDelivered, -Infinity);
  const delayed = stream.ingest([note(60, .3)], {start: 0, end: .94});
  assert.equal(delayed.events.length, 1);
  assert.equal(delayed.late.length, 0);
});

test('older newly discovered notes are neutral late events, once only', () => {
  const stream = new LiveNoteStream();
  stream.ingest([note(64, .5)], {start: 0, end: .7});
  const result = stream.ingest([note(60, .2), note(64, .51)], {start: 0, end: .82});
  assert.deepEqual(result.events, []);
  assert.deepEqual(result.late.map(event => event.pitch), [60]);
  assert.equal(stream.lastDelivered, .5);
  assert.deepEqual(stream.ingest([note(60, .22)], {start: 0, end: .94}), {events: [], late: []});
});

test('a slightly late chord tone can still join its onset', () => {
  const stream = new LiveNoteStream();
  stream.ingest([note(60, .5)], {start: 0, end: .7});
  const result = stream.ingest([note(64, .46)], {start: 0, end: .82});
  assert.equal(result.events[0].pitch, 64);
  assert.equal(stream.lastDelivered, .5);
});

test('right-edge notes wait for a later confirmed observation', () => {
  const stream = new LiveNoteStream();
  assert.deepEqual(stream.ingest([note(60, .66)], {start: 0, end: .7}), {events: [], late: []});
  assert.deepEqual(stream.ingest([], {start: 0, end: .82}), {events: [], late: []});
  const result = stream.ingest([note(60, .55)], {start: .12, end: .94});
  assert.equal(result.events.length, 1);
  assert.equal(result.events[0].time, .66);
});

test('left-edge sustain fragments never become new attacks', () => {
  const stream = new LiveNoteStream();
  stream.ingest([note(60, .2, 1.3)], {start: 0, end: 1.5});
  for (const start of [.18, .4, .8, 1.2, 1.8, 2.4]) {
    const result = stream.ingest([note(60, .02, 1.4)], {start, end: start + 1.5});
    assert.deepEqual(result, {events: [], late: []});
  }
  assert.equal(stream.history.length, 1);
  assert.ok(stream.history[0].end > 3.8);
});

test('first-window attacks at time zero are allowed', () => {
  const stream = new LiveNoteStream();
  assert.equal(stream.ingest([note(60, 0)], {start: 0, end: .7}).events.length, 1);
  assert.deepEqual(stream.ingest([note(62, .1)], {start: .2, end: .9}), {events: [], late: []});
});

test('stale responses cannot advance score position', () => {
  const stream = new LiveNoteStream();
  stream.ingest([], {start: .5, end: 2});
  const result = stream.ingest([note(60, .4)], {start: 0, end: 1.5});
  assert.equal(result.events.length, 0);
  assert.equal(result.late.length, 1);
  assert.equal(stream.lastDelivered, -Infinity);
});

test('duplicate response rows do not fabricate repeated notes', () => {
  const stream = new LiveNoteStream();
  assert.equal(stream.ingest([note(60, .3), note(60, .3)], {start: 0, end: .7}).events.length, 1);
});

test('onset-only detector results have a short duration and usable velocity', () => {
  const stream = new LiveNoteStream();
  const result = stream.ingest([{pitch: 60, onset: .3}], {start: 0, end: .7});
  assert.equal(result.events.length, 1);
  assert.ok(Math.abs(result.events[0].duration - .08) < 1e-8);
  assert.equal(result.events[0].velocity, 80);
});

test('exports work in browser and Node; malformed input is rejected', () => {
  const context = vm.createContext({});
  vm.runInContext(fs.readFileSync(require.resolve('./live-stream.js'), 'utf8'), context);
  assert.equal(typeof context.LiveNoteStream, 'function');
  assert.throws(() => new LiveNoteStream({edgeHold: -1}), /tolerances/);
  const stream = new LiveNoteStream();
  assert.throws(() => stream.ingest([], {start: 1, end: 0}), /window/);
  assert.throws(() => stream.ingest([note(200, .2)], {start: 0, end: .7}), /MIDI pitch/);
});
