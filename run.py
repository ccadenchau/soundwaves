"""Run Soundwaves at http://127.0.0.1:5001."""

import hashlib
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def setup():
    environment = ROOT / ("venv" if (ROOT / "venv/bin/python").exists() else ".venv")
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    requirements = ROOT / "requirements.txt"
    stamp = environment / (".deps-" + hashlib.sha256(requirements.read_bytes()).hexdigest()[:12])
    if not python.exists():
        venv.EnvBuilder(with_pip=True).create(environment)
    if not stamp.exists():
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", "-r",
                        str(requirements)], check=True, stdout=subprocess.DEVNULL)
        stamp.touch()
    return python


if __name__ == "__main__":
    python = setup()
    os.chdir(ROOT)
    os.execv(str(python), [str(python), "-c",
             "from soundwaves.web.app import run_server; run_server()"])
