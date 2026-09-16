#!/usr/bin/env python3
"""Run the complete add-on test suite consistently on Windows and Linux."""

from pathlib import Path
import compileall
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 oder neuer ist erforderlich.")
    if not compileall.compile_dir(ROOT / "freecad_plm_addon", quiet=1):
        return 1
    command = [
        sys.executable,
        "-m",
        "unittest",
        "discover",
        "-s",
        "tests",
    ]
    return subprocess.run(command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
