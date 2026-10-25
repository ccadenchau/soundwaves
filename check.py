"""Run PianoCoach checks: python3 check.py."""

import shutil
import subprocess
import sys

from run import ROOT, setup

UNIT_TESTS = [
    "pianocoach.test_audio_cleaner", "pianocoach.test_clean", "pianocoach.test_scoreprep",
    "pianocoach.test_report", "pianocoach.test_partial", "pianocoach.test_pipeline",
    "pianocoach.test_live", "pianocoach.test_transkun", "sheet_downloader.test_reference",
    "testing.test_notation",
]


def main():
    python = setup()
    commands = [("Python unit tests", [str(python), "-m", "unittest", *UNIT_TESTS])]
    node = shutil.which("node")
    if node:
        commands.append(("Browser logic tests", [node, "--test", *[
            str(path) for path in sorted((ROOT / "pianocoach-ui" / "tests").glob("*.test.cjs"))]]))
    commands.append(("End-to-end cases", [str(python), "-m", "pianocoach.selftest"]))
    failed = False
    for label, command in commands:
        failed |= subprocess.run(command, cwd=ROOT).returncode != 0
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, OSError) as error:
        sys.exit(f"Checks could not start: {error}")
