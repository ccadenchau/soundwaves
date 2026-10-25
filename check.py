"""Run Soundwaves checks: python3 check.py."""

import shutil
import subprocess
import sys

from run import ROOT, setup

UNIT_TESTS = [
    "testing.soundwaves.test_audio_cleaner", "testing.soundwaves.test_clean", "testing.soundwaves.test_scoreprep",
    "testing.soundwaves.test_report", "testing.soundwaves.test_partial", "testing.soundwaves.test_pipeline",
    "testing.soundwaves.test_live", "testing.soundwaves.test_transkun", "sheet_downloader.test_reference",
    "testing.test_notation", "testing.test_frontend",
]


def main():
    python = setup()
    commands = [("Python unit tests", [str(python), "-m", "unittest", *UNIT_TESTS])]
    node = shutil.which("node")
    if node:
        commands.append(("Browser logic tests", [node, "--test", *[
            str(path) for path in sorted((ROOT / "testing" / "frontend").glob("*.test.cjs"))]]))
    commands.append(("End-to-end cases", [str(python), "-m", "soundwaves.selftest"]))
    failed = False
    for label, command in commands:
        failed |= subprocess.run(command, cwd=ROOT).returncode != 0
    return int(failed)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (subprocess.CalledProcessError, OSError) as error:
        sys.exit(f"Checks could not start: {error}")
