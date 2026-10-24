"""Run just the live practice screen: score prep, live note detection, sampled piano, summary.

    .venv/bin/python -m pianocoach.practice_server [port]      # http://127.0.0.1:5002/practice

Serves /practice, the /api/practice/* routes and /api/pieces. The end-of-take final review
(/api/analyze) belongs to the full app and is not part of this launcher; the page falls back
to a download link for the captured take when that route is absent.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from flask import Flask, jsonify, redirect  # noqa: E402

from pianocoach.live import PIECES, practice  # noqa: E402

app = Flask(__name__)
app.register_blueprint(practice)


@app.get('/')
def index():
    return redirect('/practice')


@app.get('/api/pieces')
def pieces():
    items = []
    for path in sorted(PIECES.glob('*')):
        if path.suffix.lower() in ('.musicxml', '.xml', '.mxl', '.pdf'):
            sidecar = path.with_suffix('.json')
            meta = json.loads(sidecar.read_text(encoding='utf-8')) if sidecar.is_file() else {}
            items.append(dict(id=path.stem, file=path.name, title=meta.get('title', path.stem),
                              composer=meta.get('composer'), catalog=meta.get('catalog'), bpm=meta.get('bpm', 120)))
    return jsonify(items)


def run_server(port=5002):
    app.run(host='127.0.0.1', port=port, debug=False, threaded=True)


if __name__ == '__main__':
    run_server(int(sys.argv[1]) if len(sys.argv) > 1 else 5002)
