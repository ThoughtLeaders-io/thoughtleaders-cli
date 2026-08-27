#!/usr/bin/env python3
"""Shared data-access seam for skills that shell out to the ``tl`` CLI.

One wrapper instead of a copy per script. Import it with a two-line path hook
(no ``cd`` into any skill directory, so concurrent runs on different channels
never fight over a working directory):

    import pathlib, sys
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
    import tl_cli

Behaviour every consumer relies on:

* **Query bodies travel on stdin** (``tl db es -``), never argv, so a large
  ids list or SQL never hits an argument-length limit.
* **Every call has a timeout** (default 180s). One hung ``tl`` process must
  not stall a bulk run.
* **Failures are loud.** Auth, credit, plan and network errors raise; they are
  never converted into empty results, because an empty result is data and an
  error is not.

Public API:

    db_pg(sql)        -> list[dict]   rows
    db_fb(sql)        -> list[dict]   rows
    db_es(body: dict) -> list[dict]   rows (the CLI's ``results`` list)
    whoami()          -> dict
    preflight()       -> None         raises CliUnavailable if unusable
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

TL_BIN = os.environ.get("TL_CLI_BIN", "tl")
DEFAULT_TIMEOUT = 180


class CliUnavailable(RuntimeError):
    """The tl CLI cannot be used: missing, not authenticated, out of credits,
    or the account lacks the required plan."""


class DataError(RuntimeError):
    """A query executed but failed or returned something unreadable."""


def _tl(args: list[str], *, input_text: str | None = None,
        timeout: int = DEFAULT_TIMEOUT) -> str:
    exe = shutil.which(TL_BIN) or TL_BIN
    try:
        proc = subprocess.run(
            [exe, *args],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise CliUnavailable(
            f"`{TL_BIN}` CLI not found on PATH. Install it (see the tl-setup "
            f"skill) and run `tl auth login`. ({exc})"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise DataError(
            f"tl {' '.join(args[:3])} timed out after {timeout}s"
        ) from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        low = err.lower()
        if "auth" in low and ("login" in low or "required" in low or "401" in low):
            raise CliUnavailable(
                "tl CLI is not authenticated. Run `tl auth login` (or set "
                "TL_API_KEY), then retry. " + err
            )
        if "credit" in low or "payment required" in low or "402" in low:
            raise CliUnavailable("tl CLI is out of credits: " + err)
        if "intelligence" in low or "plan" in low or "403" in low:
            raise CliUnavailable(
                "tl CLI account lacks the plan required for raw queries: " + err
            )
        raise DataError(f"tl {' '.join(args[:3])} failed: {err[:500]}")
    return proc.stdout


def _tl_json(args: list[str], *, input_text: str | None = None,
             timeout: int = DEFAULT_TIMEOUT):
    out = _tl(args, input_text=input_text, timeout=timeout).strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise DataError(
            f"tl {' '.join(args[:3])} returned non-JSON output: {out[:300]}"
        ) from exc


def _rows(data) -> list[dict]:
    if data is None:
        return []
    if isinstance(data, dict):
        for key in ("results", "rows", "data"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    return list(data)


def db_pg(sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return _rows(_tl_json(["db", "pg", "-", "--json"], input_text=sql,
                          timeout=timeout))


def db_fb(sql: str, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    return _rows(_tl_json(["db", "fb", "-", "--json"], input_text=sql,
                          timeout=timeout))


def db_es(body: dict, *, timeout: int = DEFAULT_TIMEOUT) -> list[dict]:
    """Run an ES search body and return the rows.

    ``tl db es`` returns ``{"results": [...]}`` (flat rows), not the native
    ``hits.hits`` shape.
    """
    return _rows(_tl_json(["db", "es", "-", "--json"],
                          input_text=json.dumps(body), timeout=timeout))


def whoami(*, timeout: int = DEFAULT_TIMEOUT) -> dict:
    data = _tl_json(["whoami", "--json"], timeout=timeout)
    return data if isinstance(data, dict) else {}


def preflight() -> None:
    """Confirm the tl CLI is usable; raise CliUnavailable otherwise."""
    _tl(["whoami"], timeout=60)
