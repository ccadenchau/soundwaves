"""Main PianoCoach Flask app. Run from the repository root with python3 run.py."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, abort, jsonify, redirect, render_template_string, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from pianocoach.web.pipeline import CACHE, compare_files, store_upload, wait_for_feedback
from pianocoach.web.wording import plain_feedback as _plain_feedback

app = Flask(__name__)
ROOT_DIR = Path(__file__).resolve().parents[2]
app.config['MAX_CONTENT_LENGTH'] = 102 * 1024 * 1024

# The new PianoCoach pages share this server and port: /test (one-click checks), /practice (live
# screen), /record (mic, file or MIDI keyboard), and /?report=<id> (the review page).
from pianocoach.app import coach, report_page  # noqa: E402
from pianocoach.live import practice  # noqa: E402
from pianocoach.selftest import selftest  # noqa: E402
from pianocoach.web.live_demo import live_demo  # noqa: E402

for _blueprint in (coach, practice, selftest, live_demo):
    app.register_blueprint(_blueprint)

HOME = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>PianoCoach</title>{{ site_head|safe }}
<body>{{ site_header('')|safe }}<main>
<h1>Practise from your sheet music.<br>PianoCoach marks every note.</h1>
<p class="lede">For people teaching themselves piano. Play a piece you are learning and the score turns green where you were right and red, orange or purple where you weren't, bar by bar, with notes on tempo and what to practise next.</p>
<div class="paths" style="margin-top:22px">
  <section class="card"><h2>Play live</h2><p>Pick a piece, press Start and play into the microphone. Mistakes show up on the score about two seconds after you make them. When you stop you get the full review.</p><a class="btn" href="/live">Play live</a></section>
  <section class="card"><h2>Check a recording</h2><p>Already recorded yourself? Upload the recording and its sheet music and get the same review: every note, every bar, and a teacher's notes.</p><a class="btn ghost" href="/check">Check a recording</a></section>
</div>
<section class="card"><h2>How it works</h2>
<p class="muted" style="margin:0">Your sheet music (PDF or MusicXML) is read into notes. Your playing is turned into notes by Transkun, a piano transcription model. The two are lined up note by note, so a wrong key, a skipped note, an extra note or a rushed bar is found where it happened. The teacher's notes are written by Claude from those findings and the one-line bar notes by Gemini; neither model ever hears the audio or decides what was right. Measured on real student recordings with hand-labelled mistakes: 190 of 191 caught, 98% of flags real. Don't have a piece yet? <a href="/upload">Add one</a>.</p></section>
</main>{{ site_footer|safe }}</body></html>'''

CHECK = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Check a recording · PianoCoach</title>{{ site_head|safe }}
<style>form{display:grid;grid-template-columns:1fr 1fr;gap:18px}.wide{grid-column:1/-1}@media(max-width:650px){form{grid-template-columns:1fr}.wide{grid-column:auto}}</style>
<body>{{ site_header('check')|safe }}<main>
<h1>Check a recording</h1>
<p class="lede">Upload a recording of yourself and the sheet music you played from. Use the same passage in both.</p>
<section class="card"><form method="post" action="{{ url_for('check') }}" enctype="multipart/form-data" id="upload">
<label>Sheet music <small>PDF, MusicXML or MXL, up to 20 MB</small><input type="file" name="sheet" accept=".pdf,.musicxml,.xml,.mxl"></label>
<label>Recording <small>MP3, WAV or M4A, up to 10 minutes</small><input type="file" name="recording" accept=".mp3,.wav,.m4a,.webm,.ogg,.flac,audio/*" required></label>
<label>Or a link to the sheet music <small>a direct PDF or MusicXML download</small><input type="url" name="sheet_url" placeholder="https://example.com/score.pdf"></label>
<label>Tempo if the score has none <small>beats per minute</small><input type="number" name="bpm" min="20" max="400" step="any" value="120" required></label>
<div class="wide"><button type="submit" id="submit">Check my playing</button>
<p class="muted" id="status">A new PDF takes a minute or two to read the first time. After that the same piece is instant.</p></div>
</form></section>
{% if error %}<section class="card error" role="alert">{{ error }}</section>{% endif %}
</main>{{ site_footer|safe }}<script>
document.getElementById('upload').addEventListener('submit',()=>{document.getElementById('submit').disabled=true;
document.getElementById('status').textContent='Reading the sheet music and listening to your recording. Keep this page open…';});
</script></body></html>'''

REPORT = '''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ summary.title }} · PianoCoach</title>{{ site_head|safe }}
<style>
.notation{height:620px}.notation .note{cursor:pointer}
.notation .active-note{color:var(--here)!important;fill:var(--here)!important}
.notation .played-marker{cursor:pointer}
.notation .dynamic-wedge{fill:none;stroke:#58677c;stroke-width:5;stroke-linecap:round}.notation .dynamic-wedge.good{stroke:var(--matched)}.notation .dynamic-wedge.wrong{stroke:var(--wrong)}
.score-tools{display:flex;gap:18px;align-items:center;flex-wrap:wrap}.score-tools label{display:flex;align-items:center;gap:7px;font-weight:400}.score-tools select{width:auto;margin:0}
#score-play{min-width:5.5rem;text-align:center}
#playing-notes{display:block;height:1.5em;line-height:1.5;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:10px 0}
#notation{overflow-anchor:none;overscroll-behavior:contain;scrollbar-gutter:stable}
.notation.hide-overlays .played-marker{display:none}.notation.hide-overlays .note{color:black;fill:black}
.links{display:flex;gap:15px;flex-wrap:wrap}.kicker{color:var(--muted);font-weight:600;font-size:14px;letter-spacing:.04em;text-transform:uppercase;margin:0}
#teacher-body .focus{border-left:4px solid var(--accent);padding:2px 14px;margin:14px 0}
#ask{margin-top:18px;border-top:1px solid var(--line);padding-top:14px}#ask h3{margin-top:0}
#ask-chips button{background:#eef2fb;color:var(--accent);border:1px solid #c9d6f5;padding:6px 11px;font-size:14px;font-weight:600}
#ask-form{display:flex;gap:10px;align-items:stretch;margin-top:8px}#ask-form input{margin:0;flex:1}
#ask-log .q{font-weight:600;margin:12px 0 4px}#ask-log .a{background:#f8fafd;border-left:4px solid var(--accent);padding:8px 12px;border-radius:0 8px 8px 0;margin:0 0 4px;white-space:pre-wrap}
td .barnote{font-weight:600;margin-bottom:4px}
</style>
<body>{{ site_header('')|safe }}<main>
{% set report = result.report %}{% set metrics = report.metrics %}
<p class="kicker">Your review</p>
<h1>{{ summary.title }}</h1>
<p class="lede">{{ summary.line }}</p>
<section class="card"><div class="metrics">
<div class="metric"><strong>{{ summary.bars }}</strong>Bars played</div>
<div class="metric ok"><strong>{{ '%.0f'|format(metrics.pitch_recall * 100) }}%</strong>Score notes you got right</div>
<div class="metric bad"><strong>{{ summary.wrong }}</strong>Wrong keys</div>
<div class="metric miss"><strong>{{ summary.missing }}</strong>Skipped notes</div>
<div class="metric extra"><strong>{{ summary.extra }}</strong>Extra notes</div>
<div class="metric"><strong>{{ summary.tempo }}</strong>Your tempo (score {{ summary.score_bpm }})</div>
</div>
<p class="muted">Transcription: {{ 'Transkun' if report.preprocessing.transcriber == 'transkun' else 'Basic Pitch' }}.</p>
<audio controls preload="metadata" id="audio" src="{{ url_for('artifact', report_id=result.report_id, kind='audio') }}"></audio>
<div class="links"><button type="button" id="play-cleaned">Play cleaned audio</button><a class="btn" href="/live{% if summary.piece_id %}?piece={{ summary.piece_id|urlencode }}{% endif %}">Play it again live</a><a class="btn ghost" href="{{ url_for('check') }}">Check another recording</a></div>
</section>

<section class="card" id="teacher" data-url="{{ url_for('report_feedback', report_id=result.report_id) }}" data-piece="{{ summary.piece_id or '' }}">
<h2>Notes from your teacher</h2><p class="muted" id="teacher-status">Writing feedback…</p><div id="teacher-body"></div>
<div id="ask" hidden><h3>Ask your teacher</h3>
<div class="legend" id="ask-chips"></div>
<div id="ask-log"></div>
<form id="ask-form"><input id="ask-q" placeholder="Why do you say I rushed bars 1 to 8?" maxlength="500" autocomplete="off"><button type="submit" id="ask-go">Ask</button></form>
<p class="muted" id="ask-note" style="font-size:13px;margin:6px 0 0">Answers come from the note-by-note comparison of this take, not from listening again.</p></div></section>

<section class="card" id="score-view" data-url="{{ url_for('notation', report_id=result.report_id) }}">
<h2>Your playing on the score</h2>
<p class="muted">Choose Detected MIDI to hear the notes the app detected while they light up on your sheet music. Switch to Recorded audio to compare at the same moment. Click a coloured note to replay it; purple marks detected wrong or extra notes.</p>
<div class="legend"><span style="color:var(--matched)">● Right</span><span style="color:var(--missed)">● Skipped</span><span style="color:var(--wrong)">● Wrong key (the written note)</span><span style="color:var(--extra)">● What you played / extra</span><span class="muted">Hairpins: green followed, red needs more shape</span></div>
<div class="score-tools">
<label>Playback <select id="playback-mode"><option value="{{ url_for('artifact', report_id=result.report_id, kind='audio') }}">Recorded audio</option><option value="{{ url_for('artifact', report_id=result.report_id, kind='cleaned_audio') }}">Cleaned audio</option>{% if result.midi_playback %}<option value="{{ url_for('artifact', report_id=result.report_id, kind='recording_midi_audio') }}">Detected MIDI</option>{% endif %}</select></label>
<button type="button" id="score-play" disabled>Play</button>
<label>Speed <select id="playback-speed"><option value="0.5">0.5×</option><option value="0.75">0.75×</option><option value="1" selected>1×</option></select></label>
<label><input type="checkbox" id="show-overlays" checked>Show my notes</label><label><input type="checkbox" id="follow-score" checked>Follow playback</label><label>Zoom <select id="score-zoom"><option value="1">100%</option><option value="1.25">125%</option><option value="1.5">150%</option><option value="2">200%</option></select></label></div><p id="playing-notes" aria-live="polite" class="muted">Ready to play</p>
<p id="notation-status" role="status" class="muted">Drawing the score…</p>
<div class="notation" id="notation" aria-label="Sheet music with your notes"></div>
<details id="unplaced-notes" hidden><summary>Notes without a clear place in the score</summary><div></div></details>
</section>

<section class="card"><h2>Bar by bar</h2><div class="scroll"><table>
<thead><tr><th>Bar</th><th>Notes right</th><th>Skipped / wrong / extra</th><th>Tempo</th><th>Score → you (BPM)</th><th>Timing and touch</th><th>Feedback</th></tr></thead><tbody>
{% for bar in report.measures %}<tr>
<td><strong>{{ bar.number }}</strong>{% if summary.repeats %}<br><small>Pass {{ bar.occurrence + 1 }}</small>{% endif %}
{% if bar.estimated_start_seconds is not none %}<p><button class="seek" data-time="{{ [0,bar.estimated_start_seconds]|max }}">Listen</button></p>{% endif %}</td>
<td>{{ bar.correct_notes }}/{{ bar.expected_notes }}<br>{% if bar.pitch_recall is not none %}<progress aria-label="Notes right" max="1" value="{{ bar.pitch_recall }}"></progress>{% endif %}</td>
<td>{{ bar.missing_notes }} / {{ bar.wrong_pitch_notes }} / {{ bar.extra_notes }}</td>
<td><span class="badge {{ bar.tempo_status }}">{{ {'on_target':'steady','too_fast':'rushed','too_slow':'dragged','irregular':'uneven','unassessed':'not enough notes'}.get(bar.tempo_status, bar.tempo_status|replace('_',' ')) }}</span>
{% if bar.tempo_ratio is not none %}<br><small>{{ '%.2f'|format(bar.tempo_ratio) }}× score speed</small>{% endif %}</td>
<td>{{ '%.0f'|format(bar.reference_average_bpm) }} → {{ '%.0f'|format(bar.performed_average_bpm) if bar.performed_average_bpm is not none else '—' }}</td>
<td>{% if bar.median_absolute_timing_error_seconds is not none %}Off the beat by {{ '%.0f'|format(bar.median_absolute_timing_error_seconds * 1000) }} ms<br><small>{{ bar.early_notes }} early · {{ bar.late_notes }} late</small><br>{% endif %}
{% if bar.median_duration_ratio is not none %}Notes held {{ '%.2f'|format(bar.median_duration_ratio) }}× as long as written<br>{% endif %}
{% if bar.relative_dynamics_level_difference is not none %}Loudness {{ '%+.1f'|format(bar.relative_dynamics_level_difference) }} vs your average<br>{% endif %}
{% if bar.dynamics_trend %}{{ bar.dynamics_trend|replace('_',' ')|capitalize }}{% endif %}</td>
<td data-bar="{{ bar.number }}">{% for line in bar.feedback %}<div>{{ line }}</div>{% endfor %}</td></tr>{% endfor %}
</tbody></table></div><p class="muted" id="barnote-caption" hidden style="font-size:13px"></p>
{% if report.played_span and report.played_span.unplayed_bars_hidden %}<p class="muted">{{ report.played_span.unplayed_bars_hidden }} bar{{ '' if report.played_span.unplayed_bars_hidden == 1 else 's' }} you didn't reach {{ 'is' if report.played_span.unplayed_bars_hidden == 1 else 'are' }} left out.</p>{% endif %}
</section>

<section class="card"><h2>Right and wrong keys</h2>
<p class="muted">Your recording on a keyboard. A key lights green when you played the right note and red when you didn't; a dashed outline shows the key the sheet wanted.</p>
<iframe title="Right and wrong keys" src="/falling?embed=1&api={{ url_for('report_falling', report_id=result.report_id)|urlencode }}" style="width:100%;height:230px;border:1px solid var(--line);border-radius:10px;background:#0c181b" allow="autoplay"></iframe></section>

<section class="card"><details><summary>Details and downloads</summary>
<p class="muted">Matching: {{ '%.0f'|format(metrics.pitch_precision * 100) }}% of the notes you played match the score. Alignment status: {{ report.alignment.status }}. Note matches are estimates from audio, not certainties.{% if metrics.median_relative_dynamics_difference is not none %} Loudness is compared with the average of your own correct notes, not measured in decibels.{% endif %}</p>
{% if result.cache %}<p class="muted">Score: {{ 'reused' if result.cache.sheet_hit else 'read now' }} · Recording: {{ 'reused' if result.cache.recording_hit else 'transcribed now' }}</p>{% endif %}
{% if result.midi_playback %}
<h3>Hear the notes</h3><p class="muted">Synthesized from the score, and from what was heard in your recording.</p>
<label>The score<audio controls preload="none" src="{{ url_for('artifact', report_id=result.report_id, kind='sheet_midi_audio') }}"></audio></label>
<label>Your playing, as heard<audio controls preload="none" src="{{ url_for('artifact', report_id=result.report_id, kind='recording_midi_audio') }}"></audio></label>
{% endif %}
<div class="links">{% for kind, label in [('report','JSON report'),('sheet_midi','Score MIDI'),('recording_midi','Your MIDI'),('musicxml','Score as read'),('repairs','Score repair log')] %}
<a href="{{ url_for('artifact', report_id=result.report_id, kind=kind) }}">{{ label }}</a>{% endfor %}</div>
<h3>Every finding</h3><div class="scroll"><table>
<tr><th>Bar</th><th>Type</th><th>Written / played</th><th>Recording</th></tr>
{% for error in report.errors %}<tr><td>{{ error.measure if error.measure is not none else '—' }}</td><td>{{ {'missing':'skipped','wrong_pitch':'wrong key','extra':'extra','timing':'timing'}.get(error.category, error.category) }}</td>
<td>{{ error.expected_name or '—' }} / {{ error.actual_name or '—' }}</td>
<td>{% if error.audio_time is not none %}<button class="seek" data-time="{{ error.audio_time }}">{{ '%.1f'|format(error.audio_time) }} s</button>{% endif %}</td></tr>{% endfor %}
</table></div>
{% if report.warnings %}<h3>Caveats</h3><ul class="muted">{% for warning in report.warnings %}<li>{{ warning }}</li>{% endfor %}</ul>{% endif %}
</details></section>
</main>{{ site_footer|safe }}<script>
(async()=>{const box=document.getElementById('teacher');if(!box)return;
const status=document.getElementById('teacher-status'),body=document.getElementById('teacher-body');
const el=(tag,text,parent)=>{const e=document.createElement(tag);e.textContent=text;parent.appendChild(e);return e;};
try{const r=await fetch(box.dataset.url);const d=await r.json();if(!r.ok)throw Error(d.error||'Could not get feedback.');
status.remove();el('p',d.summary,body).style.fontSize='18px';
if(d.strengths&&d.strengths.length){el('h3','Going well',body);const u=el('ul','',body);d.strengths.forEach(t=>el('li',t,u));}
if(d.focus_areas&&d.focus_areas.length){el('h3','What to work on',body);d.focus_areas.forEach(f=>{const c=document.createElement('div');c.className='focus';body.appendChild(c);
el('strong',f.title+(f.bars?' · '+f.bars:''),c);el('p',f.what_happened,c);const u=el('ul','',c);f.tips.forEach(t=>el('li',t,u));
const bar=(f.bars||'').match(/[0-9]+/);if(bar&&box.dataset.piece){const a=document.createElement('a');a.className='btn ghost';a.style.cssText='padding:7px 14px;font-size:14px;margin-top:4px';a.href=`/live?piece=${encodeURIComponent(box.dataset.piece)}&bar=${bar[0]}`;a.textContent=`Practise from bar ${bar[0]} live`;c.appendChild(a);}});}
if(d.practice_plan){el('h3','Next practice session',body);el('p',d.practice_plan,body);}
if(d.written_by){const w=el('p',`Written by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from the note-by-note comparison above.`,body);w.className='muted';w.style.fontSize='13px';}
askBox(d);
}catch(e){status.textContent=e.message;}})();
function askBox(notes){
  const box=document.getElementById('ask'),log=document.getElementById('ask-log'),form=document.getElementById('ask-form'),input=document.getElementById('ask-q'),go=document.getElementById('ask-go');
  const history=[];box.hidden=false;
  const first=(notes.focus_areas||[])[0];
  const chips=[first&&first.bars?`Why do you say that about ${first.bars}?`:'What should I fix first?','What should I practise first tomorrow?','Which hand needs more work?'];
  document.getElementById('ask-chips').innerHTML=chips.map(c=>`<button type="button">${c.replace(/</g,'&lt;')}</button>`).join('');
  document.querySelectorAll('#ask-chips button').forEach(b=>b.addEventListener('click',()=>{input.value=b.textContent;form.requestSubmit();}));
  form.addEventListener('submit',async ev=>{ev.preventDefault();const q=input.value.trim();if(!q||go.disabled)return;
    const qEl=document.createElement('p');qEl.className='q';qEl.textContent=q;log.appendChild(qEl);
    const aEl=document.createElement('p');aEl.className='a muted';aEl.textContent='Thinking…';log.appendChild(aEl);
    input.value='';go.disabled=true;
    try{const r=await fetch(document.getElementById('teacher').dataset.url.replace('/feedback','/ask'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,history})});
      const d=await r.json();if(!r.ok)throw Error(d.error||'No answer.');aEl.textContent=d.answer;aEl.classList.remove('muted');history.push({role:'user',content:q},{role:'assistant',content:d.answer});
      document.getElementById('ask-note').textContent=`Answered by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from the note-by-note comparison of this take, not from listening again.`;
    }catch(e){aEl.textContent=e.message;}finally{go.disabled=false;input.focus();}
  });
}
(async()=>{const box=document.getElementById('teacher');if(!box)return;
try{const r=await fetch(box.dataset.url.replace('/feedback','/bar-notes'));const d=await r.json();if(!r.ok)return;
let n=0;for(const [bar,note] of Object.entries(d.bars||{})){const td=document.querySelector(`td[data-bar="${bar}"]`);if(!td)continue;const div=document.createElement('div');div.className='barnote';div.textContent=note;td.prepend(div);n++;}
if(n){const cap=document.getElementById('barnote-caption');cap.textContent=`The first line in each Feedback cell is written by ${/claude/i.test(d.written_by)?'Claude':'Gemini'} from that bar's measurements; the lines after it are the measurements in words.`;cap.hidden=false;}
}catch(e){}})();
document.querySelectorAll('.seek').forEach(button=>button.addEventListener('click',()=>{
const audio=document.getElementById('audio');audio.currentTime=Number(button.dataset.time);audio.play().catch(()=>{});}));
document.querySelectorAll('audio').forEach(player=>player.addEventListener('play',()=>{
document.querySelectorAll('audio').forEach(other=>{if(other!==player)other.pause();});}));
</script><script src="{{ url_for('static', filename='notation.js') }}" defer></script></html>'''


def _report_directory(report_id):
    if not re.fullmatch(r'[0-9a-f]{32}', report_id):
        abort(404)
    directory = CACHE / 'reports' / report_id
    if not (directory / 'report.json').is_file():
        abort(404)
    return directory


def _render(template, **context):
    from pianocoach.site import FOOTER, HEAD, header
    return render_template_string(template, site_head=HEAD, site_header=header, site_footer=FOOTER, **context)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return check()  # older links posted the comparison form here
    if request.args.get('report'):
        return report_page()  # the first review page, still used by /record and the self-checks
    return _render(HOME)


@app.route('/check', methods=['GET', 'POST'])
def check():
    if request.method == 'GET':
        return _render(CHECK, error=None)
    try:
        sheet = request.files.get('sheet')
        sheet_url = request.form.get('sheet_url', '').strip()
        recording = request.files.get('recording')
        if bool(sheet and sheet.filename) == bool(sheet_url):
            raise ValueError('Choose a sheet music file or paste a link to one (not both).')
        if not recording or not recording.filename:
            raise ValueError('Choose your recording (MP3, WAV or M4A).')
        if sheet_url and not sheet_url.lower().startswith(('http://', 'https://')):
            raise ValueError('Sheet music links must start with http:// or https://.')
        source = sheet_url if sheet_url else store_upload(sheet)
        audio = store_upload(recording, recording=True)
        piece_id, title = _known_piece(source)
        title = title or (Path(sheet.filename).stem.replace('_', ' ').replace('-', ' ').strip().title()
                          if sheet and sheet.filename else None)
        result = compare_files(source, audio, bpm=float(request.form.get('bpm', '120')), title=title, piece_id=piece_id)
        directory = _report_directory(result['report_id'])
        (directory / 'cache.json').write_text(json.dumps(result['cache']), encoding='utf-8')
        return redirect(url_for('show_report', report_id=result['report_id']))
    except RequestEntityTooLarge:
        raise
    except Exception as error:
        app.logger.exception('Alignment comparison failed')
        return _render(CHECK, error=str(error)), 400


def _known_piece(source):
    """(piece id, name) when this sheet music was already added on Add a piece, else (None, None)."""
    import hashlib
    try:
        piece_id = 'upload-' + hashlib.sha256(Path(source).read_bytes()).hexdigest()[:10]
        sidecar = ROOT_DIR / 'pianocoach' / 'pieces' / f'{piece_id}.json'
        if sidecar.is_file():
            return piece_id, json.loads(sidecar.read_text(encoding='utf-8')).get('title')
    except (OSError, ValueError):
        pass
    return None, None


def _summary(report, directory):
    """The few numbers and one sentence at the top of a review."""
    from statistics import median
    from music21 import pitch
    meta_path = directory / 'meta.json'
    meta = json.loads(meta_path.read_text(encoding='utf-8')) if meta_path.is_file() else {}
    title, piece_id = meta.get('title'), meta.get('piece_id')
    bars = report['measures']
    numbers = [b['number'] for b in bars]
    span = f'{min(numbers)}–{max(numbers)}' if numbers and min(numbers) != max(numbers) else str(numbers[0]) if numbers else '—'
    counts = {k: sum(m['category'] == k for m in report['matches']) for k in ('missing', 'wrong_pitch', 'extra')}
    played = [b['performed_average_bpm'] for b in bars if b.get('performed_average_bpm')]
    score_bpm = round(bars[0]['reference_average_bpm']) if bars else None
    tempo = round(median(played)) if played else None
    for e in report['errors']:  # names for the findings table
        e['expected_name'] = pitch.Pitch(midi=e['expected_pitch']).nameWithOctave if e.get('expected_pitch') is not None else None
        e['actual_name'] = pitch.Pitch(midi=e['actual_pitch']).nameWithOctave if e.get('actual_pitch') is not None else None
    right = report['metrics']['pitch_recall']
    if tempo and score_bpm and tempo > score_bpm * 1.15:
        pace = f'faster than written ({tempo} against {score_bpm})'
    elif tempo and score_bpm and tempo < score_bpm * 0.85:
        pace = f'slower than written ({tempo} against {score_bpm})'
    else:
        pace = 'close to the written tempo'
    line = (f'You played bar{"s" if "–" in span else ""} {span} and got {right:.0%} of the written notes, '
            f'{pace}. Start with the teacher notes below, then look for red and orange on the score.')
    return dict(title=title or 'Your take', piece_id=piece_id, bars=span, tempo=tempo or '—', score_bpm=score_bpm or '—', line=line,
                wrong=counts['wrong_pitch'], missing=counts['missing'], extra=counts['extra'],
                repeats=len(set(numbers)) != len(numbers))


@app.get('/report/<report_id>')
def show_report(report_id):
    directory = _report_directory(report_id)
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    cache_path = directory / 'cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else None
    artifacts = json.loads((directory / 'artifacts.json').read_text(encoding='utf-8'))
    for bar in report['measures']:
        bar['feedback'] = _plain_feedback(bar)
    return _render(REPORT, summary=_summary(report, directory), result=dict(
        report=report, report_id=report_id, cache=cache, cleaned='cleaned_audio' in artifacts,
        midi_playback='sheet_midi_audio' in artifacts and 'recording_midi_audio' in artifacts))


@app.get('/report/<report_id>/falling.json')
def report_falling(report_id):
    """This comparison's played notes, green where they match the sheet and red where they do not."""
    from pianocoach.teacher import falling_notes
    directory = _report_directory(report_id)
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    return jsonify(id=report_id, title='', **falling_notes(report))


