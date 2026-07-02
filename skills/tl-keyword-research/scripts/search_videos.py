#!/usr/bin/env python3
"""Find videos/uploads that match a topic filter — the trend-report lane.

Where `search_channels.py` answers "which channels cover this topic" (one
collapsed row per channel, for sponsorship prospecting), this returns the
matching VIDEOS themselves — for trend reports, "who's talking about X right
now", and any upload-level question. Same boolean composition surface (flat
keywords, `--any` OR-groups, `--group` self-contained SQS groups), same
always-on scope (YouTube uploads, longform by default), plus trend-friendly
sorting and windowing.

By default every matching video is a row, so one prolific channel can
dominate — pass `--distinct-channels` to keep only each channel's best match
instead. Videos are enriched with their channel's name + subscribers (one
extra ES call on channel docs).

Usage:
    search_videos.py "tiktok shop" "selling on tiktok"
    search_videos.py --group '("fable 5" | fable5)' --sort date --since 2026-06-01
    search_videos.py --any 'cannes lions,young lions' --sort views --size 50
    echo '["crypto","bitcoin"]' | search_videos.py

Output (stdout): a single JSON object — see OUTPUT_SHAPE at the bottom.
"""
import argparse
import json
import subprocess
import sys

DEFAULT_FIELDS = "title^4,summary^2,transcript^1"  # title > summary > transcript
# ES channel docs keep the LEGACY field names (reach …) — the index was not
# migrated in the big rename. Query with legacy names; emit the new
# vocabulary (subscribers) in the output.
ENRICH_SOURCE = ["id", "name", "reach"]
VIDEO_SOURCE = ["id", "title", "url", "publication_date", "views", "likes",
                "duration", "channel.id"]
ES_TIMEOUT = 90
YOUTUBE_FORMAT = 4
CONTENT_TYPES = ("longform", "short", "live", "all")
SORTS = {
    "score": [{"_score": "desc"}],
    "date": [{"publication_date": "desc"}],
    "views": [{"views": "desc"}],
}


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


def _filters(since, until, content_type="longform"):
    filt = [
        {"term": {"doc_type": "article"}},
        {"term": {"channel.format": YOUTUBE_FORMAT}},
    ]
    if content_type and content_type != "all":
        filt.append({"term": {"content_type": content_type}})
    if since or until:
        rng = {}
        if since:
            rng["gte"] = since
        if until:
            rng["lte"] = until
        filt.append({"range": {"publication_date": rng}})
    return filt


def _envelope(bool_q, size, sort, distinct_channels):
    body = {
        "size": size,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "sort": SORTS[sort],
        "_source": VIDEO_SOURCE,
    }
    if distinct_channels:
        body["collapse"] = {"field": "channel.id"}
    return body


def build_search(keywords, fields, operator, since, until, size, sort,
                 distinct_channels, not_terms=None, content_type="longform"):
    """Flat mode: a single OR/AND list of keywords (+ optional exclusions)."""
    clauses = keyword_clauses(keywords, fields)
    bool_q = {"filter": _filters(since, until, content_type)}
    if operator == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return _envelope(bool_q, size, sort, distinct_channels)


def build_composed(any_groups, not_terms, fields, since, until, size, sort,
                   distinct_channels, content_type="longform"):
    """Composed mode — AND of OR-groups, minus exclusions."""
    must = [
        {"bool": {"should": keyword_clauses(group, fields), "minimum_should_match": 1}}
        for group in any_groups
    ]
    bool_q = {"must": must, "filter": _filters(since, until, content_type)}
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return _envelope(bool_q, size, sort, distinct_channels)


def build_groups(groups, not_terms, fields, since, until, size, sort,
                 distinct_channels, operator="OR", content_type="longform"):
    """Boolean-group mode — each group is a self-contained simple_query_string
    (the delivered keyword_groups shape, so the final filter re-runs verbatim).
    `default_operator: "and"` keeps in-group `-` safe."""
    clauses = [
        {"simple_query_string": {"query": g, "fields": fields, "default_operator": "and"}}
        for g in groups
    ]
    bool_q = {"filter": _filters(since, until, content_type)}
    if operator == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return _envelope(bool_q, size, sort, distinct_channels)


