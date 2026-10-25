# Soundwaves frontend

Start the complete app from the repository root with `python3 run.py`, then open http://127.0.0.1:5001. Flask renders these templates and serves these assets. There is no separate frontend server or build step.

```text
frontend/
  templates/             Current app HTML and Jinja templates
    partials/            Shared header, footer, and stylesheet link
  static/
    site.css             Shared site design
    pages/               Page-specific CSS and JavaScript
    live.js              Main live practice screen
    notation.js          Report highlights and synchronized playback
    live-input/          Shared note matcher, stream adapter, and audio worklet
    audio/               Sampled piano bank and attribution
```

Pages: `/` redirects to `/live` for live practice, `/check` recording analysis, `/report/<id>` saved review, `/easy` simplify a recording, `/test` self-checks. The report embeds `/falling?embed=1` for keyboard replay. `/practice` and `/record` redirect to `/live` and `/check`.

Browser tests: `node --test testing/frontend/*.test.cjs`.

The standalone iPad keyboard is outside the app in `ipad_keys/`; see its README.

Shared waveform players use the original audio elements as their playback clock; envelopes are generated and cached by `soundwaves/web/waveform.py`. The shared analysis overlay is in `static/loading.js`. Quicksand is bundled locally in `static/fonts/` with its license.

Add sheet music with **New piece** in the piece dropdown; the shared upload modal selects it after saving. The old `/upload` link opens that modal. The Home and standalone audio-to-MIDI pages have been removed.
