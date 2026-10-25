"""Compatibility entry point for the local PianoCoach server."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

if __name__ == '__main__':
    from pianocoach.web.app import run_server
    run_server()
