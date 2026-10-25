# Soundwaves backend

Run `python3 run.py` from the repository root. The only application server is `soundwaves.web.app` on http://127.0.0.1:5001.

- `web/app.py`: main website, reports, artifact playback, and notation routes.
- `web/pipeline.py`: cached score conversion, transcription, and report storage.
- `web/live_demo.py`: live practice sessions and APIs for `/live`.
- `app.py`: piece management, conversion tools, and saved-session API blueprint; not a separate server.
- `live.py`: shared audio/MIDI input, piano samples, score preparation, and provisional note APIs.
- `pipeline.py`, `clean.py`, `report.py`, `scoreprep.py`: analysis and report generation.
- `transkun_backend.py`, `transkun_worker.py`: piano-specific transcription worker.
- `teacher.py`, `explain.py`: optional written feedback.
- `selftest.py`: end-to-end cases and the `/test` tool.
- `pieces/`: scores and piece metadata.
- `web/cache/`, `sessions/`: saved recordings and analysis artifacts (gitignored).

All current browser templates, styles, and scripts live in `frontend/`. The independent iPad keyboard lives in `ipad_keys/`. See `frontend/CLEANUP.md` for the removed legacy pages.

Tests: `python3 check.py`, or `venv/bin/python -m unittest discover -s testing/soundwaves -t .`.