def _q(lit):
    """Quote a multi-word literal for the readable expression string."""
    return f'"{lit}"' if " " in lit else lit


def render_cnf(pos_clauses, not_terms):
    """CNF rendering for flat/composed modes (AND of OR-clauses + NOT units)."""
    clauses = [list(c) for c in pos_clauses if c]
    clauses += [["NOT " + t] for t in not_terms]

    def lit(token):
        return "NOT " + _q(token[4:]) if token.startswith("NOT ") else _q(token)

    expression = " AND ".join(
        "(" + " OR ".join(lit(t) for t in clause) + ")" for clause in clauses
    )
    return {"expression": expression, "clauses": clauses}


def render_groups(groups, not_terms, operator):
    """Readable expression for boolean-group mode (not CNF — in-group
    exclusions are scoped to their own arm)."""
    expression = f" {operator} ".join(f"({g})" for g in groups)
    for t in not_terms:
        expression += f" AND NOT {_q(t)}"
    return {"expression": expression, "clauses": None, "groups": list(groups)}


def build_enrich(channel_ids):
    # ES holds many channel docs per id (the alias spans several backing
    # indices) — collapse to one doc per id.
    return {
        "size": len(channel_ids),
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "channel"}},
            {"terms": {"id": channel_ids}},
        ]}},
        "collapse": {"field": "id"},
        "_source": ENRICH_SOURCE,
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
    ap = argparse.ArgumentParser(description="Find matching videos/uploads for a topic filter (trend lane).")
    ap.add_argument("keywords", nargs="*", help="Keywords (or pipe a JSON array on stdin)")
    ap.add_argument("--operator", choices=["AND", "OR"], default="OR",
                    help="How to combine flat keywords / --group groups (default OR).")
    ap.add_argument("--any", action="append", default=[], metavar="TERMS",
                    help="A comma-separated OR-group. Repeat to AND groups. Enables composed mode.")
    ap.add_argument("--group", action="append", default=[], metavar="SQS",
                    help="A self-contained simple_query_string boolean group (the delivered "
                         "keyword_groups shape). Repeatable; groups combine per --operator.")
    ap.add_argument("--not", dest="exclude", action="append", default=[], metavar="TERMS",
                    help="Comma-separated terms to EXCLUDE (must_not); repeatable.")
    ap.add_argument("--fields", default=DEFAULT_FIELDS,
                    help=f"Comma list of ES fields with optional ^boost (default: {DEFAULT_FIELDS})")
    ap.add_argument("--size", type=int, default=25, help="Number of videos to return (default 25)")
    ap.add_argument("--sort", choices=sorted(SORTS), default="score",
                    help="Ranking: score (topical relevance, default), date "
                         "(newest first — trend feed), views (biggest first).")
    ap.add_argument("--distinct-channels", action="store_true",
                    help="Collapse to each channel's single best-matching video "
                         "(otherwise one prolific channel can dominate the list).")
    ap.add_argument("--content-type", choices=list(CONTENT_TYPES), default="longform",
                    help="Video content type filter (default longform). 'all' drops the "
                         "filter. YouTube-only (channel.format 4) is always enforced.")
    ap.add_argument("--since", help="publication_date >= YYYY-MM-DD")
    ap.add_argument("--until", help="publication_date <= YYYY-MM-DD")
    ap.add_argument("--no-enrich", action="store_true", help="Skip channel name/subscribers enrichment")
    args = ap.parse_args()

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    if not fields:
        sys.exit("--fields must list at least one ES field")

    def parse_group(raw):
        return [t.strip() for t in raw.split(",") if t.strip()]

    keywords = dedupe(collect_keywords(args.keywords))
    any_groups = [g for g in (parse_group(r) for r in args.any) if g]
    sqs_groups = [g.strip() for g in args.group if g.strip()]
    not_terms = dedupe([t for r in args.exclude for t in parse_group(r)])

    if sqs_groups and any_groups:
        sys.exit("--group and --any are different composition modes; use one or the other")

    if sqs_groups:
        if keywords:  # positional/stdin keywords become plain-phrase groups
            sqs_groups = [f'"{k}"' if " " in k else k for k in keywords] + sqs_groups
        env = run_es(build_groups(sqs_groups, not_terms, fields, args.since, args.until,
                                  args.size, args.sort, args.distinct_channels,
                                  args.operator, args.content_type))
        query_desc = {"mode": "groups", "operator": args.operator,
                      "groups": sqs_groups, "not": not_terms}
        expression = render_groups(sqs_groups, not_terms, args.operator)
    elif any_groups:
        if keywords:
            any_groups = [keywords] + any_groups
        env = run_es(build_composed(any_groups, not_terms, fields, args.since, args.until,
                                    args.size, args.sort, args.distinct_channels,
                                    args.content_type))
        query_desc = {"mode": "composed", "any_groups": any_groups, "not": not_terms}
        expression = render_cnf(any_groups, not_terms)
    else:
        if not keywords:
            sys.exit("provide keywords (positional args / JSON array on stdin), --any groups, or --group")
        env = run_es(build_search(keywords, fields, args.operator, args.since, args.until,
                                  args.size, args.sort, args.distinct_channels,
                                  not_terms, args.content_type))
        query_desc = {"mode": "flat", "operator": args.operator, "keywords": keywords, "not": not_terms}
        pos_clauses = [keywords] if args.operator == "OR" else [[k] for k in keywords]
        expression = render_cnf(pos_clauses, not_terms)

    videos = []
    for row in env.get("results", []):
        ch = row.get("channel") or {}
        videos.append({
            "video_id": row.get("id") or row.get("_id"),
            "title": row.get("title"),
            "url": row.get("url"),
            "publication_date": row.get("publication_date"),
            "views": row.get("views"),
            "likes": row.get("likes"),
            "duration": row.get("duration"),
            "score": round(row.get("_score") or 0.0, 3) if row.get("_score") is not None else None,
            "channel": {"channel_id": ch.get("id")},
        })

    if videos and not args.no_enrich:
        ids = sorted({v["channel"]["channel_id"] for v in videos
                      if v["channel"]["channel_id"] is not None})
        if ids:
            meta = {d.get("id"): d for d in run_es(build_enrich(ids)).get("results", [])}
            for v in videos:
                doc = meta.get(v["channel"]["channel_id"], {})
                v["channel"]["name"] = doc.get("name")
                v["channel"]["subscribers"] = doc.get("reach")

    scope = {"format": "youtube", "content_type": args.content_type}
    print(json.dumps({
        "query": query_desc,
        "expression": expression,
        "fields": args.fields,
        "scope": scope,
        "sort": args.sort,
        "distinct_channels": args.distinct_channels,
        "total_matching_videos": env.get("total", 0),
        "videos": videos,
    }, ensure_ascii=False))


# OUTPUT_SHAPE:
# {"query":{"mode":"flat"|"composed"|"groups", ...},
#  "expression":{"expression","clauses"|null[,"groups"]},
#  "fields","scope":{"format":"youtube","content_type":...},"sort","distinct_channels",
#  "total_matching_videos",
#  "videos":[{"video_id","title","url","publication_date","views","likes","duration",
#             "score","channel":{"channel_id","name","subscribers"}}, ...]}
# channel.subscribers is read from the LEGACY ES field `reach` (the index was
# not migrated in the big rename) and emitted under the new vocabulary.
# Sorting by date/views still applies the same topic filter; `score` is null
# when ES omits scoring under a non-score sort.
if __name__ == "__main__":
    main()
