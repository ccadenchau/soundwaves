"""Piece management, audio conversion, and saved-session API blueprint."""

import json
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Blueprint, abort, jsonify, request, send_file, redirect, render_template, make_response  # noqa: E402

from soundwaves.pipeline import AUDIO_SUFFIXES, MIDI_SUFFIXES, TooFewNotes, analyze, convert_once  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PIECES = Path(__file__).with_name('pieces')
SESSIONS = Path(__file__).with_name('sessions')
ID = re.compile(r'^[a-f0-9]{32}$')
SESSIONS.mkdir(exist_ok=True)

coach = Blueprint('coach', __name__)


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
    response = make_response(response)
    response.headers['Cache-Control'] = 'no-store'
    return response


from soundwaves.site import FOOTER as SITE_FOOTER, HEAD as SITE_HEAD, header as site_header  # noqa: E402

SCORE_SUFFIXES = {'.musicxml', '.xml', '.mxl', '.pdf'}
MAX_SCORE_BYTES = 20 * 1024 * 1024


@coach.get('/site.css')
def site_css():
    return _no_cache(send_file(ROOT / 'frontend' / 'static' / 'site.css', mimetype='text/css'))


@coach.get('/upload')
def upload_page():
    return _no_cache(render_template('upload.html', site_head=SITE_HEAD, site_header=site_header, site_footer=SITE_FOOTER))


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
        from soundwaves.report import score_metadata
        meta = score_metadata(paths['musicxml'])
        title = (request.form.get('title') or '').strip()[:120] or meta.get('title') or \
            Path(upload.filename).stem.replace('_', ' ').replace('-', ' ').strip().title()
        sidecar.write_text(json.dumps(dict(title=title, composer=meta.get('composer'), bpm=bpm, uploaded=True)), encoding='utf-8')
    meta = json.loads(sidecar.read_text(encoding='utf-8'))
    name = (request.form.get('title') or '').strip()[:120]
    if reused and name and name != meta.get('title'):  # uploading the same score again with a name renames it
        meta['title'] = name
        sidecar.write_text(json.dumps(meta), encoding='utf-8')
    ref = json.loads((cache / 'reference' / 'reference.json').read_text(encoding='utf-8'))
    first = ref['chunks'][0]
    beats = first['end_beat'] - first['start_beat']
    from soundwaves.report import score_metadata as _sm, _infer_time_signature
    ts = _sm(cache / 'reference' / 'reference.musicxml').get('time_signature') or _infer_time_signature(beats)
    return jsonify(id=piece_id, title=meta['title'], composer=meta.get('composer'), bars=len(ref['chunks']),
                   notes=len(ref['notes']), bpm=ref['tempo_changes'][0][1], time_signature=ts, reused=reused)


CONVERT_FILES = {'cleaned.wav', 'cleaned.mid', 'original.mid', 'cleaned-as-piano.wav', 'original-as-piano.wav', 'result.json'}


@coach.get('/easy')
def easy_page():
    return _no_cache(render_template('easy.html', site_head=SITE_HEAD, site_header=site_header, site_footer=SITE_FOOTER))


@coach.post('/api/easy')
def easy_route():
    """A recording in, an easy piece in the list out."""
    import tempfile
    from soundwaves.easy import make_easy
    upload = request.files.get('audio')
    if upload is None or not upload.filename:
        return jsonify(error='Choose a recording first.'), 400
    suffix = Path(upload.filename).suffix.lower() or '.wav'
    if suffix not in AUDIO_SUFFIXES:
        return jsonify(error='Use an audio file: MP3, WAV, M4A, WebM, OGG or FLAC.'), 400
    try:
        level = int(request.form.get('level', '3'))
        bars = int(request.form.get('bars', '8'))
        bpm = float(request.form.get('bpm', '72'))
        start = float(request.form.get('start', '0') or 0)
        if not 40 <= bpm <= 140 or start < 0:
            raise ValueError
    except ValueError:
        return jsonify(error='Check the tempo and start time.'), 400
    with tempfile.TemporaryDirectory(prefix='easy-upload-') as folder:
        path = Path(folder) / f'recording{suffix}'
        upload.save(path)
        try:
            result = make_easy(path, title=request.form.get('title', ''), level=level, bars=bars, start_seconds=start,
                               bpm=bpm, solo_piano=request.form.get('solo') == '1', workdir=Path(folder) / 'work')
        except ValueError as error:
            return jsonify(error=str(error)[:300]), 422
        except Exception as error:  # noqa: BLE001 - say why, in words
            return jsonify(error=f'Could not make an easy version: {type(error).__name__}: {error}'[:300]), 500
    return jsonify(result)


