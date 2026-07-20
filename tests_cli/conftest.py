"""Shared fixtures for the live, read-only ``tl`` CLI integration suite.

Every test here shells out to the real ``tl`` binary and talks to the
configured live API (``TL_API_URL`` + stored credentials / ``TL_API_KEY``).
The whole suite skips itself when ``tl`` is missing or the API is
unreachable/unauthenticated, so it never goes red without a backend.

See ``AGENTS.md`` in this directory for the rules every test here must follow
(read-only only; drive the real CLI, never mock).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

# The CLI under test. Override with TL_CLI_BIN to pin a specific build
# (e.g. a venv's bin/tl) without touching PATH.
TL_BIN = os.environ.get("TL_CLI_BIN", "tl")
# Generous: a raw db query against a cold backend can take tens of seconds.
DEFAULT_TIMEOUT = 120
# When truthy (the cli-integration workflow sets it), an absent CLI or an
# unreachable/unauthenticated API is a hard FAILURE instead of a skip. That is
# what makes a real outage, an expired/removed TL_API_KEY, or a broken deploy
# show up red in CI rather than hiding behind a green "all skipped". Unset
# (local / ad-hoc runs) keeps the skip-friendly behaviour.
REQUIRE_LIVE = os.environ.get("TL_CLI_REQUIRE_LIVE", "").strip().lower() in ("1", "true", "yes")


def _no_backend(reason: str) -> None:
    """Fail when a live run was demanded (REQUIRE_LIVE), otherwise skip."""
    if REQUIRE_LIVE:
        pytest.fail(f"{reason} [TL_CLI_REQUIRE_LIVE is set — this is a failure, not a skip]", pytrace=False)
    pytest.skip(reason)


def _resolve_bin() -> str:
    exe = shutil.which(TL_BIN)
    if exe is None:
        pytest.skip(f"{TL_BIN!r} not found on PATH — install the CLI to run live tests")
    return exe


def _run(*args: str, timeout: int = DEFAULT_TIMEOUT) -> subprocess.CompletedProcess:
    """Run ``tl <args>`` and return the CompletedProcess (stdout/stderr split)."""
    return subprocess.run(
        [_resolve_bin(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@pytest.fixture(scope="session", autouse=True)
def _live_api_or_skip() -> None:
    """Skip the whole suite unless a live, authenticated API answers ``whoami``.

    ``tl whoami`` is free and read-only — the cheapest reachability + auth
    probe. Connection refused, auth-required, timeout, or any non-zero exit
    skips (or fails, when ``TL_CLI_REQUIRE_LIVE`` is set — see ``_no_backend``),
    so a developer without a live backend sees skips while the cli-integration
    workflow surfaces a dead/misconfigured backend as red.
    """
    exe = shutil.which(TL_BIN)
    if exe is None:
        _no_backend(f"{TL_BIN!r} not found on PATH — install the CLI to run live tests")
    try:
        proc = subprocess.run(
            [exe, "whoami", "--json"], capture_output=True, text=True, timeout=30
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        _no_backend(f"`tl whoami` could not run ({exc}); no live API")
    if proc.returncode != 0:
        _no_backend(
            "live API not reachable/authenticated — `tl whoami` exited "
            f"{proc.returncode}: {(proc.stderr or proc.stdout).strip()[:200]}"
        )


@pytest.fixture
def tl():
    """Return ``run(*args, timeout=...) -> CompletedProcess`` for the real CLI."""
    return _run


@pytest.fixture
def tl_json():
    """Return ``run(*args) -> dict`` that runs ``tl <args> --json`` and parses stdout.

    Asserts a clean exit and JSON on stdout. The usage footer the CLI prints to
    stderr is ignored — stdout carries the data envelope.
    """

    def _run_json(*args: str, timeout: int = DEFAULT_TIMEOUT):
        proc = _run(*args, "--json", timeout=timeout)
        cmd = "tl " + " ".join([*args, "--json"])
        assert proc.returncode == 0, f"`{cmd}` failed (exit {proc.returncode}): {proc.stderr.strip()}"
        try:
            return json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(f"`{cmd}` did not emit JSON on stdout: {exc}\nstdout: {proc.stdout[:500]!r}")

    return _run_json
