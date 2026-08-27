#!/usr/bin/env python3
"""Who is this creator, and what kind of channel is this, for three queries.

Runs before any transcript is read. Establishing the creator cheaply is what
turns the transcript search from a fishing expedition into a targeted one: one
sentence of framing ("a show hosted by an entrepreneur who founded a marketing
agency") tells the scan what to expect, and costs a rounding error next to
discovering the same thing from two-hour transcripts.

Two things it returns that matter more than they look:

* **The platform's generated profile, not the raw About text.** A channel's
  literal About field is often boilerplate. Observed on a 19M-subscriber
  channel, the entire description is a one-line nag about subscribing. Both are
  returned, generated profile first, so the caller can see which is useful.
* **Whether the profile text names a person at all.** A generated profile can be
  several hundred words long and still never name the host: observed on a large
  interview channel, the profile describes the show in detail and never mentions
  the person presenting it. Length is therefore not the test for whether the
  identity step is done. The host's name is what makes the transcript search
  attributable, so ``identity_is_thin`` reports short OR nameless, and either way
  the caller runs the one web search.
* **Median duration and the recent titles.** These are the cheap format signal.
  Two-hour uploads titled "<name> sits down with <guest>" is an interview show;
  eight-minute uploads with no host name anywhere may be faceless narration. The
  format decides how far the self-reference analysis can be trusted at all, so
  it has to be settled before the expensive steps.

Usage:
    channel_profile.py --channel 138573
    channel_profile.py --channel 138573 --titles 30

Output (stdout): one JSON object. Exit 1 if the channel has no record.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys

# Interview-show tells in a title. Not a verdict, a hint for the caller.
_GUEST_MARKERS = re.compile(
    r"(\bwith\b|\bft\.?\b|\bfeat\.?\b|\bep(isode)?\.?\s*\d|\binterview\b|:\s)",
    re.I,
)

# A capitalised bigram is a weak proxy for a personal name. Words that routinely
# start sentences or label things would otherwise read as names.
_NOT_A_NAME = {
    "the", "a", "an", "this", "that", "it", "its", "his", "her", "their", "and",
    "but", "with", "for", "from", "in", "on", "of", "to", "by", "as", "at",
    "youtube", "channel", "videos", "video", "content", "english", "language",
    "shorts", "subscribers", "views", "million", "billion", "podcast", "show",
    "series", "episode", "episodes", "team", "world", "us", "uk", "ai",
}
_CAP_BIGRAM = re.compile(r"\b([A-Z][a-z]{2,})\s+([A-Z][a-z]{2,})\b")


def _tl(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"{' '.join(args[:3])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def tl_es(body: dict) -> list[dict]:
    """Run an Elasticsearch body and return the rows.

    ``tl db es`` returns ``{"results": [...]}``, not the native hits.hits shape.
    """
    out = _tl(["tl", "db", "es", json.dumps(body)])
    return json.loads(out).get("results") or []


def tl_pg(sql: str) -> list[dict]:
    out = _tl(["tl", "db", "pg", sql, "--json"])
    data = json.loads(out)
    return data if isinstance(data, list) else data.get("results") or []


def channel_row(channel_id: int) -> dict:
    rows = tl_pg(
        "SELECT id, channel_name, url, external_channel_id, subscribers, "
        "total_views, num_uploads, country, language, last_published "
        f"FROM thoughtleaders_channel WHERE id = {channel_id}"
    )
    if not rows:
        sys.exit(f"no channel record for id {channel_id}")
    return rows[0]


def channel_doc(channel_id: int) -> dict:
    """The Elasticsearch channel document, deduplicated.

    Channel documents are duplicated in the index (observed: 35 identical copies
    under one id), so this collapses on id or it pays for all of them.
    """
    rows = tl_es({
        "size": 1,
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "channel"}},
            {"term": {"id": channel_id}},
        ]}},
        "_source": ["name", "description", "ai.description",
                    "ai.topic_descriptions"],
        "collapse": {"field": "id"},
    })
    return rows[0] if rows else {}


def recent_titles(channel_id: int, limit: int) -> list[dict]:
    """Recent LONGFORM titles only.

    Sorting a Shorts-heavy channel by date returns almost nothing but Shorts,
    which says nothing about the format the self-reference scan will read. The
    corpus is longform, so the format signal has to be longform too.
    """
    rows = tl_es({
        "size": limit,
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "article"}},
            {"term": {"channel.id": channel_id}},
            {"term": {"content_type": "longform"}},
        ]}},
        "_source": ["title", "publication_date", "views", "duration",
                    "content_type"],
        "sort": [{"publication_date": "desc"}],
    })
    return [{
        "title": r.get("title"),
        "published": str(r.get("publication_date") or "")[:10],
        "views": r.get("views"),
        "duration": r.get("duration"),
        "content_type": r.get("content_type"),
    } for r in rows]


def format_hints(titles: list[dict]) -> dict:
    """Mechanical signals only. The format call itself is the caller's."""
    longform = [t for t in titles if t.get("content_type") != "short"]
    del titles
    durations = [t["duration"] for t in longform
                 if isinstance(t.get("duration"), (int, float)) and t["duration"]]
    guesty = [t["title"] for t in longform
              if t.get("title") and _GUEST_MARKERS.search(t["title"])]
    return {
        "longform_titles_sampled": len(longform),
        "median_duration_seconds": int(statistics.median(durations)) if durations else None,
        "titles_with_guest_markers": len(guesty),
        "guest_marker_share": (round(len(guesty) / len(longform), 2)
                               if longform else None),
        "note": ("guest markers are a hint towards an interview format, not a "
                 "verdict; decide the format from these plus the profile text"),
    }


