/* Learn a tune: one note at a time, no tempo. The next key is shown on the keyboard and on the
 * score; the page waits until that key is heard (microphone), tapped on screen, or comes from a
 * recording. Wrong keys get a direction. Uses the same window transcriber as Play live. */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const names = ['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const plain = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
const pitchName = p => names[p % 12] + (Math.floor(p / 12) - 1);
const WHITE = new Set([0, 2, 4, 5, 7, 9, 11]);
const diatonic = p => [0,0,1,1,2,3,3,4,4,5,5,6][p % 12] + 7 * Math.floor(p / 12);
const WIN = {first: .2, cadence: .1, context: 1.5};
const S = {phase: 'idle', score: null, steps: [], idx: 0, remaining: [], firstTry: true, ok: 0, wrong: 0, streak: 0, tries: 0,
  elements: new Map(), locations: {}, stream: null, ctx: null, worklet: null, source: null, pcm: [], origin: 0, rate: 44100,
  busy: false, last: 0, noteStream: null, token: 0, lastHit: {pitch: null, time: -9}, lastMiss: {pitch: null, time: -9},
  buffers: new Map(), hearing: false, file: null, keyLow: 60, keyHigh: 84, log: [], recent: [], hitVel: []};

const message = text => { $('#message').textContent = text || ''; $('#message').hidden = !text; };
const overlay = text => { $('#overlay').hidden = !text; if (text) $('#overlay').innerHTML = `<span class="spin"></span>${text}`; };
function setPhase(value) {
  S.phase = value;
  const live = value === 'live', busy = value === 'starting';
  $('#go').textContent = live ? 'Stop' : busy ? 'Starting…' : 'Start';
  $('#go').classList.toggle('stop', live);
  $('#go').disabled = busy || !S.score || (!live && $('#mode').value === 'file' && !$('#file').files[0]);
  for (const id of ['#piece', '#mode', '#file']) $(id).disabled = live || busy;
}

/* ---------- score ---------- */
function insertPages(pages) {
  const container = $('#notation');
  container.querySelectorAll(':scope > svg').forEach(el => el.remove());
  S.elements = new Map();
  for (const page of pages) {
    const doc = new DOMParser().parseFromString(page, 'image/svg+xml');
    if (doc.querySelector('parsererror')) throw new Error('The score drawing is invalid.');
    doc.querySelectorAll('script,foreignObject').forEach(el => el.remove());
    for (const el of doc.querySelectorAll('*')) for (const attr of [...el.attributes])
      if (/^on/i.test(attr.name) || (/href$/i.test(attr.name) && !attr.value.startsWith('#'))) el.removeAttribute(attr.name);
    const svg = document.importNode(doc.documentElement, true);
    svg.setAttribute('viewBox', `0 0 ${parseFloat(svg.getAttribute('width'))} ${parseFloat(svg.getAttribute('height'))}`);
    container.append(svg);
    svg.querySelectorAll('[id]').forEach(el => S.elements.set(el.id, el));
  }
}
const noteEl = id => S.elements.get(S.locations[id]);
async function loadPiece() {
  S.score = null; setPhase('idle'); message(''); overlay('Drawing the score…');
  const id = $('#piece').value;
  try {
    const get = async url => { const r = await fetch(url); const d = await r.json(); if (!r.ok) throw Error(d.error || 'Could not load this tune.'); return d; };
    const [score, notation] = await Promise.all([get(`/api/practice/score/${encodeURIComponent(id)}`), get(`/api/live/notation/${encodeURIComponent(id)}`)]);
    if (id !== $('#piece').value) return;
    S.locations = notation.locations; insertPages(notation.pages); S.score = score;
    // Right hand only for a two-hand piece; notes struck together are one step.
    const hands = new Set(score.notes.map(n => n.hand));
    const notes = score.notes.filter(n => !hands.has('left') || n.hand === 'right').sort((a, b) => a.beat - b.beat || a.pitch - b.pitch);
    S.steps = [];
    for (const n of notes) {
      const last = S.steps[S.steps.length - 1];
      if (last && Math.abs(last.beat - n.beat) < 1e-6) { last.pitches.push(n.pitch); last.ids.push(n.id); }
      else S.steps.push({beat: n.beat, pitches: [n.pitch], ids: [n.id], measure: n.printedMeasure ?? n.measure});
    }
    const pitches = notes.map(n => n.pitch);
    S.keyLow = Math.min(60, Math.floor(Math.min(...pitches) / 12) * 12);
    S.keyHigh = Math.max(84, Math.ceil((Math.max(...pitches) + 1) / 12) * 12);
    drawKeyboard(); reset(); overlay(''); setPhase('idle');
    $('#go-live').href = `/live?piece=${encodeURIComponent(id)}`;
  } catch (error) { overlay(''); message(error.message); }
}

/* ---------- keyboard ---------- */
function drawKeyboard() {
  const kb = $('#kb'); kb.innerHTML = '';
  const whites = []; for (let p = S.keyLow; p <= S.keyHigh; p++) if (WHITE.has(p % 12)) whites.push(p);
  const w = 100 / whites.length;
  whites.forEach((p, i) => {
    const k = document.createElement('div'); k.className = 'k w'; k.dataset.pitch = p;
    k.style.left = `${i * w}%`; k.style.width = `${w}%`; k.textContent = p % 12 === 0 ? `C${Math.floor(p / 12) - 1}` : plain[p % 12];
    kb.append(k);
  });
  for (let p = S.keyLow; p <= S.keyHigh; p++) {
    if (WHITE.has(p % 12)) continue;
    const below = whites.indexOf(p - 1); if (below < 0) continue;
    const k = document.createElement('div'); k.className = 'k b'; k.dataset.pitch = p; k.style.left = `${(below + 1) * w}%`;
    kb.append(k);
  }
  kb.querySelectorAll('.k').forEach(k => k.addEventListener('pointerdown', ev => {
    ev.preventDefault();
    if (S.phase === 'live' && $('#mode').value === 'tap') onEvent(Number(k.dataset.pitch), performance.now() / 1000, 90);
    else if (S.phase !== 'live') void hear(Number(k.dataset.pitch));
  }));
}
const keyEl = p => $(`#kb .k[data-pitch="${p}"]`);
function flash(p, cls) { const k = keyEl(p); if (!k) return; k.classList.add(cls); setTimeout(() => k.classList.remove(cls), 380); }

/* ---------- the lesson ---------- */
function reset() {
  S.idx = 0; S.ok = S.wrong = S.streak = S.tries = 0; S.firstTry = true;
  S.lastHit = {pitch: null, time: -9}; S.lastMiss = {pitch: null, time: -9}; S.recent = []; S.hitVel = [];
  for (const el of S.elements.values()) el.classList?.remove('done', 'now', 'hard');
  $('#kb').querySelectorAll('.k').forEach(k => k.classList.remove('next', 'hit', 'miss'));
  $('#finish').classList.remove('show'); $('#n-total').textContent = S.steps.length;
  showStep();
}
function showStep() {
  const step = S.steps[S.idx];
  $('#kb').querySelectorAll('.k.next').forEach(k => k.classList.remove('next'));
  $('#n-done').textContent = S.idx; $('#n-ok').textContent = S.ok; $('#n-wrong').textContent = S.wrong; $('#streak').textContent = S.streak;
  $('#bar').style.width = `${S.steps.length ? S.idx / S.steps.length * 100 : 0}%`;
  if (!step) return finish();
  S.remaining = step.pitches.slice(); S.firstTry = true; S.tries = 0;
  for (const p of step.pitches) keyEl(p)?.classList.add('next');
  S.elements.forEach(el => el.classList?.remove('now'));
  for (const id of step.ids) noteEl(id)?.classList.add('now');
  const first = noteEl(step.ids[0]);
  if (first) { const box = $('#notation'), top = first.getBoundingClientRect().top - box.getBoundingClientRect().top; if (top < 20 || top > box.clientHeight - 120) box.scrollTo({top: box.scrollTop + top - 80, behavior: 'smooth'}); }
  const big = $('#big'); big.className = 'big'; big.textContent = step.pitches.map(pitchName).join('+');
  const where = step.pitches[0] % 12 === 0 ? 'the white key just left of the two black keys' : WHITE.has(step.pitches[0] % 12) ? 'a white key' : 'a black key';
  $('#say').textContent = S.idx === 0 ? `Start with ${pitchName(step.pitches[0])}. It's ${where}, lit up blue below.` : `Next: ${step.pitches.map(pitchName).join(' and ')}.`;
  $('#sub').textContent = `Note ${S.idx + 1} of ${S.steps.length}, bar ${step.measure}.`;
}
function direction(got, want) {
  const d = diatonic(want) - diatonic(got);
  if (Math.abs(want - got) === 12) return want > got ? 'That is the right key, one octave too low. Go to the same key further right.' : 'That is the right key, one octave too high. Go to the same key further left.';
  if (d === 0) return `Almost: ${pitchName(want)} is the ${WHITE.has(want % 12) ? 'white' : 'black'} key right next to it.`;
  const n = Math.abs(d);
  return `You want ${pitchName(want)}, ${n === 1 ? 'the next white key' : `${n} white keys`} to the ${d > 0 ? 'right' : 'left'}.`;
}
function onEvent(pitch, time, velocity, duration) {
  if (S.phase !== 'live' || S.idx >= S.steps.length) return;
  S.log.push({pitch, dt: +(time - S.lastHit.time).toFixed(2), velocity, duration, want: S.remaining.slice(), lastHit: S.lastHit.pitch});
  const want = S.remaining;
  // What the quick transcriber hears besides the key that was pressed, and how it is told apart
  // (rules checked on a replay of a correctly played tune: 9 false "wrong key" calls to 0):
  // 1. far outside the tune's range: a sub-harmonic of a low string.
  if (pitch < S.keyLow - 12 || pitch > S.keyHigh + 12) return;
  // 2. a quieter note at the same instant as a louder one: a ringing key re-triggered by the new attack.
  if (S.recent.some(r => r.pitch !== pitch && Math.abs(r.time - time) <= 0.03 && velocity < 0.75 * r.velocity)) { S.recent.push({pitch, time, velocity}); return; }
  // 3. the same key heard again within a second, much quieter: the ring, not a new press. Stricter when
  //    the tune wants that key next, so a quiet real repeat still counts.
  const ringLimit = want.includes(pitch) ? 0.6 : 0.8;
  if (S.recent.some(r => r.pitch === pitch && time - r.time >= 0 && time - r.time <= 1.0 && velocity < ringLimit * r.velocity)) { S.recent.push({pitch, time, velocity}); return; }
  // 4. a wrong note much softer than the player's recent correct ones: an overtone.
  const hits = S.hitVel.slice(-3).sort((a, b) => a - b);
  if (!want.includes(pitch) && hits.length && velocity < 0.6 * hits[hits.length >> 1]) { S.recent.push({pitch, time, velocity}); return; }
  S.recent.push({pitch, time, velocity}); if (S.recent.length > 12) S.recent.shift();
  if (time - S.lastMiss.time < 0.4 && pitch === S.lastMiss.pitch) return;
  const octave = want.find(p => p !== pitch && (p - pitch) % 12 === 0);
  if (want.includes(pitch) || octave !== undefined) {
    const hit = want.includes(pitch) ? pitch : octave;
    S.remaining = want.filter(p => p !== hit); S.lastHit = {pitch, time}; S.hitVel.push(velocity);
    flash(hit, 'hit');
    if (octave !== undefined && !want.includes(pitch)) $('#sub').textContent = direction(pitch, octave);
    if (S.remaining.length) { $('#say').textContent = `Good, now add ${S.remaining.map(pitchName).join(' and ')}.`; return; }
    const step = S.steps[S.idx];
    for (const id of step.ids) { const el = noteEl(id); if (el) { el.classList.remove('now'); el.classList.add(S.tries >= 2 ? 'hard' : 'done'); } }
    if (S.firstTry) { S.ok++; S.streak++; } else S.streak = 0;
    S.idx++;
    showStep();  // the next target is set at once, so a quick next note is judged against the right step
    if (S.idx < S.steps.length) {
      const big = $('#big'), label = big.textContent;
      big.className = 'big ok'; big.textContent = 'Yes';
      setTimeout(() => { if (S.phase === 'live' && big.textContent === 'Yes') { big.className = 'big'; big.textContent = label; } }, 350);
    }
    return;
  }
  S.wrong++; S.tries++; S.firstTry = false; S.streak = 0; S.lastMiss = {pitch, time};
  flash(pitch, 'miss');
  const big = $('#big'); big.className = 'big bad'; big.textContent = pitchName(pitch);
  $('#say').textContent = direction(pitch, want[0]);
  $('#n-wrong').textContent = S.wrong; $('#streak').textContent = 0;
}
function finish() {
  $('#big').className = 'big ok'; $('#big').textContent = '✓';
  $('#say').textContent = 'Complete.'; $('#sub').textContent = '';
  $('#bar').style.width = '100%'; $('#n-done').textContent = S.steps.length;
  const n = S.steps.length, first = S.ok;
  $('#finish-text').textContent = `${first}/${n} correct  /  ${S.wrong} retries`;
  $('#finish').classList.add('show');
  void stop(false);
}

/* ---------- hearing notes ---------- */
async function buffer(pitch) {
  if (S.buffers.has(pitch)) return S.buffers.get(pitch);
  if (!S.ctx) { S.ctx = new AudioContext(); await S.ctx.resume(); }
  const bytes = await (await fetch(`/api/practice/piano/${pitch}`)).arrayBuffer();
  const buf = await S.ctx.decodeAudioData(bytes);
  S.buffers.set(pitch, buf); return buf;
}
async function hear(pitch, at = 0, length = 0.9) {
  try {
    const buf = await buffer(pitch);
    const src = S.ctx.createBufferSource(), g = S.ctx.createGain(); src.buffer = buf;
    const t = S.ctx.currentTime + at; g.gain.setValueAtTime(0.5, t); g.gain.setValueAtTime(0.5, t + length); g.gain.exponentialRampToValueAtTime(0.001, t + length + 0.15);
    src.connect(g).connect(S.ctx.destination); src.start(t); src.stop(t + length + 0.2);
  } catch {}
}
async function hearTune() {
  if (!S.steps.length || S.hearing) return;
  S.hearing = true; $('#hear-all').disabled = true;
  const spb = 60 / 90, start = S.steps[0].beat;
  for (const step of S.steps) for (const p of step.pitches) await hear(p, (step.beat - start) * spb, 0.7);
  const total = (S.steps[S.steps.length - 1].beat - start) * spb + 1;
  setTimeout(() => { S.hearing = false; $('#hear-all').disabled = false; }, total * 1000);
}

/* ---------- audio in ---------- */
function wav(samples, rate) {
  const data = new ArrayBuffer(44 + samples.length * 2), v = new DataView(data);
  const ascii = (o, t) => { for (let i = 0; i < t.length; i++) v.setUint8(o + i, t.charCodeAt(i)); };
  ascii(0, 'RIFF'); v.setUint32(4, data.byteLength - 8, true); ascii(8, 'WAVE'); ascii(12, 'fmt ');
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); ascii(36, 'data'); v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) { const x = Math.max(-1, Math.min(1, samples[i])); v.setInt16(44 + i * 2, x < 0 ? x * 32768 : x * 32767, true); }
  return new Blob([data], {type: 'audio/wav'});
}
async function sendWindow() {
  if (S.phase !== 'live' || S.busy || !S.pcm.length) return;
  const tail = S.pcm.at(-1), end = tail.time + tail.samples.length / S.rate;
  if (end < WIN.first || end - S.last < WIN.cadence) return;
  const start = Math.max(0, end - WIN.context), samples = new Float32Array(Math.round((end - start) * S.rate));
  for (const c of S.pcm) {
    const offset = Math.round((c.time - start) * S.rate), from = Math.max(0, -offset), to = Math.min(c.samples.length, samples.length - offset);
    if (to > from) samples.set(c.samples.subarray(from, to), Math.max(0, offset));
  }
  S.last = end; S.busy = true; const token = S.token, form = new FormData(); form.append('audio', wav(samples, S.rate), 'window.wav');
  try {
    const res = await fetch('/api/practice/notes', {method: 'POST', body: form, signal: AbortSignal.timeout(20000)});
    if (res.status === 503) return;
    const data = await res.json(); if (!res.ok) throw Error(data.error);
    if (token !== S.token || S.phase !== 'live') return;
    for (const e of S.noteStream.ingest(data.notes, {start, end}).events) onEvent(e.pitch, e.time, e.velocity, e.duration);
  } catch {} finally { if (token === S.token) { S.busy = false; void sendWindow(); } }
}
async function capture(node) {
  await S.ctx.audioWorklet.addModule('/practice-assets/live-audio-worklet.js');
  S.worklet = new AudioWorkletNode(S.ctx, 'practice-capture');
  const mute = S.ctx.createGain(); mute.gain.value = 0;
  S.worklet.port.onmessage = ({data}) => {
    if (S.phase !== 'live') return;
    const time = Math.max(0, data.frame / S.rate - S.origin);
    S.pcm.push({time, samples: data.samples}); S.pcm = S.pcm.filter(c => c.time > time - WIN.context - .2);
    void sendWindow();
  };
  node.connect(S.worklet).connect(mute).connect(S.ctx.destination);
}
async function start() {
  if (!S.score) return;
  message(''); S.token++; setPhase('starting'); reset();
  S.pcm = []; S.last = 0; S.busy = false; S.noteStream = new LiveNoteStream();
  const mode = $('#mode').value;
  try {
    if (mode !== 'tap') {  // tapping on screen needs no audio at all
      if (S.ctx && S.ctx.state === 'closed') S.ctx = null;
      if (!S.ctx) S.ctx = new AudioContext({sampleRate: 44100});
      await Promise.race([S.ctx.resume(), new Promise(r => setTimeout(r, 1500))]);
      if (S.ctx.state !== 'running') throw Error('The browser did not allow audio to start. Click Start again.');
      S.rate = S.ctx.sampleRate;
    }
    if (mode === 'mic') {
      S.stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
      S.source = S.ctx.createMediaStreamSource(S.stream); await capture(S.source); S.origin = S.ctx.currentTime;
    } else if (mode === 'file') {
      S.file = $('#file').files[0];
      const player = $('#player'); player.src = URL.createObjectURL(S.file); player.currentTime = 0;
      if (!S.fileSource) { S.fileSource = S.ctx.createMediaElementSource(player); S.fileSource.connect(S.ctx.destination); }
      S.source = S.fileSource; await capture(S.source);
      player.onended = () => { if (S.phase === 'live') setTimeout(() => void stop(true), 1500); };
      try { await player.play(); } catch (error) { throw Error(`Could not play that recording (${error.name}).`); }
      S.origin = S.ctx.currentTime;
    }
    setPhase('live');
    $('#say').textContent = mode === 'tap' ? `Tap ${pitchName(S.steps[0].pitches[0])}, the blue key.` : `Play ${pitchName(S.steps[0].pitches[0])}, the blue key. Take your time.`;
  } catch (error) { await stop(false); message(error.name === 'NotAllowedError' ? 'The browser blocked the microphone. Allow it in the address bar and press Start again.' : error.message); }
}
async function stop(keepPhase) {
  const player = $('#player'); player.pause(); player.onended = null;
  if (S.stream) { S.stream.getTracks().forEach(t => t.stop()); S.stream = null; }
  S.worklet?.disconnect(); S.worklet = null;
  if (S.source && S.source !== S.fileSource) S.source.disconnect();
  S.source = null; S.token++;
  if (!keepPhase || S.idx >= S.steps.length) setPhase('idle');
}

