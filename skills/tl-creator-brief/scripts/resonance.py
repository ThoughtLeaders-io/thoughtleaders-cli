#!/usr/bin/env python3
"""Score a channel's uploads against their own nearest-in-age peers, per format.

Two failure modes this exists to avoid:

1. **Mixing formats.** Shorts and long-form have completely different view
   distributions on the same channel (observed: Shorts medians 36k-219k against
   a long-form median of 3.36m). A shared baseline scores a whole format wrong.
2. **Fixed calendar buckets.** 0-30 / 31-90 / 91-180 / 181+ day windows assume a
   high-frequency uploader. A channel posting twice a month leaves the recent
   buckets with 2 or 3 uploads, so its newest videos - the ones anyone actually
   cares about - get no peer group at all. Cohorts are therefore built by
   *count*: each upload is compared to the N uploads nearest to it in age, same
   format, excluding itself.

Recent uploads are still accumulating views, so a young video compared to other
young videos is the fair comparison; that is what nearest-in-age gives you.

Input (stdin): the JSON returned by the authenticity skill's ``resolve_channel``,
which already splits ``longform`` and ``shorts``:

    python3 -c "import json, resolve_channel as rc; \
        print(json.dumps(rc.resolve('55243'), default=str))" | resonance.py

Usage:
    resonance.py [--peers 8] [--min-peers 5] [--today YYYY-MM-DD]

Output (stdout): one JSON object, ``{"longform": {...}, "shorts": {...}}``, each
with ``scored`` (per upload: multiple vs its cohort median) and ``unscoreable``
(uploads with too few peers, reported rather than silently dropped).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import statistics
import sys


def _age_days(pub: str, today: dt.date) -> int:
    y, m, d = (int(x) for x in str(pub)[:10].split("-"))
    return (today - dt.date(y, m, d)).days


def score_format(uploads: list[dict], peers: int, min_peers: int,
                 today: dt.date) -> dict:
    rows = []
    for v in uploads:
        if not v.get("views") or not v.get("publication_date"):
            continue
        rows.append({
            "video_id": v.get("video_id") or v.get("id"),
            "title": v.get("title"),
            "published": str(v["publication_date"])[:10],
            "views": int(v["views"]),
            "age": _age_days(v["publication_date"], today),
        })
    rows.sort(key=lambda r: r["age"])  # youngest first

    scored, unscoreable = [], []
    for i, r in enumerate(rows):
        # nearest-in-age peers: walk outwards from i, skipping self
        cohort, lo, hi = [], i - 1, i + 1
        while len(cohort) < peers and (lo >= 0 or hi < len(rows)):
            cand = []
            if lo >= 0:
                cand.append((abs(rows[lo]["age"] - r["age"]), lo))
            if hi < len(rows):
                cand.append((abs(rows[hi]["age"] - r["age"]), hi))
            _, idx = min(cand)
            cohort.append(rows[idx])
            if idx == lo:
                lo -= 1
            else:
                hi += 1
        if len(cohort) < min_peers:
            unscoreable.append({**r, "peers": len(cohort),
                                "reason": f"fewer than {min_peers} peers in this format"})
            continue
        med = statistics.median([c["views"] for c in cohort])
        scored.append({
            **r,
            "cohort_median": int(med),
            "cohort_size": len(cohort),
            "multiple": round(r["views"] / med, 2) if med else None,
        })

    scored.sort(key=lambda r: -(r["multiple"] or 0))
    return {
        "uploads": len(rows),
        "scored": scored,
        "unscoreable": unscoreable,
        "note": (f"cohort = {peers} nearest-in-age uploads of the same format; "
                 f"a format with fewer than {min_peers + 1} uploads is not scored"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--peers", type=int, default=8)
    ap.add_argument("--min-peers", type=int, default=5)
    ap.add_argument("--today", default=None,
                    help="reference date, defaults to the newest upload in the input")
    a = ap.parse_args()

    data = json.load(sys.stdin)
    if a.today:
        y, m, d = (int(x) for x in a.today.split("-"))
        today = dt.date(y, m, d)
    else:
        newest = max(
            (str(v["publication_date"])[:10]
             for k in ("longform", "shorts") for v in data.get(k, [])
             if v.get("publication_date")),
            default=None,
        )
        if not newest:
            sys.exit("input has no uploads with publication_date")
        y, m, d = (int(x) for x in newest.split("-"))
        today = dt.date(y, m, d)

    out = {"reference_date": today.isoformat()}
    for fmt in ("longform", "shorts"):
        out[fmt] = score_format(data.get(fmt, []), a.peers, a.min_peers, today)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
