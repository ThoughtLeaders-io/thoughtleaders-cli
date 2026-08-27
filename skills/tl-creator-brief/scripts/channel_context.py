#!/usr/bin/env python3
"""Channel identity plus the context brief: format MEASURED from transcripts.

Two jobs, one script:

* **Identity inputs** — the channel row, its About text, and the platform's
  generated profile (``ai.description``), which is usually the better identity
  source because raw About fields are often subscribe-boilerplate. These seed
  the identity & socials lane and the host-terms for the scan.
* **Context stats** — once the corpus is local (``--corpus``), format is
  measured from the transcripts themselves, not guessed from titles:
  first-person window density, interview markers, question density, and
  per-title second-voice hints. Deterministic numbers only; the label
  (solo / interview / multi-host / faceless-scripted) is called by a model
  read of a small sample WITH this evidence, per references/transcript-mining.md.

Nothing here is a gate. Near-zero first-person density flags "likely faceless"
early so model tokens are spent accordingly — but nothing exits early, and a
faceless channel with one personal Q&A upload still gets scanned.

Usage:
    channel_context.py --channel <id>
    channel_context.py --channel <id> \\
        --corpus tl-creator-profiles/.corpus/<id>/corpus.jsonl

Output (stdout): one JSON object.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_cli

FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|i'll|my|me|myself)\b", re.I)

INTERVIEW = re.compile(
    r"\b(my guest|our guest|today'?s guest|welcome (back )?to the (show|"
    r"podcast)|please welcome|thanks for (coming on|joining|having me)|"
    r"joining me today|great to have you|tell (us|me) about yourself)\b", re.I)

TITLE_SECOND_VOICE = {
    "interview_or_collab": re.compile(
        r"(\binterview(s|ed|ing)?\b|\bsits down with\b|\bin conversation "
        r"with\b|\bft\.?\s|\bfeat\.?\s|\bw/\s?\w|\bwith @|\bvs\.?\s)", re.I),
    "reaction": re.compile(
        r"(\breact(s|ing|ion|ions)?\b|\bfirst time (watching|hearing|playing|"
        r"seeing)\b)", re.I),
}


def channel_row(channel_id: int) -> dict:
    rows = tl_cli.db_pg(
        "SELECT id, channel_name, url, external_channel_id, subscribers, "
        "total_views, num_uploads, country, language, last_published "
        f"FROM thoughtleaders_channel WHERE id = {channel_id}"
    )
    if not rows:
        sys.exit(f"no channel record for id {channel_id}")
    return rows[0]


def channel_doc(channel_id: int) -> dict:
    # Channel documents are duplicated in the index; collapse on id or every
    # copy comes back.
    rows = tl_cli.db_es({
        "size": 1,
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "channel"}},
            {"term": {"id": channel_id}},
        ]}},
        "_source": ["name", "description", "ai.description",
                    "ai.topic_descriptions", "social_links"],
        "collapse": {"field": "id"},
    })
    return rows[0] if rows else {}


def _nested(doc: dict, path: str):
    """Read ``ai.description`` whether the CLI flattened the key or nested it."""
    if path in doc:
        return doc[path]
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def corpus_stats(corpus_path: pathlib.Path) -> dict:
    per_video = []
    with open(corpus_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            v = json.loads(line)
            cues = v.get("cues") or []
            if not cues:
                continue
            text = " ".join(c[1] for c in cues)
            words = max(len(text.split()), 1)
            per_video.append({
                "id": str(v.get("id")),
                "title": v.get("title"),
                "fp_per_1k_words": round(
                    1000 * len(FIRST_PERSON.findall(text)) / words, 1),
                "interview_markers": len(INTERVIEW.findall(text)),
                "questions_per_1k_words": round(
                    1000 * text.count("?") / words, 1),
                "title_hint": next(
                    (fmt for fmt, rx in TITLE_SECOND_VOICE.items()
                     if v.get("title") and rx.search(v["title"])), None),
            })
    if not per_video:
        return {"videos_measured": 0}
    fp = [v["fp_per_1k_words"] for v in per_video]
    return {
        "videos_measured": len(per_video),
        "fp_per_1k_words_median": round(statistics.median(fp), 1),
        "fp_per_1k_words_p10": round(sorted(fp)[len(fp) // 10], 1),
        "videos_with_interview_markers": sum(
            1 for v in per_video if v["interview_markers"] >= 2),
        "questions_per_1k_words_median": round(statistics.median(
            v["questions_per_1k_words"] for v in per_video), 1),
        "title_hints": {
            fmt: sum(1 for v in per_video if v["title_hint"] == fmt)
            for fmt in TITLE_SECOND_VOICE
        },
        "likely_faceless": statistics.median(fp) < 2.0,
        "per_video": per_video,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, required=True,
                    help="internal TL channel id, from `tl channels find`")
    ap.add_argument("--corpus", default=None,
                    help="corpus.jsonl from fetch_corpus.py; adds measured "
                         "format stats")
    a = ap.parse_args()

    row = channel_row(a.channel)
    doc = channel_doc(a.channel)

    out = {
        "channel_id": a.channel,
        "name": row.get("channel_name") or doc.get("name"),
        "url": row.get("url"),
        "external_channel_id": row.get("external_channel_id"),
        "subscribers": row.get("subscribers"),
        "total_views": row.get("total_views"),
        "num_uploads": row.get("num_uploads"),
        "country": row.get("country"),
        "language": row.get("language"),
        "last_published": str(row.get("last_published") or "")[:10] or None,
        "generated_profile": _nested(doc, "ai.description"),
        "about_text": doc.get("description"),
        # the identity & socials lane opens these; a profile that cannot be
        # read is reported "linked but unread", never silently skipped
        "social_links": doc.get("social_links") or [],
        "topic_descriptions": _nested(doc, "ai.topic_descriptions"),
        "note": ("format label is called by a model read of a small sample "
                 "WITH these stats as evidence; the stats are inputs, not a "
                 "verdict, and nothing here exits the pipeline early"),
    }
    if a.corpus:
        out["context_stats"] = corpus_stats(pathlib.Path(a.corpus))
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
