"""Main Soundwaves Flask app. Run from the repository root with python3 run.py."""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from soundwaves.web.pipeline import CACHE, compare_files, store_upload, wait_for_feedback
from soundwaves.web.wording import plain_feedback as _plain_feedback

app = Flask(__name__, template_folder=str(Path(__file__).resolve().parents[2] / "frontend/templates"),
            static_folder=str(Path(__file__).resolve().parents[2] / "frontend/static"), static_url_path="/static")
ROOT_DIR = Path(__file__).resolve().parents[2]
app.config['MAX_CONTENT_LENGTH'] = 102 * 1024 * 1024

# All page blueprints use the templates and assets in frontend/.
from soundwaves.app import coach  # noqa: E402
from soundwaves.live import practice  # noqa: E402
from soundwaves.selftest import selftest  # noqa: E402
from soundwaves.web.live_demo import live_demo  # noqa: E402

for _blueprint in (coach, practice, selftest, live_demo):
    app.register_blueprint(_blueprint)


def _report_directory(report_id):
    if not re.fullmatch(r'[0-9a-f]{32}', report_id):
        abort(404)
    directory = CACHE / 'reports' / report_id
    if not (directory / 'report.json').is_file():
        from soundwaves.app import SESSIONS
        session = SESSIONS / report_id
        if not (session / 'review_artifacts.json').is_file():
            abort(404)
        from soundwaves.web.pipeline import import_session
        directory = import_session(session)
    return directory


def _render(template, **context):
    from soundwaves.site import FOOTER, HEAD, header
    return render_template(template, site_head=HEAD, site_header=header, site_footer=FOOTER, **context)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        return check()  # older links posted the comparison form here
    if request.args.get('report'):
        from soundwaves.app import _session_dir
        report_id = request.args['report']
        if report_id == 'latest':
            report_id = _session_dir(report_id).name
        return redirect(url_for('show_report', report_id=report_id))
    return redirect(url_for('live_demo.live_page'))


@app.route('/check', methods=['GET', 'POST'])
def check():
    if request.method == 'GET':
        return _render('check.html', error=None)
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
        return _render('check.html', error=str(error)), 400


def _known_piece(source):
    """(piece id, name) when this sheet music was already added on Add a piece, else (None, None)."""
    import hashlib
    try:
        piece_id = 'upload-' + hashlib.sha256(Path(source).read_bytes()).hexdigest()[:10]
        sidecar = ROOT_DIR / 'soundwaves' / 'pieces' / f'{piece_id}.json'
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
    counts = {k: sum(m['category'] == k for m in report['matches']) for k in ('missing', 'wrong_pitch')}
    counts['extra'] = sum(m['category'] == 'extra' and not m.get('maybe_noise') for m in report['matches'])
    noise = sum(m['category'] == 'extra' and bool(m.get('maybe_noise')) for m in report['matches'])
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
                wrong=counts['wrong_pitch'], missing=counts['missing'], extra=counts['extra'], noise=noise,
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
    return _render('report.html', summary=_summary(report, directory), result=dict(
        report=report, report_id=report_id, cache=cache, cleaned='cleaned_audio' in artifacts,
        midi_playback='sheet_midi_audio' in artifacts and 'recording_midi_audio' in artifacts))


@app.get('/report/<report_id>/falling.json')
def report_falling(report_id):
    """This comparison's played notes, green where they match the sheet and red where they do not."""
    from soundwaves.teacher import falling_notes
    directory = _report_directory(report_id)
    report = json.loads((directory / 'report.json').read_text(encoding='utf-8'))
    return jsonify(id=report_id, title='', **falling_notes(report))


def _meta_title(directory):
    meta = directory / 'meta.json'
    return json.loads(meta.read_text(encoding='utf-8')).get('title', '') if meta.is_file() else ''


@app.get('/report/<report_id>/feedback')
def report_feedback(report_id):
    """The teacher's written notes (Claude, or Gemini without an Anthropic key), cached with the report."""
    from soundwaves.teacher import FeedbackUnavailable, teacher_feedback
    directory = _report_directory(report_id)
    wait_for_feedback(report_id, 'teacher')  # started when the comparison finished; usually ready by now
    try:
        return jsonify(teacher_feedback(json.loads((directory / 'report.json').read_text(encoding='utf-8')), directory, _meta_title(directory)))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


@app.get('/report/<report_id>/bar-notes')
def report_bar_notes(report_id):
    """One line per bar (Gemini), cached with the report."""
    from soundwaves.teacher import FeedbackUnavailable, bar_notes
    directory = _report_directory(report_id)
    wait_for_feedback(report_id, 'bars')
    try:
        return jsonify(bar_notes(json.loads((directory / 'report.json').read_text(encoding='utf-8')), directory, _meta_title(directory)))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


@app.post('/report/<report_id>/ask')
def report_ask(report_id):
    """A question about this review, answered from the comparison (Claude)."""
    from soundwaves.teacher import FeedbackUnavailable, answer_question
    directory = _report_directory(report_id)
    body = request.get_json(silent=True) or {}
    try:
        return jsonify(answer_question(json.loads((directory / 'report.json').read_text(encoding='utf-8')), directory,
                                       _meta_title(directory), body.get('question', ''), body.get('history') or []))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


@app.get('/artifact/<report_id>/<kind>/waveform')
def artifact_waveform(report_id, kind):
    if kind not in {'audio', 'original_audio', 'recording_midi_audio', 'sheet_midi_audio'}:
        abort(404)
    directory = _report_directory(report_id)
    manifest = json.loads((directory / 'artifacts.json').read_text())
    if kind not in manifest:
        abort(404)
    path = (CACHE / manifest[kind]).resolve()
    if not path.is_relative_to(CACHE.resolve()) or not path.is_file():
        abort(404)
    from soundwaves.web.waveform import waveform_response
    try:
        return waveform_response(path)
    except (ValueError, OSError):
        return jsonify(error='Waveform unavailable.'), 422


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
        from soundwaves.web.pipeline import _cached, _hash

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
    from soundwaves.web.notation import build_notation
    from soundwaves.web.pipeline import _cached, _hash, _write_json
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
    return _render('check.html', error='Upload too large. Sheet limit: 20 MB; recording limit: 80 MB.'), 413


def run_server(port=5001):
    from soundwaves.app import warm_transcriber
    warm_transcriber()
    app.run(host='127.0.0.1', port=port, debug=False, use_reloader=False, threaded=True)


if __name__ == '__main__':
    run_server()
