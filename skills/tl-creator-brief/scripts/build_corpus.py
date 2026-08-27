#!/usr/bin/env python3
"""Choose which uploads get read, and cap how many. Never the whole catalogue.

This is the cost control for the whole skill. A channel in this corpus can carry
hundreds of uploads running two hours each; reading all of them is a bill with no
ceiling, and nothing in a markdown instruction reliably stops a model from doing
it. So the decision is made here, in code, before any transcript is fetched, and
the script reports what it left out so the caller can say so in the output.

Three strategies:

* ``spread`` (default). The channel's whole history is cut into ``max`` equal
  slices of TIME, and the most-viewed upload in each slice is taken. Equal slices
  of time rather than of count, because upload rates rise over a channel's life
  and equal-count slices would quietly collapse into a recent-only sample. The
  point is a sample that is neither all recent nor all old: an offhand personal
  detail is as likely to sit in a five-year-old video as in last week's.
* ``recent``. Newest first, for a caller who only cares about now.
* ``top-views``. Most-viewed first, for a caller who wants the flagship videos.

Longform only by default. Shorts are mostly hooks and clips, so they cost
transcript fetches and return little self-talk.

Usage:
    build_corpus.py --channel 138573                       # spread, 40 videos
    build_corpus.py --channel 138573 --max 25 --strategy recent
    build_corpus.py --channel 138573 --since 2024-01-01

Output (stdout): one JSON object, ready to pipe into selftalk_scan.py.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

ES_PAGE = 10000  # the index's ceiling for a plain size request


def tl_pg(sql: str) -> list[dict]:
    proc = subprocess.run(["tl", "db", "pg", sql, "--json"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    data = json.loads(proc.stdout)
    return data if isinstance(data, list) else data.get("results") or []


def tl_es(body: dict) -> list[dict]:
    proc = subprocess.run(["tl", "db", "es", json.dumps(body)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"tl db es failed: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout).get("results") or []


def fetch_uploads(channel_id: int, content_type: str | None,
                  since: str | None, until: str | None) -> list[dict]:
    flt: list[dict] = [
        {"term": {"doc_type": "article"}},
        {"term": {"channel.id": channel_id}},
    ]
    if content_type:
        flt.append({"term": {"content_type": content_type}})
    rng = {}
    if since:
        rng["gte"] = since
    if until:
        rng["lte"] = until
    if rng:
        flt.append({"range": {"publication_date": rng}})

    rows = tl_es({
        "size": ES_PAGE,
        "query": {"bool": {"filter": flt}},
        "_source": ["id", "title", "publication_date", "views", "duration",
                    "content_type"],
        "sort": [{"publication_date": "asc"}],
    })
    out = []
    for r in rows:
        pub = str(r.get("publication_date") or "")[:10]
        if not pub or not r.get("id"):
            continue
        out.append({
            "id": r["id"],
            "video_id": str(r["id"]).split(":")[-1],
            "title": r.get("title"),
            "published": pub,
            "views": int(r["views"]) if r.get("views") else 0,
            "duration": r.get("duration"),
            "content_type": r.get("content_type"),
        })
    out.sort(key=lambda v: v["published"])
    return out


def _days(a: str, b: str) -> int:
    import datetime as dt
    ya, ma, da = (int(x) for x in a.split("-"))
    yb, mb, db = (int(x) for x in b.split("-"))
    return (dt.date(yb, mb, db) - dt.date(ya, ma, da)).days


def pick_spread(uploads: list[dict], want: int) -> list[dict]:
    """Most-viewed upload from each of ``want`` equal slices of the timeline."""
    if len(uploads) <= want:
        return list(uploads)
    first, last = uploads[0]["published"], uploads[-1]["published"]
    span = max(_days(first, last), 1)

    buckets: list[list[dict]] = [[] for _ in range(want)]
    for v in uploads:
        pos = _days(first, v["published"]) / span
        idx = min(int(pos * want), want - 1)
        buckets[idx].append(v)

    picked, leftovers = [], []
    for b in buckets:
        if not b:
            continue
        b.sort(key=lambda v: -v["views"])
        picked.append(b[0])
        leftovers.extend(b[1:])

    # Empty slices (a hiatus, or a channel that only got going late) would leave
    # the sample short, so backfill from the busiest slices by views.
    if len(picked) < want:
        leftovers.sort(key=lambda v: -v["views"])
        chosen = {v["id"] for v in picked}
        for v in leftovers:
            if len(picked) >= want:
                break
            if v["id"] not in chosen:
                picked.append(v)
                chosen.add(v["id"])

    picked.sort(key=lambda v: v["published"])
    return picked


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, required=True)
    ap.add_argument("--max", type=int, default=40,
                    help="hard ceiling on videos returned (default 40)")
    ap.add_argument("--strategy", choices=["spread", "recent", "top-views"],
                    default="spread")
    ap.add_argument("--content-type", default="longform",
                    help="'longform' (default), 'short', or 'all'")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD")
    a = ap.parse_args()

    ctype = None if a.content_type == "all" else a.content_type
    uploads = fetch_uploads(a.channel, ctype, a.since, a.until)
    if not uploads:
        sys.exit(f"no uploads found for channel {a.channel} "
                 f"(content_type={a.content_type}, since={a.since})")

    if a.strategy == "spread":
        selected = pick_spread(uploads, a.max)
    elif a.strategy == "recent":
        selected = sorted(uploads, key=lambda v: v["published"],
                          reverse=True)[:a.max]
        selected.sort(key=lambda v: v["published"])
    else:
        selected = sorted(uploads, key=lambda v: -v["views"])[:a.max]
        selected.sort(key=lambda v: v["published"])

    name_rows = tl_pg("SELECT channel_name FROM thoughtleaders_channel "
                      f"WHERE id = {a.channel}")

    print(json.dumps({
        "channel_id": a.channel,
        "channel_name": (name_rows[0].get("channel_name")
                         if name_rows else None),
        "strategy": a.strategy,
        "max": a.max,
        "content_type": a.content_type,
        "available": len(uploads),
        "selected_count": len(selected),
        "not_read": len(uploads) - len(selected),
        "date_range_available": [uploads[0]["published"],
                                 uploads[-1]["published"]],
        "date_range_selected": ([selected[0]["published"],
                                 selected[-1]["published"]]
                                if selected else None),
        "coverage_note": (
            f"{len(selected)} of {len(uploads)} {a.content_type} uploads read, "
            f"chosen by {a.strategy}; {len(uploads) - len(selected)} not read"
        ),
        "selected": selected,
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
