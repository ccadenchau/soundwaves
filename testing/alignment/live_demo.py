"""Live version of the alignment page: the engraved score lights up while you play,
then the whole take goes through the same comparison as the upload form.

GET  /live                         the page
GET  /api/live/notation/<piece_id> engraved score + score-note -> engraved-element map
POST /api/live/finish              piece + recording -> full alignment report URL
"""

import json
import tempfile
from pathlib import Path
from threading import Lock

from flask import Blueprint, abort, jsonify, request, send_file, url_for

from pianocoach.live import SCORE_CACHE, _piece
from pianocoach.pipeline import convert_once
from testing.alignment.pipeline import CACHE, compare_files

live_demo = Blueprint('live_demo', __name__)
PAGE = Path(__file__).with_name('static') / 'live.html'
_notation_cache, _lock = {}, Lock()


@live_demo.get('/live')
def live_page():
    from flask import Response
    from pianocoach.site import FOOTER, header
    html = PAGE.read_text(encoding='utf-8').replace('<!--SITE_HEADER-->', header('live')).replace('<!--SITE_FOOTER-->', FOOTER)
    return Response(html, mimetype='text/html', headers={'Cache-Control': 'no-store'})


@live_demo.get('/live-assets/<name>')
def live_asset(name):
    if name not in ('live.js', 'learn.js'):
        return ('', 404)
    return send_file(PAGE.with_name(name), mimetype='text/javascript', max_age=0)


@live_demo.get('/learn')
def learn_page():
    """Step-by-step mode for someone who has never played: the next key is shown, the page waits for it."""
    from flask import Response
    from pianocoach.site import FOOTER, header
    html = PAGE.with_name('learn.html').read_text(encoding='utf-8').replace('<!--SITE_HEADER-->', header('learn')).replace('<!--SITE_FOOTER-->', FOOTER)
    return Response(html, mimetype='text/html', headers={'Cache-Control': 'no-store'})


@live_demo.get('/api/live/notation/<piece_id>')
def live_notation(piece_id):
    source, metadata = _piece(piece_id)
    key = (piece_id, source.stat().st_mtime_ns)
    with _lock:
        if key not in _notation_cache:
            try:
                from testing.alignment.notation import render_score
                paths = convert_once(source, SCORE_CACHE / piece_id, bpm=metadata.get('bpm', 120))
                notes = json.loads(Path(paths['notes']).read_text(encoding='utf-8'))['notes']
                toolkit, locations = render_score(paths['musicxml'], notes)
                pages = [toolkit.renderToSVG(page) for page in range(1, toolkit.getPageCount() + 1)]
                # Engraved spelling of each note, so a played pitch can be drawn on the right line.
                spelled = {}
                for xml_id in locations.values():
                    attrs = toolkit.getElementAttr(xml_id)
                    if attrs.get('pname') and attrs.get('oct') is not None:
                        spelled[xml_id] = 'cdefgab'.index(attrs['pname']) + 7 * int(attrs['oct'])
                _notation_cache[key] = dict(pages=pages, locations=locations, steps=spelled)
            except Exception as error:  # conversion or engraving failed; say so plainly
                return jsonify(error=f'Could not draw this score: {error}'[:300]), 422
    return jsonify(_notation_cache[key])


@live_demo.post('/api/live/finish')
def live_finish():
    piece_id = request.form.get('piece', '')
    source, metadata = _piece(piece_id)
    upload = request.files.get('recording')
    if upload is None or not upload.filename:
        return jsonify(error='No recording arrived. Try the take again.'), 400
    suffix = Path(upload.filename).suffix.lower() or '.webm'
    with tempfile.TemporaryDirectory(prefix='live-take-') as folder:
        path = Path(folder) / f'take{suffix}'
        upload.save(path)
        try:
            result = compare_files(str(source), path, bpm=float(metadata.get('bpm', 120)),
                                   title=metadata.get('title') or piece_id, piece_id=piece_id)
        except Exception as error:
            return jsonify(error=str(error)[:300]), 422
    directory = CACHE / 'reports' / result['report_id']
    (directory / 'cache.json').write_text(json.dumps(result['cache']), encoding='utf-8')
    return jsonify(report_url=url_for('show_report', report_id=result['report_id']))


# ---------------------------------------------------------------------------------------------
# Accurate live layer. The browser streams the take as 16-bit PCM. A worker re-transcribes the
# last few seconds with the same transcriber the final report uses (Transkun when installed),
# keeps one growing note list, and re-aligns the whole take so far with the same aligner. What
# the page paints from this layer is what the final report will say about the bars played so far.
# ---------------------------------------------------------------------------------------------
import threading
import time
import uuid

