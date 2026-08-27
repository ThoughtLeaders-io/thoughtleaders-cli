#!/usr/bin/env python3
"""Locate a quote in a video's transcript and return its start offset.

Transcripts are stored as YouTube caption XML with per-cue offsets
(``<text start="12.34" dur="2.1">cue</text>``). The keyword-research
``fetch_context.py`` strips those tags, so quotes come back with no way to link
to the moment they were said. This restores that: give it a video and a quote,
get back the second the quote starts and a ``&t=`` link.

A quote spans cue boundaries (captions break mid-sentence), so matching is done
against the normalized concatenation of all cues, then mapped back to the cue
that contains the match's first character.

Usage:
    quote_timestamp.py 55243:gzLPa6NbcrE "my chronotype is the lion"
    echo "my chronotype is the lion" | quote_timestamp.py 55243:gzLPa6NbcrE

Output (stdout): one JSON object.
    {"video": "...", "found": true, "start": 512, "url": "https://...&t=512s",
     "cue": "...", "matched_text": "..."}
Exit 0 when found, 1 when not (a not-found is data, not an error: it usually
means the caption mangled a proper noun, so retry with a variant).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys


def _tl_es(body: dict) -> dict:
    proc = subprocess.run(
        ["tl", "db", "es", json.dumps(body)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"tl db es failed: {proc.stderr.strip()[:300]}")
    return json.loads(proc.stdout)


def fetch_cues(video_ref: str) -> list[dict]:
    """Return [{start: float, text: str}] for a ``<channel_id>:<video_id>`` ref."""
    res = _tl_es({
        "size": 1,
        "_source": ["transcript"],
        "query": {"ids": {"values": [video_ref]}},
    })
    hits = res.get("results") or []
    if not hits:
        sys.exit(f"no document for {video_ref}")
    xml = hits[0].get("transcript") or ""
    cues = []
    for m in re.finditer(r'<text start="([\d.]+)"[^>]*>(.*?)</text>', xml, re.S):
        text = re.sub(r"<[^>]+>", "", m.group(2))
        # captions double-escape: &amp;#39; -> &#39; -> '
        text = text.replace("&amp;", "&")
        for ent, ch in (("&#39;", "'"), ("&apos;", "'"), ("&quot;", '"'),
                        ("&gt;", ">"), ("&lt;", "<"), ("&nbsp;", " "),
                        ("&amp;", "&")):
            text = text.replace(ent, ch)
        cues.append({"start": float(m.group(1)), "text": text.replace("\n", " ")})
    return cues


def _norm(s: str) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", s.lower())).strip()


def locate(cues: list[dict], quote: str) -> dict | None:
    """Find the cue where ``quote`` starts, tolerant of caption line breaks."""
    # Build the normalized haystack, remembering which cue each char came from.
    parts, owner = [], []
    for i, cue in enumerate(cues):
        n = _norm(cue["text"])
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
        return None
    pos = hay.find(needle)
    if pos < 0:  # retry on the first 8 words, in case the tail is mangled
        short = " ".join(needle.split()[:8])
        pos = hay.find(short) if len(short.split()) >= 4 else -1
        if pos < 0:
            return None
    cue = cues[owner[pos]]
    return {"start": int(cue["start"]), "cue": cue["text"]}


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    video_ref = sys.argv[1]
    quote = " ".join(sys.argv[2:]).strip() or sys.stdin.read().strip()
    if not quote:
        sys.exit("no quote given")

    cues = fetch_cues(video_ref)
    hit = locate(cues, quote)
    video_id = video_ref.split(":")[-1]
    base = f"https://www.youtube.com/watch?v={video_id}"
    if not hit:
        print(json.dumps({"video": video_ref, "found": False, "url": base,
                          "cues": len(cues)}))
        sys.exit(1)
    print(json.dumps({
        "video": video_ref, "found": True, "start": hit["start"],
        "url": f"{base}&t={hit['start']}s", "cue": hit["cue"],
        "matched_text": quote,
    }))


if __name__ == "__main__":
    main()
