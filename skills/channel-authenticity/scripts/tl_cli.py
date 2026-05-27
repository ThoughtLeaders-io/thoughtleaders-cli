#!/usr/bin/env python3
"""Single data-access seam for the channel-authenticity skill.

Every TL data getter shells out to the ``tl`` CLI (``tl db pg/fb/es``,
``tl channels similar``), so the skill works for anyone with a ThoughtLeaders
CLI account (Intelligence plan) and needs no database credentials of any kind.
It fails fast with a clear message if the CLI is missing or not authenticated —
it never reaches for a database directly.

Public API:

    db_pg(sql)            -> list[dict]
    db_fb(sql)            -> list[dict]
    db_es(body: dict)     -> dict        # normalized ES response (hits)
    channels_show(ref)    -> dict
    channels_similar(cid, limit=20) -> list[dict]
    preflight()           -> None        # raises CliUnavailable if unusable
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess

import _io_utf8

TL_BIN = os.environ.get("TL_CLI_BIN", "tl")


class CliUnavailable(RuntimeError):
    """Raised when the tl CLI cannot be used (missing, not authenticated, or
    the account lacks the required plan)."""


class DataError(RuntimeError):
    """A query executed but returned an error."""


class AmbiguousChannel(DataError):
    """A name/handle matched multiple channels; the caller must pick by id.

    Carries the candidate rows (ordered by subscribers desc) so the
    orchestrator can present them and re-run with a specific id.
    """

    def __init__(self, ref, candidates: list[dict]):
        self.ref = ref
        self.candidates = candidates
        lines = "\n".join(
            f"  {c.get('id'):>9}  {(c.get('reach') or 0):>13,}  "
            f"{c.get('channel_name', '')}"
            for c in candidates
        )
        super().__init__(
            f"Multiple channels match '{ref}'. Re-run with a specific id.\n"
            f"  {'id':>9}  {'subscribers':>13}  name\n{lines}"
        )


# --------------------------------------------------------------------------- #
# tl CLI invocation
# --------------------------------------------------------------------------- #
def _tl(args: list[str], *, input_text: str | None = None) -> str:
    exe = shutil.which(TL_BIN) or TL_BIN
    try:
        proc = subprocess.run(
            [exe, *args],
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_io_utf8.child_env(),
            timeout=180,
        )
    except FileNotFoundError as exc:
        raise CliUnavailable(
            f"`{TL_BIN}` CLI not found on PATH. Install it (see the tl-setup "
            f"skill) and run `tl auth login`. ({exc})"
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
                "tl CLI account lacks the Intelligence plan required for raw "
                "queries: " + err
            )
        raise DataError(f"tl {' '.join(args)} failed: {err}")
    return proc.stdout


def _tl_json(args: list[str], *, input_text: str | None = None):
    out = _tl(args, input_text=input_text).strip()
    if not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError as exc:
        raise DataError(f"tl {' '.join(args)} returned non-JSON output: {out[:300]}") from exc


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def _db(engine: str, sql: str) -> list[dict]:
    """Run a raw query through `tl db <engine>` and return coerced rows."""
    return _coerce_rows(_tl_json(["db", engine, sql, "--json"]))


def db_pg(sql: str) -> list[dict]:
    return _db("pg", sql)


def db_fb(sql: str) -> list[dict]:
    return _db("fb", sql)


def db_es(body: dict) -> dict:
    res = _tl_json(["db", "es", json.dumps(body), "--json"])
    # `tl db es` returns the CLI envelope {results:[...flat rows...], ...};
    # normalize to the native ES shape {hits:{hits:[{_source:{...}}]}} that
    # every consumer (h["_source"]) expects.
    if isinstance(res, dict):
        rows = res.get("results", [])
    else:
        rows = res or []
    return {"hits": {"hits": [{"_source": r} for r in rows]}}


def channels_show(ref: str | int) -> dict:
    # Build the exact query rather than calling `tl channels show`: the
    # structured command returns a curated public schema (channel_id/name/
    # subscribers/category) that doesn't match the raw-table columns the rest
    # of the skill reads (id/channel_name/reach/content_category).
    sql = (
        "SELECT id, channel_name, slug, url, external_channel_id, reach, "
        "total_views, country, language, content_category, is_active, "
        "media_selling_network_join_date, is_tl_channel, engagement, "
        "sponsorship_score, num_uploads, last_published, "
        "demographic_male_share, demographic_usa_share "
        f"FROM thoughtleaders_channel WHERE {_channel_where(ref)} "
        "ORDER BY reach DESC NULLS LAST LIMIT 10"
    )
    rows = db_pg(sql)
    if not rows:
        raise DataError(f"channel not found: {ref}")
    if len(rows) > 1:
        # A name/handle matched several channels (e.g. localized dupes). Don't
        # silently pick one — surface candidates (biggest first) so the caller
        # can re-run with the intended id.
        raise AmbiguousChannel(ref, rows)
    return rows[0]


def channels_similar(channel_id: int, limit: int = 20) -> list[dict]:
    rows = _tl_json(
        ["channels", "similar", str(channel_id), "--limit", str(limit), "--json"]
    )
    return _coerce_rows(rows)


def preflight() -> None:
    """Confirm the tl CLI is usable; raise CliUnavailable otherwise."""
    _tl(["whoami"])  # raises CliUnavailable if not authed / missing


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _coerce_rows(rows) -> list[dict]:
    if rows is None:
        return []
    if isinstance(rows, dict):
        # CLI may wrap results: {"rows": [...]} or {"data": [...]}
        for key in ("rows", "data", "results"):
            if key in rows and isinstance(rows[key], list):
                return rows[key]
        return [rows]
    return list(rows)


def _channel_where(ref: str | int) -> str:
    s = str(ref).strip()
    if s.isdigit():
        return f"id = {int(s)}"
    handle = s
    ext_id = None
    if "youtube.com" in s or "youtu.be" in s:
        path = s.split("youtube.com", 1)[-1].split("youtu.be", 1)[-1]
        path = path.split("?")[0].split("#")[0]
        if "@" in path:                       # /@handle
            handle = path.split("@", 1)[1].split("/")[0]
        elif "/channel/" in path:             # /channel/UCxxxx (external id)
            ext_id = path.split("/channel/", 1)[1].split("/")[0]
        elif "/c/" in path:                   # /c/CustomName
            handle = path.split("/c/", 1)[1].split("/")[0]
        elif "/user/" in path:                # /user/LegacyName
            handle = path.split("/user/", 1)[1].split("/")[0]
        else:
            handle = path.strip("/").split("/")[0]
    if ext_id:
        return f"external_channel_id = '{ext_id.replace(chr(39), '')}'"
    handle = handle.lstrip("@").replace("'", "''")
    # /c/ and /user/ custom names are often spaced in channel_name
    spaced = handle.replace("-", " ").replace("_", " ")
    return (
        f"url ILIKE '%@{handle}%' OR slug ILIKE '%{handle}%' "
        f"OR channel_name ILIKE '%{handle}%' "
        f"OR channel_name ILIKE '%{spaced}%'"
    )


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="tl_cli data-access probe")
    p.add_argument("cmd", choices=["pg", "fb", "es", "show", "similar", "preflight"])
    p.add_argument("arg", nargs="?")
    a = p.parse_args()
    if a.cmd == "preflight":
        preflight()
        print("OK")
    elif a.cmd == "pg":
        print(json.dumps(db_pg(a.arg), default=str, indent=2))
    elif a.cmd == "fb":
        print(json.dumps(db_fb(a.arg), default=str, indent=2))
    elif a.cmd == "es":
        print(json.dumps(db_es(json.loads(a.arg)), default=str, indent=2)[:2000])
    elif a.cmd == "show":
        print(json.dumps(channels_show(a.arg), default=str, indent=2))
    elif a.cmd == "similar":
        print(json.dumps(channels_similar(int(a.arg)), default=str, indent=2))