@coach.get('/convert')
def convert_page():
    return _no_cache(render_template('convert.html', site_head=SITE_HEAD, site_header=site_header, site_footer=SITE_FOOTER))


@coach.post('/api/convert')
def convert_route():
    from soundwaves.convert import AUDIO_TYPES, CONVERT, convert_audio
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
    from soundwaves.convert import CONVERT
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
    return _no_cache(redirect('/check'))


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


def _hydrate_score_dynamics(report_data, session_dir):
    """Refresh printed score symbols for older reports, including recovered hairpins."""
    candidates = [session_dir / 'score']
    title = report_data.get('piece', {}).get('title')
    for piece in _pieces():
        if piece.get('title') == title:
            candidates.append(SESSIONS / 'scores' / piece['id'])
    for root in candidates:
        reference_path = root / 'reference' / 'reference.json'
        musicxml_path = root / 'reference' / 'reference.musicxml'
        if not reference_path.is_file() or not musicxml_path.is_file():
            continue
        reference = json.loads(reference_path.read_text(encoding='utf-8'))
        first_chunk, ui_measure = {}, {}
        for chunk in reference['chunks']:
            printed = chunk['measures'][0]
            if printed not in first_chunk:
                first_chunk[printed] = chunk
                ui_measure[printed] = len(ui_measure) + 1
        denominator = report_data.get('piece', {}).get('time_signature', [4, 4])[1]
        unit = denominator / 4.0
        from soundwaves.report import score_dynamics
        report_data['score_dynamics'] = score_dynamics(
            musicxml_path, first_chunk, ui_measure,
            lambda onset, chunk: round(1 + (onset - chunk['start_beat']) * unit, 3))
        for bar in report_data.get('dynamics', {}).get('bars', []):
            issues = bar.setdefault('issues', [])
            delta, trend = bar.get('relative_level_difference'), bar.get('trend')
            if delta is not None and delta >= 8 and 'too_loud' not in issues:
                issues.append('too_loud')
            elif delta is not None and delta <= -8 and 'too_soft' not in issues:
                issues.append('too_soft')
            if trend in ('crescendo_needs_more', 'decrescendo_needs_more') and trend not in issues:
                issues.append(trend)
        return report_data
    return report_data


@coach.get('/api/report/<report_id>')
def report(report_id):
    session_dir = _session_dir(report_id)
    path = session_dir / 'report.json'
    if not path.is_file():
        abort(404)
    data = json.loads(path.read_text(encoding='utf-8'))
    _hydrate_score_dynamics(data, session_dir)
    return _no_cache(jsonify(data))


@coach.get('/falling')
def falling_page():
    """Falling-notes view of a take. /falling?report=<id|latest> loads a finished comparison."""
    return _no_cache(render_template('keyboard-replay.html'))


@coach.get('/api/falling/<report_id>')
def falling(report_id):
    """The recording's notes, each marked as matching the score or not.

    'correct' = the score note at this spot was played with this pitch; 'wrong_pitch' and 'extra'
    = a played note the score does not call for. For a wrong pitch, `expected` is the key the
    score wanted. Score notes that were never played have no time in the recording and are
    only counted, in `missing`."""
    from soundwaves.teacher import falling_notes
    session_dir = _session_dir(report_id)
    path = session_dir / 'alignment.json'
    if not path.is_file():
        abort(404)
    data = falling_notes(json.loads(path.read_text(encoding='utf-8')))
    report_path = session_dir / 'report.json'
    title = json.loads(report_path.read_text(encoding='utf-8')).get('piece', {}).get('title', '') if report_path.is_file() else ''
    return _no_cache(jsonify(id=session_dir.name, title=title, **data))


@coach.get('/api/feedback/<report_id>')
def feedback(report_id):
    """Piano-teacher feedback on a finished comparison (Gemini; cached per take)."""
    from soundwaves.teacher import FeedbackUnavailable, teacher_feedback
    session_dir = _session_dir(report_id)
    path = session_dir / 'alignment.json'
    if not path.is_file():
        abort(404)
    try:
        return _no_cache(jsonify(teacher_feedback(json.loads(path.read_text(encoding='utf-8')), session_dir)))
    except FeedbackUnavailable as error:
        return jsonify(error=str(error)), 503


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


def warm_transcriber():
    """Load the transcriber in the background so the first take is not slow."""
    from threading import Thread
    from soundwaves.pipeline import transcriber

    def warm():
        backend = transcriber()
        if backend is not None:
            backend.start()

    Thread(target=warm, daemon=True).start()


