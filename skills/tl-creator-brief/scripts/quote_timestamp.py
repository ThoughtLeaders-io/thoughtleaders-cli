#!/usr/bin/env python3
"""Locate a verbatim quote in a video's transcript and return its ``&t=`` link.

Reads cues from the local corpus store when given one (free — the corpus is
already on disk), and falls back to one indexed fetch otherwise.

**A partial match is never a verification.** The full normalized quote must be
present, contiguously, or the result says exactly what did and did not match:

* ``match: "exact"`` — the whole quote found; safe to publish as verbatim.
* ``match: "partial"`` — only an opening prefix found (captions mangled the
  tail, or the quote drifted from the captions). ``found`` is false; the
  matched prefix and the unmatched tail come back so the caller can fix the
  quote to what the captions actually hold, or drop it. Never publish the
  original quote against a partial match.
* ``match: "none"`` — nothing found. Retry with a spelling or phonetic
  variant; if it still fails, the quote does not publish.

Usage:
    quote_timestamp.py <channel>:<video> "the quote, verbatim" \\
        [--corpus tl-creator-profiles/.corpus/<id>/corpus.jsonl.gz]

Output (stdout): one JSON object. Exit 0 on exact match, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data
from fetch_corpus import cues as parse_cues
from fetch_corpus import open_corpus


def fetch_cues(video_ref: str, corpus: str | None) -> list[tuple[float, str]]:
    """[(start_seconds, text)] from the local corpus, else one indexed fetch."""
    if corpus:
        with open_corpus(corpus) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                v = json.loads(line)
                if str(v.get("id")) == video_ref:
                    return [(float(c[0]), c[1]) for c in v.get("cues") or []]
        sys.exit(f"{video_ref} not in corpus {corpus}")
    rows = tl_data.db_es({
        "size": 1,
        "_source": ["transcript"],
        "query": {"ids": {"values": [video_ref]}},
    })
    if not rows:
        sys.exit(f"no document for {video_ref}")
    return parse_cues(rows[0].get("transcript") or "")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def locate(cues: list[tuple[float, str]], quote: str,
           hint_start: float | None = None) -> dict:
    """Find the quote in the normalized cue stream; say how much matched.

    A quote can occur more than once in a video (a catchphrase, a repeated
    line on a multi-voice upload). With ``hint_start`` — the candidate's
    claimed timestamp — the exact match nearest that time wins, so
    verification never silently relocates a fact to an earlier occurrence
    spoken by someone else. Without a hint, the first occurrence wins.
    """
    parts, owner = [], []
    for i, (_, text) in enumerate(cues):
        n = _norm(text)
        if not n:
            continue
        if parts:
            parts.append(" ")
            owner.append(i)
        parts.append(n)
        owner.extend([i] * len(n))
    hay = "".join(parts)
    needle = _norm(quote)
    if not needle:
        return {"match": "none"}

    starts = []
    pos = hay.find(needle)
    while pos >= 0:
        cue = cues[owner[pos]]
        starts.append((int(cue[0]), cue[1]))
        pos = hay.find(needle, pos + 1)
    if starts:
        if hint_start is not None:
            starts.sort(key=lambda s: abs(s[0] - hint_start))
        start, cue_text = starts[0]
        return {"match": "exact", "start": start, "cue": cue_text,
                "occurrences": len(starts)}

    # Longest word-prefix of the quote that IS present, reported as partial —
    # never as a verification of the whole quote.
    words = needle.split()
    best = None
    for n in range(len(words) - 1, 3, -1):
        prefix = " ".join(words[:n])
        pos = hay.find(prefix)
        if pos >= 0:
            cue = cues[owner[pos]]
            best = {"match": "partial", "start": int(cue[0]), "cue": cue[1],
                    "matched_prefix": prefix,
                    "unmatched_tail": " ".join(words[n:])}
            break
    return best or {"match": "none"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("video_ref", help="<channel_id>:<video_id>")
    ap.add_argument("quote", nargs="*", help="the quote, verbatim (or stdin)")
    ap.add_argument("--corpus", default=None,
                    help="corpus.jsonl.gz from fetch_corpus.py (a plain "
                         ".jsonl corpus is read too); skips the "
                         "indexed fetch")
    a = ap.parse_args()
    quote = " ".join(a.quote).strip() or sys.stdin.read().strip()
    if not quote:
        sys.exit("no quote given")

    cues = fetch_cues(a.video_ref, a.corpus)
    hit = locate(cues, quote)
    video_id = a.video_ref.split(":")[-1]
    base = f"https://www.youtube.com/watch?v={video_id}"

    out = {"video": a.video_ref, "match": hit["match"],
           "found": hit["match"] == "exact", "cues": len(cues), "url": base}
    if hit["match"] != "none":
        out["start"] = hit["start"]
        out["url"] = f"{base}&t={hit['start']}s"
        out["cue"] = hit["cue"]
    if hit["match"] == "partial":
        out["matched_prefix"] = hit["matched_prefix"]
        out["unmatched_tail"] = hit["unmatched_tail"]
        out["warning"] = ("partial match: do NOT publish the quote as "
                          "verbatim; fix it to the caption text or drop it")
    print(json.dumps(out))
    sys.exit(0 if hit["match"] == "exact" else 1)


if __name__ == "__main__":
    main()