import numpy as np

LIVE_WINDOW = 6.0      # seconds of audio per pass (Transkun costs about the same up to ~8 s)
LIVE_FROZEN = 0.6      # notes this far into a window's left edge were already decided by earlier passes
LIVE_MAX_SECONDS = 600
LIVE_HOLD = 1.5        # seconds of later audio needed before a mistake is shown
_sessions = {}
_sessions_lock = threading.Lock()


class LiveSession:
    def __init__(self, piece_id, rate, start_bar=1):
        source, metadata = _piece(piece_id)
        paths = convert_once(source, SCORE_CACHE / piece_id, bpm=metadata.get('bpm', 120))
        self.reference = json.loads(Path(paths['notes']).read_text(encoding='utf-8'))
        self.piece_id, self.rate = piece_id, int(rate)
        self.pcm = np.zeros(0, dtype=np.int16)
        self.notes = []            # heard notes, absolute seconds
        self.done_until = 0.0      # audio seconds covered by the last pass
        self.frozen = {}           # score note id -> mark the page has settled on
        self.streak = {}           # mark key -> (category, passes in a row)
        self.prepared, self.front, self.hits = None, None, []
        self.start_occ = max(0, int(start_bar) - 1)  # the player says where they start; guessing from a few notes is unreliable
        self.state = dict(version=0, ready=False)
        self.active, self.updated = True, time.time()
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self._loop, daemon=True, name=f'live-{piece_id}')
        self.thread.start()

    def add_audio(self, offset, data):
        samples = np.frombuffer(data, dtype='<i2')
        with self.lock:
            end = offset + len(samples)
            if end > LIVE_MAX_SECONDS * self.rate:
                raise ValueError('Live takes are limited to 10 minutes.')
            if end > len(self.pcm):
                self.pcm = np.concatenate([self.pcm, np.zeros(end - len(self.pcm), dtype=np.int16)])
            self.pcm[offset:end] = samples
            self.updated = time.time()

    def _loop(self):
        from pianocoach.pipeline import transcriber
        backend = transcriber()
        while self.active and time.time() - self.updated < 120:
            with self.lock:
                total = len(self.pcm) / self.rate
            if total - self.done_until < 0.3:
                time.sleep(0.1)
                continue
            try:
                self._pass(backend, total)
            except Exception as error:  # keep listening; report the problem on the page
                self.state = dict(self.state, error=f'Live check hiccup: {type(error).__name__}')
                time.sleep(0.5)

    def _transcribe(self, backend, audio, start):
        import soundfile as sf
        from transcribe_recording.events import normalize_notes
        from transcribe_recording.models import TranscriptionConfig
        config = TranscriptionConfig()
        with tempfile.TemporaryDirectory(prefix='live-pass-') as folder:
            wav = Path(folder) / 'window.wav'
            sf.write(wav, audio, self.rate, subtype='PCM_16')
            if backend is not None:
                prediction = backend.transcribe(wav, config)
            else:
                from pianocoach.live import _backend
                prediction = _backend.transcribe(wav, config)
        notes, _ = normalize_notes(prediction.notes, len(audio) / self.rate, config)
        return [dict(pitch=int(n.pitch), onset=float(n.onset) + start, duration=float(n.duration),
                     velocity=int(n.velocity),
                     model_score=0.9 if backend is not None else float(getattr(n, 'model_score', None) or 0.5))
                for n in notes]

    def _pass(self, backend, total):
        from pianocoach.clean import clean_notes
        from pianocoach.pipeline import align_windowed
        start = max(0.0, total - LIVE_WINDOW)
        with self.lock:
            audio = self.pcm[int(start * self.rate):int(total * self.rate)].copy()
        fresh = self._transcribe(backend, audio, start)
        cut = start + LIVE_FROZEN if start > 0 else 0.0
        kept_old = [n for n in self.notes if n['onset'] < cut]
        # Near the seam a note can land either side of the cut between passes: take the new pass's
        # notes from a little before it, unless the same key was already kept at that moment.
        seam = [n for n in kept_old if n['onset'] >= cut - 0.2]
        added = [n for n in fresh if n['onset'] >= cut - 0.15 and not any(
            o['pitch'] == n['pitch'] and abs(o['onset'] - n['onset']) < 0.12 for o in seam)]
        self.notes = kept_old + added
        self.done_until = total
        heard = [dict(n, id=f'p{i:06d}') for i, n in enumerate(sorted(self.notes, key=lambda n: (n['onset'], n['pitch'])))]
        kept, _ = clean_notes(heard, harmonics=backend is None)
        if len(kept) < 4:
            self.state = dict(version=self.state['version'] + 1, ready=False, heard_seconds=round(total, 2), notes=len(kept))
            return
        try:
            alignment = self._align(kept, total)
        except ValueError:
            return
        from pianocoach.noise import apply_noise_rules
        apply_noise_rules(alignment, kept, self.reference['notes'])
        self.state = self._summary(alignment, kept, total)

    def _align(self, kept, total):
        """Align the take so far. The first pass finds where the player started; after that the
        score is cut off two bars past where the player is, because a live take only moves forward
        and a pitch-only aligner otherwise pins a stray note to a similar bar far ahead, which
        makes everything in between look skipped."""
        from alignment import align_performance
        from pianocoach.pipeline import _window, align_windowed
        from pianocoach.scoreprep import prepare_reference
        if self.prepared is None:
            self.prepared, _ = prepare_reference(self.reference)
        chunks = self.prepared['chunks']
        last = len(chunks) - 1
        self.start_occ = min(self.start_occ, last)
        start_beat = chunks[self.start_occ]['start_beat']
        bar_beats = chunks[self.start_occ]['end_beat'] - start_beat
        tempi = self.reference.get('tempo_changes') or [[0, 120]]
        marked_bps = float(tempi[0][1]) / 60.0
        # Where the player is now, from timing: a robust tempo line through recent correct notes.
        # Until there are enough of them, assume no faster than 1.5x the marked tempo.
        predicted = start_beat + total * marked_bps * 1.5
        if len(self.hits) >= 8:
            recent = self.hits[-24:]
            ts = np.array([h[0] for h in recent]); bs = np.array([h[1] for h in recent])
            slopes = [(bs[j] - bs[i]) / (ts[j] - ts[i]) for i in range(len(ts)) for j in range(i + 1, len(ts))
                      if ts[j] - ts[i] > 0.05]
            if slopes:
                slope = float(np.clip(np.median(slopes), 0.25 * marked_bps, 3.0 * marked_bps))
                intercept = float(np.median(bs - slope * ts))
                predicted = intercept + slope * total
        limit_beat = max(start_beat + bar_beats, predicted + bar_beats)
        hi = next((c['measure_occurrence'] for c in chunks if c['start_beat'] <= limit_beat < c['end_beat']), last)
        hi = max(self.start_occ, min(last, hi))
        sub, mapping = _window(self.prepared, self.start_occ, hi)
        alignment = align_performance(sub, kept)
        for m in alignment['matches'] + alignment['errors']:
            if m.get('measure_occurrence') is not None:
                m['measure_occurrence'] = mapping[m['measure_occurrence']]
        for b in alignment['measures']:
            b['occurrence'] = mapping[b['occurrence']]
        hits = sorted((m['audio_time'], m['score_beat']) for m in alignment['matches']
                      if m['category'] == 'correct' and m['audio_time'] is not None and m['score_beat'] is not None)
        # Keep only hits consistent with moving forward in time (drop pitch matches pinned far ahead).
        self.hits = [h for h in hits if h[1] <= limit_beat]
        self.front = hi
        return alignment

    def _summary(self, alignment, kept, total):
        last_heard = max(n['onset'] for n in kept)
        span = alignment.get('played_span') or {}
        last_occ = span.get('last_occurrence')
        timing = {e['score_note_id']: e['onset_error_seconds'] for e in alignment['errors']
                  if e['category'] == 'timing' and e.get('score_note_id')}
        # A mistake is only shown once the transcriber has heard enough audio after it: notes at the
        # playing edge are often half-heard, and a red mark that turns green a second later is worse
        # than one that appears a second later. Correct notes can be shown at once.
        settled = total - LIVE_HOLD
        # A skipped note is settled when a correct note at least a beat later was heard before `settled`.
        later = [m['score_beat'] for m in alignment['matches'] if m['category'] == 'correct'
                 and m['score_beat'] is not None and m['audio_time'] is not None and m['audio_time'] <= settled]
        later = sorted(later)
        settled_beat = later[max(0, len(later) - 4)] - 1.0 if later else -1  # robust to one stray match
        marks = []
        for m in alignment['matches']:
            category = m['category']
            if category == 'missing':
                if m['score_beat'] is None or m['score_beat'] > settled_beat:
                    continue
                if last_occ is not None and m.get('measure_occurrence') is not None and m['measure_occurrence'] > last_occ:
                    continue
            elif category in ('wrong_pitch', 'extra') and (m['audio_time'] is None or m['audio_time'] > settled):
                continue
            mark = dict(id=m['score_note_id'], category=category, expected=m['expected_pitch'], actual=m['actual_pitch'],
                        time=m['audio_time'], measure=m['measure'], occurrence=m['measure_occurrence'])
            if m.get('maybe_noise'):
                mark['maybe_noise'] = True
            if category == 'correct' and timing.get(m['score_note_id']) is not None:
                mark['timing_ms'] = round(timing[m['score_note_id']] * 1000)
            marks.append(mark)
        # A mistake is shown once two passes in a row agree on it; any mark three passes old is kept
        # from then on, so the page never repaints a note the player already saw because a later pass
        # re-paired notes a few beats back. The final report re-checks everything.
        matched_total = sum(1 for m in marks if m['category'] == 'correct')
        streak = {}
        for m in marks:
            key = m['id'] or f"x{m['actual']}@{round(m['time'] or 0, 1)}"
            old = self.streak.get(key)
            streak[key] = (m['category'], old[1] + 1 if old and old[0] == m['category'] else 1)
            m['_key'] = key
        self.streak = streak
        shown = {}
        for m in marks:
            key = m.pop('_key')
            if key in self.frozen:
                continue
            count = streak[key][1]
            if m['category'] == 'correct' or count >= 2:
                shown[key] = m
            # Nothing is locked until the take has enough matched notes to be sure where it is: a short
            # tune that repeats its opening phrase can be aligned to the repeat for the first few passes.
            if count >= 3 and matched_total >= 10 and (m['category'] != 'correct' or m['time'] is None or m['time'] <= settled):
                self.frozen[key] = m
        marks = list(self.frozen.values()) + list(shown.values())
        bars = []
        for b in alignment['measures']:
            if last_occ is not None and b['occurrence'] > last_occ:
                continue
            if not (b['correct_notes'] or b['missing_notes'] or b['wrong_pitch_notes'] or b['extra_notes']):
                continue
            bars.append(dict(number=b['number'], occurrence=b['occurrence'], expected=b['expected_notes'],
                             correct=b['correct_notes'], missing=b['missing_notes'], wrong=b['wrong_pitch_notes'],
                             extra=b['extra_notes'], tempo_status=b['tempo_status'], tempo_ratio=b['tempo_ratio'],
                             score_bpm=b.get('reference_average_bpm'), played_bpm=b.get('performed_average_bpm'),
                             early=b.get('early_notes'), late=b.get('late_notes'),
                             median_onset_ms=(round(b['median_absolute_timing_error_seconds'] * 1000)
                                              if b.get('median_absolute_timing_error_seconds') is not None else None),
                             feedback=_plain(b)))
        # Missing notes in the bar being played right now may still arrive; only bars before it count.
        return dict(version=self.state['version'] + 1, ready=True, heard_seconds=round(total, 2),
                    last_heard=round(last_heard, 2), marks=marks, bars=bars,
                    metrics=dict(alignment['metrics']), status=alignment['alignment']['status'])


