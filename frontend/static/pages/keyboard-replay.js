"use strict";
// ---------- MIDI parsing ----------
function parseMidi(buf) {
  const d = new DataView(buf); let p = 0;
  const str = n => { let s = ""; for (let i = 0; i < n; i++) s += String.fromCharCode(d.getUint8(p++)); return s; };
  if (str(4) !== "MThd") throw new Error("Not a MIDI file");
  p += 4; p += 2; // length, format
  const ntrk = d.getUint16(p); p += 2;
  const div = d.getUint16(p); p += 2;
  if (div & 0x8000) throw new Error("SMPTE timing is not supported");
  const tempos = [{ tick: 0, uspq: 500000 }];
  const raw = []; // {tick, ch, note, vel, on}
  for (let t = 0; t < ntrk && p + 8 <= d.byteLength; t++) {
    const id = str(4), len = d.getUint32(p); p += 4;
    const end = Math.min(p + len, d.byteLength);
    if (id !== "MTrk") { p = end; continue; }
    let tick = 0, status = 0;
    const vlq = () => { let v = 0, b; do { b = d.getUint8(p++); v = (v << 7) | (b & 0x7f); } while (b & 0x80); return v; };
    while (p < end) {
      tick += vlq();
      let b = d.getUint8(p);
      if (b & 0x80) { status = b; p++; }
      if (status === 0xff) {
        const type = d.getUint8(p++), l = vlq();
        if (type === 0x51 && l === 3) tempos.push({ tick, uspq: (d.getUint8(p) << 16) | (d.getUint8(p + 1) << 8) | d.getUint8(p + 2) });
        p += l;
      } else if (status === 0xf0 || status === 0xf7) { p += vlq(); }
      else {
        const hi = status & 0xf0, ch = status & 15;
        if (hi === 0xc0 || hi === 0xd0) { p += 1; }
        else {
          const a = d.getUint8(p++), v = d.getUint8(p++);
          if (hi === 0x90 && v > 0) raw.push({ tick, ch, note: a, vel: v, on: true });
          else if (hi === 0x80 || hi === 0x90) raw.push({ tick, ch, note: a, vel: 0, on: false });
        }
      }
    }
    p = end;
  }
  tempos.sort((a, b) => a.tick - b.tick);
  // tick -> seconds via tempo map
  const seg = []; let acc = 0;
  tempos.forEach((t, i) => {
    if (i) acc += (t.tick - tempos[i - 1].tick) * tempos[i - 1].uspq / 1e6 / div;
    seg.push({ tick: t.tick, sec: acc, uspq: t.uspq });
  });
  const toSec = tick => { let s = seg[0]; for (const x of seg) { if (x.tick <= tick) s = x; else break; } return s.sec + (tick - s.tick) * s.uspq / 1e6 / div; };
  raw.sort((a, b) => a.tick - b.tick || a.on - b.on); // offs before ons at same tick
  const open = new Map(), notes = [];
  for (const e of raw) {
    const k = e.ch * 128 + e.note;
    if (e.on) { const s = open.get(k) || []; s.push(e); open.set(k, s); }
    else { const s = open.get(k); if (s && s.length) { const o = s.shift(); notes.push({ t: toSec(o.tick), end: toSec(e.tick), note: o.note, vel: o.vel, ch: o.ch }); } }
  }
  for (const s of open.values()) for (const o of s) { const t = toSec(o.tick); notes.push({ t, end: t + 0.5, note: o.note, vel: o.vel, ch: o.ch }); }
  notes.sort((a, b) => a.t - b.t);
  if (!notes.length) throw new Error("No notes found in this file");
  return { notes, duration: Math.max(...notes.map(n => n.end)) };
}

