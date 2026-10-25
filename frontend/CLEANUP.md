# Removed legacy interfaces

These were alternate interfaces rather than the current main app design:

- `soundwaves-ui/index.html`: standalone sample report viewer and its older review design.
- `soundwaves-ui/fixtures/sample_report.json`: sample data for that viewer.
- `soundwaves-ui/practice/index.html`, `practice.css`, `practice.js`, and `practice-demo.js`: older alternate live screen and its demo.
- `soundwaves-ui/tests/practice-demo.test.cjs`: tests only for that removed demo.
- `soundwaves/app.py`: removed its embedded `RECORD` page, report loader, and separate Flask application/launcher. The file remains as a blueprint for the current app's APIs and tools.
- `soundwaves/practice_server.py`: alternate development server for the old practice screen.
- `testing/web-server/`: unused preview Flask server, preview renderer, HTML, scripts, styles, and its separate requirements file. Its shared piano samples and attribution were preserved under `frontend/static/audio/`.

Moved and retained:

- `soundwaves-ui/ipad-keys.html` → `ipad_keys/index.html` (standalone; not served by the app).
- Current HTML embedded in Python → `frontend/templates/`.
- `soundwaves/web/static/live.html` → `frontend/templates/live.html`.
- `soundwaves/web/static/live.js` and `notation.js` → `frontend/static/`.
- `soundwaves-ui/shared/site.css` → `frontend/static/site.css`.
- Shared audio worklet, note matcher, stream adapter → `frontend/static/live-input/`.
- Keyboard replay → `frontend/templates/keyboard-replay.html`; it is still embedded by the current report page.
- Retained browser tests → `testing/frontend/`.

The old `soundwaves-ui/` and `soundwaves/web/static/` directories are gone. Saved reports, recordings, scores, and transcription models are preserved. Saved API/self-check sessions use the same current report template. Conversion and self-check tools now inherit the shared light theme; dark piano rolls and the embedded keyboard are visualization surfaces.

Further consolidation: removed `frontend/templates/home.html`, `upload.html`, and `convert.html`, plus the old upload/conversion page CSS and scripts. Piece uploads now use `frontend/static/piece-modal.js`; `/` opens Play, and `/upload` opens the modal. The score-transcription backend and MIDI downloads remain part of practice/review.
