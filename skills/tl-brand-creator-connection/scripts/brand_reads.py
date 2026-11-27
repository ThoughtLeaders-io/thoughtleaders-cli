#!/usr/bin/env python3
"""A brand's past sponsorship reads: what creators have said about it on camera.

Returns sponsored mentions the platform detected across YouTube, whoever
brokered them, **newest first**: a product changes, and the current
description of it is the one being sold.

Every snippet is re-checked per mention: only ``type == "sponsored"`` AND
``field == "transcript"`` counts, so an organic mention earlier in a video can
never displace the real sponsored read.

**Never returns price, cost, rate cards or performance grades.** None of them
say what the product is, and the output can be forwarded.

Usage:
    brand_reads.py --brand <id>
    brand_reads.py --brand <id> --brand <old-id> --max 15   # after a rebrand
    brand_reads.py --brand <id> --channel <id> --max 50     # this creator's past reads

Output (stdout): one JSON object.
"""
from __future__ import annotations

import argparse
import calendar
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data

PAD = 25  # seconds before a detected mention, since the read starts earlier

# The detector sometimes records that a mention exists without capturing what
# was said, as a bare placeholder. That is not a read.
PLACEHOLDER = re.compile(r"^\(?\s*(in|found in)\s+(the\s+)?"
                         r"(transcript|description|title)\s*\)?\.?$", re.I)


def _on_channel(channel: int | None) -> list[dict]:
    return [{"term": {"channel.id": int(channel)}}] if channel else []


def mention_videos(brand_ids: list[int], max_videos: int,
                   channel: int | None = None) -> list[dict]:
    """Videos carrying a sponsored mention of the brand, newest first."""
    return tl_data.db_es({
        "size": max_videos,
        "query": {"bool": {"should": [
            {"term": {"sponsored_brand_mentions": str(b)}} for b in brand_ids
        ], "minimum_should_match": 1, "filter": _on_channel(channel)}},
        "_source": ["id", "title", "channel.id", "channel.name",
                    "publication_date"],
        "sort": [{"publication_date": "desc"}],
    })


def mention_snippets(brand_ids: list[int], max_videos: int,
                     channel: int | None = None) -> dict:
    """The detected ad-read snippet per video, from the nested mention field."""
    rows = tl_data.db_es({
        "size": max_videos,
        "query": {"bool": {"filter": _on_channel(channel), "must": [
            {"nested": {"path": "brand_mentions", "query": {"bool": {
            "must": [
                {"terms": {"brand_mentions.id": [str(b) for b in brand_ids]}},
                {"term": {"brand_mentions.type": "sponsored"}},
                # constrain to spoken reads HERE, not only in Python after
                # paging: otherwise description-only rows can fill the page
                # and hide older videos whose read has words
                {"term": {"brand_mentions.field": "transcript"}},
            ]}}}}]}},
        "_source": ["id", "title", "publication_date", "channel.id",
                    "channel.name", "brand_mentions"],
        "sort": [{"publication_date": "desc"}],
    })
    out: dict[str, dict] = {}
    wanted = {str(b) for b in brand_ids}
    for r in rows:
        mentions = r.get("brand_mentions") or []
        if isinstance(mentions, dict):
            mentions = [mentions]
        for m in mentions:
            # Re-check every condition per mention: the video-level query
            # matched the DOC, but this list holds ALL of the video's
            # mentions, organic ones and other brands' included.
            if str(m.get("id")) not in wanted:
                continue
            if m.get("type") != "sponsored":
                continue
            if m.get("field") != "transcript":
                continue  # a summary (description) hit is the affiliate link, not speech
            key = str(r.get("id"))
            if key in out:
                continue
            words = (m.get("snippet") or "").strip()
            if PLACEHOLDER.match(words):
                words = ""
            chan = r.get("channel") if isinstance(r.get("channel"), dict) else {}
            out[key] = {
                "snippet": words,
                "entity_as_heard": m.get("entity"),
                "start": m.get("start_ts"),
                "end": m.get("end_ts"),
                # meta, so a spoken read whose video fell off the
                # mention_videos page still becomes a full row
                "title": r.get("title"),
                "published": str(r.get("publication_date") or "")[:10],
                "channel_id": chan.get("id") or r.get("channel.id"),
                "channel_name": chan.get("name") or r.get("channel.name"),
            }
    return out