def _meta_title(directory):
    meta = directory / 'meta.json'
    return json.loads(meta.read_text(encoding='utf-8')).get('title', '') if meta.is_file() else ''


@app.get('/report/<report_id>/feedback')
def report_feedback(report_id):
    """The teacher's written notes (Claude, or Gemini without an Anthropic key), cached with the report."""
    from pianocoach.teacher import FeedbackUnavailable, teacher_feedback
    directory = _report_directory(report_id)
    wait_for_feedback(report_id, 'teacher')  # started when the comparison finished; usually ready by now
    try:
        return jsonify(teacher_feedback(json.loads((directory / 'report.json').read_text(encoding='utf-8')), directory, _meta_title(directory)))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


@app.get('/report/<report_id>/bar-notes')
def report_bar_notes(report_id):
    """One line per bar (Gemini), cached with the report."""
    from pianocoach.teacher import FeedbackUnavailable, bar_notes
    directory = _report_directory(report_id)
    wait_for_feedback(report_id, 'bars')
    try:
        return jsonify(bar_notes(json.loads((directory / 'report.json').read_text(encoding='utf-8')), directory, _meta_title(directory)))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


@app.post('/report/<report_id>/ask')
def report_ask(report_id):
    """A question about this review, answered from the comparison (Claude)."""
    from pianocoach.teacher import FeedbackUnavailable, answer_question
    directory = _report_directory(report_id)
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(answer_question(json.loads((directory / 'report.json').read_text(encoding='utf-8')), directory,
                                       _meta_title(directory), body.get('question', ''), body.get('history') or []))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