def _plain(bar):
    from testing.alignment.wording import plain_feedback
    return plain_feedback(bar)


def _session(sid):
    with _sessions_lock:
        session = _sessions.get(sid)
    if session is None:
        abort(404)
    return session


@live_demo.post('/api/live/session')
def live_session_start():
    piece_id = request.form.get('piece', '')
    rate = int(request.form.get('rate', '44100'))
    start_bar = int(request.form.get('start_bar', '1') or 1)
    if not 8000 <= rate <= 96000:
        return jsonify(error='Unsupported sample rate.'), 400
    with _sessions_lock:  # one live take at a time on a laptop
        for old in _sessions.values():
            old.active = False
        _sessions.clear()
    try:
        session = LiveSession(piece_id, rate, start_bar)
    except Exception as error:
        return jsonify(error=f'Could not prepare the live check: {error}'[:300]), 422
    sid = uuid.uuid4().hex
    with _sessions_lock:
        _sessions[sid] = session
    return jsonify(session=sid)


@live_demo.post('/api/live/session/<sid>/audio')
def live_session_audio(sid):
    session = _session(sid)
    try:
        session.add_audio(int(request.args.get('offset', '0')), request.get_data())
    except ValueError as error:
        return jsonify(error=str(error)), 413
    return jsonify(session.state)


@live_demo.get('/api/live/session/<sid>')
def live_session_state(sid):
    return jsonify(_session(sid).state)


@live_demo.delete('/api/live/session/<sid>')
def live_session_stop(sid):
    with _sessions_lock:
        session = _sessions.pop(sid, None)
    if session is not None:
        session.active = False
    return jsonify(ok=True)


@live_demo.post('/api/live/session/<sid>/stop')
def live_session_beacon(sid):
    return live_session_stop(sid)
