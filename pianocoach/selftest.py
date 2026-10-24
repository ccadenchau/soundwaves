"""Check the audio/MIDI converters end to end with takes that have known mistakes.

    .venv/bin/python -m pianocoach.selftest            # all cases, prints PASS/FAIL, exit 1 on failure
    .venv/bin/python -m pianocoach.selftest mistakes   # one case

The same cases back the buttons on http://127.0.0.1:5001/test. Each case renders a piano
recording (or MIDI file) of the Minuet in G with mistakes planted at known places, runs the
real pipeline, and compares what it found with what was planted. Nothing here calls an
explanation service.
"""

import json
import shutil
import sys
import time
import uuid
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flask import Blueprint, Response, abort, jsonify  # noqa: E402

from pianocoach.pipeline import TooFewNotes, analyze, transcriber  # noqa: E402

PIECE = ROOT / 'pianocoach' / 'pieces' / 'minuet_in_g.mxl'
CACHE = Path(__file__).with_name('cache') / 'selftest'
SESSIONS = Path(__file__).with_name('sessions')
SCORE_CACHE = SESSIONS / 'scores' / 'minuet_in_g'
META = dict(title='Minuet in G major', composer='Christian Petzold', catalog='BWV Anh. 114')

MISTAKES = dict(wrong=['3:3.5'], drop=['7:2'], rush=['5'], late=['15:2:150'])

CASES = {
    'mistakes': dict(
        title='Piano recording with four mistakes',
        text='Renders a sampled-piano take, then checks that every planted mistake is found: '
             'F♯5 played as F5 (bar 3), G4 skipped (bar 7), bar 5 rushed, B4 150 ms late (bar 15).'),
    'clean': dict(
        title='Piano recording with no mistakes',
        text='The same piece played correctly. Nothing should be flagged.'),
    'midi': dict(
        title='MIDI keyboard take with the same mistakes',
        text='Skips transcription, as a USB keyboard would. Same four mistakes, found with full confidence.'),
    'partial': dict(
        title='Only the first four bars played',
        text='The student stops early. Only bars 1 to 4 may be marked, nothing after.'),
    'silent': dict(
        title='Silent recording',
        text='A dead microphone. The take must be refused with a clear message, not marked as 200 missing notes.'),
}


