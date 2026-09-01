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
        --corpus tl-creator-profiles/.corpus/<id>/corpus.jsonl.gz

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
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data
from fetch_corpus import open_corpus  # sibling script

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
    rows = tl_data.db_pg(
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
    rows = tl_data.db_es({
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


SECOND_CHANNEL_PHRASE = re.compile(
    r"(second channel|other channel|vlog channel|clips channel|gaming "
    r"channel|podcast channel|main channel)", re.I)
# Channel URL forms only: a youtu.be shortlink identifies a VIDEO, so it
# must never be surfaced as a second-channel candidate.
YT_LINK = re.compile(
    r"youtube\.com/(?:@[\w.-]+|channel/UC[\w-]+|c/[\w.-]+|user/[\w.-]+)",
    re.I)


def second_channel_candidates(row: dict, doc: dict) -> list[dict]:
    """Other YouTube channels this creator points at — often the gem mine.

    A big channel's smaller vlog/second channel is frequently where the
    personal material lives. Candidates come from the channel's own pointers:
    YouTube links among its social links, and YouTube links or "my second
    channel" phrasing in the About text. Detection only — resolving a
    candidate to a TL channel id (`tl channels find`) and deciding to scan it
    belongs to the identity & socials lane.
    """
    # Compare exact channel identities, never substrings: the second channel
    # is routinely a derivative handle (@foo -> @fooVlogs), so a substring
    # test against the main URL would reject exactly the channels we want.
    def _identity(link: str) -> str:
        s = link.lower().rstrip("/")
        for marker in ("/channel/", "/@", "/c/", "/user/"):
            if marker in s:
                return s.split(marker, 1)[1].split("/")[0].split("?")[0]
        if "youtu.be/" in s:
            return s.split("youtu.be/", 1)[1].split("/")[0].split("?")[0]
        return s

    own = {str(row.get("external_channel_id") or "").lower()} | {
        _identity(str(u)) for u in (row.get("url"),) if u
    }
    own.discard("")
    seen: set[str] = set()
    out: list[dict] = []

    def add(link: str, source: str) -> None:
        key = _identity(link)
        if not key or key in seen or key in own:
            return
        seen.add(key)
        out.append({"link": link, "source": source})

    for link in doc.get("social_links") or []:
        if isinstance(link, str) and YT_LINK.search(link):
            add(link, "social_links")
    about = doc.get("description") or ""
    for m in YT_LINK.finditer(about):
        add(m.group(0), "about_text")
    phrases = sorted({m.group(0).lower()
                      for m in SECOND_CHANNEL_PHRASE.finditer(about)})
    if phrases and not out:
        # The About text names another channel without linking it: still a
        # lead, handed to the lane as a phrase to chase, never dropped.
        out.append({"link": None, "source": "about_text_phrase",
                    "phrases": phrases})
    return out


def corpus_stats(corpus_path: pathlib.Path) -> dict:
    per_video = []
    with open_corpus(corpus_path) as f:
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
            lang = str(v.get("transcript_language") or "").lower()
            per_video.append({
                "id": str(v.get("id")),
                "title": v.get("title"),
                "language": lang or None,
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
    # The first-person stats are English regex counts; on other languages
    # (pro-drop Spanish, subject-omitting Japanese) they measure nothing, so
    # they are computed over English-language videos only — and a channel
    # with no English videos gets null, never "likely faceless".
    en_videos = [v for v in per_video
                 if not v["language"] or v["language"].startswith("en")]
    langs: dict[str, int] = {}
    for v in per_video:
        key = v["language"] or "unknown"
        langs[key] = langs.get(key, 0) + 1
    fp = [v["fp_per_1k_words"] for v in en_videos]
    if not fp:
        return {
            "videos_measured": len(per_video),
            "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
            "fp_per_1k_words_median": None,
            "fp_per_1k_words_p10": None,
            "likely_faceless": None,
            "language_note": ("no English-language videos: first-person "
                              "density is not meaningful here — format and "
                              "faceless calls belong to the model read of a "
                              "sample, with no lexical prior"),
            "videos_with_interview_markers": sum(
                1 for v in per_video if v["interview_markers"] >= 2),
            "questions_per_1k_words_median": round(statistics.median(
                v["questions_per_1k_words"] for v in per_video), 1),
            "title_hints": {
                fmt: sum(1 for v in per_video if v["title_hint"] == fmt)
                for fmt in TITLE_SECOND_VOICE
            },
            "per_video": per_video,
        }
    return {
        "videos_measured": len(per_video),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
        "fp_videos_measured": len(en_videos),
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
                    help="corpus.jsonl.gz from fetch_corpus.py (a plain "
                         ".jsonl corpus is read too); adds measured "
                         "format stats")
    ap.add_argument("--per-video-out", dest="per_video_out", default=None,
                    help="write the per-video stat rows to this JSON file "
                         "(they never go to stdout: on a large channel the "
                         "array is megabytes, and stdout is read by the "
                         "orchestrating session)")
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
        "second_channel_candidates": second_channel_candidates(row, doc),
        "topic_descriptions": _nested(doc, "ai.topic_descriptions"),
        "note": ("format label is called by a model read of a small sample "
                 "WITH these stats as evidence; the stats are inputs, not a "
                 "verdict, and nothing here exits the pipeline early"),
    }
    if a.corpus:
        stats = corpus_stats(pathlib.Path(a.corpus))
        per_video = stats.pop("per_video", None)
        if per_video is not None and a.per_video_out:
            path = pathlib.Path(a.per_video_out)
            path.write_text(json.dumps(per_video, default=str),
                            encoding="utf-8")
            stats["per_video_file"] = str(path)
        out["context_stats"] = stats
    print(json.dumps(out, indent=1, default=str))


if __name__ == "__main__":
    main()
