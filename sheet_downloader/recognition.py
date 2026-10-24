import os
import shutil
import subprocess
from pathlib import Path


def find_audiveris(executable=None):
    candidates = [
        executable,
        os.environ.get("AUDIVERIS_PATH"),
        shutil.which("audiveris"),
        shutil.which("Audiveris"),
        Path.home() / "Applications/Audiveris.app/Contents/MacOS/Audiveris",
        Path("/Applications/Audiveris.app/Contents/MacOS/Audiveris"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(candidate)
    raise RuntimeError("Install Audiveris and set AUDIVERIS_PATH to its executable.")


def exported_score(output):
    scores = sorted(output.rglob("*.mxl")) or sorted(output.rglob("*.musicxml"))
    return scores[0] if len(scores) == 1 else None


def convert_pdf(source, output, *, executable=None, timeout=300):
    if output.exists() and any(output.iterdir()):
        raise ValueError("Recognition output directory must be empty.")
    output.mkdir(parents=True, exist_ok=True)
    command = [
        find_audiveris(executable),
        "-batch",
        "-export",
        "-output",
        str(output),
        "--",
        str(source),
    ]
    try:
        result = subprocess.run(
            command, capture_output=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("Recognition timed out. Try a shorter PDF.") from error
    if result.returncode:
        raise RuntimeError("Audiveris could not read this score. Try a clearer PDF.")
    score = exported_score(output)
    if score is None:
        raise RuntimeError("Upload one piece at a time. Recognition must produce one score.")
    return score