def make_take(kind):
    """Path to the take for a case, rendered once and cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    if kind == 'silent':
        path = CACHE / 'silent.wav'
        if not path.exists():
            with wave.open(str(path), 'wb') as h:
                h.setnchannels(1); h.setsampwidth(2); h.setframerate(16000); h.writeframes(b'\x00\x00' * 16000 * 3)
        return path
    from testing.make_demo_take import build
    if kind == 'midi':
        path = CACHE / 'mistakes.mid'
        if not path.exists():
            import pretty_midi
            wav = make_take('mistakes')
            events = json.loads((wav.parent / 'mistakes' / 'events.json').read_text())
            midi = pretty_midi.PrettyMIDI()
            piano = pretty_midi.Instrument(program=0)
            for e in events:
                piano.notes.append(pretty_midi.Note(velocity=int(e['velocity']), pitch=int(e['pitch']),
                                                    start=float(e['start_seconds']), end=float(e['end_seconds'])))
            midi.instruments.append(piano)
            midi.write(str(path))
        return path
    folder = CACHE / kind
    wav = folder / 'take.wav'
    if not wav.exists():
        if kind == 'mistakes':
            build(PIECE, folder, score_cache=SCORE_CACHE, **MISTAKES)
        elif kind == 'clean':
            build(PIECE, folder, score_cache=SCORE_CACHE)
        elif kind == 'partial':
            build(PIECE, folder, score_cache=SCORE_CACHE, max_bars=4)
        else:
            raise KeyError(kind)
    shutil.copy(wav, CACHE / f'{kind}.wav')
    return CACHE / f'{kind}.wav'


def _find(report, category, measure, **fields):
    return next((e for e in report['errors'] if e['category'] == category and e['measure'] == measure
                 and all(e.get(k) == v for k, v in fields.items())), None)


def evaluate(kind, report, transcriber_name):
    """[(label, ok, detail, required)]. Optional checks warn instead of failing."""
    strict = transcriber_name in ('transkun', 'midi')
    found = [f"{e['category']} bar {e['measure']}" for e in report['errors']]
    # A partial take covers under half the piece, so overall recall is low by design.
    checks = [] if kind == 'partial' else [
        ('The take was located and aligned', report['meta']['alignment_status'] == 'aligned',
         f"status {report['meta']['alignment_status']}, pitch recall {report['meta']['pitch_recall']:.2f}", True)]
    if kind in ('mistakes', 'midi'):
        wrong = _find(report, 'wrong_pitch', 3, expected='F#5', actual='F5')
        missing = _find(report, 'missing', 7, expected='G4')
        late = _find(report, 'timing', 15, expected='B4')
        checks += [
            ('Wrong note: F♯5 played as F5, bar 3', wrong is not None, 'found' if wrong else 'not found', True),
            ('Skipped note: G4, bar 7', missing is not None, 'found' if missing else 'not found', True),
            ('Late note: B4 about 150 ms late, bar 15', late is not None and 80 <= late.get('delta_ms', 0) <= 250,
             f"{late['delta_ms']} ms" if late else 'not found', True),
            ('Rushed bar: bar 5', 5 in report['pace']['rushed_bars'], f"rushed bars {report['pace']['rushed_bars']}", True),
        ]
        extras = len(report['errors']) - sum(x is not None for x in (wrong, missing, late))
        checks.append(('No false alarms beyond the planted mistakes', extras <= 1,
                       f'{extras} unplanned finding{"s" if extras != 1 else ""}'
                       + ('' if extras <= 1 else ' (' + ', '.join(found[:6]) + '). Basic Pitch is noisier than Transkun.'),
                       strict))
    elif kind == 'clean':
        n = len(report['errors'])
        checks.append(('Nothing flagged on a correct performance', n <= 2,
                       f'{n} finding{"s" if n != 1 else ""}' + ('' if n <= 2 else ': ' + ', '.join(found[:6])), strict))
    elif kind == 'partial':
        played = report['meta']['played_bars']
        n = len(report['errors'])
        checks += [('Only the played bars are marked (1 to 4)', played == [1, 4], f'played bars {played}', True),
                   ('Nothing flagged in them', n <= 1, f'{n} finding{"s" if n != 1 else ""}', strict)]
    return checks


def run_case(kind, explain=False):
    if kind not in CASES:
        raise KeyError(kind)
    started = time.time()
    take = make_take(kind)
    session = uuid.uuid4().hex
    out = SESSIONS / session
    out.mkdir(parents=True)
    recording = out / ('recording' + take.suffix)
    shutil.copy(take, recording)
    result = dict(kind=kind, title=CASES[kind]['title'], id=None, url=None, seconds=0.0, transcriber=None)
    try:
        report, paths = analyze(PIECE, recording, out, bpm=108, piece=META, hands='right',
                                explain=explain, score_cache=SCORE_CACHE)
    except TooFewNotes as error:
        result['checks'] = [('Refused with a message the student can act on', kind == 'silent', str(error), True)]
        result['transcriber'] = 'n/a'
    else:
        pre = json.loads(Path(paths['alignment']).read_text()).get('preprocessing', {})
        name = 'midi' if take.suffix == '.mid' else pre.get('transcriber', 'basic-pitch')
        result.update(id=session, url=f'/?report={session}', transcriber=name)
        result['checks'] = evaluate(kind, report, name)
        if kind == 'silent':
            result['checks'] = [('Refused with a message the student can act on', False, 'the take was analysed instead', True)]
    result['seconds'] = round(time.time() - started, 1)
    result['ok'] = all(ok for _, ok, _, required in result['checks'] if required)
    result['checks'] = [dict(label=l, ok=ok, detail=d, required=r) for l, ok, d, r in result['checks']]
    return result


# ---------------------------------------------------------------- web page

selftest = Blueprint('selftest', __name__)

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Test the converters</title>
<style>
:root{color-scheme:dark;--bg:#0c181b;--card:#13242a;--line:#23393f;--text:#eaf4f3;--dim:#8fa7a8;--ok:#5fe0b0;--bad:#ff7a6b;--warn:#f2c14e}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(1200px 600px at 20% -10%,#17323a,var(--bg));color:var(--text);font:16px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif}
main{max-width:860px;margin:0 auto;padding:40px 20px 80px}h1{font-size:34px;margin:0 0 6px;letter-spacing:-.02em}
p.lead{color:var(--dim);margin:0 0 24px}.chips{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:28px}
.chip{border:1px solid var(--line);border-radius:999px;padding:5px 12px;font-size:13px;color:var(--dim)}.chip b{color:var(--text);font-weight:600}.chip.good{border-color:#2c6b57}.chip.warn{border-color:#7a6221}
.bar{display:flex;gap:10px;flex-wrap:wrap;margin:0 0 20px}
button,.btn{font:inherit;font-weight:600;color:#06201a;background:var(--ok);border:0;border-radius:999px;padding:10px 20px;cursor:pointer;text-decoration:none;display:inline-block}
button.ghost,.btn.ghost{background:transparent;color:var(--text);border:1px solid var(--line)}button[disabled]{opacity:.5;cursor:default}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px 20px;margin-bottom:14px}
.card h2{font-size:18px;margin:0 0 4px}.card p{margin:0 0 12px;color:var(--dim);font-size:14px}.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.state{font-size:14px;color:var(--dim)}.state.pass{color:var(--ok)}.state.fail{color:var(--bad)}
ul.checks{list-style:none;margin:14px 0 0;padding:0;font-size:14px}ul.checks li{padding:5px 0;border-top:1px solid var(--line);display:flex;gap:10px}
.mark{width:18px;flex:none;text-align:center}.mark.ok{color:var(--ok)}.mark.no{color:var(--bad)}.mark.warn{color:var(--warn)}.detail{color:var(--dim)}
h3{margin:34px 0 10px;font-size:16px;color:var(--dim);font-weight:600;letter-spacing:.04em;text-transform:uppercase}
input[type=file]{color:var(--dim);font:inherit}a{color:var(--ok)}
</style></head><body><main>
<h1>Test the converters</h1>
<p class="lead">Each case plays the Minuet in G with mistakes planted at known places, runs the real pipeline, and checks that what comes out matches what went in.</p>
<div class="chips" id="chips"></div>
<div class="bar"><button id="all">Run all checks</button><a class="btn ghost" href="/practice">Open the live practice screen</a><a class="btn ghost" href="/record">Record a take</a></div>
<div id="cases"></div>
<h3>Try your own recording</h3>
<div class="card"><p>Upload a WAV, MP3, M4A or MIDI file of someone playing the Minuet in G. You get the full review page.</p>
<form id="own" class="row"><input type="file" name="performance" accept="audio/*,.wav,.mp3,.m4a,.webm,.mid,.midi" required><input type="hidden" name="piece" value="minuet_in_g"><input type="hidden" name="explain" value="0"><button type="submit">Analyse</button><span class="state" id="own-state"></span></form></div>
</main>
<script>
const $=s=>document.querySelector(s);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CASES=__CASES__;
const chips=(label,value,cls='')=>`<span class="chip ${cls}">${label} <b>${esc(value)}</b></span>`;
async function status(){
  const s=await (await fetch('/api/selftest/status')).json();
  const base=chips('Transcriber',s.transcriber==='transkun'?'Transkun (best)':'Basic Pitch (install Transkun for better results)',s.transcriber==='transkun'?'good':'warn')+chips('Explanations',s.explainer,s.explainer_key?'good':'')+chips('Piece',s.piece);
  const extra={};const draw=()=>{$('#chips').innerHTML=base+Object.values(extra).join('');};draw();
  const wait=(p,ms)=>Promise.race([p,new Promise((_,no)=>setTimeout(()=>no(Error('timeout')),ms))]);
  (async()=>{try{const m=await wait(navigator.requestMIDIAccess(),4000);const n=[...m.inputs.values()].length;extra.midi=chips('MIDI keyboards',n?`${n} connected`:'none found',n?'good':'');}catch(e){extra.midi=chips('MIDI keyboards','not allowed or not available');}draw();})();
  (async()=>{try{const p=await navigator.permissions.query({name:'microphone'});extra.mic=chips('Microphone',p.state,p.state==='granted'?'good':p.state==='denied'?'warn':'');draw();}catch(e){}})();
}
function renderResult(el,r){
  const state=el.querySelector('.state');state.className='state '+(r.ok?'pass':'fail');
  state.textContent=(r.ok?'PASS':'FAIL')+` · ${r.seconds} s`+(r.transcriber&&r.transcriber!=='n/a'?` · ${r.transcriber}`:'');
  el.querySelector('ul').innerHTML=r.checks.map(c=>`<li><span class="mark ${c.ok?'ok':c.required?'no':'warn'}">${c.ok?'✓':c.required?'✗':'!'}</span><span>${esc(c.label)} <span class="detail">· ${esc(c.detail)}</span></span></li>`).join('');
  const link=el.querySelector('.open');link.hidden=!r.url;if(r.url)link.href=r.url;
}
async function run(kind){
  const el=$('#case-'+kind),btn=el.querySelector('button'),state=el.querySelector('.state');
  btn.disabled=true;state.className='state';state.textContent='Running… the first run renders the piano take and takes a bit longer';el.querySelector('ul').innerHTML='';
  try{const res=await fetch('/api/selftest/run/'+kind,{method:'POST'});const r=await res.json();if(!res.ok)throw Error(r.error||'failed');renderResult(el,r);return r.ok;}
  catch(e){state.className='state fail';state.textContent='FAIL · '+e.message;return false;}
  finally{btn.disabled=false;}
}
$('#cases').innerHTML=Object.entries(CASES).map(([k,c])=>`<div class="card" id="case-${k}"><h2>${esc(c.title)}</h2><p>${esc(c.text)}</p><div class="row"><button onclick="run('${k}')">Run</button><span class="state">Not run yet</span><a class="open" hidden target="_blank">Open the result ↗</a></div><ul class="checks"></ul></div>`).join('');
$('#all').onclick=async()=>{$('#all').disabled=true;let pass=0;for(const k of Object.keys(CASES))if(await run(k))pass++;$('#all').textContent=`${pass} of ${Object.keys(CASES).length} passed · run again`;$('#all').disabled=false;};
$('#own').onsubmit=async e=>{e.preventDefault();const s=$('#own-state');s.textContent='Listening to your take…';try{const res=await fetch('/api/analyze',{method:'POST',body:new FormData(e.target)});const d=await res.json();if(!res.ok)throw Error(d.error||'Analysis failed.');location.href=d.url;}catch(err){s.className='state fail';s.textContent=err.message;}};
window.run=run;status();
</script></body></html>"""


