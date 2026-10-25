"""Ask Claude to explain each finding in plain words. Cached on disk, offline-safe.

The fallback wording written by `pianocoach.report` stays in place when there is
no credential, no network, or the request is refused, and `meta.explanations`
says which one the page is showing.
"""

import hashlib
import json
import sys
from pathlib import Path

MODEL = 'claude-opus-5-5'
GEMINI_MODEL = 'gemini-3.8-flash'
CACHE = Path(__file__).with_name('cache') / 'explanations'
ENV_FILE = Path(__file__).resolve().parents[1] / '.env'


def load_env(path=ENV_FILE):
    """Read KEY=VALUE lines from the repo's .env (gitignored) into os.environ without overriding."""
    import os
    if not Path(path).is_file():
        return
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def provider(choice=None):
    """Which model writes the explanations. PIANOCOACH_EXPLAINER=claude|gemini|auto.
    auto: Claude when an Anthropic credential is set, else Gemini when GEMINI_API_KEY or
    GOOGLE_API_KEY is set, else none (the plain fallback wording stays)."""
    import os
    load_env()
    choice = (choice or os.environ.get('PIANOCOACH_EXPLAINER', 'auto')).lower()
    if choice in ('claude', 'gemini'):
        return choice
    if os.environ.get('ANTHROPIC_API_KEY') or os.environ.get('ANTHROPIC_AUTH_TOKEN'):
        return 'claude'
    if os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY'):
        return 'gemini'
    return 'claude'  # the SDK may still find a stored profile; otherwise it falls back cleanly

SYSTEM = """You are a piano teacher writing short notes to a self-taught student who just recorded a practice take and cannot afford lessons. A program compared the take with the score and found the spots listed in the JSON. You explain each one and give one thing to try.

How to write:
- Plain words a teenager would use. Say which note and which bar. Keep the explanation to one or two sentences and the tip to one or two sentences.
- Each tip is a concrete drill: which bar or beats, which hand, roughly what tempo, how many clean repeats. Vary the drills; do not reuse the same shape of sentence for every finding.
- If two findings are the same mistake in a repeated passage, say so in the second one instead of repeating the advice.
- When the confidence is "possible" or the finding is an extra note that could be a harmonic or recording noise, say plainly that it might be the recording rather than the playing.
- Timing findings compare the note with the pace of the rest of that bar, not with a metronome. Rushed or dragged bars are reported separately under bar_tempo; mention it when it matters.
- No praise filler, no exclamation marks, no bullet lists, no lists of three, no mention of software or AI. Do not start every sentence the same way.
- Also write a two-sentence summary of the whole take for the top of the page, in the same voice. Lead with the most useful thing to practise next.

Return JSON only, matching the schema."""

SCHEMA = {
    'type': 'object',
    'properties': {
        'summary': {'type': 'string'},
        'findings': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {'id': {'type': 'string'}, 'explanation': {'type': 'string'}, 'tip': {'type': 'string'}},
                'required': ['id', 'explanation', 'tip'],
                'additionalProperties': False,
            },
        },
    },
    'required': ['summary', 'findings'],
    'additionalProperties': False,
}


def _payload(report):
    by_bar = {}
    for measure, beat, pitch, dur in report['notes']:
        by_bar.setdefault(measure, []).append(f'{beat:g}:{pitch}:{dur:g}')
    bars = {b['measure']: b for b in report.get('bars', [])}
    findings = []
    for e in report['errors']:
        bar = bars.get(e['measure'], {})
        item = dict(id=e['id'], category=e['category'], bar=e['measure'], beat=e['beat'],
                    expected=e.get('expected'), actual=e.get('actual'), tier=e['tier'],
                    confidence=e['confidence'], score_notes_in_bar=by_bar.get(e['measure'], []),
                    bar_tempo=dict(pace=bar.get('pace'), pace_ratio=bar.get('pace_ratio'),
                                   performed_bpm=bar.get('performed_bpm')),
                    maybe_ornament=bool(e.get('maybe_ornament')), octave=bool(e.get('octave')),
                    occurrences=e.get('occurrences', 1))
        if 'delta_ms' in e:
            item['delta_ms'] = e['delta_ms']
        if 'held_beats' in e:
            item['held_beats'] = e['held_beats']
        findings.append(item)
    return dict(piece=report['piece'], take=report['take'], pace=report.get('pace'), findings=findings,
                played_bars=report.get('meta', {}).get('played_bars'),
                notes_format='beat:pitch:duration_in_beats, right hand only',
                pace_format='pace compares each bar with the median tempo of this take, not the printed tempo')


