"""Serve the practice page with real reports, and a one-button page to record a take.

    python -m pianocoach.app            # http://127.0.0.1:5002
    open /record to record or upload a take; the page then opens /?report=<id>
"""

import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Blueprint, Flask, abort, jsonify, request, send_file  # noqa: E402

from pianocoach.pipeline import AUDIO_SUFFIXES, MIDI_SUFFIXES, TooFewNotes, analyze, convert_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'pianocoach-ui' / 'index.html'
PIECES = Path(__file__).with_name('pieces')
SESSIONS = Path(__file__).with_name('sessions')
ID = re.compile(r'^[a-f0-9]{32}$')
SESSIONS.mkdir(exist_ok=True)

app = Flask(__name__)
coach = Blueprint('coach', __name__)
app.config['MAX_CONTENT_LENGTH'] = 120 * 1024 * 1024

from pianocoach.live import practice  # noqa: E402
app.register_blueprint(practice)
from pianocoach.selftest import selftest  # noqa: E402
app.register_blueprint(selftest)

LOADER = """
<script>
(async () => {
  const id = new URLSearchParams(location.search).get('report');
  if (!id) return;
  try {
    const res = await fetch(`/api/report/${encodeURIComponent(id)}`, {cache: 'no-store'});
    if (!res.ok) throw new Error('No report with that id.');
    const report = await res.json();
    let file = null;
    const audio = await fetch(`/api/audio/${encodeURIComponent(id)}`, {cache: 'no-store'});
    if (audio.ok) file = await audio.blob();
    window.PianoCoach.loadReport(report, file);
  } catch (error) { console.error('[pianocoach]', error); }
})();
</script>
"""