@selftest.get('/test')
def page():
    body = PAGE.replace('__CASES__', json.dumps({k: dict(title=v['title'], text=v['text']) for k, v in CASES.items()}))
    response = Response(body, mimetype='text/html')
    response.headers['Cache-Control'] = 'no-store'
    return response


@selftest.get('/api/selftest/status')
def status():
    from pianocoach.explain import provider
    import os
    backend = transcriber()
    which = provider()
    key = bool(os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'))
    return jsonify(transcriber='transkun' if backend is not None else 'basic-pitch', explainer=which if key else 'plain wording (no key set)',
                   explainer_key=key, piece=META['title'])


@selftest.post('/api/selftest/run/<kind>')
def run(kind):
    if kind not in CASES:
        abort(404)
    try:
        return jsonify(run_case(kind))
    except Exception as error:  # noqa: BLE001 - show the reason on the page
        return jsonify(error=f'{type(error).__name__}: {error}'[:400]), 500


def main(argv):
    kinds = argv[1:] or list(CASES)
    unknown = [k for k in kinds if k not in CASES]
    if unknown:
        print(f'Unknown case {unknown}. Choose from: {", ".join(CASES)}')
        return 2
    print('Rendering takes and running the pipeline. The first run is slower (it renders the piano audio).\n')
    failed = 0
    for kind in kinds:
        r = run_case(kind)
        print(f"{'PASS' if r['ok'] else 'FAIL'}  {CASES[kind]['title']}  ({r['seconds']} s, {r['transcriber']})")
        for c in r['checks']:
            print(f"      {'✓' if c['ok'] else ('✗' if c['required'] else '!')} {c['label']} · {c['detail']}")
        failed += not r['ok']
    print(f"\n{len(kinds) - failed} of {len(kinds)} passed.")
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
