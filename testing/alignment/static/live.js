/* Live alignment page.
 *
 * Two layers run while someone plays:
 *  - fast: 1.5 s windows -> Basic Pitch (/api/practice/notes) -> LiveNoteStream -> LiveScoreFollower.
 *    Only moves the "you are here" cursor and fades in notes it hears. It never paints a mistake,
 *    because on a microphone a third of its mistake marks are wrong.
 *  - accurate: the whole take streams to /api/live/session, where the same transcriber and
 *    comparison as the final report re-check the last few seconds about every 1.3 s. Every green,
 *    red, orange and purple mark, the feedback list and the bar table come from this layer.
 * Stop sends the take to /api/live/finish for the full report page. */
(() => {
'use strict';
const $ = s => document.querySelector(s);
const NS = 'http://www.w3.org/2000/svg';
const names = ['C','C♯','D','D♯','E','F','F♯','G','G♯','A','A♯','B'];
const pitchName = p => p == null ? '?' : names[p % 12] + (Math.floor(p / 12) - 1);
const diatonic = p => [0,0,1,1,2,3,3,4,4,5,5,6][p % 12] + 7 * (Math.floor(p / 12) - 1);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmt = t => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
const WIN = {first: .2, cadence: .1, context: 1.5};
const S = {phase: 'idle', score: null, elements: new Map(), locations: {}, steps: {}, follower: null, stream: null,
  ctx: null, worklet: null, source: null, recorder: null, chunks: [], pcm: [], origin: 0, rate: 44100,
  busy: false, last: 0, noteStream: null, file: null, token: 0, now: null, here: null,
  session: null, sent: 0, queue: [], uploading: false, version: -1, shown: new Map(), feedKeys: new Set(), markers: new Map(), barsSeen: new Set(),
  extras: {}, fastBar: 0, checkedBar: 0, tempoItems: [], feedHtml: ''};

const message = text => { $('#message').textContent = text || ''; $('#message').hidden = !text; };
const overlay = text => { $('#overlay').hidden = !text; if (text) $('#overlay').innerHTML = `<span class="spin"></span>${text}`; };
function setPhase(value) {
  S.phase = value;
  const live = value === 'live', busy = value === 'starting' || value === 'finishing';
  $('#go').textContent = live ? 'Stop and get the full report' : value === 'starting' ? 'Starting…' : value === 'finishing' ? 'Checking the take…' : 'Start';
  $('#go').classList.toggle('stop', live);
  $('#go').disabled = busy || !S.score || (!live && $('#mode').value === 'file' && !$('#file').files[0]);
  for (const id of ['#piece', '#mode', '#file', '#start-bar']) $(id).disabled = live || busy;
  $('#dot').classList.toggle('on', live);
  $('#state').textContent = live ? ($('#mode').value === 'mic' ? 'Listening' : 'Playing the recording') : value === 'finishing' ? 'Checking the whole take' : 'Ready';
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
  S.score = null; setPhase('idle'); message(''); overlay('Drawing the score… (a new PDF takes a minute the first time)');
  const id = $('#piece').value;
  try {
    const get = async url => { const r = await fetch(url); const d = await r.json(); if (!r.ok) throw Error(d.error || 'Could not load this score.'); return d; };
    const [score, notation] = await Promise.all([get(`/api/practice/score/${encodeURIComponent(id)}`), get(`/api/live/notation/${encodeURIComponent(id)}`)]);
    if (id !== $('#piece').value) return;
    S.locations = notation.locations; S.steps = notation.steps || {}; insertPages(notation.pages);
    S.score = score; S.sorted = score.notes.slice().sort((a, b) => a.beat - b.beat);
    $('#start-bar').max = score.piece.measures;
    reset(); overlay(''); setPhase('idle');
  } catch (error) { overlay(''); message(error.message); }
}
function reset() {
  for (const el of S.elements.values()) el.classList?.remove('matched', 'missed', 'wrong', 'heard', 'now', 'here', 'fresh');
  for (const g of S.markers.values()) g.remove();
  S.markers.clear(); S.shown.clear(); S.feedKeys.clear(); S.barsSeen.clear(); S.version = -1; S.now = S.here = null;
  S.extras = {}; S.fastBar = S.checkedBar = 0; S.tempoItems = []; S.feedHtml = '';
  for (const id of ['#n-ok', '#n-wrong', '#n-miss', '#n-extra']) $(id).textContent = '0';
  $('#bar').textContent = '–'; $('#behind').textContent = '';
  $('#feed').innerHTML = '<p class="muted" id="feed-empty">Feedback appears here while you play: wrong keys, skipped notes, extra notes, and bars that rush or drag.</p>';
  $('#bars').innerHTML = '<tr><td colspan="7" class="muted">Nothing yet.</td></tr>';
  $('#notation').scrollTop = 0;
}

/* ---------- fast layer: cursor and faint "heard" notes only ---------- */
function acceptFast(events) {
  if (S.phase !== 'live' || !events.length) return;
  const result = S.follower.feed(events);
  for (const mark of result.marks) {
    if (mark.kind !== 'matched' || S.shown.has(mark.id)) continue;
    noteEl(mark.id)?.classList.add('heard');
  }
  if (result.aligned) follow(result.positionBeat);
}
function follow(beat) {
  let current = null;
  for (const n of S.sorted) { if (n.beat <= beat + .01) current = n; else break; }
  if (!current) return;
  S.fastBar = current.printedMeasure ?? current.measure; showBar();
  const el = noteEl(current.id);
  if (el && el !== S.now) { S.now?.classList.remove('now'); el.classList.add('now'); S.now = el; }
  const measure = el?.closest('.measure');
  if (measure && measure !== S.here) {
    S.here = measure;
    const box = $('#notation'), top = measure.getBoundingClientRect().top - box.getBoundingClientRect().top;
    if (top < 20 || top > box.clientHeight - 200) box.scrollTo({top: box.scrollTop + top - 90, behavior: 'smooth'});
  }
}

function showBar() {
  // The quick cursor can stall on a hard passage; the accurate layer's furthest bar keeps it honest.
  const bar = Math.max(S.fastBar || 0, S.checkedBar || 0);
  if (bar) $('#bar').textContent = bar;
}

/* ---------- accurate layer: marks, played-pitch markers, feed, bar table ---------- */
const CLASS = {correct: 'matched', missing: 'missed', wrong_pitch: 'wrong'};
function marker(note, mark, extra) {
  // Purple notehead at the pitch actually played, as on the report page.
  const head = note.querySelector('.notehead'); if (!head) return null;
  const box = head.getBBox(), staff = note.closest('.staff');
  const lines = [...(staff?.children || [])].filter(el => el.tagName === 'path').map(el => el.getBBox().y).sort((a, b) => a - b);
  const gap = lines.length > 1 ? lines[1] - lines[0] : box.height;
  const engraved = S.steps[note.id];
  const shift = engraved == null ? 0 : diatonic(mark.actual) - engraved;
  const x = box.x + box.width / 2 + (extra ? box.width * 1.4 : 0), y = box.y + box.height / 2 - shift * gap / 2;
  const g = document.createElementNS(NS, 'g'); g.classList.add('played-marker', 'fresh');
  const e = document.createElementNS(NS, 'ellipse');
  for (const [k, v] of Object.entries({cx: x, cy: y, rx: box.width / 2, ry: box.height / 2})) e.setAttribute(k, v);
  const t = document.createElementNS(NS, 'text');
  t.setAttribute('x', x + box.width * .7); t.setAttribute('y', y - box.height * .7); t.setAttribute('font-size', gap * .7);
  t.textContent = `${extra ? '+ ' : ''}${pitchName(mark.actual)}`;
  const title = document.createElementNS(NS, 'title'); title.textContent = extra ? `Extra ${pitchName(mark.actual)}` : `Played ${pitchName(mark.actual)}`;
  g.append(e, t, title); note.append(g);
  return g;
}
function renderFeed(marks) {
  // Rebuilt from the current marks every update, one line per bar and kind of mistake, newest first:
  // a note the check later re-reads as right drops out instead of lingering in the list.
  const groups = new Map();
  for (const m of marks) {
    if (m.category === 'correct') continue;
    const id = `${m.category}-${m.occurrence}`;
    const g = groups.get(id) || {id, kind: m.category, bar: m.measure, items: [], time: -1};
    g.items.push(m); g.time = Math.max(g.time, m.time ?? -1); groups.set(id, g);
  }
  for (const t of S.tempoItems) groups.set(t.id, t);
  const list = [...groups.values()].sort((a, b) => b.time - a.time);
  const text = g => {
    const n = g.items?.length || 0;
    if (g.kind === 'tempo') return g.text;
    if (g.kind === 'wrong_pitch') return n === 1 ? `The score has ${pitchName(g.items[0].expected)}; you played ${pitchName(g.items[0].actual)}.`
      : `${n} wrong keys: ${g.items.slice(0, 4).map(m => `${pitchName(m.actual)} for ${pitchName(m.expected)}`).join(', ')}${n > 4 ? '…' : ''}.`;
    if (g.kind === 'missing') return n === 1 ? `${pitchName(g.items[0].expected)} didn't sound.`
      : `${n} notes didn't sound: ${[...new Set(g.items.map(m => pitchName(m.expected)))].slice(0, 6).join(', ')}.`;
    const names = [...new Set(g.items.map(m => pitchName(m.actual)))];
    return n === 1 ? `An extra ${names[0]} that isn't in the score.` : `${n} keys that aren't in the score (${names.slice(0, 5).join(', ')}${names.length > 5 ? '…' : ''}).`;
  };
  const label = {wrong_pitch: 'wrong key', missing: 'skipped', extra: 'extra notes', tempo: 'tempo'};
  const colour = {wrong_pitch: '#c43d48', missing: '#c07700', extra: '#793bcc', tempo: '#805000'};
  const feedEl = $('#feed');
  if (!list.length) return;
  $('#feed-empty')?.remove();
  const html = list.map(g => {
    const isNew = !S.feedKeys.has(g.id);
    return `<div class="item${isNew ? '' : ' seen'}" style="--c:${colour[g.kind]}"><small>Bar ${esc(g.bar)} · ${label[g.kind]}</small>${esc(text(g))}</div>`;
  }).join('');
  if (html !== S.feedHtml) { feedEl.innerHTML = html; S.feedHtml = html; }
  for (const g of list) { if (!S.feedKeys.has(g.id)) say(`Bar ${g.bar}. ${text(g)}`); S.feedKeys.add(g.id); }
}
/* ---------- spoken coach: the browser's own voice, nothing to install ---------- */
const voice = {queue: [], busy: false};
function say(text) {
  if (!$('#speak').checked || !('speechSynthesis' in window) || S.phase !== 'live') return;
  // Keep it short and current: never more than two lines waiting, and never a stale one.
  voice.queue.push(text.replace(/[♯]/g, ' sharp').replace(/[♭]/g, ' flat').replace(/\b([A-G])(\d)\b/g, '$1 $2'));
  if (voice.queue.length > 2) voice.queue.splice(0, voice.queue.length - 2);
  speakNext();
}
function speakNext() {
  if (voice.busy || !voice.queue.length) return;
  const u = new SpeechSynthesisUtterance(voice.queue.shift());
  u.rate = 1.08; u.pitch = 1; voice.busy = true;
  u.onend = u.onerror = () => { voice.busy = false; speakNext(); };
  speechSynthesis.speak(u);
}
function applyState(state) {
  if (!state || state.version === S.version) return;
  S.version = state.version;
  if (state.heard_seconds != null && S.ctx) {
    const behind = Math.max(0, (S.ctx.currentTime - S.origin) - state.heard_seconds);
    $('#behind').textContent = `Checked up to ${fmt(state.heard_seconds)} · ${behind.toFixed(1)} s behind`;
  }
  if (!state.ready) return;
  const timed = (state.marks || []).filter(m => m.time != null && m.measure != null);
  if (timed.length) { S.checkedBar = timed.reduce((a, b) => (b.time > a.time ? b : a)).measure; showBar(); }
  const counts = {correct: 0, wrong_pitch: 0, missing: 0, extra: 0};
  const located = (state.marks || []).filter(m => m.id && noteEl(m.id));
  for (const m of state.marks || []) {
    counts[m.category] = (counts[m.category] || 0) + 1;
    const key = m.id || `x${m.actual}@${(m.time ?? 0).toFixed(1)}`;
    const before = S.shown.get(key);
    if (before === m.category) continue;
    S.shown.set(key, m.category);
    S.markers.get(key)?.remove(); S.markers.delete(key);
    const bar = m.measure;
    if (m.category === 'extra') {
      const near = located.filter(o => o.occurrence === m.occurrence && o.time != null)
        .sort((a, b) => Math.abs(a.time - m.time) - Math.abs(b.time - m.time))[0];
      const el = near && noteEl(near.id);
      if (el) { const g = marker(el, m, true); if (g) S.markers.set(key, g); }
      continue;
    }
    const el = noteEl(m.id); if (!el) continue;
    el.classList.remove('matched', 'missed', 'wrong', 'heard', 'fresh');
    void el.getBBox(); el.classList.add(CLASS[m.category]);
    if (m.category !== 'correct') el.classList.add('fresh');
    if (m.category === 'wrong_pitch') { const g = marker(el, m, false); if (g) S.markers.set(key, g); }
  }
  renderFeed(state.marks || []);
  $('#n-ok').textContent = counts.correct; $('#n-wrong').textContent = counts.wrong_pitch;
  $('#n-miss').textContent = counts.missing; $('#n-extra').textContent = counts.extra;
  renderBars(state.bars || []);
}
function renderBars(bars) {
  if (!bars.length) return;
  const newest = Math.max(...bars.map(b => b.occurrence));
  $('#bars').innerHTML = bars.map(b => {
    const ratio = b.tempo_ratio, status = b.tempo_status || 'unassessed';
    const label = {on_target: 'steady', too_fast: 'rushed', too_slow: 'dragged', irregular: 'uneven', unassessed: 'not enough notes yet'}[status] || status;
    const detail = [b.median_onset_ms != null ? `Off the beat by ${b.median_onset_ms} ms` : '', (b.early != null && b.late != null) ? `<small>${b.early} early · ${b.late} late</small>` : ''].filter(Boolean).join('<br>');
    return `<tr class="${b.occurrence === newest ? 'newest' : ''}"><td><strong>${b.number}</strong></td>
      <td>${b.correct}/${b.expected}<br><progress max="${b.expected}" value="${b.correct}"></progress></td>
      <td>${b.missing} / ${b.wrong} / ${b.extra}</td>
      <td><span class="badge ${status}">${label}</span>${ratio ? `<br><small>${ratio.toFixed(2)}× score speed</small>` : ''}</td>
      <td>${b.score_bpm ? b.score_bpm.toFixed(0) : '–'} → ${b.played_bpm ? b.played_bpm.toFixed(0) : '–'}</td>
      <td>${detail}</td><td>${(b.feedback || []).map(esc).join(' ')}</td></tr>`;
  }).join('');
  for (const b of bars) {
    if (S.barsSeen.has(b.occurrence) || b.occurrence === newest) continue;
    S.barsSeen.add(b.occurrence);  // tempo is only worth saying once a bar is finished
    if ((b.tempo_status === 'too_fast' || b.tempo_status === 'too_slow') && b.tempo_ratio)
      S.tempoItems.push({id: `tempo-${b.occurrence}`, kind: 'tempo', bar: b.number, time: S.ctx ? S.ctx.currentTime - S.origin : 0,
        text: `About ${Math.round(Math.abs(b.tempo_ratio - 1) * 100)}% ${b.tempo_status === 'too_fast' ? 'faster' : 'slower'} than written.`});
  }
}

/* ---------- audio ---------- */
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
    acceptFast(S.noteStream.ingest(data.notes, {start, end}).events);
  } catch {} finally { if (token === S.token) { S.busy = false; void sendWindow(); } }
}
async function upload() {
  // Stream the take to the accurate layer in order, one request at a time.
  if (S.uploading || !S.queue.length || !S.session) return;
  S.uploading = true; const token = S.token;
  try {
    while (S.queue.length && token === S.token) {
      const parts = S.queue.splice(0), length = parts.reduce((n, p) => n + p.length, 0), pcm = new Int16Array(length);
      let at = 0; for (const p of parts) { pcm.set(p, at); at += p.length; }
      const res = await fetch(`/api/live/session/${S.session}/audio?offset=${S.sent}`, {method: 'POST', body: pcm.buffer, headers: {'Content-Type': 'application/octet-stream'}});
      S.sent += length;
      if (res.ok) applyState(await res.json());
    }
  } catch {} finally { S.uploading = false; }
}
async function poll() {
  // While the browser sends nothing new (a pause, or after the recording ends) keep reading results.
  const token = S.token;
  while (token === S.token && (S.phase === 'live' || S.phase === 'finishing') && S.session) {
    try { const r = await fetch(`/api/live/session/${S.session}`); if (r.ok) applyState(await r.json()); } catch {}
    await new Promise(r => setTimeout(r, 700));
  }
}
async function capture(node) {
  await S.ctx.audioWorklet.addModule('/practice-assets/live-audio-worklet.js');
  S.worklet = new AudioWorkletNode(S.ctx, 'practice-capture');
  const mute = S.ctx.createGain(); mute.gain.value = 0;
  S.worklet.port.onmessage = ({data}) => {
    if (S.phase !== 'live') return;
    const time = Math.max(0, data.frame / S.rate - S.origin);
    S.pcm.push({time, samples: data.samples}); S.pcm = S.pcm.filter(c => c.time > time - WIN.context - .2);
    const ints = new Int16Array(data.samples.length); let energy = 0;
    for (let i = 0; i < data.samples.length; i++) { const x = Math.max(-1, Math.min(1, data.samples[i])); ints[i] = x < 0 ? x * 32768 : x * 32767; energy += x * x; }
    S.queue.push(ints); if (S.queue.reduce((n, p) => n + p.length, 0) >= S.rate / 4) void upload();
    $('#level').style.width = `${Math.min(100, Math.sqrt(energy / data.samples.length) * 800)}%`;
    void sendWindow();
  };
  node.connect(S.worklet).connect(mute).connect(S.ctx.destination);
}
async function start() {
  if (!S.score) return;
  message(''); S.token++; setPhase('starting'); reset();
  S.pcm = []; S.last = 0; S.busy = false; S.chunks = []; S.file = null; S.queue = []; S.sent = 0; S.session = null;
  S.noteStream = new LiveNoteStream();
  const startBar = Math.max(1, Math.min(S.score.piece.measures, Number($('#start-bar').value) || 1));
  const from = S.score.bars?.find(b => b.measure === startBar)?.startBeat ?? 0;
  S.follower = new LiveScoreFollower(S.score.notes.filter(n => n.beat >= from - 1e-6), {bpm: S.score.piece.bpm, input: 'mic'});
  try {
    S.ctx = new AudioContext({sampleRate: 44100}); await S.ctx.resume(); S.rate = S.ctx.sampleRate;
    const form = new FormData(); form.append('piece', $('#piece').value); form.append('rate', S.rate); form.append('start_bar', startBar);
    const res = await fetch('/api/live/session', {method: 'POST', body: form}); const data = await res.json();
    if (!res.ok) throw Error(data.error || 'Could not start the live check.');
    S.session = data.session;
    if ($('#mode').value === 'mic') {
      S.stream = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
      S.source = S.ctx.createMediaStreamSource(S.stream); await capture(S.source);
      S.recorder = new MediaRecorder(S.stream); S.recorder.ondataavailable = e => { if (e.data.size) S.chunks.push(e.data); }; S.recorder.start(1000);
      S.origin = S.ctx.currentTime;
    } else {
      S.file = $('#file').files[0];
      const player = $('#player'); player.src = URL.createObjectURL(S.file); player.currentTime = 0;
      S.source = S.ctx.createMediaElementSource(player); S.source.connect(S.ctx.destination); await capture(S.source);
      player.onended = () => { if (S.phase === 'live') setTimeout(() => void finish(), 2500); };
      await player.play(); S.origin = S.ctx.currentTime;
    }
    setPhase('live'); void poll();
  } catch (error) { await cleanup(); setPhase('idle'); message(error.name === 'NotAllowedError' ? 'The browser blocked the microphone. Allow it in the address bar and press Start again.' : error.message); }
}
async function cleanup() {
  const player = $('#player'); player.pause(); player.onended = null;
  if (S.stream) { S.stream.getTracks().forEach(t => t.stop()); S.stream = null; }
  S.worklet?.disconnect(); S.source?.disconnect(); S.worklet = S.source = null;
  if (S.ctx) { await S.ctx.close().catch(() => {}); S.ctx = null; }
  $('#level').style.width = '0%';
}
async function finish() {
  if (S.phase !== 'live') return;
  if ('speechSynthesis' in window) { voice.queue = []; speechSynthesis.cancel(); }
  setPhase('finishing');
  let file = S.file;
  try {
    if (S.recorder) {
      const recorder = S.recorder; S.recorder = null;
      await new Promise(resolve => { recorder.addEventListener('stop', resolve, {once: true}); recorder.stop(); });
      const type = recorder.mimeType || 'audio/webm';
      file = new File(S.chunks, `take.${type.includes('mp4') ? 'm4a' : 'webm'}`, {type});
    }
    await cleanup();
    if (S.session) fetch(`/api/live/session/${S.session}`, {method: 'DELETE'}).catch(() => {});
    S.token++;
    if (!file || !file.size) throw Error('Nothing was recorded. Check the microphone and try again.');
    overlay('Checking the whole take for the full report… about 10–30 seconds');
    const form = new FormData(); form.append('piece', $('#piece').value); form.append('recording', file);
    const res = await fetch('/api/live/finish', {method: 'POST', body: form, signal: AbortSignal.timeout(300000)});
    const data = await res.json(); if (!res.ok) throw Error(data.error || 'The full check failed.');
    location.href = data.report_url;
  } catch (error) { await cleanup(); overlay(''); setPhase('idle'); message(error.name === 'TimeoutError' ? 'The full check took too long. Try a shorter take.' : error.message); }
}

