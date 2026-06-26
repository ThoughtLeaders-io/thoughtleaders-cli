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


def _filters(since, until):
    filt = [{"term": {"doc_type": "article"}}]
    if since or until:
        rng = {}
        if since:
            rng["gte"] = since
        if until:
            rng["lte"] = until
        filt.append({"range": {"publication_date": rng}})
    return filt


def _envelope(bool_q, size):
    return {
        "size": size,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "collapse": {"field": "channel.id"},
        "sort": [{"_score": "desc"}],
        "_source": ["channel.id", "title", "publication_date"],
    }


def build_search(keywords, fields, operator, since, until, size, not_terms=None):
    """Flat mode: a single OR/AND list of keywords (+ optional exclusions)."""
    clauses = keyword_clauses(keywords, fields)
    bool_q = {"filter": _filters(since, until)}
    if operator == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return _envelope(bool_q, size)


def build_composed(any_groups, not_terms, fields, since, until, size):
    """Composed mode — AND of OR-groups, minus exclusions:
        (g1a OR g1b …) AND (g2a OR g2b …) AND NOT (n1 OR n2 …)
    Each `--any` group is one required dimension (internally OR); adding a group
    NARROWS, adding terms to a group WIDENS it, `--not` excludes a sense."""
    must = [
        {"bool": {"should": keyword_clauses(group, fields), "minimum_should_match": 1}}
        for group in any_groups
    ]
    bool_q = {"must": must, "filter": _filters(since, until)}
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return _envelope(bool_q, size)


def _q(lit):
    """Quote a multi-word literal for the readable CNF string."""
    return f'"{lit}"' if " " in lit else lit


def render_cnf(pos_clauses, not_terms):
    """Render the boolean query as Conjunctive Normal Form — an AND of clauses,
    each clause an OR of literals. Positive OR-groups are disjunctive clauses;
    each excluded term becomes a negated unit clause (NOT t). This CNF expression
    is the skill's distilled, reusable artifact."""
    clauses = [list(c) for c in pos_clauses if c]
    clauses += [["NOT " + t] for t in not_terms]

    def lit(token):
        return "NOT " + _q(token[4:]) if token.startswith("NOT ") else _q(token)

    expression = " AND ".join(
        "(" + " OR ".join(lit(t) for t in clause) + ")" for clause in clauses
    )
    return {"expression": expression, "clauses": clauses}


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
    ap.add_argument("--operator", choices=["AND", "OR"], default="OR",
                    help="How to combine flat keywords (default OR). Ignored when --any is used.")
    ap.add_argument("--any", action="append", default=[], metavar="TERMS",
                    help="A comma-separated OR-group. Repeat to AND groups: "
                         "--any 'a,b' --any 'c,d' → (a OR b) AND (c OR d). Enables composed mode.")
    ap.add_argument("--not", dest="exclude", action="append", default=[], metavar="TERMS",
                    help="Comma-separated terms to EXCLUDE (must_not); repeatable. Narrows away a confusable sense.")
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

    def parse_group(raw):
        return [t.strip() for t in raw.split(",") if t.strip()]

    keywords = dedupe(collect_keywords(args.keywords))
    any_groups = [g for g in (parse_group(r) for r in args.any) if g]
    not_terms = dedupe([t for r in args.exclude for t in parse_group(r)])

    if any_groups:
        if keywords:  # positional/stdin keywords become a leading required OR-group
            any_groups = [keywords] + any_groups
        env = run_es(build_composed(any_groups, not_terms, fields, args.since, args.until, args.size))
        query_desc = {"mode": "composed", "any_groups": any_groups, "not": not_terms}
        pos_clauses = any_groups
    else:
        if not keywords:
            sys.exit("provide keywords (positional args / JSON array on stdin) or --any groups")
        env = run_es(build_search(keywords, fields, args.operator, args.since, args.until, args.size, not_terms))
        query_desc = {"mode": "flat", "operator": args.operator, "keywords": keywords, "not": not_terms}
        pos_clauses = [keywords] if args.operator == "OR" else [[k] for k in keywords]

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
        "query": query_desc,
        "cnf": render_cnf(pos_clauses, not_terms),
        "fields": args.fields,
        "total_matching_videos": env.get("total", 0),
        "channels": channels,
    }, ensure_ascii=False))


# OUTPUT_SHAPE:
# {"query":{"mode":"flat","operator","keywords","not"} | {"mode":"composed","any_groups":[[...]],"not"},
#  "cnf":{"expression":"(a OR b) AND (c) AND (NOT x)","clauses":[["a","b"],["c"],["NOT x"]]},
#  "fields","total_matching_videos",
#  "channels":[{"channel_id","name","score","top_video_id","top_video_title",
#               "sponsorability":{"is_active","is_tpp","is_msn","msn_join_date",
#                                 "has_outreach_email","sponsorship_price","reach"}}, ...]}
if __name__ == "__main__":
    main()