def channel_names(channel_ids: list[int]) -> dict[int, str]:
    ids = sorted({int(c) for c in channel_ids if c})
    if not ids:
        return {}
    rows = tl_data.db_pg("SELECT id, channel_name FROM thoughtleaders_channel "
                        f"WHERE id IN ({','.join(str(i) for i in ids)})")
    return {int(r["id"]): r.get("channel_name") for r in rows if r.get("id")}


def funnel(**fields) -> None:
    """One machine-parseable stage line for debugging (stderr)."""
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def funnel_fields(summary: dict, elapsed: float) -> dict:
    """The TL-data lane's stage line. CONNECT had no timing of its own, so a
    slow brand read looked like a slow merge."""
    return {
        "stage": "brand_read",
        "brands": len(summary.get("brand_ids") or []),
        "mention_videos": summary.get("mention_videos_found"),
        "reads": summary.get("reads_returned"),
        "with_spoken_words": summary.get("reads_with_spoken_words"),
        "elapsed_s": elapsed,
    }


def collect_reads(brand_ids: list[int], max_reads: int, channel: int | None) -> dict:
    """The brand's sponsored reads (or this channel's), newest descriptive first."""
    videos = mention_videos(brand_ids, max(max_reads * 3, 30), channel)
    snippets = mention_snippets(brand_ids, max(max_reads * 3, 30), channel)

    chan_ids = [s.get("channel_id") for s in snippets.values() if s.get("channel_id")]
    for v in videos:
        c = v.get("channel") if isinstance(v.get("channel"), dict) else {}
        cid = c.get("id") or v.get("channel.id")
        if cid:
            chan_ids.append(cid)
    names = channel_names(chan_ids)

    reads, seen = [], set()
    for v in videos:
        key = str(v.get("id") or "")
        seen.add(key)
        snip = snippets.get(key) or {}
        vid = key.split(":")[-1]
        start = snip.get("start")
        url = f"https://www.youtube.com/watch?v={vid}"
        if isinstance(start, (int, float)) and start > 0:
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
                             or (names.get(int(cid)) if cid else None)),
            "read_words": snip.get("snippet") or None,
            "entity_as_heard": snip.get("entity_as_heard"),
            "start": start,
            "end": snip.get("end"),
            "url": url,
        })

    # Spoken reads whose video fell off the mention_videos page still count.
    for key, snip in snippets.items():
        if key in seen:
            continue
        seen.add(key)
        vid = key.split(":")[-1]
        start = snip.get("start")
        url = f"https://www.youtube.com/watch?v={vid}"
        if isinstance(start, (int, float)) and start > 0:
            url += f"&t={max(int(start) - PAD, 0)}s"
        reads.append({
            "id": key,
            "video_id": vid,
            "title": snip.get("title"),
            "published": snip.get("published"),
            "channel_id": snip.get("channel_id"),
            "channel_name": (snip.get("channel_name")
                             or (names.get(int(snip["channel_id"])) if snip.get("channel_id") else None)),
            "read_words": snip.get("snippet") or None,
            "entity_as_heard": snip.get("entity_as_heard"),
            "start": start,
            "end": snip.get("end"),
            "url": url,
        })

    # A read whose words we actually have outranks a bare row; newest first
    # within each group.
    reads.sort(key=lambda r: r["published"] or "", reverse=True)
    reads.sort(key=lambda r: 0 if r["read_words"] else 1)
    kept = reads[:max_reads]
    with_words = sum(1 for r in kept if r["read_words"])

    return {
        "brand_ids": brand_ids,
        "channel": channel,
        "mention_videos_found": len(videos),
        "reads_returned": len(kept),
        "reads_with_spoken_words": with_words,
        "usage_note": ("read the words to learn what the product is, newest "
                       "first, an old read can describe a product that no "
                       "longer exists. A read with no words describes nothing. "
                       "If no read has words at all, use the brand's website "
                       "or their own brief instead."),
        "excluded_by_design": ["price", "cost", "rate cards",
                               "performance grades"],
        "reads": kept,
    }




# ---------------------------------------------------------------------------
# The TL-data lane: every query the lane runs, as one script (no agent)
# ---------------------------------------------------------------------------

SHOW_FIELDS = ("name", "website", "description", "company_description", "what_it_does", "offer",
               "type", "sponsored_topics", "ideal_customers")