@app.get('/artifact/<report_id>/<kind>')
def artifact(report_id, kind):
    directory = _report_directory(report_id)
    manifest = json.loads((directory / 'artifacts.json').read_text(encoding='utf-8'))
    source_kind = 'audio' if kind == 'cleaned_audio' and kind not in manifest else kind
    if source_kind not in manifest:
        abort(404)
    path = (CACHE / manifest[source_kind]).resolve()
    if not path.is_relative_to(CACHE.resolve()) or not path.is_file():
        abort(404)
    if kind == 'cleaned_audio' and source_kind == 'audio':
        from audio_cleaner.clean_audio import clean_audio
        from pianocoach.web.pipeline import _cached, _hash

        signature = _hash(ROOT_DIR / 'audio_cleaner' / 'clean_audio.py')
        try:
            cleaned, _ = _cached('cleaned-audio', path, signature,
                lambda stage: clean_audio(path, stage / 'cleaned.wav', mode='piano'),
                dict(audio='cleaned.wav'))
            path = cleaned['audio']
        except Exception:
            app.logger.exception('Audio cleanup failed')
            return jsonify(error='Could not clean this recording. Original audio is still available.'), 422
    inline_audio = kind in {'audio', 'cleaned_audio', 'original_audio', 'sheet_midi_audio', 'recording_midi_audio'}
    mimetype = {'.mp3': 'audio/mpeg', '.wav': 'audio/wav'}.get(path.suffix.lower()) if inline_audio else None
    return send_file(path, as_attachment=not inline_audio or request.args.get('download') == '1',
                     conditional=True, mimetype=mimetype)


@app.get('/report/<report_id>/notation')
def notation(report_id):
    from pianocoach.web.notation import build_notation
    from pianocoach.web.pipeline import _cached, _hash, _write_json
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
    warm_transcriber()
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    run_server()
