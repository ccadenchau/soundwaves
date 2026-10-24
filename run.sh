#!/usr/bin/env bash
# One command to set up and start PianoCoach.   ./run.sh            full setup (Transkun, best accuracy)
#                                               ./run.sh --fast     skip Transkun (Basic Pitch only, much smaller install)
# Then open http://127.0.0.1:5002/test
set -euo pipefail
cd "$(dirname "$0")"
FAST=0; [ "${1:-}" = "--fast" ] && FAST=1
PORT="${PORT:-5002}"

command -v uv >/dev/null 2>&1 || { echo "Install uv first:  brew install uv   (or see https://docs.astral.sh/uv/)"; exit 1; }

STAMP=".venv/.deps-$(shasum requirements.txt | cut -c1-12)"
if [ ! -f "$STAMP" ]; then
  echo "==> Setting up Python 3.14 environment (first run takes a minute or two)"
  [ -x .venv/bin/python ] || uv venv --python 3.14 .venv
  uv pip install --python .venv/bin/python -q -r requirements.txt anthropic
  touch "$STAMP"
fi

if [ "$FAST" = 0 ] && [ ! -x .venv-transkun/bin/python ]; then
  echo "==> Installing Transkun (better transcription, about 1 GB). Use ./run.sh --fast to skip."
  if uv venv --python 3.12 .venv-transkun && uv pip install --python .venv-transkun/bin/python -q transkun torch torchaudio soundfile "setuptools<80"; then
    echo "    Transkun ready."
  else
    echo "    Transkun install failed; continuing with Basic Pitch."
    rm -rf .venv-transkun
  fi
fi

if [ -z "${NO_BROWSER:-}" ]; then
  ( for _ in $(seq 1 40); do curl -s -o /dev/null "http://127.0.0.1:$PORT/test" && break; sleep 0.5; done
    (command -v open >/dev/null && open "http://127.0.0.1:$PORT/test") || (command -v xdg-open >/dev/null && xdg-open "http://127.0.0.1:$PORT/test") || true ) &
fi
echo "==> PianoCoach on http://127.0.0.1:$PORT   (test page: /test, live practice: /practice)   Ctrl+C to stop"
exec .venv/bin/python -m pianocoach.app "$PORT"