// ---------- Audio ----------
let ctx = null, master = null;
function ensureAudio() {
  if (ctx) return;
  ctx = new (window.AudioContext || window.webkitAudioContext)();
  const comp = ctx.createDynamicsCompressor();
  master = ctx.createGain(); master.gain.value = +$("vol").value;
  master.connect(comp); comp.connect(ctx.destination);
}
function voice(note, vel, when, dur) {
  const f = 440 * Math.pow(2, (note - 69) / 12);
  const peak = Math.pow(vel / 127, 1.4) * 0.35 * Math.min(1, 6 / Math.max(1, f / 261));
  const g = ctx.createGain();
  const filt = ctx.createBiquadFilter(); filt.type = "lowpass"; filt.frequency.value = Math.min(9000, f * 6);
  g.connect(filt); filt.connect(master);
  const mix = [[1, 1, "triangle"], [2, 0.35, "sine"], [3, 0.15, "sine"]];
  const oscs = mix.map(([m, a, type]) => {
    const o = ctx.createOscillator(), og = ctx.createGain();
    o.type = type; o.frequency.value = f * m; og.gain.value = a; o.connect(og); og.connect(g); o.start(when); return o;
  });
  // piano-like: fast attack, decaying body that lengthens for low notes, short release at note-off
  const decay = 0.8 + 3 * (1 - (note - 21) / 87);
  const rel = 0.12, offT = when + Math.max(0.05, dur);
  g.gain.setValueAtTime(0.0001, when);
  g.gain.linearRampToValueAtTime(peak, when + 0.005);
  g.gain.setTargetAtTime(peak * 0.3, when + 0.005, decay / 3);
  g.gain.setTargetAtTime(0.0001, offT, rel / 3);
  oscs.forEach(o => o.stop(offT + rel * 2));
}

// ---------- State ----------
const $ = id => document.getElementById(id);
let song = null, playing = false, pos = 0, startCtx = 0, startPos = 0, nextIdx = 0, timer = 0;
const speed = () => +$("speed").value;
const cur = () => playing ? startPos + (ctx.currentTime - startCtx) * speed() : pos;

function load(buf, name) {
  $("msg").textContent = "";
  try { song = parseMidi(buf); } catch (e) { $("msg").textContent = e.message; return; }
  stop(); pos = 0; nextIdx = 0; viewIdx = 0; $("legend").hidden = true;
  $("name").textContent = name; $("name").title = name;
  $("play").disabled = false; $("seek").disabled = false; $("drop").hidden = true;
  updateTime();
}
function seekTo(t) {
  pos = Math.max(0, Math.min(song.duration, t));
  nextIdx = firstAtOrAfter(pos);
  if (playing) { startPos = pos; startCtx = ctx.currentTime; }
  updateTime();
}
function firstAtOrAfter(t) { let i = 0; while (i < song.notes.length && song.notes[i].t < t) i++; return i; }
function play() {
  if (!song) return;
  ensureAudio(); ctx.resume();
  if (pos >= song.duration) pos = 0;
  playing = true; startPos = pos; startCtx = ctx.currentTime + 0.05; nextIdx = firstAtOrAfter(pos);
  $("play").textContent = "Pause";
  timer = setInterval(schedule, 25); schedule();
}
function stop() {
  if (playing) { pos = cur(); playing = false; clearInterval(timer); }
  if (ctx) { ctx.close(); ctx = null; master = null; } // closing the context cuts already-scheduled voices
  $("play").textContent = "Play";
}
function schedule() {
  const s = speed(), horizon = cur() + 0.15 * s;
  while (nextIdx < song.notes.length && song.notes[nextIdx].t < horizon) {
    const n = song.notes[nextIdx++];
    const when = startCtx + (n.t - startPos) / s;
    if (when < ctx.currentTime - 0.02) continue; // already past (e.g. after tab stall)
    voice(n.note, n.vel, Math.max(when, ctx.currentTime), (n.end - n.t) / s);
  }
  if (cur() >= song.duration + 0.5) { pos = song.duration; stop(); }
}

// ---------- Rendering ----------
const cv = $("cv"), g2 = cv.getContext("2d");
const LO = 21, HI = 108, isBlack = n => [1, 3, 6, 8, 10].includes(n % 12);
const NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const keyGeo = (() => { // x/width in unit space where white key = 1
  const geo = {}; let w = 0;
  for (let n = LO; n <= HI; n++) if (!isBlack(n)) { geo[n] = { x: w, w: 1 }; w++; }
  for (let n = LO; n <= HI; n++) if (isBlack(n)) { const l = geo[n - 1]; geo[n] = { x: l.x + 1 - 0.3, w: 0.6 }; }
  geo.total = w; return geo;
})();
const GREEN = [145, 70], RED = [0, 85]; // hue, saturation
function colorFor(n, a) {
  if (n.ok !== undefined) { const [h, sat] = n.ok ? GREEN : RED; return `hsla(${h},${sat}%,${isBlack(n.note) ? 50 : 58}%,${a})`; } const h = n.ch % 2 ? 190 : 150 - (n.note - LO) * 0.3 + 60; return `hsla(${h},75%,${isBlack(n.note) ? 55 : 62}%,${a})`; }
