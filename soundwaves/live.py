"""Score data and bounded, provisional microphone transcription for /practice.

The final recording still goes through /api/analyze. This blueprint never grades
an incomplete score and never calls an explanation service.
"""

import base64
import io
import json
import math
import re
import tempfile
import time
import wave
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from functools import lru_cache
from pathlib import Path
from statistics import median
from threading import BoundedSemaphore, Lock

from flask import Blueprint, abort, jsonify, request, send_file, redirect
from werkzeug.exceptions import RequestEntityTooLarge

from alignment.inputs import load_score
from sheet_downloader import convert_score
from transcribe_recording.backend import BasicPitchBackend
from transcribe_recording.events import normalize_notes
from transcribe_recording.models import TranscriptionConfig

from .clean import clean_notes
from .report import score_metadata
from .scoreprep import prepare_reference

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / 'frontend' / 'static' / 'live-input'
PIECES = Path(__file__).with_name('pieces')
SCORE_CACHE = Path(__file__).with_name('sessions') / 'scores'
SESSIONS = Path(__file__).with_name('sessions')
PIANO_BANK = ROOT / 'frontend' / 'static' / 'audio' / 'piano.json'
MAX_AUDIO_BYTES = 3 * 1024 * 1024
MAX_AUDIO_SECONDS = 12
INFERENCE_TIMEOUT_SECONDS = 15
PIECE_ID = re.compile(r'^[A-Za-z0-9_-]{1,120}$')
ASSET_NAME = re.compile(r'^[A-Za-z0-9_-]+\.(?:css|js|svg|woff2)$')
REPORT_ID = re.compile(r'^[a-f0-9]{32}$')
SCORE_SUFFIXES = ('.musicxml', '.xml', '.mxl', '.pdf')

practice = Blueprint('practice', __name__)
_score_lock = Lock()
_inference_slot = BoundedSemaphore(1)
_inference_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='practice-audio')
_backend = BasicPitchBackend()  # Loads once, lazily, on the inference thread.
_config = TranscriptionConfig(maximum_duration_seconds=MAX_AUDIO_SECONDS)
_prepared_scores = {}


@practice.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store'
    return response


@practice.get('/practice')
def practice_page():
    return redirect('/live')


@practice.get('/practice-assets/<filename>')
def practice_asset(filename):
    # Only single-file frontend assets; never expose reports or arbitrary paths.
    if not ASSET_NAME.fullmatch(filename):
        abort(404)
    path = (UI / filename).resolve()
    if path.parent != UI.resolve() or not path.is_file():
        abort(404)
    return send_file(path)


@lru_cache(maxsize=1)
def _piano_bank():
    return json.loads(PIANO_BANK.read_text(encoding='utf-8'))


@lru_cache(maxsize=88)
def _piano_sample(pitch):
    names = ('C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B')
    name = f'{names[pitch % 12]}{pitch // 12 - 1}'
    prefix, separator, encoded = _piano_bank()[name].partition(',')
    if not separator or prefix not in ('data:audio/mp3;base64', 'data:audio/mpeg;base64'):
        raise ValueError('Invalid bundled piano sample.')
    return base64.b64decode(encoded, validate=True)


@practice.get('/api/practice/piano/<int:pitch>')
def practice_piano(pitch):
    # Fixed, bundled piano range: no filenames or arbitrary paths are accepted.
    # The recording samples retain their CC BY 3.0 credit.
    if not 21 <= pitch <= 108:
        abort(404)
    try:
        sample = _piano_sample(pitch)
    except (OSError, ValueError, KeyError, TypeError):
        return jsonify(error='The bundled piano sample is unavailable.'), 503
    response = send_file(io.BytesIO(sample), mimetype='audio/mpeg', download_name=f'piano-{pitch}.mp3')
    response.headers['X-Audio-Attribution'] = 'FluidR3_GM by Frank Wen; MP3 packaging by Benjamin Gleitzman; CC BY 3.0'
    response.headers['Link'] = '<https://creativecommons.org/licenses/by/3.0/>; rel="license"'
    return response