RECORD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Record a take</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0b0d;color:#f2f2f4;font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif}
main{width:min(520px,92vw);display:grid;gap:22px}
h1{font-size:28px;font-weight:600;margin:0}
label{display:grid;gap:6px;font-size:13px;color:#a9a9b3}
select,input[type=file]{font:inherit;color:inherit;background:#17171b;border:1px solid #2a2a31;border-radius:10px;padding:10px 12px}
.big{font:inherit;font-size:18px;font-weight:600;border:0;border-radius:999px;padding:18px 28px;background:#f2f2f4;color:#0b0b0d;cursor:pointer}
.big[disabled]{opacity:.45;cursor:default}
.big.rec{background:#ff3b30;color:#fff}
.big.alt{background:#17171b;color:#f2f2f4;border:1px solid #2a2a31}
.big.alt.live{background:#30d158;color:#0b0b0d}
#status{min-height:1.5em;color:#a9a9b3}
#level{height:6px;border-radius:3px;background:#17171b;overflow:hidden}
#level i{display:block;height:100%;width:0;background:#30d158;transition:width .08s}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.quiet{font-size:13px;color:#6f6f78}
</style></head><body><main>
<h1>Record a take</h1>
<label>Piece <select id="piece"></select></label>
<p class="quiet"><a href="/upload" style="color:#8fd">Add your own sheet music</a></p>
<div class="row"><button class="big" id="rec">Start recording</button><button class="big alt" id="midi" hidden>Use MIDI keyboard</button><span id="timer" class="quiet"></span></div>
<div id="level"><i></i></div>
<p id="status"></p>
<p id="midi-status" class="quiet" hidden></p>
<label>Or upload a recording or MIDI file <input type="file" id="file" accept="audio/*,.wav,.mp3,.m4a,.webm,.mid,.midi"></label>
<p class="quiet">Play the whole passage from the start. Give the microphone a second of silence before the first note.</p>
</main>
<script>
const $ = s => document.querySelector(s);
let media, chunks = [], recorder, startedAt, timerId, ctx, analyser, meterId;
async function pieces() {
  const list = await (await fetch('/api/pieces')).json();
  $('#piece').innerHTML = list.map(p => `<option value="${p.id}">${p.title}</option>`).join('') || '<option value="">(no pieces yet, add one first)</option>';
  const want = new URLSearchParams(location.search).get('piece'); if (want && list.some(p => p.id === want)) $('#piece').value = want;
}
function meter(stream) {
  ctx = new AudioContext(); const src = ctx.createMediaStreamSource(stream); analyser = ctx.createAnalyser(); analyser.fftSize = 512; src.connect(analyser);
  const buf = new Uint8Array(analyser.fftSize);
  const tick = () => { analyser.getByteTimeDomainData(buf); let peak = 0; for (const v of buf) peak = Math.max(peak, Math.abs(v - 128)); $('#level i').style.width = Math.min(100, peak / 128 * 180) + '%'; meterId = requestAnimationFrame(tick); };
  tick();
}
async function start() {
  media = await navigator.mediaDevices.getUserMedia({audio: {echoCancellation: false, noiseSuppression: false, autoGainControl: false}});
  meter(media);
  chunks = []; recorder = new MediaRecorder(media);
  recorder.ondataavailable = e => chunks.push(e.data);
  recorder.onstop = upload;
  recorder.start(); startedAt = Date.now();
  timerId = setInterval(() => { const s = Math.round((Date.now() - startedAt) / 1000); $('#timer').textContent = `${Math.floor(s/60)}:${String(s%60).padStart(2,'0')}`; }, 250);
  $('#rec').textContent = 'Stop and analyse'; $('#rec').classList.add('rec'); $('#status').textContent = 'Recording. Play from the top.';
}
function stop() {
  recorder.stop(); media.getTracks().forEach(t => t.stop()); clearInterval(timerId); cancelAnimationFrame(meterId); if (ctx) ctx.close();
  $('#rec').disabled = true; $('#rec').classList.remove('rec'); $('#rec').textContent = 'Working';
}
async function upload() {
  const blob = new Blob(chunks, {type: recorder.mimeType || 'audio/webm'});
  const ext = (recorder.mimeType || 'audio/webm').includes('mp4') ? 'm4a' : 'webm';
  await send(new File([blob], `take.${ext}`, {type: blob.type}));
}
async function send(file) {
  $('#status').textContent = 'Listening to your take. This usually takes a few seconds for a short piece.';
  const form = new FormData(); form.append('piece', $('#piece').value); form.append('performance', file);
  try {
    const res = await fetch('/api/analyze', {method: 'POST', body: form});
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Analysis failed.');
    $('#status').textContent = 'Done. Opening your score.';
    location.href = data.url;
  } catch (error) {
    $('#status').textContent = error.message; $('#rec').disabled = false; $('#rec').textContent = 'Start recording';
  }
}
$('#rec').addEventListener('click', () => recorder && recorder.state === 'recording' ? stop() : start().catch(e => $('#status').textContent = e.message));

/* ---- USB MIDI keyboard: notes go straight to the aligner, no transcription ---- */
let midiAccess, midiOn = false, midiEvents = [], midiOpen = {}, midiStart = 0;
function vlq(n) { const out = [n & 0x7f]; while ((n >>= 7) > 0) out.unshift((n & 0x7f) | 0x80); return out; }
function encodeMidi(events, ppq = 480) {
  // events: [{t (ms from start), on (bool), pitch, velocity}], type-0 file at 120 bpm so 1 ms = 0.96 ticks
  const bytes = [], tempo = [0x00, 0xff, 0x51, 0x03, 0x07, 0xa1, 0x20];
  bytes.push(...tempo);
  let last = 0;
  for (const e of events.slice().sort((a, b) => a.t - b.t)) {
    const tick = Math.round(e.t * ppq / 500);
    bytes.push(...vlq(Math.max(0, tick - last)), e.on ? 0x90 : 0x80, e.pitch & 0x7f, e.on ? Math.max(1, e.velocity & 0x7f) : 0);
    last = tick;
  }
  bytes.push(0x00, 0xff, 0x2f, 0x00);
  const u32 = n => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];
  const head = [0x4d, 0x54, 0x68, 0x64, ...u32(6), 0, 0, 0, 1, (ppq >> 8) & 255, ppq & 255];
  const track = [0x4d, 0x54, 0x72, 0x6b, ...u32(bytes.length), ...bytes];
  return new Uint8Array([...head, ...track]);
}
window.__encodeMidi = encodeMidi;
function onMidiMessage(message) {
  if (!midiOn) return;
  const [status, data1, data2] = message.data, kind = status & 0xf0;
  if (kind !== 0x90 && kind !== 0x80) return;
  const on = kind === 0x90 && data2 > 0;
  if (!midiEvents.length && !on) return;
  if (!midiEvents.length) midiStart = performance.now() - 1000;  // one second of lead-in
  const t = performance.now() - midiStart;
  midiEvents.push({t, on, pitch: data1, velocity: data2});
  if (on) midiOpen[data1] = true; else delete midiOpen[data1];
  $('#midi-status').textContent = `${midiEvents.filter(e => e.on).length} notes captured`;
  $('#level i').style.width = on ? Math.min(100, data2 / 127 * 100) + '%' : '0%';
}
async function midiSetup() {
  if (!navigator.requestMIDIAccess) return;
  try {
    midiAccess = await navigator.requestMIDIAccess();
    const refresh = () => {
      const inputs = Array.from(midiAccess.inputs.values());
      $('#midi').hidden = !inputs.length;
      $('#midi-status').hidden = !inputs.length;
      if (inputs.length && !midiOn) $('#midi-status').textContent = `Keyboard found: ${inputs.map(i => i.name).join(', ')}`;
      inputs.forEach(i => i.onmidimessage = onMidiMessage);
    };
    midiAccess.onstatechange = refresh; refresh();
  } catch (error) { console.log('[pianocoach] MIDI unavailable:', error.message); }
}
async function midiToggle() {
  if (!midiOn) {
    midiOn = true; midiEvents = []; midiOpen = {}; $('#midi').textContent = 'Stop and analyse'; $('#midi').classList.add('live');
    $('#rec').disabled = true; $('#status').textContent = 'Listening to the keyboard. Play from the top.';
    return;
  }
  midiOn = false;
  const now = performance.now() - midiStart;
  for (const pitch of Object.keys(midiOpen)) midiEvents.push({t: now, on: false, pitch: +pitch, velocity: 0});
  $('#midi').classList.remove('live'); $('#midi').disabled = true; $('#midi').textContent = 'Working';
  if (!midiEvents.length) { $('#status').textContent = 'No notes came in.'; $('#midi').disabled = false; $('#midi').textContent = 'Use MIDI keyboard'; $('#rec').disabled = false; return; }
  const file = new File([encodeMidi(midiEvents)], 'take.mid', {type: 'audio/midi'});
  await send(file);
}
$('#midi').addEventListener('click', midiToggle);
midiSetup();
$('#file').addEventListener('change', () => { const f = $('#file').files[0]; if (f) { $('#rec').disabled = true; send(f); } });
pieces();
</script></body></html>"""


def _pieces():
    items = []
    for path in sorted(PIECES.glob('*')):
        if path.suffix.lower() in ('.musicxml', '.xml', '.mxl', '.pdf'):
            sidecar = path.with_suffix('.json')
            meta = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else {}
            items.append(dict(id=path.stem, file=path.name, title=meta.get('title', path.stem),
                              composer=meta.get('composer'), catalog=meta.get('catalog'),
                              bpm=meta.get('bpm', 120), meta=meta))
    return items


def _no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


def report_page():
    """The finished report page. Opens /?report=<id> by fetching that report."""
    from flask import Response
    html = UI.read_text(encoding='utf-8')
    if '</body>' in html:
        html = html.replace('</body>', LOADER + '</body>', 1)
    return _no_cache(Response(html, mimetype='text/html'))


@app.get('/')
def index():
    return report_page()


SCORE_SUFFIXES = {'.musicxml', '.xml', '.mxl', '.pdf'}
MAX_SCORE_BYTES = 20 * 1024 * 1024

UPLOAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Add sheet music</title>
<style>
:root{color-scheme:dark}
body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(1200px 600px at 20% -10%,#17323a,#0c181b);color:#eaf4f3;font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif}
main{width:min(560px,92vw);display:grid;gap:18px}h1{font-size:30px;margin:0}p{margin:0;color:#8fa7a8}
.drop{border:2px dashed #2c4a50;border-radius:18px;padding:34px 20px;text-align:center;cursor:pointer;transition:.15s}.drop.over{border-color:#5fe0b0;background:#12262b}
input[type=file]{display:none}label.f{display:grid;gap:6px;font-size:13px;color:#8fa7a8}
input[type=number]{font:inherit;color:inherit;background:#13242a;border:1px solid #23393f;border-radius:10px;padding:9px 12px;width:120px}
button,.btn{font:inherit;font-weight:600;color:#06201a;background:#5fe0b0;border:0;border-radius:999px;padding:11px 22px;cursor:pointer;text-decoration:none;display:inline-block}
.btn.ghost{background:transparent;color:#eaf4f3;border:1px solid #23393f}#msg{min-height:1.4em}#msg.err{color:#ff7a6b}
#done{display:none;background:#13242a;border:1px solid #23393f;border-radius:18px;padding:18px 20px;gap:12px}#done.show{display:grid}
ul{margin:0;padding-left:18px;color:#8fa7a8;font-size:14px}.row{display:flex;gap:10px;flex-wrap:wrap}
</style></head><body><main>
<h1>Add sheet music</h1>
<p>Any MusicXML, MXL or XML file works right away. PDFs need Audiveris installed on this computer. One piece at a time, up to 20 MB.</p>
<label class="drop" id="drop"><input type="file" id="file" accept=".musicxml,.xml,.mxl,.pdf"><span id="pick">Drop a score here, or click to choose one</span></label>
<label class="f">Tempo to use when the score has none <input type="number" id="bpm" value="100" min="20" max="400"></label>
<p id="msg"></p>
<div id="done"><strong id="title"></strong><ul id="facts"></ul>
<div class="row"><a class="btn" id="go-practice">Practice it live</a><a class="btn ghost" id="go-record">Record a take</a><a class="btn ghost" href="/">Compare with a recording</a></div></div>
<div class="row"><a class="btn ghost" href="/test">Back to the checks</a></div>
</main><script>
const $=s=>document.querySelector(s);
async function send(file){
  $('#msg').className='';$('#msg').textContent='Reading the score…';$('#done').classList.remove('show');
  const f=new FormData();f.append('score',file);f.append('bpm',$('#bpm').value);
  try{const r=await fetch('/api/pieces/upload',{method:'POST',body:f});const d=await r.json();if(!r.ok)throw Error(d.error||'Could not read this score.');
    $('#msg').textContent='';$('#title').textContent=d.title+(d.composer?' · '+d.composer:'');
    $('#facts').innerHTML=[`${d.bars} bar${d.bars===1?'':'s'}, ${d.time_signature[0]}/${d.time_signature[1]}`,`${d.notes} note${d.notes===1?'':'s'}, tempo ${Math.round(d.bpm)}`,d.reused?'This score was already added.':'Saved. Everyone using this server can pick it.'].map(t=>`<li>${t}</li>`).join('');
    $('#go-practice').href='/practice?piece='+encodeURIComponent(d.id);$('#go-record').href='/record?piece='+encodeURIComponent(d.id);$('#done').classList.add('show');
  }catch(e){$('#msg').className='err';$('#msg').textContent=e.message;}
}
$('#file').onchange=e=>e.target.files[0]&&send(e.target.files[0]);
const drop=$('#drop');['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('over');}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('over');}));
drop.addEventListener('drop',e=>e.dataTransfer.files[0]&&send(e.dataTransfer.files[0]));
</script></body></html>"""


@coach.get('/upload')
def upload_page():
    from flask import Response
    return _no_cache(Response(UPLOAD, mimetype='text/html'))


@coach.post('/api/pieces/upload')
def upload_piece():
    """Add a score to the piece list used by /practice, /record and the checks. Converted now, so a
    bad file is rejected here with a reason instead of failing later in the middle of a take."""
    import hashlib
    upload = request.files.get('score')
    if upload is None or not upload.filename:
        return jsonify(error='Choose a score file.'), 400
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in SCORE_SUFFIXES:
        return jsonify(error='Use a MusicXML, MXL, XML or PDF score.'), 400
    data = upload.stream.read(MAX_SCORE_BYTES + 1)
    if not data:
        return jsonify(error='That file is empty.'), 400
    if len(data) > MAX_SCORE_BYTES:
        return jsonify(error='Scores can be up to 20 MB.'), 413
    try:
        bpm = float(request.form.get('bpm', '100'))
        if not 20 <= bpm <= 400:
            raise ValueError
    except ValueError:
        return jsonify(error='Tempo must be between 20 and 400.'), 400
    piece_id = 'upload-' + hashlib.sha256(data).hexdigest()[:10]
    target, sidecar = PIECES / (piece_id + suffix), PIECES / (piece_id + '.json')
    cache = SESSIONS / 'scores' / piece_id
    reused = sidecar.is_file() and (cache / 'reference' / 'reference.json').is_file()
    if not reused:
        PIECES.mkdir(exist_ok=True)
        target.write_bytes(data)
        try:
            paths = convert_once(target, cache, bpm=bpm)
        except Exception as error:  # noqa: BLE001 - say why, in words
            target.unlink(missing_ok=True)
            message = str(error)
            if 'Audiveris' in message:
                message = 'PDFs need Audiveris, which is not installed on this computer. Export the score as MusicXML or MXL from MuseScore or similar and upload that.'
            return jsonify(error=f'Could not read this score: {message}'[:300]), 422
        from pianocoach.report import score_metadata
        meta = score_metadata(paths['musicxml'])
        title = meta.get('title') or Path(upload.filename).stem.replace('_', ' ').replace('-', ' ').strip().title()
        sidecar.write_text(json.dumps(dict(title=title, composer=meta.get('composer'), bpm=bpm, uploaded=True)), encoding='utf-8')
    meta = json.loads(sidecar.read_text(encoding='utf-8'))
    ref = json.loads((cache / 'reference' / 'reference.json').read_text(encoding='utf-8'))
    first = ref['chunks'][0]
    beats = first['end_beat'] - first['start_beat']
    from pianocoach.report import score_metadata as _sm, _infer_time_signature
    ts = _sm(cache / 'reference' / 'reference.musicxml').get('time_signature') or _infer_time_signature(beats)
    return jsonify(id=piece_id, title=meta['title'], composer=meta.get('composer'), bars=len(ref['chunks']),
                   notes=len(ref['notes']), bpm=ref['tempo_changes'][0][1], time_signature=ts, reused=reused)


CONVERT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Audio to MIDI</title>
<style>
:root{color-scheme:dark;--bg:#0c181b;--card:#13242a;--line:#23393f;--text:#eaf4f3;--dim:#8fa7a8;--ok:#5fe0b0;--bad:#ff7a6b;--add:#7cc4ff}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,#17323a,var(--bg));color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif}
main{max-width:980px;margin:0 auto;padding:36px 20px 80px}h1{font-size:32px;margin:0 0 4px}p{margin:0}.dim{color:var(--dim)}
.drop{display:block;border:2px dashed #2c4a50;border-radius:18px;padding:28px 20px;text-align:center;cursor:pointer;margin:22px 0 12px}.drop.over{border-color:var(--ok);background:#12262b}
input[type=file]{display:none}.opts{display:flex;gap:22px;flex-wrap:wrap;align-items:center;font-size:14px;color:var(--dim)}
.opts input[type=range]{accent-color:var(--ok);vertical-align:middle}#msg{margin:12px 0;min-height:1.4em}#msg.err{color:var(--bad)}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin:14px 0}.card h2{font-size:17px;margin:0 0 10px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}audio{width:100%;height:36px}
.facts{display:flex;gap:18px;flex-wrap:wrap;margin:6px 0 12px}.fact strong{display:block;font-size:22px}.fact span{font-size:12px;color:var(--dim)}
.roll{width:100%;height:220px;background:#0e1c20;border-radius:10px;display:block}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-top:10px}
a.btn{font-weight:600;color:#06201a;background:var(--ok);border-radius:999px;padding:8px 16px;text-decoration:none;font-size:14px}a.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}
details{margin-top:10px}summary{cursor:pointer;color:var(--dim);font-size:14px}table{width:100%;border-collapse:collapse;font-size:13px;margin-top:8px}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left}
.legend{font-size:12px;color:var(--dim);display:flex;gap:14px;margin-top:6px}.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
</style></head><body><main>
<h1>Audio to MIDI</h1>
<p class="dim">No sheet music needed. Drop in a recording of piano playing. It is cleaned with the piano cleaner, then transcribed to MIDI, and the uncleaned recording is transcribed too so you can hear and see what cleaning changes.</p>
<label class="drop" id="drop"><input type="file" id="file" accept="audio/*,.m4a,.wav,.mp3,.webm,.ogg,.flac,.aiff,.caf"><span>Drop a recording here, or click to choose one (M4A, WAV, MP3, WebM, OGG, FLAC)</span></label>
<div class="opts"><label>Cleaner strength <input type="range" id="strength" min="0" max="1" step="0.1" value="0.7"> <b id="sv">0.7</b></label>
<label><input type="checkbox" id="compare" checked> Also transcribe the uncleaned audio</label><a href="/test" class="dim">Back to the checks</a></div>
<p id="msg"></p><div id="out"></div>
</main><script>
const $=s=>document.querySelector(s);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
$('#strength').oninput=e=>$('#sv').textContent=e.target.value;
function roll(notes,dur,marks){
  if(!notes.length)return '<p class="dim">No notes detected.</p>';
  const lo=Math.min(...notes.map(n=>n.p))-2,hi=Math.max(...notes.map(n=>n.p))+2,W=940,H=220,x=t=>8+t/Math.max(dur,.5)*(W-16),y=p=>H-8-(p-lo)/(hi-lo)*(H-16),h=Math.max(3,(H-16)/(hi-lo)-1);
  let g='';for(let p=lo;p<=hi;p++){if([1,3,6,8,10].includes(((p%12)+12)%12))g+=`<rect x="0" y="${y(p)-h/2}" width="${W}" height="${h}" fill="#ffffff07"/>`;if(p%12===0)g+=`<text x="2" y="${y(p)+3}" fill="#8fa7a8" font-size="9">C${p/12-1}</text>`;}
  for(const n of notes){const k=marks&&marks.get(n.t.toFixed(2)+':'+n.p);const col=k==='add'?'var(--add)':k==='lost'?'var(--bad)':`hsl(158,62%,${38+n.v/127*30}%)`;g+=`<rect x="${x(n.t)}" y="${y(n.p)-h/2}" width="${Math.max(2,x(n.t+n.d)-x(n.t))}" height="${h}" rx="2" fill="${col}"><title>${n.name} at ${n.t.toFixed(2)} s, ${n.d.toFixed(2)} s long, velocity ${n.v}</title></rect>`;}
  return `<svg class="roll" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">${g}</svg>`;
}
function show(r){
  const f=n=>`/api/convert/${r.id}/${n}`,room=r.room;
  let html=`<div class="card"><h2>${esc(r.file)}</h2><p class="dim">Transcriber: <b>${esc(r.engine)}</b> · cleaner strength ${r.strength} · ${r.seconds} s. Loud-to-quiet spread ${room.before_db} dB${room.cleaner_skipped?' (very quiet room, the cleaner left it alone)':' → '+room.after_db+' dB after cleaning'}.</p>
  <div class="grid" style="margin-top:12px"><div><p class="dim">Original</p><audio controls preload="metadata" src="${f('original')}"></audio></div><div><p class="dim">Cleaned</p><audio controls preload="metadata" src="${f('cleaned.wav')}"></audio></div></div></div>`;
  const marks=new Map();if(r.difference){for(const n of r.difference.only_after_cleaning)marks.set(n.t.toFixed(2)+':'+n.p,'add');for(const n of r.difference.lost_by_cleaning)marks.set(n.t.toFixed(2)+':'+n.p,'lost');}
  if(r.difference){const d=r.difference;html+=`<div class="card"><h2>What cleaning changed</h2><p>${d.only_after_cleaning.length||d.lost_by_cleaning.length?`Cleaning found <b>${d.only_after_cleaning.length}</b> note${d.only_after_cleaning.length===1?'':'s'} the raw audio missed and lost <b>${d.lost_by_cleaning.length}</b>.`:'Nothing. Both versions give the same notes.'}</p>${[...d.only_after_cleaning.map(n=>'+ '+n.name+' at '+n.t.toFixed(2)+' s'),...d.lost_by_cleaning.map(n=>'− '+n.name+' at '+n.t.toFixed(2)+' s')].slice(0,30).map(x=>`<span class="dim" style="margin-right:12px">${x}</span>`).join('')}</div>`;}
  for(const [key,v] of Object.entries(r.versions)){const s=v.stats;
    html+=`<div class="card"><h2>${key==='cleaned'?'MIDI from the cleaned audio':'MIDI from the original audio'}</h2>
    <div class="facts"><div class="fact"><strong>${s.notes}</strong><span>notes</span></div><div class="fact"><strong>${s.chords}</strong><span>chords</span></div><div class="fact"><strong>${s.biggest_chord}</strong><span>biggest chord</span></div><div class="fact"><strong>${s.lowest??'–'}–${s.highest??'–'}</strong><span>range</span></div></div>
    ${roll(v.notes,v.duration,key==='cleaned'?marks:null)}
    ${r.difference?'<div class="legend"><span><i class="sw" style="background:hsl(158,62%,55%)"></i>note (brighter = louder)</span><span><i class="sw" style="background:var(--add)"></i>only found after cleaning</span></div>':''}
    <div class="row">${s.notes?`<span class="dim" style="font-size:14px">Hear the MIDI on a piano:</span><audio controls preload="metadata" src="${f(key+'-as-piano.wav')}" style="max-width:360px"></audio>`:''}<a class="btn" href="${f(key+'.mid')}" download="${esc(r.file.replace(/\.[^.]+$/,''))}-${key}.mid">Download MIDI</a></div>
    <details><summary>All ${s.notes} notes</summary><table><tr><th>Time</th><th>Note</th><th>Length</th><th>Velocity</th></tr>${v.notes.map(n=>`<tr><td>${n.t.toFixed(2)} s</td><td>${n.name}</td><td>${n.d.toFixed(2)} s</td><td>${n.v}</td></tr>`).join('')}</table></details>
    ${v.warnings.length?`<p class="dim" style="margin-top:8px">${v.warnings.map(esc).join(' ')}</p>`:''}</div>`;}
  $('#out').innerHTML=html;history.replaceState(null,'','/convert?id='+r.id);
}
async function send(file){
  $('#msg').className='';$('#msg').textContent='Cleaning and transcribing… a few seconds per minute of audio.';$('#out').innerHTML='';
  const fd=new FormData();fd.append('audio',file);fd.append('strength',$('#strength').value);fd.append('compare',$('#compare').checked?'1':'0');
  try{const res=await fetch('/api/convert',{method:'POST',body:fd});const d=await res.json();if(!res.ok)throw Error(d.error||'Conversion failed.');$('#msg').textContent='';show(d);}
  catch(e){$('#msg').className='err';$('#msg').textContent=e.message;}
}
$('#file').onchange=e=>e.target.files[0]&&send(e.target.files[0]);
const drop=$('#drop');['dragenter','dragover'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.add('over');}));
['dragleave','drop'].forEach(t=>drop.addEventListener(t,e=>{e.preventDefault();drop.classList.remove('over');}));
drop.addEventListener('drop',e=>e.dataTransfer.files[0]&&send(e.dataTransfer.files[0]));
const id=new URLSearchParams(location.search).get('id');
if(id)fetch('/api/convert/'+encodeURIComponent(id)+'/result.json').then(r=>r.ok?r.json():Promise.reject()).then(r=>{r.id=id;show(r);}).catch(()=>{$('#msg').className='err';$('#msg').textContent='That conversion was not found.';});
</script></body></html>"""

CONVERT_FILES = {'cleaned.wav', 'cleaned.mid', 'original.mid', 'cleaned-as-piano.wav', 'original-as-piano.wav', 'result.json'}


@coach.get('/convert')
def convert_page():
    from flask import Response
    return _no_cache(Response(CONVERT_PAGE, mimetype='text/html'))


@coach.post('/api/convert')
def convert_route():
    from pianocoach.convert import AUDIO_TYPES, CONVERT, convert_audio
    upload = request.files.get('audio')
    if upload is None or not upload.filename:
        return jsonify(error='Choose a recording.'), 400
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in AUDIO_TYPES:
        return jsonify(error='Use an audio file: M4A, WAV, MP3, WebM, OGG, FLAC, AIFF or CAF.'), 400
    try:
        strength = float(request.form.get('strength', '0.7'))
        if not 0 <= strength <= 1:
            raise ValueError
    except ValueError:
        return jsonify(error='Cleaner strength must be between 0 and 1.'), 400
    staging = CONVERT / ('.upload-' + uuid.uuid4().hex)
    staging.mkdir(parents=True)
    source = staging / ('upload' + suffix)
    upload.save(source)
    try:
        result = convert_audio(source, compare=request.form.get('compare', '1') != '0', strength=strength)
        result['file'] = Path(upload.filename).name
        (CONVERT / result['id'] / 'result.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
        return jsonify(result)
    except TooFewNotes as error:
        return jsonify(error=str(error)), 422
    except Exception as error:  # noqa: BLE001 - show the reason on the page
        return jsonify(error=f'{type(error).__name__}: {error}'[:400]), 500
    finally:
        import shutil
        shutil.rmtree(staging, ignore_errors=True)


@coach.get('/api/convert/<run_id>/<name>')
def convert_file(run_id, name):
    from pianocoach.convert import CONVERT
    if not ID.match(run_id):
        abort(404)
    folder = CONVERT / run_id
    if name == 'original':
        matches = sorted(folder.glob('original.*'))
        if not matches:
            abort(404)
        return _no_cache(send_file(matches[0]))
    if name not in CONVERT_FILES or not (folder / name).is_file():
        abort(404)
    return _no_cache(send_file(folder / name, as_attachment=name.endswith('.mid')))


@coach.get('/record')
def record():
    from flask import Response
    return _no_cache(Response(RECORD, mimetype='text/html'))


@coach.get('/api/pieces')
def pieces():
    return jsonify([{k: v for k, v in p.items() if k != 'meta'} for p in _pieces()])


def _session_dir(report_id):
    if report_id == 'latest':
        dirs = [d for d in SESSIONS.iterdir() if d.is_dir() and ID.match(d.name) and (d / 'report.json').is_file()]
        if not dirs:
            abort(404)
        return max(dirs, key=lambda d: (d / 'report.json').stat().st_mtime)
    if not ID.match(report_id):
        abort(404)
    directory = SESSIONS / report_id
    if not directory.is_dir():
        abort(404)
    return directory


@coach.get('/api/report/<report_id>')
def report(report_id):
    path = _session_dir(report_id) / 'report.json'
    if not path.is_file():
        abort(404)
    return _no_cache(send_file(path, mimetype='application/json'))


@coach.get('/api/audio/<report_id>')
def audio(report_id):
    matches = [p for p in _session_dir(report_id).glob('recording.*') if p.suffix.lower() in AUDIO_SUFFIXES]
    if not matches:
        abort(404)
    return _no_cache(send_file(matches[0]))


@coach.post('/api/analyze')
def analyze_route():
    upload = request.files.get('performance')
    if upload is None or not upload.filename:
        return jsonify(error='Attach a recording or a MIDI file as "performance".'), 400
    suffix = Path(upload.filename).suffix.lower()
    if suffix not in AUDIO_SUFFIXES | MIDI_SUFFIXES:
        return jsonify(error=f'Unsupported file type {suffix or "(none)"}.'), 400
    pieces = {p['id']: p for p in _pieces()}
    piece = pieces.get(request.form.get('piece', ''))
    score_upload = request.files.get('score')
    if piece is None and (score_upload is None or not score_upload.filename):
        return jsonify(error='Choose a piece or attach a score.'), 400

    session_id = uuid.uuid4().hex
    directory = SESSIONS / session_id
    directory.mkdir(parents=True)
    performance = directory / f'recording{suffix}'
    upload.save(performance)
    if piece is not None:
        score = PIECES / piece['file']
        score_cache = SESSIONS / 'scores' / piece['id']
        meta = dict(title=piece['title'], composer=piece.get('composer'), catalog=piece.get('catalog'))
        bpm = piece.get('bpm', 120)
    else:
        score = directory / ('score' + Path(score_upload.filename).suffix.lower())
        score_upload.save(score)
        score_cache = directory / 'score'
        meta, bpm = {}, 120
    try:
        take = int(request.form.get('take', '1'))
        explain = request.form.get('explain', '1') != '0'
        analyze(score, performance, directory, bpm=bpm, take_number=take, piece=meta,
                hands=request.form.get('hands', 'right'), explain=explain, score_cache=score_cache)
    except TooFewNotes as error:
        return jsonify(error=str(error)), 422
    except Exception as error:  # noqa: BLE001 - surface the message to the page
        return jsonify(error=f'{type(error).__name__}: {error}'[:400]), 500
    return jsonify(id=session_id, url=f'/?report={session_id}')


app.register_blueprint(coach)


def warm_transcriber():
    """Load the transcriber in the background so the first take is not slow."""
    from threading import Thread
    from pianocoach.pipeline import transcriber

    def warm():
        backend = transcriber()
        if backend is None:
            print('[pianocoach] transcriber: Basic Pitch (bundled)', flush=True)
            return
        info = backend.start()
        print(f"[pianocoach] transcriber: Transkun on {info.get('device')} (loaded in {info.get('load_seconds')} s)", flush=True)

    Thread(target=warm, daemon=True).start()


def run_server(port=5002):
    SESSIONS.mkdir(exist_ok=True)
    warm_transcriber()
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_server(int(sys.argv[1]) if len(sys.argv) > 1 else 5002)