function resize() {
  const r = cv.getBoundingClientRect(), dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr);
  g2.setTransform(dpr, 0, 0, dpr, 0, 0);
}
function rr(x, y, w, h, r) { g2.beginPath(); g2.roundRect(x, y, w, Math.max(0, h), r); }
function draw() {
  const W = cv.clientWidth, H = cv.clientHeight, kh = EMBED ? H : Math.min(150, H * 0.22), fallH = H - kh;
  const u = W / keyGeo.total, t = cur(), look = +$("look").value * speed();
  g2.clearRect(0, 0, W, H);
  // lane guides on C
  g2.fillStyle = "#ffffff07";
  for (let n = LO; n <= HI; n++) if (n % 12 === 0) g2.fillRect(keyGeo[n].x * u, 0, 1, fallH);
  const wanted = new Set(); // keys the score wanted while a wrong note sounds
  const active = new Map(); // key -> colour while a note is sounding
  if (song) {
    for (let i = Math.max(0, nextIdxView(t) - 1); i < song.notes.length; i++) {
      const n = song.notes[i]; if (n.t > t + look) break;
      if (n.end < t - 0.01) continue;
      if (n.t <= t && n.end >= t) active.set(n.note, n.ok === false ? "bad" : "good");
      if (n.expected != null && n.t <= t && n.end >= t) wanted.add(n.expected);
      if (!EMBED && n.expected != null && keyGeo[n.expected]) { // key the score wanted: hollow red outline
        const ek = keyGeo[n.expected], eb = Math.min(fallH - (n.t - t) / look * fallH, fallH), et = Math.max(fallH - (n.end - t) / look * fallH, -4);
        g2.strokeStyle = "#ff5d5d"; g2.lineWidth = 1.5; g2.setLineDash([4, 3]);
        rr(ek.x * u + 2, et, ek.w * u - 4, Math.max(4, eb - et) - 1, 3); g2.stroke(); g2.setLineDash([]);
      }
      if (EMBED) continue; // keyboard-only view: keys light up, notes do not fall
      const gk = keyGeo[n.note]; if (!gk) continue;
      const yBot = fallH - (n.t - t) / look * fallH, yTop = fallH - (n.end - t) / look * fallH;
      const top = Math.max(yTop, -4), bot = Math.min(yBot, fallH);
      const pad = isBlack(n.note) ? 1 : 1.5;
      g2.fillStyle = colorFor(n, 0.92);
      rr(gk.x * u + pad, top, gk.w * u - pad * 2, Math.max(4, bot - top) - 1, 3); g2.fill();
    }
  }
  // keys
  const ky = fallH;
  g2.fillStyle = "#071214"; g2.fillRect(0, ky - 2, W, 2);
  for (let n = LO; n <= HI; n++) if (!isBlack(n)) {
    const k = keyGeo[n], on = active.has(n);
    g2.fillStyle = on ? (active.get(n) === "bad" ? "#ff8a8a" : "#7fe8c8") : "#f4f8f6"; g2.fillRect(k.x * u + 0.5, ky, k.w * u - 1, kh);
    if (n % 12 === 0) { g2.fillStyle = "#5d7771"; g2.font = `${Math.min(10, u * 0.6)}px ui-monospace,monospace`; g2.textAlign = "center"; g2.fillText(NAMES[0] + (Math.floor(n / 12) - 1), (k.x + 0.5) * u, ky + kh - 6); }
  }
  for (let n = LO; n <= HI; n++) if (isBlack(n)) {
    const k = keyGeo[n], on = active.has(n);
    g2.fillStyle = on ? (active.get(n) === "bad" ? "#d63d3d" : "#2fb58f") : "#14201f"; rr(k.x * u, ky, k.w * u, kh * 0.62, [0, 0, 3, 3]); g2.fill();
  }
  g2.strokeStyle = "#ff3b3b"; g2.lineWidth = 3; g2.setLineDash([5, 3]);
  for (const n of wanted) { const k = keyGeo[n]; if (k) { g2.strokeRect(k.x * u + 2, ky + 2, k.w * u - 4, (isBlack(n) ? kh * 0.62 : kh) - 4); } }
  g2.setLineDash([]);
  if (!$("seek").matches(":active")) $("seek").value = song ? 1000 * Math.min(1, t / song.duration) : 0;
  updateTime(t);
}
let viewIdx = 0; // cached lower bound for notes still on screen
function nextIdxView(t) {
  if (!song) return 0;
  const ns = song.notes;
  if (viewIdx > ns.length || (viewIdx > 0 && ns[viewIdx - 1].t > t)) viewIdx = 0;
  while (viewIdx < ns.length && ns[viewIdx].t < t - 8) viewIdx++; // notes longer than 8s still need a scan; rare
  return viewIdx;
}
const fmt = s => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;
function updateTime(t = cur()) { $("time").textContent = song ? `${fmt(Math.min(t, song.duration))} / ${fmt(song.duration)}` : "0:00 / 0:00"; }
function frame() { draw(); requestAnimationFrame(frame); }