def _piece(piece_id):
    if not PIECE_ID.fullmatch(piece_id):
        abort(404)
    matches = [PIECES / (piece_id + suffix) for suffix in SCORE_SUFFIXES]
    source = next((path for path in matches if path.is_file() and path.resolve().parent == PIECES.resolve()), None)
    if source is None:
        abort(404)
    sidecar = source.with_suffix('.json')
    metadata = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else {}
    return source, metadata


def _score_payload(piece_id, metadata, reference, musicxml=None):
    reference, _ = prepare_reference(reference)
    _, notes, bars, tempi = load_score(reference)
    notation = score_metadata(musicxml)
    by_part = defaultdict(list)
    for note in notes:
        by_part[note.get('part', '')].append(note['pitch'])
    right_part = max(by_part, key=lambda part: median(by_part[part]))
    rows = []
    bar_index = 0
    for note in notes:
        while bar_index + 1 < len(bars) and note['onset'] >= bars[bar_index]['end_beat']:
            bar_index += 1
        bar = bars[bar_index]
        rows.append(dict(id=note['id'], pitch=note['pitch'], beat=note['onset'],
                         duration=note['duration'], measure=bar_index + 1,
                         printedMeasure=bar['number'], occurrence=bar_index,
                         beatInMeasure=1 + note['onset'] - bar['start_beat'],
                         hand='right' if note.get('part', '') == right_part else 'left'))
    fallback_beats = bars[0]['end_beat'] - bars[0]['start_beat']
    signature = notation.get('time_signature') or metadata.get('time_signature')
    if signature is None:
        signature = [int(fallback_beats), 4] if fallback_beats.is_integer() else [int(fallback_beats * 2), 8]
    return dict(piece=dict(id=piece_id, title=metadata.get('title') or notation.get('title') or piece_id,
                           composer=metadata.get('composer') or notation.get('composer'),
                           time_signature=signature, bpm=tempi[0][1], measures=len(bars),
                           printedMeasures=len({bar['number'] for bar in bars})),
                notes=rows, totalBeats=bars[-1]['end_beat'],
                bars=[dict(measure=index + 1, printedMeasure=bar['number'], occurrence=index,
                           startBeat=bar['start_beat'], endBeat=bar['end_beat'])
                      for index, bar in enumerate(bars)])


def _read_score(piece_id, source, metadata):
    cached = SCORE_CACHE / piece_id
    reference = cached / 'reference' / 'reference.json'
    musicxml = cached / 'reference' / 'reference.musicxml'
    if reference.is_file() and musicxml.is_file():
        return _score_payload(piece_id, metadata, json.loads(reference.read_text(encoding='utf-8')), musicxml)
    key = (str(source.resolve()), source.stat().st_mtime_ns, json.dumps(metadata, sort_keys=True))
    if key in _prepared_scores:
        return _prepared_scores[key]
    # Conversion only touches a fresh directory. Never remove an incomplete
    # cache another recording request may currently be creating.
    SCORE_CACHE.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f'.live-{piece_id}-', dir=SCORE_CACHE) as folder:
        staging = Path(folder) / 'converted'
        result = convert_score(source, staging, bpm=metadata.get('bpm', 120), measures_per_chunk=1)
        payload = _score_payload(piece_id, metadata, json.loads(result.notes.read_text(encoding='utf-8')), result.musicxml)
        # Keep the result in memory instead of publishing over a cache directory
        # a concurrent final-analysis request may have just started writing.
        _prepared_scores[key] = payload
        return payload


@practice.get('/api/practice/score/<piece_id>')
def practice_score(piece_id):
    source, metadata = _piece(piece_id)
    if not _score_lock.acquire(timeout=1):
        return jsonify(error='The score is being prepared. Try again shortly.'), 503, {'Retry-After': '1'}
    try:
        return jsonify(_read_score(piece_id, source, metadata))
    except (ValueError, OSError, KeyError) as error:
        return jsonify(error=f'Could not prepare this score: {error}'[:240]), 422
    finally:
        _score_lock.release()


