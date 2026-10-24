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

from flask import Flask, abort, jsonify, request, send_file  # noqa: E402

from pianocoach.pipeline import AUDIO_SUFFIXES, MIDI_SUFFIXES, TooFewNotes, analyze  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'pianocoach-ui' / 'index.html'
PIECES = Path(__file__).with_name('pieces')
SESSIONS = Path(__file__).with_name('sessions')
ID = re.compile(r'^[a-f0-9]{32}$')

app = Flask(__name__)
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
  $('#piece').innerHTML = list.map(p => `<option value="${p.id}">${p.title}</option>`).join('') || '<option value="">(no pieces in pianocoach/pieces)</option>';
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


@app.get('/')
def index():
    html = UI.read_text(encoding='utf-8')
    if '</body>' in html:
        html = html.replace('</body>', LOADER + '</body>', 1)
    return _no_cache(app.response_class(html, mimetype='text/html'))


@app.get('/record')
def record():
    return _no_cache(app.response_class(RECORD, mimetype='text/html'))


@app.get('/api/pieces')
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


@app.get('/api/report/<report_id>')
def report(report_id):
    path = _session_dir(report_id) / 'report.json'
    if not path.is_file():
        abort(404)
    return _no_cache(send_file(path, mimetype='application/json'))


@app.get('/api/audio/<report_id>')
def audio(report_id):
    matches = [p for p in _session_dir(report_id).glob('recording.*') if p.suffix.lower() in AUDIO_SUFFIXES]
    if not matches:
        abort(404)
    return _no_cache(send_file(matches[0]))


@app.post('/api/analyze')
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


def run_server(port=5002):
    SESSIONS.mkdir(exist_ok=True)
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
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_server(int(sys.argv[1]) if len(sys.argv) > 1 else 5002)
