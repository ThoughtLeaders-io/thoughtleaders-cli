"""Every tl-keyword-research script with a shebang must be executable.

The scripts advertise direct invocation (`probe.py ...`) in their usage text;
a 0644 checkout fails with `Permission denied`, so the mode is part of the
user-visible surface and is pinned here.
"""
import os
from pathlib import Path

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills" / "tl-keyword-research" / "scripts"
)


def test_shebang_scripts_are_executable():
    scripts = sorted(_SCRIPTS_DIR.glob("*.py"))
    assert scripts, f"no scripts found in {_SCRIPTS_DIR}"
    not_executable = [
        p.name for p in scripts
        if p.read_bytes().startswith(b"#!") and not os.access(p, os.X_OK)
    ]
    assert not_executable == [], (
        f"scripts with a shebang but no executable bit: {not_executable} — "
        f"run: chmod +x skills/tl-keyword-research/scripts/*.py"
    )