# a description line that says the upload was sponsored: a sponsor word, or a
# hashtag ending in partner or ad (#brandpartner, #ad)
SPONSOR_LINE = re.compile(r"(partner|sponsor|thank you to|thanks to|#\w*partner\b|#\w*ad\b|#ad\b)", re.I)
MAX_UPLOADS = 600


def brand_show(brand_id: int) -> dict:
    rows = tl_data.cli_rows(["brands", "show", str(brand_id), "--json"])
    rec = rows[0] if rows and isinstance(rows[0], dict) else {}
    out = {k: rec.get(k) for k in SHOW_FIELDS if k in rec}
    out["brand_id"] = brand_id
    return out


def brand_names(ids: list) -> dict[str, str]:
    """Brand id to name, one Postgres lookup; unknown ids (``-1``) stay unnamed."""
    clean = sorted({int(i) for i in ids if str(i).lstrip("-").isdigit() and int(i) > 0})
    if not clean:
        return {}
    rows = tl_data.db_pg(f"SELECT id, name FROM thoughtleaders_brand WHERE id IN ({','.join(map(str, clean))}) "
                         f"LIMIT {len(clean)}")
    return {str(r["id"]): r.get("name") for r in rows if r.get("id")}


def mentions_by_year_and_channel(brand_ids: list[int]) -> tuple[dict, list[dict]]:
    """The brand's sponsored mentions by publication year, and its top 20 channels."""
    q = {"bool": {"should": [{"term": {"sponsored_brand_mentions": str(b)}} for b in brand_ids],
                  "minimum_should_match": 1}}
    _, aggs = tl_data.db_es_with_aggs({"size": 0, "query": q, "aggs": {
        "year": {"date_histogram": {"field": "publication_date", "calendar_interval": "year",
                                    "format": "yyyy", "min_doc_count": 1}},
        "chan": {"terms": {"field": "channel.id", "size": 20}}}})
    by_year = {str(b.get("key_as_string")): b.get("doc_count") for b in (aggs.get("year") or {}).get("buckets") or []}
    buckets = (aggs.get("chan") or {}).get("buckets") or []
    names = channel_names([b.get("key") for b in buckets])
    top = [{"id": int(b["key"]), "name": names.get(int(b["key"])), "count": b.get("doc_count")}
           for b in buckets if str(b.get("key", "")).lstrip("-").isdigit()]
    return by_year, top


def channel_uploads(channel: int) -> list[dict]:
    """This channel's uploads, newest first: title, date, description, sponsors."""
    return tl_data.db_es({
        "size": MAX_UPLOADS,
        "query": {"bool": {"filter": [{"term": {"doc_type": "article"}}, {"term": {"channel.id": int(channel)}}]}},
        "_source": ["id", "title", "publication_date", "summary", "sponsored_brand_mentions"],
        "sort": [{"publication_date": "desc"}]})


def sponsor_line(summary: str) -> str | None:
    for line in str(summary or "").splitlines():
        if SPONSOR_LINE.search(line):
            return line.strip()[:300]
    return None


def months_ago(today: str, months: int) -> str:
    """The same day ``months`` earlier, moved back to the month's last day
    when that month is shorter (29 February to 28 February)."""
    y, m = int(today[:4]), int(today[5:7]) - months
    while m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-{min(int(today[8:10]), calendar.monthrange(y, m)[1]):02d}"


def split_rivals(rivals: list[str]) -> tuple[list[str], list[str]]:
    """``--rivals`` names, and the ones marked ``~`` as also an everyday word
    ("~Haven"). The marker only tells moment_check to read that name in
    captions with care; the name itself matches sponsor records as usual."""
    clean, everyday = [], []
    for r in rivals:
        r = (r or "").strip()
        name = r.lstrip("~").strip()
        if not name:
            continue
        clean.append(name)
        if r.startswith("~"):
            everyday.append(name)
    return clean, sorted(set(everyday))


