#!/usr/bin/env python3
"""Find channels that cover a topic, ranked by field-weighted relevance.

Runs ONE collapsed Elasticsearch search (`collapse` on `channel.id`, sorted by
`_score`) so each channel surfaces its single best-matching video — ranked by
topical strength, with `title` weighted above `summary` above `transcript`.
Then enriches the candidate channels with name + sponsorability flags from the
channel docs (one more ES call). This is the skill's DEFAULT output; keyword
distribution (`probe.py`) is the opt-in mode.

Usage:
    search_channels.py investing "index funds" "stock market"
    echo '["investing","index funds"]' | search_channels.py
    search_channels.py --operator AND "tiktok shop" affiliate
    search_channels.py --since 2025-01-01 --size 40 investing

Output (stdout): a single JSON object — see OUTPUT_SHAPE at the bottom.
"""
import argparse
import json
import subprocess
import sys

DEFAULT_FIELDS = "title^4,summary^2,transcript^1"  # title > summary > transcript
ENRICH_SOURCE = [
    "id", "name", "is_active", "is_tl_channel",
    "media_selling_network_join_date", "has_outreach_email",
    "sponsorship_price", "reach",
]
ES_TIMEOUT = 90


def run_es(body):
    """POST an ES body via `tl db es` and return the parsed envelope, or exit."""
    proc = subprocess.run(
        ["tl", "db", "es", "-", "--json"],
        input=json.dumps(body), capture_output=True, text=True, timeout=ES_TIMEOUT,
    )
    if proc.returncode != 0:
        sys.stderr.write(
            f"tl db es failed (rc={proc.returncode}): "
            f"{(proc.stderr or proc.stdout).strip()}\n"
        )
        sys.exit(proc.returncode or 1)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        sys.stderr.write(f"could not parse tl db es output: {exc}\n")
        sys.exit(1)


def keyword_clauses(keywords, fields):
    """One `multi_match phrase` clause per keyword over the boosted fields."""
    return [
        {"multi_match": {"query": kw, "type": "phrase", "fields": fields}}
        for kw in keywords
    ]


def build_search(keywords, fields, operator, since, until, size):
    clauses = keyword_clauses(keywords, fields)
    bool_q = {"filter": [{"term": {"doc_type": "article"}}]}
    if operator == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    if since or until:
        rng = {}
        if since:
            rng["gte"] = since
        if until:
            rng["lte"] = until
        bool_q["filter"].append({"range": {"publication_date": rng}})
    return {
        "size": size,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "collapse": {"field": "channel.id"},
        "sort": [{"_score": "desc"}],
        "_source": ["channel.id", "title", "publication_date"],
    }


def build_enrich(channel_ids):
    # ES holds many channel docs per id (the `tl-platform` alias spans several
    # backing indices). Collapse to one doc per id, else a single channel's
    # copies fill the result window and starve the other ids.
    return {
        "size": len(channel_ids),
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "channel"}},
            {"terms": {"id": channel_ids}},
        ]}},
        "collapse": {"field": "id"},
        "_source": ENRICH_SOURCE,
    }


def sponsorability(doc):
    """Flag (do NOT filter) how bookable a channel is."""
    return {
        "is_active": doc.get("is_active"),
        "is_tpp": bool(doc.get("is_tl_channel")),
        "is_msn": doc.get("media_selling_network_join_date") is not None,
        "msn_join_date": doc.get("media_selling_network_join_date"),
        "has_outreach_email": doc.get("has_outreach_email"),
        "sponsorship_price": doc.get("sponsorship_price"),
        "reach": doc.get("reach"),
    }


def collect_keywords(argv_words):
    if argv_words:
        return [w.strip() for w in argv_words if w.strip()]
    if sys.stdin.isatty():
        return []
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if isinstance(parsed, list):
        return [str(x).strip() for x in parsed if str(x).strip()]
    sys.exit("stdin JSON must be a list of strings")


def dedupe(items):
    seen, out = set(), []
    for it in items:
        k = it.lower()
        if k not in seen:
            seen.add(k)
            out.append(it)
    return out


def main():
    ap = argparse.ArgumentParser(description="Rank channels by field-weighted topic relevance.")
    ap.add_argument("keywords", nargs="*", help="Keywords (or pipe a JSON array on stdin)")
    ap.add_argument("--operator", choices=["AND", "OR"], default="OR")
    ap.add_argument("--fields", default=DEFAULT_FIELDS,
                    help=f"Comma list of ES fields with optional ^boost (default: {DEFAULT_FIELDS})")
    ap.add_argument("--size", type=int, default=25, help="Number of channels to return (default 25)")
    ap.add_argument("--since", help="publication_date >= YYYY-MM-DD")
    ap.add_argument("--until", help="publication_date <= YYYY-MM-DD")
    ap.add_argument("--no-enrich", action="store_true", help="Skip name + sponsorability enrichment")
    args = ap.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    if not fields:
        sys.exit("--fields must list at least one ES field")
    keywords = dedupe(collect_keywords(args.keywords))
    if not keywords:
        sys.exit("provide at least one keyword (positional args or JSON array on stdin)")

    env = run_es(build_search(keywords, fields, args.operator, args.since, args.until, args.size))
    channels = []
    for row in env.get("results", []):
        ch = row.get("channel") or {}
        cid = ch.get("id")
        if cid is None:
            continue
        channels.append({
            "channel_id": cid,
            "score": round(row.get("_score") or 0.0, 3),
            "top_video_id": row.get("_id"),
            "top_video_title": row.get("title"),
        })

    if channels and not args.no_enrich:
        meta = {d.get("id"): d for d in run_es(build_enrich([c["channel_id"] for c in channels])).get("results", [])}
        for c in channels:
            doc = meta.get(c["channel_id"], {})
            c["name"] = doc.get("name")
            c["sponsorability"] = sponsorability(doc)

    print(json.dumps({
        "operator": args.operator,
        "fields": args.fields,
        "total_matching_videos": env.get("total", 0),
        "channels": channels,
    }, ensure_ascii=False))


# OUTPUT_SHAPE:
# {"operator","fields","total_matching_videos",
#  "channels":[{"channel_id","name","score","top_video_id","top_video_title",
#               "sponsorability":{"is_active","is_tpp","is_msn","msn_join_date",
#                                 "has_outreach_email","sponsorship_price","reach"}}, ...]}
if __name__ == "__main__":
    main()
