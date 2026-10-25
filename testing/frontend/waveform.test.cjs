const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

async function player(ok = true) {
  class Element extends EventTarget {
    constructor(tag) {
      super(); this.tag = tag; this.children = []; this.attributes = {}; this.dataset = {};
      this.hidden = false; this.clientWidth = 300; this.clientHeight = 62;
      const classes = new Set(); this.classList = {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x)};
    }
    append(...nodes) { this.children.push(...nodes); }
    after(node) { this.player = node; }
    setAttribute(k,v) { this.attributes[k] = String(v); }
    getAttribute(k) { return this.attributes[k] || null; }
    querySelector() { return null; }
    focus() {}
    setPointerCapture() {}
    getBoundingClientRect() { return {left: 0, width: this.clientWidth}; }
    getContext() { return {setTransform(){}, clearRect(){}, beginPath(){}, roundRect(){}, fill(){}, fillRect(){}}; }
  }
  const audio = new Element('audio'); audio.controls = true; audio.duration = 10; audio.currentTime = 0; audio.paused = true;
  audio.setAttribute('src', '/artifact/abc/audio');
  audio.play = () => { audio.paused = false; audio.dispatchEvent(new Event('play')); return Promise.resolve(); };
  audio.pause = () => { audio.paused = true; audio.dispatchEvent(new Event('pause')); };
  const requests = [];
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../../frontend/static/waveform.js'), 'utf8'), {
    document: {createElement: tag => new Element(tag), querySelectorAll: () => [audio], body: {}},
    window: {devicePixelRatio: 1}, location: {href: 'http://localhost/', origin: 'http://localhost'},
    URL, AbortController, requestAnimationFrame: () => 1, cancelAnimationFrame() {},
    ResizeObserver: class {observe() {}}, MutationObserver: class {observe() {}},
    fetch: async url => {requests.push(url); return {ok, json: async () => ({duration:10, peaks:[.2,.4,.8,1]})};},
  });
  await new Promise(setImmediate);
  return {audio, requests, root: audio.player, play: audio.player.children[0], track: audio.player.children[1], time: audio.player.children[2]};
}
function key(target, value) {
  const event = new Event('keydown'); Object.defineProperty(event, 'key', {value}); target.dispatchEvent(event);
}

test('waveform controls play the original audio and seek its shared clock', async () => {
  const p = await player();
  assert.equal(p.audio.controls, false);
  assert.deepEqual(p.requests, ['/artifact/abc/audio/waveform']);
  p.play.dispatchEvent(new Event('click'));
  assert.equal(p.audio.paused, false);
  assert.equal(p.play.textContent, 'Pause');
  key(p.track, 'ArrowRight');
  assert.equal(p.audio.currentTime, 5);
  assert.equal(p.time.textContent, '0:05 / 0:10');
  p.play.dispatchEvent(new Event('click'));
  assert.equal(p.audio.paused, true);
});

test('switching recording to detected MIDI loads the corresponding waveform', async () => {
  const p = await player();
  p.audio.setAttribute('src', '/artifact/abc/recording_midi_audio');
  p.audio.dispatchEvent(new Event('loadstart'));
  await new Promise(setImmediate);
  assert.equal(p.requests.at(-1), '/artifact/abc/recording_midi_audio/waveform');
  key(p.track, 'End'); assert.equal(p.audio.currentTime, 10);
  key(p.track, 'Home'); assert.equal(p.audio.currentTime, 0);
});

test('failed waveform loading restores standard audio controls', async () => {
  const p = await player(false);
  assert.equal(p.audio.controls, true);
  assert.equal(p.root.hidden, true);
  assert.equal(p.audio.classList.contains('waveform-source'), false);
});