def names_a_person(text: str | None, channel_name: str | None) -> bool:
    """Weak proxy: does this text contain something shaped like a person's name.

    Deliberately conservative. A false negative just triggers one web search; a
    false positive would let the run proceed with no idea who the host is, which
    is the expensive mistake.
    """
    if not text:
        return False
    own = {w.lower() for w in re.findall(r"[A-Za-z]+", channel_name or "")}
    for first, second in _CAP_BIGRAM.findall(str(text)):
        pair = (first.lower(), second.lower())
        if any(w in _NOT_A_NAME or w in own for w in pair):
            continue
        return True
    return False


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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, required=True,
                    help="internal TL channel id, from `tl channels find`")
    ap.add_argument("--titles", type=int, default=20)
    a = ap.parse_args()

    row = channel_row(a.channel)
    doc = channel_doc(a.channel)
    titles = recent_titles(a.channel, a.titles)

    generated = _nested(doc, "ai.description")
    about = doc.get("description")
    name = row.get("channel_name") or doc.get("name")
    named = (names_a_person(generated, name)
             or names_a_person(about, name))

    print(json.dumps({
        "channel_id": a.channel,
        "name": name,
        "url": row.get("url"),
        "external_channel_id": row.get("external_channel_id"),
        "subscribers": row.get("subscribers"),
        "total_views": row.get("total_views"),
        "num_uploads": row.get("num_uploads"),
        "country": row.get("country"),
        "language": row.get("language"),
        "last_published": str(row.get("last_published") or "")[:10] or None,
        "generated_profile": generated,
        "about_text": about,
        "topic_descriptions": _nested(doc, "ai.topic_descriptions"),
        "profile_names_a_person": named,
        "identity_is_thin": (not (generated and len(str(generated)) > 120)
                             or not named),
        "identity_note": ("if identity_is_thin, run one web search of the form "
                          "'who is <name>'. The host's name is the attribution "
                          "key for the transcript scan, not background colour."),
        "recent_longform_titles": titles,
        "format_hints": format_hints(titles),
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
