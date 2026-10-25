const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function playback() {
  const source = fs.readFileSync(path.join(__dirname, '../../frontend/static/notation.js'), 'utf8');
  const start = source.indexOf('    const playbackNotes =');
  const end = source.indexOf('    status.textContent = `${data.annotations.length}', start);
  const scrolls = [];
  const caption = {textContent: ''};
  const controls = {'playing-notes': caption, 'follow-score': {checked: true, addEventListener() {}},
    'score-zoom': {addEventListener() {}}};
  const container = {clientTop: 0, clientHeight: 620, scrollTop: 0,
    getBoundingClientRect: () => ({top: 0}),
    scrollTo(options) { scrolls.push(options); this.scrollTop = options.top; }};
  const firstSystem = {getBoundingClientRect: () => ({top: 32-container.scrollTop, bottom: 300-container.scrollTop})};
  const secondSystem = {getBoundingClientRect: () => ({top: 700-container.scrollTop, bottom: 1000-container.scrollTop})};
  function note(time, duration, system) {
    const classes = new Set();
    const changes = [];
    return {item: {audio_time: time, duration, actual_name: 'C4'},
      target: {classList: {add(c) { classes.add(c); changes.push(['add', c]); },
        remove(c) { classes.delete(c); changes.push(['remove', c]); }}}, changes,
      note: {closest: () => system}};
  }
  const timed = [note(0, 10, firstSystem), note(1, .2, secondSystem), note(2, .2, secondSystem)];
  const audio = {currentTime: 0, paused: false, addEventListener() {}};
  const context = {timed, audio, container, plausible: () => true,
    document: {getElementById: id => controls[id]}};
  vm.runInNewContext(source.slice(start, end) + '\nglobalThis.step = update;', context);
  return {step: context.step, audio, timed, scrolls, controls};
}

test('held bass and rests cannot pull following back to an earlier system', () => {
  const p = playback();
  p.step();
  p.audio.currentTime = 1.1; p.step();
  p.audio.currentTime = 1.5; p.step();
  p.audio.currentTime = 2.1; p.step();
  assert.equal(p.scrolls.length, 1);
  assert.equal(p.scrolls[0].top, 668);
});

test('unchanged active notes do not have their highlight removed and re-added', () => {
  const p = playback();
  p.step(); p.step(); p.step();
  assert.equal(p.timed[0].changes.length, 1);
});

test('paused playback and disabled following leave the score position alone', () => {
  const p = playback();
  p.audio.paused = true; p.audio.currentTime = 1.1; p.step();
  assert.equal(p.scrolls.length, 0);
  p.audio.paused = false; p.controls['follow-score'].checked = false; p.step();
  assert.equal(p.scrolls.length, 0);
});
