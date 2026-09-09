#!/usr/bin/env python3
"""Single data-access seam for the tl-channel-authenticity skill.

Every TL data getter uses the shared transport provider. CLI users keep their
existing authentication; MCP sessions obtain evidence through the connected
host. No database credentials are used.

Public API:

    db_pg(sql)            -> list[dict]
    db_fb(sql)            -> list[dict]
    db_es(body: dict)     -> dict        # normalized ES response (hits)
    channels_show(ref)    -> dict
    channels_similar(cid, limit=20) -> list[dict]
    preflight()           -> None        # raises CliUnavailable if unusable
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import _io_utf8

_SHARED = Path(__file__).resolve().parents[2] / "_shared"
if _SHARED.is_dir():
    sys.path.insert(0, str(_SHARED))

import tl_data
from tl_data import CliUnavailable, DataError


class AmbiguousChannel(DataError):
    """A name/handle matched multiple channels; the caller must pick by id.

    Carries the candidate rows (ordered by subscribers desc) so the
    orchestrator can present them and re-run with a specific id.
    """

    def __init__(self, ref, candidates: list[dict]):
        self.ref = ref
        self.candidates = candidates
        lines = "\n".join(
            f"  {c.get('id'):>9}  {(c.get('subscribers') or 0):>13,}  "
            f"{c.get('channel_name', '')}"
            for c in candidates
        )
        super().__init__(
            f"Multiple channels match '{ref}'. Re-run with a specific id.\n"
            f"  {'id':>9}  {'subscribers':>13}  name\n{lines}"
        )


def _db(engine: str, sql: str) -> list[dict]:
    return tl_data.rows(tl_data.query(engine, sql))


def db_pg(sql: str) -> list[dict]:
    return _db("pg", sql)


def db_fb(sql: str) -> list[dict]:
    return _db("fb", sql)


def db_es(body: dict) -> dict:
    result = tl_data.query("es", body)
    return {"hits": {"hits": [{"_source": row} for row in tl_data.rows(result)]}}


def channels_show(ref: str | int) -> dict:
    # Build the exact query rather than calling `tl channels show`: the
    # structured command returns a curated public schema (channel_id/name/
    # subscribers/category) that doesn't match the raw-table columns the rest
    # of the skill reads (id/channel_name/subscribers/content_category).
    sql = (
        "SELECT id, channel_name, slug, url, external_channel_id, subscribers, "
        "total_views, country, language, content_category, is_active, "
        "media_selling_network_join_date, is_tpp, engagement, "
        "sponsorship_score, num_uploads, last_published, "
        "demographic_male_share, demographic_usa_share "
        f"FROM thoughtleaders_channel WHERE {_channel_where(ref)} "
        "ORDER BY subscribers DESC NULLS LAST LIMIT 10"
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
    return tl_data.channels_similar(channel_id, limit=limit)


def preflight() -> None:
    tl_data.preflight()


def _coerce_rows(value) -> list[dict]:
    return tl_data.rows(value)


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