def _validate_wav(data):
    try:
        with wave.open(io.BytesIO(data), 'rb') as audio:
            rate, frames = audio.getframerate(), audio.getnframes()
            channels, width = audio.getnchannels(), audio.getsampwidth()
            if channels not in (1, 2) or width != 2 or not 8000 <= rate <= 96000:
                raise ValueError('Use a mono or stereo 16-bit PCM WAV between 8 and 96 kHz.')
            if frames == 0 or frames / rate > MAX_AUDIO_SECONDS:
                raise ValueError(f'Audio windows must contain 0–{MAX_AUDIO_SECONDS} seconds of sound.')
            if len(audio.readframes(frames)) != frames * channels * width:
                raise ValueError('The audio window is truncated.')
    except (wave.Error, EOFError) as error:
        raise ValueError('Send a readable 16-bit PCM WAV audio window.') from error


def _transcribe_window(data):
    """Use the bundled model directly: no ffmpeg, final report, or disk cache."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    started = time.monotonic()
    samples, rate = sf.read(io.BytesIO(data), dtype='float32', always_2d=True)
    samples = samples.mean(axis=1)
    duration = len(samples) / rate
    if not np.isfinite(samples).all():
        raise ValueError('The audio window contains invalid samples.')
    if not np.any(samples):
        return dict(notes=[], latencySeconds=round(time.monotonic() - started, 3), backend='basic-pitch')
    if rate != 22050:
        divisor = math.gcd(rate, 22050)
        samples = resample_poly(samples, 22050 // divisor, rate // divisor)
    with tempfile.TemporaryDirectory(prefix='soundwaves-live-') as folder:
        wav = Path(folder) / 'window.wav'
        sf.write(wav, samples, 22050, subtype='FLOAT')
        prediction = _backend.transcribe(wav, _config)
    normalized, _ = normalize_notes(prediction.notes, duration, _config)
    kept, _ = clean_notes(normalized, harmonics=True)
    return dict(notes=[dict(pitch=n['pitch'], onset=round(n['onset'], 4),
                            duration=round(n['duration'], 4), velocity=n['velocity']) for n in kept],
                latencySeconds=round(time.monotonic() - started, 3), backend='basic-pitch')


def _run_window(data):
    try:
        return _transcribe_window(data)
    finally:
        _inference_slot.release()


@practice.post('/api/practice/notes')
def practice_notes():
    # Reject oversized bodies before multipart parsing and bound streamed bodies.
    request.max_content_length = MAX_AUDIO_BYTES + 65536
    try:
        upload = request.files.get('audio')
        if upload is None:
            return jsonify(error='Attach a WAV window in the audio field.'), 400
        data = upload.stream.read(MAX_AUDIO_BYTES + 1)
        if len(data) > MAX_AUDIO_BYTES:
            raise RequestEntityTooLarge()
        _validate_wav(data)
    except RequestEntityTooLarge:
        return jsonify(error='Audio windows must be smaller than 3 MB.'), 413
    except ValueError as error:
        return jsonify(error=str(error)), 400
    # Never queue stale microphone windows. An inference that outlives the HTTP
    # timeout retains this slot until it finishes; following requests get 503.
    if not _inference_slot.acquire(blocking=False):
        return jsonify(error='Still listening to the previous window. Send the newest window next.'), 503, {'Retry-After': '1'}
    try:
        future = _inference_pool.submit(_run_window, data)
    except RuntimeError:
        _inference_slot.release()
        return jsonify(error='Live listening is unavailable.'), 503
    try:
        return jsonify(future.result(timeout=INFERENCE_TIMEOUT_SECONDS))
    except FutureTimeout:
        return jsonify(error='Live listening took too long. The full recording can still be reviewed when you stop.'), 504
    except ValueError as error:
        return jsonify(error=str(error)), 400
    except Exception as error:  # Keep failures visible without exposing local paths.
        return jsonify(error=f'Live listening failed ({type(error).__name__}). Please try again.'), 500


def _prefix_matches(alignment):
    """Align all heard attacks against a score prefix; the unplayed tail is free.

    The final batch report contains every original expected and detected note,
    even when its global traceback chose the wrong repeated passage. Reusing
    those events avoids new transcription and keeps this endpoint deterministic.
    """
    import numpy as np
    from alignment.matching import assign_chord, onset_groups

    score, played = {}, {}
    for match in alignment.get('matches', []):
        if match.get('score_note_id') is not None and match.get('score_beat') is not None:
            score[match['score_note_id']] = dict(id=match['score_note_id'], pitch=match['expected_pitch'],
                                               onset=match['score_beat'])
        if match.get('performance_note_id') is not None and match.get('audio_time') is not None:
            played[match['performance_note_id']] = dict(id=match['performance_note_id'], pitch=match['actual_pitch'],
                                                      onset=match['audio_time'])
    config = alignment.get('configuration', {})
    sg = onset_groups(sorted(score.values(), key=lambda n: n['onset']), config.get('score_chord_window_beats', 0.0001))
    pg = onset_groups(sorted(played.values(), key=lambda n: n['onset']), config.get('chord_window_seconds', 0.05))
    if not sg or not pg:
        return [], [], list(score.values()), len(played)
    n, m = len(sg), len(pg)
    if (n + 1) * (m + 1) > 4_000_000:
        return [], [], list(score.values()), len(played)
    trace = np.zeros((n + 1, m + 1), dtype=np.uint8)
    trace[0, 1:], trace[1:, 0] = 2, 1
    previous = np.arange(m + 1, dtype=float) * 0.9
    endpoint_costs = [previous[m]]
    for i, expected in enumerate(sg, 1):
        current = np.empty(m + 1)
        current[0] = i * 0.9
        for j, heard in enumerate(pg, 1):
            overlap = sum((expected['pitches'] & heard['pitches']).values())
            total = sum(expected['pitches'].values()) + sum(heard['pitches'].values())
            choices = (previous[j - 1] + 1.35 * (1 - 2 * overlap / total),
                       previous[j] + 0.9, current[j - 1] + 0.9)
            step = min(range(3), key=choices.__getitem__)
            current[j], trace[i, j] = choices[step], step
        endpoint_costs.append(current[m])
        previous = current
    # Earliest endpoint wins ties: repeating a phrase does not imply that the
    # performer skipped an entire intervening section of identical music.
    endpoint = min(range(n + 1), key=endpoint_costs.__getitem__)
    pairs, i, j = [], endpoint, m
    while i or j:
        step = trace[i, j]
        if step == 0:
            pairs.append((sg[i - 1], pg[j - 1])); i -= 1; j -= 1
        elif step == 1:
            pairs.append((sg[i - 1], None)); i -= 1
        else:
            pairs.append((None, pg[j - 1])); j -= 1
    matches, anchors = [], []
    for expected, heard in reversed(pairs):
        if expected and heard and expected['pitches'] & heard['pitches']:
            anchors.append(dict(score_beat=expected['onset'], audio_time=heard['onset']))
        for score_note, played_note in assign_chord(expected['notes'] if expected else [], heard['notes'] if heard else []):
            matches.append(dict(category='extra' if score_note is None else 'missing' if played_note is None else
                                'correct' if score_note['pitch'] == played_note['pitch'] else 'wrong_pitch',
                                score_beat=score_note['onset'] if score_note else None,
                                audio_time=played_note['onset'] if played_note else None,
                                expected_pitch=score_note['pitch'] if score_note else None,
                                actual_pitch=played_note['pitch'] if played_note else None))
    return matches, anchors, list(score.values()), len(played)


def _summary_payload(report_id, report, alignment):
    """Review only a confidently aligned prefix, never the unplayed suffix."""
    from .report import fallback_text, pitch_name

    measures = alignment.get('measures', [])
    detected = int(alignment.get('metrics', {}).get('performed_notes', 0))
    result = dict(errors=[], coach=None, completed=False, reachedMeasure=None,
                  detectedNotes=detected, reportUrl=f'/?report={report_id}',
                  title=report.get('piece', {}).get('title', 'Your practice'),
                  coverage='No notes were detected.' if not detected else 'Not enough matching notes to locate this take reliably.')
    if not detected or not measures:
        return result
    matches, anchors, score_notes, heard = _prefix_matches(alignment)
    if not anchors:
        return result
    first, last = anchors[0]['score_beat'], anchors[-1]['score_beat']
    expected_prefix = sum(n['onset'] <= last for n in score_notes)
    correct = sum(m['category'] == 'correct' and m['score_beat'] <= last for m in matches)
    # A located partial take lists one lead-in bar before the first played bar,
    # so the first anchor may sit in the second listed bar.
    lead_in_end = measures[min(1, len(measures) - 1)]['end_beat']
    reliable = (len(anchors) >= 3 and first < lead_in_end
                and correct / max(1, expected_prefix) >= 0.5 and correct / max(1, heard) >= 0.5)
    if not reliable:
        return result
    def bar_index(beat):
        return next((i for i, bar in enumerate(measures) if bar['start_beat'] <= beat < bar['end_beat']), None)
    reached = bar_index(last)
    if reached is None:
        return result
    expected_measures = {bar_index(n['onset']) for n in score_notes}
    anchored_measures = {bar_index(a['score_beat']) for a in anchors}
    # Coverage must be continuous across measures, not just a sufficiently high
    # global recall and a coincidental matching note in the final repeated bar.
    complete = (last >= max(n['onset'] for n in score_notes) - 1e-6
                and expected_measures <= anchored_measures)
    result.update(completed=complete, reachedMeasure=reached + 1,
                  reachedPrintedMeasure=measures[reached]['number'],
                  coverage='Full passage reviewed.' if complete else f'Partial take  /  reached bar {measures[reached]["number"]}.')
    if complete and alignment.get('alignment', {}).get('status') == 'aligned':
        result['errors'] = report.get('errors', [])
        result['coach'] = report.get('coach')
        return result
    signature = report.get('piece', {}).get('time_signature', [4, 4])
    unit = signature[1] / 4
    for match in matches:
        category, beat = match['category'], match['score_beat']
        if category == 'correct':
            continue
        if beat is None:
            audio_time = match['audio_time']
            if audio_time is None or not anchors[0]['audio_time'] <= audio_time <= anchors[-1]['audio_time']:
                continue
            import numpy as np
            beat = float(np.interp(audio_time, [a['audio_time'] for a in anchors], [a['score_beat'] for a in anchors]))
        index = bar_index(beat)
        if index is None or beat > last:
            continue
        bar = measures[index]
        if category == 'missing' and bar['end_beat'] > last:
            continue  # A held final chord or an unfinished bar has not been skipped.
        entry = dict(id=f'prefix-{len(result["errors"]) + 1}', category=category,
                     measure=bar['number'], occurrence=index, beat=round(1 + (beat - bar['start_beat']) * unit, 3),
                     expected=pitch_name(match['expected_pitch']) if match['expected_pitch'] is not None else None,
                     actual=pitch_name(match['actual_pitch']) if match['actual_pitch'] is not None else None,
                     audio_time=match['audio_time'])
        entry['explanation'], entry['tip'] = fallback_text(entry, None, signature)
        result['errors'].append(entry)
    return result


@practice.get('/api/practice/summary/<report_id>')
def practice_summary(report_id):
    if not REPORT_ID.fullmatch(report_id):
        abort(404)
    directory = SESSIONS / report_id
    if directory.resolve().parent != SESSIONS.resolve():
        abort(404)
    report, alignment = directory / 'report.json', directory / 'alignment.json'
    if not report.is_file() or not alignment.is_file():
        abort(404)
    try:
        return jsonify(_summary_payload(report_id, json.loads(report.read_text(encoding='utf-8')),
                                        json.loads(alignment.read_text(encoding='utf-8'))))
    except (ValueError, KeyError, TypeError):
        return jsonify(error='This take does not contain a readable practice summary.'), 422