def lane(brand_ids: list[int], channel: int, rivals: list[str], today: str) -> dict:
    """Everything the TL-data lane writes to ``brand-tl.json``. ``rivals`` are
    the category's best-known names the orchestrator is certain of; a channel
    sponsor whose name matches one is the category history."""
    brand = brand_show(brand_ids[0])
    reads = collect_reads(brand_ids, 10, None)["reads"]
    own_reads = collect_reads(brand_ids, 50, channel)["reads"]
    by_year, top = mentions_by_year_and_channel(brand_ids)
    uploads = channel_uploads(channel)
    since = months_ago(today, 24)
    own_ids = {str(b) for b in brand_ids}
    ids = {str(i) for u in uploads for i in (u.get("sponsored_brand_mentions") or [])}
    names = brand_names(list(ids))
    sponsors: dict[str, dict] = {}       # all years, for the map writer to judge
    tags, history = [], []
    rivals, everyday = split_rivals(rivals)
    rival_lc = {r.lower() for r in rivals}
    for u in uploads:
        day = str(u.get("publication_date") or "")[:10]
        vid = str(u.get("id") or "").split(":")[-1]
        line = sponsor_line(u.get("summary"))
        if day >= since and line:
            tags.append({"video_id": str(u.get("id")), "published": day, "title": u.get("title"), "line": line})
        for b in u.get("sponsored_brand_mentions") or []:
            b = str(b)
            if b in own_ids:
                continue
            row = sponsors.setdefault(b, {"id": int(b) if b.lstrip("-").isdigit() else b, "name": names.get(b),
                                          "videos": 0, "videos_24m": 0, "last_seen": ""})
            row["videos"] += 1
            row["videos_24m"] += 1 if day >= since else 0
            row["last_seen"] = max(row["last_seen"], day)
            name = str(names.get(b) or "")
            if name and name.lower() in rival_lc:
                history.append({"brand": name, "video_id": vid, "published": day,
                                "title": u.get("title"), "line": line})
    all_years = sorted(sponsors.values(), key=lambda r: (-r["videos"], r["last_seen"]))
    return {
        "brand": brand, "reads": reads, "this_channel_reads": own_reads, "by_year": by_year,
        "top_channels": top, "description_tags": tags,
        "rivals": sorted(set(rivals)),
        "rivals_everyday": everyday,
        "category_history": sorted(history, key=lambda h: h["published"], reverse=True),
        "all_sponsors": all_years,
        "notes": (f"{len(uploads)} uploads read. A detection is a tag, not a deal. category_history holds "
                  "the channel's sponsors whose names are in rivals; all_sponsors lists every sponsor "
                  "across all years for the map writer to judge complements. Unknown ids (-1) carry no name."),
    }


def main() -> None:
    t0 = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--brand", type=int, action="append", required=True,
                    help="brand id from `tl brands find`; repeat for a rebrand")
    ap.add_argument("--max", type=int, default=10,
                    help="reads returned, newest descriptive first (default 10)")
    ap.add_argument("--channel", type=int, default=None,
                    help="only this channel's reads: the creator's own past reads")
    ap.add_argument("--lane", type=pathlib.Path, default=None,
                    help="run the whole TL-data lane for --channel and write brand-tl.json here")
    ap.add_argument("--rivals", default="",
                    help="with --lane: the category's best-known brand names, comma-separated; "
                         "prefix a name that is also an everyday word with ~ (~Haven)")
    a = ap.parse_args()
    if a.lane:
        if not a.channel:
            ap.error("--lane needs --channel")
        today = time.strftime("%Y-%m-%d")
        out = lane(a.brand, a.channel, [r for r in a.rivals.split(",")], today)
        a.lane.parent.mkdir(parents=True, exist_ok=True)
        a.lane.write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        summary = {"file": str(a.lane), "reads": len(out["reads"]),
                   "this_channel_reads": len(out["this_channel_reads"]), "years": len(out["by_year"]),
                   "top_channels": len(out["top_channels"]), "all_sponsors": len(out["all_sponsors"]),
                   "description_tags": len(out["description_tags"]), "rivals": len(out["rivals"]),
                   "rivals_everyday": len(out["rivals_everyday"]),
                   "category_history": len(out["category_history"]), "all_sponsors": len(out["all_sponsors"])}
        print(json.dumps(summary, indent=1))
        funnel(stage="brand_tl_lane", **{k: v for k, v in summary.items() if k != "file"},
               elapsed_s=round(time.monotonic() - t0, 1))
        return
    summary = collect_reads(a.brand, a.max, a.channel)
    print(json.dumps(summary, indent=1, default=str))
    funnel(**funnel_fields(summary, round(time.monotonic() - t0, 1)))


if __name__ == "__main__":
    main()
