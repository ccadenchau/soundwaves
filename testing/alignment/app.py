"""Single-file local Flask preview. Run: python testing/alignment/app.py."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from testing.alignment.pipeline import CACHE, compare_files, store_upload

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 102 * 1024 * 1024

# The new PianoCoach pages share this server and port: /test (one-click checks), /practice (live
# screen), /record (mic, file or MIDI keyboard), and /?report=<id> (the review page).
from pianocoach.app import coach, report_page  # noqa: E402
from pianocoach.live import practice  # noqa: E402
from pianocoach.selftest import selftest  # noqa: E402

for _blueprint in (coach, practice, selftest):
    app.register_blueprint(_blueprint)

PAGE = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Soundwaves · Alignment</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f3f5fa;color:#17243a;font:16px system-ui,sans-serif}
main{max-width:1150px;margin:36px auto;padding:0 22px}h1{margin-bottom:8px}h2{font-size:21px}
.muted{color:#576780}.card{background:white;border:1px solid #dce3ef;border-radius:14px;padding:22px;margin:20px 0}
form{display:grid;grid-template-columns:1fr 1fr;gap:18px}label{display:block;font-weight:600}
input{display:block;max-width:100%;width:100%;margin-top:8px;padding:10px;border:1px solid #aebdd2;border-radius:7px}
button{background:#315bdb;color:white;border:0;border-radius:7px;padding:11px 18px;cursor:pointer}
button:disabled{opacity:.6}.wide{grid-column:1/-1}.metrics{display:flex;gap:28px;flex-wrap:wrap}.metric strong{display:block;font-size:29px}
.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:14px}th,td{text-align:left;vertical-align:top;padding:13px 9px;border-bottom:1px solid #e1e7ef}
th{white-space:nowrap}progress{width:90px;accent-color:#25805c}.badge{display:inline-block;border-radius:6px;padding:4px 7px;background:#edf0f7;white-space:nowrap}
.on_target{background:#dff3e8;color:#155b3a}.too_fast,.too_slow,.irregular{background:#fff0d3;color:#805000}
.error{background:#ffe8e6;color:#852a22}.links{display:flex;gap:15px;flex-wrap:wrap}a{color:#244fca}audio{width:100%;margin:12px 0}
small{font-weight:400}ul{padding-left:21px}li{margin:7px 0}.seek{padding:6px 9px;font-size:13px}
.notation{height:650px;overflow:auto;background:#fff;border:1px solid #dce3ef;border-radius:10px;margin-top:16px}
.notation>svg{display:block;width:100%;min-width:900px;height:auto;border-bottom:1px solid #dce3ef}
.notation .note{cursor:pointer}.notation .note.matched{color:#16804a;fill:#16804a}
.notation .note.missed{color:#c07700;fill:#c07700}.notation .note.wrong{color:#c43d48;fill:#c43d48}
.notation .active-note{filter:drop-shadow(0 0 35px #2684ff);stroke:#2684ff;stroke-width:14}
.notation .played-marker{color:#793bcc;fill:#793bcc;cursor:pointer}
.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:14px}.score-tools{display:flex;gap:18px;align-items:center;flex-wrap:wrap}
.score-tools label{display:flex;align-items:center;gap:7px;font-weight:400}.score-tools input{width:auto;margin:0}
.notation.hide-overlays .played-marker{display:none}.notation.hide-overlays .note{color:black;fill:black}
@media(max-width:650px){form{grid-template-columns:1fr}.wide{grid-column:auto}.card{padding:15px}}
</style>
<main><h1>Performance alignment</h1><p class="muted">Compare sheet music with your piano recording. See correct pitches and tempo separately, bar by bar.</p>
<p class="muted" style="margin-top:-6px"><strong>New on this server:</strong> <a href="/test">Run the one-click checks</a> · <a href="/practice">Live practice screen</a> · <a href="/record">Record a take</a> · <a href="/upload">Add sheet music for live practice</a> · <a href="/convert">Audio to MIDI only (no sheet music)</a>. This page now uses the better transcriber, note cleaning and partial-take detection too.</p>
<section class="card"><form method="post" action="{{ url_for('index') }}" enctype="multipart/form-data" id="upload">
<label>Sheet music <small>PDF, MusicXML, XML, MXL · up to 20 MB</small>
<input type="file" name="sheet" accept=".pdf,.musicxml,.xml,.mxl"></label>
<label>Recording <small>MP3, WAV, M4A · up to 80 MB, 10 minutes</small>
<input type="file" name="recording" accept=".mp3,.wav,.m4a,.webm,.ogg,.flac,audio/*" required></label>
<label>Or a direct sheet download URL<input type="url" name="sheet_url" placeholder="https://example.com/score.pdf"></label>
<label>Fallback score tempo (BPM)<input type="number" name="bpm" min="20" max="400" step="any" value="120" required></label>
<div class="wide"><button type="submit" id="submit">Compare performance</button>
<p class="muted" id="status">With the basic transcriber, recordings first go through the piano-safe cleaner (full keyboard range kept, nothing trimmed, quiet rooms left untouched); with Transkun the original recording is used. Use the same passage in both files. First-time conversion may take several minutes; later comparisons reuse the cache.</p></div>
</form></section>
{% if error %}<section class="card error" role="alert">{{ error }}</section>{% endif %}
{% if result %}{% set report = result.report %}{% set metrics = report.metrics %}
<section class="card"><h2>Alignment: {{ report.alignment.status }}</h2>
<div class="metrics">
<div class="metric"><strong>{{ '%.1f'|format(metrics.pitch_recall * 100) }}%</strong>Expected pitches matched</div>
<div class="metric"><strong>{{ '%.1f'|format(metrics.pitch_precision * 100) }}%</strong>Played notes matching</div>
<div class="metric"><strong>{{ metrics.tempo_assessed_measures }}/{{ report.measures|length }}</strong>Bars with tempo estimates</div>
</div><p class="muted">These are candidate note matches, not a certainty score for the alignment path.</p>
{% if result.cache %}<p>Score conversion: {{ 'cache reused' if result.cache.sheet_hit else 'newly cached' }} · Recording conversion: {{ 'cache reused' if result.cache.recording_hit else 'newly cached' }}</p>{% endif %}
{% if result.cleaned %}
<h2>Cleaned recording</h2>
<p class="muted">Bar and note listen buttons use this recording. Cleaning may trim silence, so its timestamps can differ from the original.</p>
{% if result.cache and result.cache.cleaning_hit is defined %}<p>Audio cleaning: {{ 'cache reused' if result.cache.cleaning_hit else 'newly cached' }}</p>{% endif %}
{% else %}<h2>Recording</h2>{% endif %}
<audio controls preload="metadata" id="audio" src="{{ url_for('artifact', report_id=result.report_id, kind='audio') }}"></audio>
{% if result.cleaned %}
<p><a href="{{ url_for('artifact', report_id=result.report_id, kind='cleaned_audio', download=1) }}">Download cleaned WAV</a></p>
<details><summary>Original MP3 recording</summary><audio controls preload="none" src="{{ url_for('artifact', report_id=result.report_id, kind='original_audio') }}"></audio></details>
{% endif %}
{% if result.midi_playback %}
<h2>MIDI playback</h2><p class="muted">Synthesized previews of the actual MIDI files, including their note timing. The sheet MIDI follows the score tempo; the recording MIDI follows your performance.</p>
<label>Sheet MIDI<audio controls preload="none" src="{{ url_for('artifact', report_id=result.report_id, kind='sheet_midi_audio') }}"></audio></label>
<label>Recording MIDI<audio controls preload="none" src="{{ url_for('artifact', report_id=result.report_id, kind='recording_midi_audio') }}"></audio></label>
{% endif %}
<div class="links">
{% for kind, label in [('report','JSON report'),('sheet_midi','Sheet MIDI'),('recording_midi','Recording MIDI'),('musicxml','Recognized score'),('repairs','Score repair log')] %}
<a href="{{ url_for('artifact', report_id=result.report_id, kind=kind) }}">{{ label }}</a>
{% endfor %}</div></section>
<section class="card" id="score-view" data-url="{{ url_for('notation', report_id=result.report_id) }}">
<h2>Follow your performance on the score</h2>
<p class="muted">Play the recording to follow detected notes. Click a colored note to listen there. Purple noteheads show the detected pitch; hover or focus for the exact note and time. Extra notes sit beside the nearest matched note in their bar.</p>
<div class="legend"><span style="color:#16804a">● Matched</span><span style="color:#c07700">● Missing</span><span style="color:#c43d48">● Expected, different pitch played</span><span style="color:#793bcc">● Played pitch / extra</span></div>
<p class="muted">This is the recognized score with repeats expanded. Detected notes and their score locations are estimates{% if report.alignment.status != 'aligned' %}; alignment is uncertain, so treat placement cautiously{% endif %}.</p>
<div class="score-tools"><label><input type="checkbox" id="show-overlays" checked>Show performance overlay</label><label><input type="checkbox" id="follow-score" checked>Follow playback</label><label>Zoom <select id="score-zoom"><option value="1">100%</option><option value="1.25">125%</option><option value="1.5">150%</option><option value="2">200%</option></select></label><span id="playing-notes" aria-live="polite">Ready to play</span></div>
<p id="notation-status" role="status">Rendering sheet music…</p>
<div class="notation" id="notation" aria-label="Sheet music with detected performance notes"></div>
<details id="unplaced-notes" hidden><summary>Notes without a reliable score location</summary><div></div></details>
</section>
<section class="card"><h2>Bar-by-bar comparison</h2><div class="scroll"><table>
<thead><tr><th>Bar</th><th>Pitch matches</th><th>Missing / wrong / extra</th><th>Tempo</th><th>Score → played BPM</th><th>Feedback</th></tr></thead><tbody>
{% for bar in report.measures %}<tr>
<td><strong>{{ bar.number }}</strong><br><small>Pass {{ bar.occurrence + 1 }}</small>
{% if bar.estimated_start_seconds is not none %}<p><button class="seek" data-time="{{ [0,bar.estimated_start_seconds]|max }}">Listen {{ '%.1f'|format([0,bar.estimated_start_seconds]|max) }}s</button></p>{% endif %}</td>
<td>{{ bar.correct_notes }}/{{ bar.expected_notes }}<br>{% if bar.pitch_recall is not none %}<progress aria-label="Pitch recall" max="1" value="{{ bar.pitch_recall }}"></progress>{% else %}No attacks{% endif %}</td>
<td>{{ bar.missing_notes }} / {{ bar.wrong_pitch_notes }} / {{ bar.extra_notes }}</td>
<td><span class="badge {{ bar.tempo_status }}">{{ bar.tempo_status|replace('_',' ') }}</span>
{% if bar.tempo_ratio is not none %}<br><small>{{ '%.2f'|format(bar.tempo_ratio) }}× score speed</small>{% endif %}</td>
<td>{{ '%.1f'|format(bar.reference_average_bpm) }} → {{ '%.1f'|format(bar.performed_average_bpm) if bar.performed_average_bpm is not none else '—' }}</td>
<td>{% for line in bar.feedback %}<div>{{ line }}</div>{% endfor %}</td></tr>{% endfor %}
</tbody></table></div></section>
<section class="card"><details><summary>Candidate note discrepancies ({{ report.errors|length }})</summary><div class="scroll"><table>
<tr><th>Bar</th><th>Type</th><th>Expected / played MIDI pitch</th><th>Recording</th></tr>
{% for error in report.errors %}<tr><td>{{ error.measure if error.measure is not none else 'Unassigned' }}</td><td>{{ error.category }}</td>
<td>{{ error.expected_pitch if error.expected_pitch is not none else '—' }} / {{ error.actual_pitch if error.actual_pitch is not none else '—' }}</td>
<td>{% if error.audio_time is not none %}<button class="seek" data-time="{{ error.audio_time }}">{{ '%.2f'|format(error.audio_time) }}s</button>{% else %}No detected attack{% endif %}</td></tr>{% endfor %}
</table></div></details></section>
<section class="card"><h2>Assessment notes</h2><ul>{% for warning in report.warnings %}<li>{{ warning }}</li>{% endfor %}</ul></section>
{% endif %}
</main><script>
document.getElementById('upload').addEventListener('submit',()=>{
document.getElementById('submit').disabled=true;
document.getElementById('status').textContent='Converting sheet and original recording, preparing MIDI playback, then aligning bars. Keep this page open…';
});
document.querySelectorAll('.seek').forEach(button=>button.addEventListener('click',()=>{
const audio=document.getElementById('audio');audio.currentTime=Number(button.dataset.time);audio.play().catch(()=>{});
}));
// Keep comparisons audible by allowing only one audio player at a time.
document.querySelectorAll('audio').forEach(player=>player.addEventListener('play',()=>{
document.querySelectorAll('audio').forEach(other=>{if(other!==player)other.pause();});
}));
</script><script src="{{ url_for('static', filename='notation.js') }}" defer></script></html>'''


def _report_directory(report_id):
    if not re.fullmatch(r'[0-9a-f]{32}', report_id):
        abort(404)
    directory = CACHE / 'reports' / report_id
    if not (directory / 'report.json').is_file():
        abort(404)
    return directory


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'GET':
        if request.args.get('report'):
            return report_page()  # the PianoCoach review page, e.g. after /record or /test
        return render_template_string(PAGE, result=None, error=None)
    try:
        sheet = request.files.get('sheet')
        sheet_url = request.form.get('sheet_url', '').strip()
        recording = request.files.get('recording')
        if bool(sheet and sheet.filename) == bool(sheet_url):
            raise ValueError('Supply either a sheet file or a direct download URL.')
        if not recording or not recording.filename:
            raise ValueError('Supply a recording (MP3, WAV or M4A).')
        if sheet_url and not sheet_url.lower().startswith(('http://', 'https://')):
            raise ValueError('Sheet URLs must start with http:// or https://.')
        source = sheet_url if sheet_url else store_upload(sheet)
        audio = store_upload(recording, recording=True)
        result = compare_files(source, audio, bpm=float(request.form.get('bpm', '120')))
        directory = _report_directory(result['report_id'])
        (directory / 'cache.json').write_text(json.dumps(result['cache']), encoding='utf-8')
        return redirect(url_for('show_report', report_id=result['report_id']))
    except RequestEntityTooLarge:
        raise
    except Exception as error:
        app.logger.exception('Alignment comparison failed')
        return render_template_string(PAGE, result=None, error=str(error)), 400


@app.get('/report/<report_id>')
def show_report(report_id):
    directory = _report_directory(report_id)
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    cache_path = directory / 'cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else None
    artifacts = json.loads((directory / 'artifacts.json').read_text(encoding='utf-8'))
    return render_template_string(PAGE, result=dict(
        report=report, report_id=report_id, cache=cache, cleaned='cleaned_audio' in artifacts,
        midi_playback='sheet_midi_audio' in artifacts and 'recording_midi_audio' in artifacts), error=None)


@app.get('/artifact/<report_id>/<kind>')
def artifact(report_id, kind):
    directory = _report_directory(report_id)
    manifest = json.loads((directory / 'artifacts.json').read_text(encoding='utf-8'))
    if kind not in manifest:
        abort(404)
    path = (CACHE / manifest[kind]).resolve()
    if not path.is_relative_to(CACHE.resolve()) or not path.is_file():
        abort(404)
    inline_audio = kind in {'audio', 'cleaned_audio', 'original_audio', 'sheet_midi_audio', 'recording_midi_audio'}
    mimetype = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav'}.get(path.suffix.lower()) if inline_audio else None
    return send_file(path, as_attachment=not inline_audio or request.args.get('download') == '1',
                     conditional=True, mimetype=mimetype)


@app.get('/report/<report_id>/notation')
def notation(report_id):
    from testing.alignment.notation import build_notation
    from testing.alignment.pipeline import _cached, _hash, _write_json
    from importlib.metadata import version

    directory = _report_directory(report_id)
    artifacts = json.loads((directory / 'artifacts.json').read_text(encoding='utf-8'))
    paths = {}
    for kind in ('musicxml', 'sheet_notes', 'recording_notes'):
        if kind not in artifacts:
            abort(404)
        path = (CACHE / artifacts[kind]).resolve()
        if not path.is_relative_to(CACHE.resolve()) or not path.is_file():
            abort(404)
        paths[kind] = path
    try:
        signature = json.dumps(dict(
            renderer=_hash(Path(__file__).with_name('notation.py')),
            verovio=version('verovio'), reference=_hash(paths['sheet_notes']),
            performance=_hash(paths['recording_notes']), report=_hash(directory / 'report.json')),
            sort_keys=True)
        def build(stage):
            data = build_notation(paths['musicxml'], paths['sheet_notes'], paths['recording_notes'],
                                  json.loads((directory / 'report.json').read_text(encoding='utf-8')))
            _write_json(stage / 'notation.json', data)
        result, _ = _cached('notation', paths['musicxml'], signature, build, dict(data='notation.json'))
        return send_file(result['data'], mimetype='application/json')
    except Exception:
        app.logger.exception('Score visualization failed')
        return jsonify(error='Could not render the score overlay. Check that requirements.txt is installed; the recording and report remain available.'), 422


@app.errorhandler(RequestEntityTooLarge)
def too_large(error):
    return render_template_string(PAGE, result=None,
                                  error='Upload too large. Sheet limit: 20 MB; recording limit: 80 MB.'), 413


def run_server(port=5001):
    from pianocoach.app import warm_transcriber
    print(f'Open http://127.0.0.1:{port} to upload your sheet music and recording.', flush=True)
    print(f'  one-click checks: http://127.0.0.1:{port}/test   live practice: http://127.0.0.1:{port}/practice', flush=True)
    print('Press Ctrl+C to stop the server.', flush=True)
    warm_transcriber()
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    run_server()
