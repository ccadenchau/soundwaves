"""What the comparison page needs beyond the raw alignment: the falling-keys note list, and
piano-teacher feedback written by Claude (or Gemini when only a Gemini key is set).

Both take an alignment report (the dict `alignment.align_performance` returns, saved as
alignment.json or report.json). Feedback is cached next to the report so reopening a take
never spends another request. Without a real key, `FeedbackUnavailable` carries a message
the page can show; nothing else in the app depends on it.
"""

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from .explain import GEMINI_MODEL, MODEL as CLAUDE_MODEL, load_env, provider

PLACEHOLDER_KEY = 'YOUR_GEMINI_API_KEY_HERE'
NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


class FeedbackUnavailable(RuntimeError):
    """No usable key, or Gemini refused/failed. The message is safe to show the student."""


def _name(midi):
    return None if midi is None else f'{NAMES[int(midi) % 12]}{int(midi) // 12 - 1}'


def falling_notes(alignment):
    """The performance's notes, each marked as matching the score or not (see /api/falling)."""
    notes, missing = [], 0
    for m in alignment['matches']:
        if m['performance_note_id'] is None:
            missing += 1
            continue
        notes.append(dict(t=m['audio_time'], end=m['audio_time'] + m['performance_duration_seconds'],
                          note=m['actual_pitch'], vel=int(m.get('performance_velocity') or 80),
                          ok=m['category'] == 'correct', category=m['category'],
                          expected=m['expected_pitch'] if m['category'] == 'wrong_pitch' else None))
    notes.sort(key=lambda n: (n['t'], n['note']))
    return dict(notes=notes, missing=missing, matched=sum(n['ok'] for n in notes))


def feedback_payload(alignment, title=''):
    """A compact, readable summary of the comparison for the model: totals, per-bar facts for the
    bars that were played, and the specific wrong notes. No raw note lists."""
    metrics = alignment['metrics']
    bars, unplayed = [], 0
    for b in alignment['measures']:
        played = b['correct_notes'] + b['wrong_pitch_notes'] + b['extra_notes']
        if not played:
            unplayed += 1
            continue
        bar = dict(bar=b['number'], expected=b['expected_notes'], correct=b['correct_notes'],
                   missing=b['missing_notes'], wrong=b['wrong_pitch_notes'], extra=b['extra_notes'],
                   tempo=b['tempo_status'])
        if b.get('tempo_ratio') is not None:
            bar['speed_vs_score'] = round(b['tempo_ratio'], 2)
        if b.get('median_absolute_timing_error_seconds') is not None:
            bar['typical_timing_error_ms'] = round(b['median_absolute_timing_error_seconds'] * 1000)
            bar['early'], bar['late'] = b['early_notes'], b['late_notes']
        if b.get('median_duration_ratio') is not None:
            bar['note_length_vs_score'] = round(b['median_duration_ratio'], 2)
        if b.get('dynamics_trend'):
            bar['dynamics_trend'] = b['dynamics_trend']
        if b.get('relative_dynamics_level_difference') is not None:
            bar['louder_than_score_by'] = round(b['relative_dynamics_level_difference'], 1)
        bars.append(bar)
    wrong, counts = [], {}
    for e in alignment['errors']:
        counts[e['category']] = counts.get(e['category'], 0) + 1
        if e['category'] in ('wrong_pitch', 'missing', 'extra') and len(wrong) < 40:
            wrong.append(dict(bar=e.get('measure'), kind=e['category'],
                              should_play=_name(e.get('expected_pitch')), played=_name(e.get('actual_pitch'))))
    return dict(
        piece=title or None, source=alignment.get('performance_source'),
        alignment_reliable=alignment['alignment']['status'] == 'aligned',
        totals=dict(score_notes=metrics['expected_notes'], played_notes=metrics['performed_notes'],
                    notes_correct=metrics['correct_notes'],
                    share_of_score_played_correctly=round(metrics['pitch_recall'], 2),
                    share_of_played_notes_correct=round(metrics['pitch_precision'], 2),
                    bars_with_no_notes_detected=unplayed),
        problem_counts=counts, bars=bars, specific_notes=wrong)


SYSTEM = """You are a kind, experienced piano teacher giving a student feedback after they recorded a practice take. A program compared the take with the sheet music; the JSON is what it found. Speak to the student directly ("you").

What good feedback looks like:
- Simple, practical tips and tricks a real teacher would say out loud: slow down, practise hands separately, loop the hard two beats, count aloud, use a metronome at a slower tempo, check fingering, relax the wrist, play louder or softer, hold notes their full length.
- Name the bars. Say what to work on most and how to hit those notes better. A few focus areas, not a list of everything.
- Start with what went well when something did, briefly and honestly. Do not flatter.
- Timing "speed_vs_score" above 1 means rushing, below 1 means dragging. Short "note_length_vs_score" means notes cut off early.
- If alignment_reliable is false, or the source is audio and many notes are wrong or extra, say that some of what was flagged may be the recording rather than the playing, and suggest a cleaner recording (quiet room, phone near the piano). Never blame the student for what is probably a transcription error.
- Plain language, no jargon without a few words of explanation. No exclamation marks, no mention of software, AI or JSON.

Return JSON only, matching the schema."""