$('#go').addEventListener('click', () => S.phase === 'live' ? void finish() : void start());
$('#piece').addEventListener('change', () => { history.replaceState(null, '', `?piece=${encodeURIComponent($('#piece').value)}`); void loadPiece(); });
$('#mode').addEventListener('change', () => { $('#file-wrap').hidden = $('#mode').value !== 'file'; $('#file-spacer').hidden = $('#mode').value === 'file'; $('#speak').checked = $('#mode').value === 'file'; setPhase(S.phase); });
$('#file').addEventListener('change', () => setPhase(S.phase));
window.addEventListener('pagehide', () => { if (S.session) navigator.sendBeacon?.(`/api/live/session/${S.session}/stop`); S.phase = 'idle'; void cleanup(); });
(async () => {
  try {
    const pieces = await (await fetch('/api/pieces')).json();
    if (!pieces.length) throw Error('No pieces yet. Add sheet music first.');
    $('#piece').innerHTML = pieces.map(p => `<option value="${esc(p.id)}">${esc(p.title)}</option>`).join('');
    const params = new URLSearchParams(location.search), want = params.get('piece');
    if (want && pieces.some(p => p.id === want)) $('#piece').value = want;
    if (params.get('bar')) $('#start-bar').value = params.get('bar');
    await loadPiece();
  } catch (error) { overlay(''); message(error.message); }
})();
})();