$('#go').addEventListener('click', () => S.phase === 'live' ? void stop(false) : void start());
$('#hear').addEventListener('click', () => { const step = S.steps[S.idx]; if (step) step.pitches.forEach(p => void hear(p)); });
$('#hear-all').addEventListener('click', () => void hearTune());
$('#again').addEventListener('click', () => { reset(); if (S.phase !== 'live') void start(); });
$('#piece').addEventListener('change', () => { history.replaceState(null, '', `?piece=${encodeURIComponent($('#piece').value)}`); void loadPiece(); });
$('#mode').addEventListener('change', () => { $('#file-wrap').hidden = $('#mode').value !== 'file'; $('#file-spacer').hidden = $('#mode').value === 'file'; setPhase(S.phase); });
$('#file').addEventListener('change', () => setPhase(S.phase));
window.addEventListener('pagehide', () => { S.phase = 'idle'; void stop(false); });
window.learnDebug = {onEvent: (p, v = 90) => onEvent(p, performance.now() / 1000, v, 0.3), state: () => ({idx: S.idx, ok: S.ok, wrong: S.wrong, steps: S.steps.length, phase: S.phase}), log: () => S.log};
(async () => {
  try {
    const pieces = await (await fetch('/api/pieces')).json();
    if (!pieces.length) throw Error('No tunes yet. Make one on Make it easy first.');
    const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
    const ordered = [...pieces.filter(p => /\(easy\)/.test(p.title)), ...pieces.filter(p => !/\(easy\)/.test(p.title))];
    $('#piece').innerHTML = ordered.map(p => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
    const want = new URLSearchParams(location.search).get('piece');
    if (want && pieces.some(p => p.id === want)) $('#piece').value = want;
    await loadPiece();
  } catch (error) { overlay(''); message(error.message); }
})();
})();