SCHEMA = {
    'type': 'object',
    'properties': {
        'summary': {'type': 'string', 'description': 'Two to three sentences: how the take went overall and the single most useful thing to do next.'},
        'strengths': {'type': 'array', 'items': {'type': 'string'}, 'description': 'Zero to three short things that went well.'},
        'focus_areas': {'type': 'array', 'items': {
            'type': 'object',
            'properties': {
                'title': {'type': 'string'},
                'bars': {'type': 'string', 'description': 'Which bars, e.g. "bars 5-8"; empty if it applies everywhere.'},
                'what_happened': {'type': 'string'},
                'tips': {'type': 'array', 'items': {'type': 'string'}, 'description': 'One to three concrete things to try.'},
            },
            'required': ['title', 'bars', 'what_happened', 'tips'],
        }, 'description': 'Two to four things to work on, most important first.'},
        'practice_plan': {'type': 'string', 'description': 'A short routine for the next practice session, two or three sentences.'},
    },
    'required': ['summary', 'strengths', 'focus_areas', 'practice_plan'],
}


def _key():
    load_env()
    key = (os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY') or '').strip()
    if not key or key == PLACEHOLDER_KEY:
        raise FeedbackUnavailable('Teacher feedback is switched off. Put an ANTHROPIC_API_KEY or a Google AI Studio '
                                  'GEMINI_API_KEY in .env and restart the server.')
    return key


def _ask_claude(payload, model):
    """Claude writes the notes; the same system prompt and JSON schema as the Gemini path."""
    import anthropic
    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=model, max_tokens=3000, system=SYSTEM,
            messages=[{'role': 'user', 'content': json.dumps(payload)}],
            output_config={'format': {'type': 'json_schema', 'schema': _strict(SCHEMA)}})
    except anthropic.AuthenticationError:
        raise FeedbackUnavailable('Anthropic rejected the API key in .env.') from None
    except anthropic.APIConnectionError as error:
        raise FeedbackUnavailable(f'Could not reach Claude: {error}'[:300]) from None
    except anthropic.APIStatusError as error:
        raise FeedbackUnavailable(f'Claude request failed ({error.status_code}).') from None
    if response.stop_reason == 'refusal':
        raise FeedbackUnavailable('Claude declined to write feedback for this take.')
    try:
        text = next(b.text for b in response.content if b.type == 'text')
        return json.loads(text)
    except (StopIteration, ValueError):
        raise FeedbackUnavailable('Claude returned no usable feedback. Try again.') from None


def _strict(schema):
    """Claude's structured output wants every object closed; Gemini's wants them open."""
    out = json.loads(json.dumps(schema))
    def close(node):
        if isinstance(node, dict):
            if node.get('type') == 'object':
                node['additionalProperties'] = False
                node['required'] = list(node.get('properties', {}))
            for v in node.values():
                close(v)
        elif isinstance(node, list):
            for v in node:
                close(v)
    close(out)
    return out


def _ask(payload, key, model):
    body = dict(
        systemInstruction=dict(parts=[dict(text=SYSTEM)]),
        contents=[dict(role='user', parts=[dict(text=json.dumps(payload))])],
        generationConfig=dict(responseMimeType='application/json', responseSchema=SCHEMA, temperature=0.6))
    request = urllib.request.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': key})  # header, not URL: keys in URLs get logged
    import time
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                result = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 503) and attempt < 2:  # Google's "high demand" spikes pass quickly
                time.sleep(3 * (attempt + 1))
                continue
            result = error
            break
        except (urllib.error.URLError, TimeoutError) as error:
            raise FeedbackUnavailable(f'Could not reach Gemini: {error}'[:300]) from None
    if isinstance(result, urllib.error.HTTPError):
        error = result
        detail = ''
        try:
            detail = json.load(error).get('error', {}).get('message', '')
        except Exception:  # noqa: BLE001
            pass
        if error.code in (400, 401, 403) and 'key' in detail.lower():
            raise FeedbackUnavailable('Google rejected the API key in .env. Check that it is a valid '
                                      'Google AI Studio key.') from None
        raise FeedbackUnavailable(f'Gemini request failed ({error.code}). {detail[:200]}'.strip()) from None
    try:
        parts = result['candidates'][0]['content']['parts']
        return json.loads(''.join(p.get('text', '') for p in parts))
    except (KeyError, IndexError, ValueError):
        raise FeedbackUnavailable('Gemini returned no usable feedback. Try again.') from None


def teacher_feedback(alignment, cache_dir, title='', force=False):
    """Piano-teacher feedback for one comparison; cached in cache_dir/teacher.json."""
    load_env()
    payload = feedback_payload(alignment, title)
    which = provider()
    if which == 'claude' and not (os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN')):
        which = 'gemini'  # no Anthropic credential: fall back rather than fail
    model = CLAUDE_MODEL if which == 'claude' else (os.environ.get('GEMINI_MODEL') or GEMINI_MODEL)
    digest = hashlib.sha256((model + SYSTEM + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
    cache = Path(cache_dir) / 'teacher.json'
    if cache.is_file() and not force:
        saved = json.loads(cache.read_text(encoding='utf-8'))
        if saved.get('digest') == digest:
            return dict(saved['feedback'], written_by=saved.get('written_by', model))
    feedback = _ask_claude(payload, model) if which == 'claude' else _ask(payload, _key(), model)
    cache.write_text(json.dumps(dict(digest=digest, written_by=model, feedback=feedback), indent=2) + '\n', encoding='utf-8')
    return dict(feedback, written_by=model)
