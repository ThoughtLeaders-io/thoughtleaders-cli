#!/usr/bin/env python3
"""One paged ES sweep brings EVERY transcript of a channel home.

All selection intelligence runs locally over this store, and the model layer
sees ranked windows, never raw dumps. Deterministic: same channel -> same
local corpus, byte for byte.

One ``search_after`` walk over the whole catalogue — no per-video fetch loop,
no read cap, no sampling. Videos without a stored transcript come back from
the same sweep without the field, so transcript coverage is a census taken for
free rather than a second query. A query failure aborts loudly; it is never
recorded as a coverage gap.

Usage:
    fetch_corpus.py --channel <id>
    fetch_corpus.py --channel <id> --out tl-creator-profiles/.corpus

Output (stdout): one JSON summary. The corpus itself is written to
``<out>/<channel_id>/corpus.jsonl``, one video per line:
    {"id", "title", "publication_date", "views", "duration", "content_type",
     "cues": [[start_seconds, text], ...]}    # [] = no transcript stored
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data

PAGE = 500
FIELDS = ["id", "title", "publication_date", "views", "duration",
          "content_type", "transcript"]

CUE = re.compile(r'<text start="([\d.]+)"[^>]*>(.*?)</text>', re.S)
TAG = re.compile(r"<[^>]+>")


def _unescape(text: str) -> str:
    """Unescape to a fixed point: caption text is sometimes double-escaped
    (``&amp;#39;``), so a single pass leaves ``&#39;`` behind."""
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return text


def cues(raw: str | None) -> list[tuple[float, str]]:
    """Caption XML -> [(start_seconds, text)]."""
    out = []
    for start, body in CUE.findall(raw or ""):
        text = _unescape(TAG.sub(" ", body)).replace("\n", " ").strip()
        if text:
            out.append((float(start), re.sub(r"\s+", " ", text)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, required=True,
                    help="internal TL channel id, from `tl channels find`")
    ap.add_argument("--out", default="tl-creator-profiles/.corpus",
                    help="corpus root; the channel id becomes a subdirectory, "
                         "so concurrent runs on different channels never "
                         "collide")
    a = ap.parse_args()
    out = pathlib.Path(a.out) / str(a.channel)
    out.mkdir(parents=True, exist_ok=True)

    # Write to a sibling temp file and rename only after the last page lands:
    # a timeout / credit failure mid-sweep must never leave a valid-looking
    # partial corpus (or clobber a previous complete one) — a later scan
    # could not tell it from the promised census.
    final = out / "corpus.jsonl"
    partial = out / "corpus.jsonl.partial"
    after, n_total, n_with = None, 0, 0
    with open(partial, "w", encoding="utf-8") as f:
        while True:
            body = {"size": PAGE,
                    "query": {"bool": {"filter": [
                        {"term": {"doc_type": "article"}},
                        {"term": {"channel.id": a.channel}}]}},
                    "_source": FIELDS,
                    "sort": [{"publication_date": "asc"}, {"id": "asc"}]}
            if after:
                body["search_after"] = after
            rows = tl_data.db_es(body)
            if not rows:
                break
            for r in rows:
                n_total += 1
                c = cues(r.pop("transcript", None))
                if c:
                    n_with += 1
                r["cues"] = c            # [] = no transcript: census for free
                f.write(json.dumps(r, default=str) + "\n")
            after = [rows[-1].get("publication_date"), rows[-1].get("id")]

    if n_total == 0:
        partial.unlink(missing_ok=True)
        sys.exit(f"no uploads found for channel {a.channel}")
    partial.replace(final)

    print(json.dumps({
        "channel": a.channel, "videos": n_total,
        "with_transcript": n_with,
        "coverage": round(n_with / n_total, 2),
        "corpus": str(final),
        "note": "all transcripts fetched; nothing sampled away"}))


if __name__ == "__main__":
    main()