def explain_report(report, *, client=None, model=MODEL, cache_dir=CACHE, force=False):
    report.setdefault('meta', {})
    if not report['errors']:
        report['meta']['explanations'] = 'none'
        report['coach'] = 'Every right-hand note matched the score on this take.'
        return report
    payload = _payload(report)
    which = provider()
    if which == 'gemini':
        import os
        model = os.environ.get('GEMINI_MODEL', GEMINI_MODEL)
    key = hashlib.sha256((model + json.dumps(payload, sort_keys=True)).encode()).hexdigest()
    cache_dir = Path(cache_dir)
    cache_file = cache_dir / f'{key}.json'
    if cache_file.is_file() and not force:
        _apply(report, json.loads(cache_file.read_text(encoding='utf-8')), model, cached=True, provider_name=which)
        return report
    try:
        data = _ask_gemini(payload, model) if which == 'gemini' else _ask_claude(payload, model, client)
    except Exception as error:  # noqa: BLE001 - the page must still render
        report['meta']['explanations'] = 'fallback'
        report['meta']['explain_error'] = f'{type(error).__name__}: {error}'[:300]
        return report
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
    _apply(report, data, model, cached=False, provider_name=which)
    return report


def _ask_claude(payload, model, client=None):
    import anthropic
    client = client or anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=6000,
        system=SYSTEM,
        messages=[{'role': 'user', 'content': json.dumps(payload)}],
        output_config={'format': {'type': 'json_schema', 'schema': SCHEMA}},
    )
    if response.stop_reason == 'refusal':
        raise RuntimeError('Claude declined this request.')
    text = next(b.text for b in response.content if b.type == 'text')
    return json.loads(text)


def _ask_gemini(payload, model):
    """Gemini through the REST API with a JSON response schema. The key travels in a header."""
    import os
    import urllib.request
    key = os.environ.get('GEMINI_API_KEY') or os.environ.get('GOOGLE_API_KEY')
    if not key:
        raise RuntimeError('GEMINI_API_KEY is not set.')
    schema = json.loads(json.dumps(SCHEMA))
    for obj in (schema, schema['properties']['findings']['items']):
        obj.pop('additionalProperties', None)
    body = dict(
        systemInstruction=dict(parts=[dict(text=SYSTEM)]),
        contents=[dict(role='user', parts=[dict(text=json.dumps(payload))])],
        generationConfig=dict(responseMimeType='application/json', responseSchema=schema, temperature=0.7),
    )
    request = urllib.request.Request(
        f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
        data=json.dumps(body).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'x-goog-api-key': key})
    with urllib.request.urlopen(request, timeout=120) as response:
        result = json.load(response)
    candidate = result['candidates'][0]
    text = ''.join(part.get('text', '') for part in candidate['content']['parts'])
    return json.loads(text)


def _apply(report, data, model, *, cached, provider_name='claude'):
    by_id = {f['id']: f for f in data.get('findings', [])}
    filled = 0
    for e in report['errors']:
        f = by_id.get(e['id'])
        if f and f.get('explanation') and f.get('tip'):
            e['explanation'], e['tip'] = f['explanation'].strip(), f['tip'].strip()
            filled += 1
    if data.get('summary'):
        report['coach'] = data['summary'].strip()
    report['meta']['explanations'] = provider_name if filled else 'fallback'
    report['meta']['explain_model'] = model
    report['meta']['explain_cached'] = cached
    report['meta']['explain_filled'] = filled


def main(argv):
    if len(argv) != 2:
        print('usage: python -m pianocoach.explain report.json', file=sys.stderr)
        return 2
    path = Path(argv[1])
    report = json.loads(path.read_text(encoding='utf-8'))
    explain_report(report, force=True)
    path.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps(report['meta'], indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
