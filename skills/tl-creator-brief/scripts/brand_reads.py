#!/usr/bin/env python3
"""A brand's past sponsorship reads: what creators have actually said on camera.

One of three ways the skill can be told what a brand offers, and the only one
that needs a query. The others are the brand's website and a brief pasted in by
whoever ran the skill.

**The purpose is to learn what the product is**, in the words creators have used
out loud. It is not to find the brand's best-performing ad. Which past read did
well is a different question and this script deliberately does not answer it: no
prices, no costs, no rate cards, no performance grades are fetched or returned.
None of that says what the product does, and none of it may reach an output that
can be forwarded.

**Two sources, always both, always labelled:**

* ``deal``: a sponsorship brokered through the platform. Unambiguous.
* ``mention``: a sponsorship the platform detected out on YouTube, whoever
  brokered it. Essential, because a brand may never have bought through us at
  all, and the skill still has to work for them.

Never read zero deals as "never sponsored anything". Observed: one brand returns
zero brokered deals and roughly ten thousand detected mention videos. The two
numbers measure different things.

**What matters is whether a read has words.** Any single read that describes the
product tells you what the product is, which is the only thing this step is for,
so there is no sample size to satisfy. A read that only drops a link says nothing
about the product and is simply useless, which is visible from the absence of
words rather than something needing a verdict.

Usage:
    brand_reads.py --brand 50485
    brand_reads.py --brand 50485 --brand 61234 --max 15   # after a rebrand

Output (stdout): one JSON object.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

PAD = 25  # seconds either side of a detected mention, since the read is longer

# The detector sometimes records that a mention exists without capturing what was
# said, as a bare placeholder like "(in transcript)". That is not a read, and
# counting it as one would let the three-verified-reads floor pass on nothing.
PLACEHOLDER = re.compile(r"^\(?\s*(in|found in)\s+(the\s+)?"
                         r"(transcript|description|title)\s*\)?\.?$", re.I)


def _tl(args: list[str]) -> str:
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"{' '.join(args[:3])} failed: {proc.stderr.strip()[:300]}")
    return proc.stdout


def tl_es(body: dict) -> list[dict]:
    return json.loads(_tl(["tl", "db", "es", json.dumps(body)])).get("results") or []


def tl_pg(sql: str) -> list[dict]:
    data = json.loads(_tl(["tl", "db", "pg", sql, "--json"]))
    return data if isinstance(data, list) else data.get("results") or []


def mention_videos(brand_ids: list[int], max_videos: int) -> list[dict]:
    """Videos carrying a sponsored mention of the brand, newest first."""
    return tl_es({
        "size": max_videos,
        "query": {"bool": {"should": [
            {"term": {"sponsored_brand_mentions": str(b)}} for b in brand_ids
        ], "minimum_should_match": 1}},
        "_source": ["id", "title", "channel.id", "channel.name",
                    "publication_date"],
        "sort": [{"publication_date": "desc"}],
    })


def mention_snippets(brand_ids: list[int], max_videos: int) -> dict:
    """The detected ad-read snippet per video, from the nested mention field."""
    rows = tl_es({
        "size": max_videos,
        "query": {"nested": {"path": "brand_mentions", "query": {"bool": {
            "must": [
                {"terms": {"brand_mentions.id": [str(b) for b in brand_ids]}},
                {"term": {"brand_mentions.type": "sponsored"}},
            ]}}}},
        "_source": ["id", "title", "publication_date", "brand_mentions"],
        "sort": [{"publication_date": "desc"}],
    })
    out: dict[str, dict] = {}
    wanted = {str(b) for b in brand_ids}
    for r in rows:
        mentions = r.get("brand_mentions") or []
        if isinstance(mentions, dict):
            mentions = [mentions]
        for m in mentions:
            if str(m.get("id")) not in wanted:
                continue
            if m.get("field") != "transcript":
                continue  # a description hit is the affiliate link, not speech
            key = str(r.get("id"))
            if key in out:
                continue
            words = (m.get("snippet") or "").strip()
            if PLACEHOLDER.match(words):
                words = ""
            out[key] = {
                "snippet": words,
                "entity_as_heard": m.get("entity"),
                "start": m.get("start_ts"),
                "end": m.get("end_ts"),
            }
    return out


def channel_names(channel_ids: list[int]) -> dict[int, str]:
    """Backfill names for detected mentions, where the index carries only an id."""
    ids = [int(c) for c in channel_ids if c]
    if not ids:
        return {}
    rows = tl_pg("SELECT id, channel_name FROM thoughtleaders_channel "
                 f"WHERE id IN ({','.join(str(i) for i in ids)})")
    return {int(r["id"]): r.get("channel_name") for r in rows if r.get("id")}


def brokered_deals(brand_ids: list[int]) -> list[dict]:
    """Sponsorships brokered through the platform. No price or cost selected."""
    ids = ",".join(str(b) for b in brand_ids)
    return tl_pg(
        "SELECT a.id AS adlink_id, a.publish_date, a.article_id, "
        "ch.id AS channel_id, ch.channel_name "
        "FROM thoughtleaders_adlink a "
        "JOIN thoughtleaders_profile p ON a.advertiser_profile_id = p.id "
        "JOIN thoughtleaders_profile_brands pb ON p.id = pb.profile_id "
        "JOIN thoughtleaders_adspot s ON a.ad_spot_id = s.id "
        "JOIN thoughtleaders_channel ch ON s.channel_id = ch.id "
        f"WHERE pb.brand_id IN ({ids}) AND a.publish_status = 3 "
        "AND a.publish_date IS NOT NULL "
        "ORDER BY a.publish_date DESC LIMIT 200"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", type=int, action="append", required=True,
                    help="brand id from `tl brands find`; repeat for a rebrand")
    ap.add_argument("--max", type=int, default=10,
                    help="reads returned, most descriptive first (default 10)")
    a = ap.parse_args()

    videos = mention_videos(a.brand, max(a.max * 3, 30))
    snippets = mention_snippets(a.brand, max(a.max * 3, 30))
    deals = brokered_deals(a.brand)
    deal_articles = {str(d.get("article_id")): d for d in deals
                     if d.get("article_id")}

    chan_ids = []
    for v in videos:
        c = v.get("channel") if isinstance(v.get("channel"), dict) else {}
        cid = c.get("id") or v.get("channel.id")
        if cid:
            chan_ids.append(cid)
    names = channel_names(chan_ids)

    reads = []
    for v in videos:
        key = str(v.get("id") or "")
        snip = snippets.get(key) or {}
        vid = key.split(":")[-1]
        start = snip.get("start")
        url = f"https://www.youtube.com/watch?v={vid}"
        if isinstance(start, (int, float)):
            url += f"&t={max(int(start) - PAD, 0)}s"
        chan = v.get("channel") if isinstance(v.get("channel"), dict) else {}
        cid = chan.get("id") or v.get("channel.id")
        reads.append({
            "id": key,
            "video_id": vid,
            "title": v.get("title"),
            "published": str(v.get("publication_date") or "")[:10],
            "channel_id": cid,
            "channel_name": (chan.get("name") or v.get("channel.name")
                             or names.get(int(cid)) if cid else None)
                            or (deal_articles.get(key) or {}).get("channel_name"),
            "source": "deal" if key in deal_articles else "mention",
            "read_words": snip.get("snippet") or None,
            "entity_as_heard": snip.get("entity_as_heard"),
            "start": start,
            "url": url,
        })

    # A read whose words we actually have is worth more than a bare row.
    reads.sort(key=lambda r: (0 if r["read_words"] else 1,
                              0 if r["source"] == "deal" else 1,
                              r["published"] or ""), reverse=False)
    kept = reads[:a.max]
    with_words = sum(1 for r in kept if r["read_words"])

    print(json.dumps({
        "brand_ids": a.brand,
        "mention_videos_found": len(videos),
        "brokered_deals_found": len(deals),
        "reads_returned": len(kept),
        "reads_with_spoken_words": with_words,
        "counts_note": ("brokered deals and detected mentions measure different "
                        "things; zero deals does not mean the brand has never "
                        "sponsored anyone"),
        "usage_note": ("read the words to learn what the product is. A read with "
                       "no words describes nothing and can be ignored. If no "
                       "read has words at all, use the brand's website or a "
                       "brief instead."),
        "excluded_by_design": ["price", "cost", "rate cards",
                               "performance grades"],
        "reads": kept,
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
