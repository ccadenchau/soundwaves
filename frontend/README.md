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

Pages: `/` home, `/live` live practice, `/check` recording analysis, `/report/<id>` saved review, `/upload` add a score, `/easy` simplify a recording, `/convert` audio-to-MIDI tools, and `/test` self-checks. The report embeds `/falling?embed=1` for keyboard replay. `/practice` and `/record` redirect to `/live` and `/check`.

Browser tests: `node --test testing/frontend/*.test.cjs`.

The standalone iPad keyboard is outside the app in `ipad_keys/`; see its README.
