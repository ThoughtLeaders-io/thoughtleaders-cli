"""Shared UTF-8 I/O setup for the channel-authenticity scripts.

YouTube data is full of non-ASCII: channel names, comment text, emoji.
On POSIX the default I/O encoding is already UTF-8, but on Windows the
console and the default file encoding are the legacy code page (cp1252),
so printing or writing that text raises ``UnicodeEncodeError`` (or
silently mojibakes on read-back).

Importing this module reconfigures ``stdout``/``stderr`` to UTF-8 on
Windows (a no-op elsewhere, and idempotent), so every script that does
``import _io_utf8`` can safely print Unicode. File reads/writes must
still pass ``encoding="utf-8"`` explicitly — that's done at each call
site — and child processes get ``child_env()`` so their stdio is UTF-8
too. ``UTF8`` is exported for call sites that prefer the named constant.
"""
from __future__ import annotations

import os
import sys

UTF8 = "utf-8"


def _reconfigure_std_streams() -> None:
    """Force stdout/stderr to UTF-8 on Windows. No-op on POSIX."""
    if sys.platform != "win32":
        return
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding=UTF8)
        except (ValueError, OSError):
            # Stream already detached / not reconfigurable (e.g. piped to a
            # non-text sink) — leave it as-is rather than crash on import.
            pass


def child_env() -> dict[str, str]:
    """``os.environ`` with UTF-8 forced, for subprocess children.

    ``PYTHONUTF8=1`` enables UTF-8 mode for Python children; the
    redundant ``PYTHONIOENCODING`` covers tools that read it directly.
    Use as ``subprocess.run(..., env=child_env())``.
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = UTF8
    return env


_reconfigure_std_streams()