// ---------- UI ----------
$("file").onchange = e => { const f = e.target.files[0]; if (f) f.arrayBuffer().then(b => load(b, f.name)); };
$("play").onclick = () => playing ? stop() : play();
$("seek").oninput = e => { if (song) seekTo(e.target.value / 1000 * song.duration); };
$("vol").oninput = e => { if (master) master.gain.value = +e.target.value; };
$("speed").oninput = e => {
  $("speedv").textContent = (+e.target.value).toFixed(2) + "×";
  if (playing) { const t = cur(); startPos = t; startCtx = ctx.currentTime; nextIdx = firstAtOrAfter(t); } // reschedule at new rate
};
addEventListener("keydown", e => {
  if (e.target.matches("input[type=range],input[type=file]") && e.code !== "Space") return;
  if (!song) return;
  if (e.code === "Space") { e.preventDefault(); $("play").click(); }
  else if (e.code === "ArrowLeft") seekTo(cur() - 5);
  else if (e.code === "ArrowRight") seekTo(cur() + 5);
});
const drop = $("drop");
["dragenter", "dragover"].forEach(ev => addEventListener(ev, e => { e.preventDefault(); drop.hidden = false; drop.classList.add("over"); }));
["dragleave", "drop"].forEach(ev => addEventListener(ev, e => { e.preventDefault(); drop.classList.remove("over"); if (song) drop.hidden = true; }));
addEventListener("drop", e => { const f = e.dataTransfer.files[0]; if (f) f.arrayBuffer().then(b => load(b, f.name)); });
addEventListener("resize", resize);
// optional: ?src=path/to/file.mid
// ---------- Backend (served by soundwaves.app) ----------
const qs0 = new URLSearchParams(location.search), EMBED = qs0.has("embed");
if (EMBED) document.body.classList.add("embed");
let feedbackUrl = null;
function loadReport(id, url = "/api/falling/" + id) {
  $("msg").textContent = "";
  return fetch(url).then(r => r.ok ? r.json() : Promise.reject(new Error("No comparison found for " + id)))
    .then(d => {
      const notes = d.notes.map(n => ({ ...n, ch: 0 }));
      if (!notes.length) throw new Error("That take has no notes");
      stop(); song = { notes, duration: Math.max(...notes.map(n => n.end)) }; pos = 0; nextIdx = 0; viewIdx = 0;
      $("name").textContent = $("name").title = d.title || "Your take";
      $("play").disabled = $("seek").disabled = false; $("drop").hidden = true;
      $("legend").hidden = false;
      $("score").textContent = `· ${d.matched}/${notes.length} played notes match` + (d.missing ? `, ${d.missing} score notes missed` : "");
      if (!EMBED) history.replaceState(null, "", "?report=" + d.id);
      feedbackUrl = EMBED ? null : "/api/feedback/" + d.id; $("fb").hidden = true; $("fb").textContent = ""; $("fbtn").hidden = !feedbackUrl;
      const t0 = +qs0.get("t"); if (t0 > 0) seekTo(t0); // ?t=12.5 starts there
      updateTime();
    }).catch(e => $("msg").textContent = e.message);
}
fetch("/api/pieces").then(r => r.ok ? r.json() : []).then(list => {
  $("piece").hidden = !list.length;
  $("piece").innerHTML = '<option value="">or pick a built-in piece…</option>' + list.map(p => `<option value="${p.id}">${p.title}</option>`).join("");
  $("compare").hidden = false;
}).catch(() => {});
// An uploaded score replaces the piece for the next comparison; click the name to go back to the piece.
let scoreFile = null;
function setScore(f) {
  scoreFile = f; $("piece").hidden = !!f; $("scorename").hidden = !f;
  $("scorename").textContent = f ? f.name + " ✕" : "";
}
$("scorefile").onchange = e => { setScore(e.target.files[0] || null); e.target.value = ""; };
$("scorename").onclick = () => setScore(null);
$("scorename").style.cursor = "pointer";
$("rec").onchange = e => {
  const f = e.target.files[0]; if (!f) return;
  if (!scoreFile && !$("piece").value) { $("msg").textContent = "Upload your score first."; e.target.value = ""; return; }
  const form = new FormData(); form.append("performance", f); if (scoreFile) form.append("score", scoreFile); else form.append("piece", $("piece").value); form.append("explain", "0");
  $("msg").style.color = "var(--ink-2)"; $("msg").textContent = "Analysing… (audio can take a minute)";
  fetch("/api/analyze", { method: "POST", body: form }).then(r => r.json().then(d => r.ok ? d : Promise.reject(new Error(d.error || "Analysis failed"))))
    .then(d => loadReport(d.id)).then(() => { if (!$("msg").textContent.startsWith("No")) $("msg").textContent = ""; })
    .catch(err => { $("msg").style.color = ""; $("msg").textContent = err.message; })
    .finally(() => { e.target.value = ""; });
};
// Teacher feedback drawer (standalone page only; the comparison page shows it itself)
const mk = (tag, text, parent, cls) => { const e = document.createElement(tag); e.textContent = text; if (cls) e.className = cls; parent.appendChild(e); return e; };
$("fbtn").onclick = () => {
  const fb = $("fb"); fb.hidden = !fb.hidden;
  if (fb.hidden || fb.dataset.loaded === feedbackUrl) return;
  fb.textContent = "Writing feedback…";
  fetch(feedbackUrl).then(r => r.json().then(d => r.ok ? d : Promise.reject(new Error(d.error || "Could not get feedback"))))
    .then(d => {
      fb.textContent = ""; fb.dataset.loaded = feedbackUrl;
      mk("p", d.summary, fb);
      if (d.strengths && d.strengths.length) { mk("h3", "Going well", fb); const u = mk("ul", "", fb); d.strengths.forEach(t => mk("li", t, u)); }
      if (d.focus_areas && d.focus_areas.length) { mk("h3", "What to work on", fb); d.focus_areas.forEach(f => {
        const c = mk("div", "", fb, "area"); mk("strong", f.title + (f.bars ? " · " + f.bars : ""), c); mk("p", f.what_happened, c);
        const u = mk("ul", "", c); f.tips.forEach(t => mk("li", t, u)); }); }
      if (d.practice_plan) { mk("h3", "Next practice session", fb); mk("p", d.practice_plan, fb); }
    }).catch(e => { fb.textContent = e.message; });
};
const qs = new URLSearchParams(location.search), report = qs.get("report"), api = qs.get("api");
if (api && api.startsWith("/")) loadReport("embedded", api); // same-origin paths only
else if (report) loadReport(report);
const src = new URLSearchParams(location.search).get("src");
if (src) fetch(src).then(r => r.ok ? r.arrayBuffer() : Promise.reject(new Error("Could not load " + src))).then(b => load(b, src.split("/").pop())).catch(e => $("msg").textContent = e.message);
resize(); requestAnimationFrame(frame);
