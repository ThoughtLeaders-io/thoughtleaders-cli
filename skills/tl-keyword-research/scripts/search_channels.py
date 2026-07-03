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
    # boolean-group mode: each --group is one self-contained simple_query_string
    # (the final keyword_groups filter re-runs verbatim; groups OR-combine)
    search_channels.py --group '("fable 5" | fable5)' --group '("mythos 5" | mythos5) -keto'
    # intensity mode: classify every channel's relationship to the topic
    # (core / recurring / occasional / one_off) — 2-3 ES calls total
    search_channels.py --intensity --group '("cannes lions" | canneslions)'

Output (stdout): a single JSON object — see OUTPUT_SHAPE at the bottom.
"""
import argparse
import datetime
import json
import subprocess
import sys

DEFAULT_FIELDS = "title^4,summary^2,transcript^1"  # title > summary > transcript
# ES channel docs keep the LEGACY field names (reach / is_tl_channel …) — the
# index was not migrated in the big rename. Query with legacy names; emit the
# new vocabulary (subscribers / is_tpp) in the output. See sponsorability().
ENRICH_SOURCE = [
    "id", "name", "is_active", "is_tl_channel",
    "media_selling_network_join_date", "has_outreach_email",
    "sponsorship_price", "reach",
]
ES_TIMEOUT = 90
# Always scope to YouTube uploads (channel.format 4 — our inventory); at video
# level also default to longform (best sponsorable-content signal).
YOUTUBE_FORMAT = 4
CONTENT_TYPES = ("longform", "short", "live", "all")


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


def _envelope(bool_q, size):
    return {
        "size": size,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "collapse": {"field": "channel.id"},
        "sort": [{"_score": "desc"}],
        "_source": ["channel.id", "title", "publication_date"],
    }


def search_bool(keywords, fields, operator, since, until, not_terms=None,
                content_type="longform"):
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
    return bool_q


def composed_bool(any_groups, not_terms, fields, since, until,
                  content_type="longform"):
    """Composed mode — AND of OR-groups, minus exclusions:
        (g1a OR g1b …) AND (g2a OR g2b …) AND NOT (n1 OR n2 …)
    Each `--any` group is one required dimension (internally OR); adding a group
    NARROWS, adding terms to a group WIDENS it, `--not` excludes a sense."""
    must = [
        {"bool": {"should": keyword_clauses(group, fields), "minimum_should_match": 1}}
        for group in any_groups
    ]
    bool_q = {"must": must, "filter": _filters(since, until, content_type)}
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return bool_q


def groups_bool(groups, not_terms, fields, since, until, operator="OR",
                content_type="longform"):
    """Boolean-group mode — each group is a self-contained simple_query_string
    (`("fable 5" | fable5) -keto` scopes its exclusion to its own arm), exactly
    the shape the delivered keyword_groups filter stores. Groups combine per
    `operator` (default OR — a filter's groups union); `--not` still excludes
    across the whole query. `default_operator: "and"` keeps in-group `-` safe."""
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
    return bool_q


def intensity_envelope(bool_q, top, recency_cutoff):
    """ONE aggregation call that measures every channel's relationship to the
    topic: matching-upload count per channel (terms on channel.id, biggest
    first), how many of those matches are recent (filter sub-agg), and the
    true distinct-channel breadth (cardinality — the terms agg is truncated
    at `top`)."""
    return {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "aggs": {
            "distinct_channels": {"cardinality": {"field": "channel.id"}},
            "by_channel": {
                "terms": {"field": "channel.id", "size": top},
                "aggs": {"recent": {"filter": {
                    "range": {"publication_date": {"gte": recency_cutoff}}}}},
            },
        },
    }


def totals_body(channel_ids, content_type="longform"):
    """Per-channel TOTAL upload counts in the same scope — the denominator for
    topic share (matching_uploads / total_uploads). One call for all ids."""
    filt = [
        {"term": {"doc_type": "article"}},
        {"term": {"channel.format": YOUTUBE_FORMAT}},
        {"terms": {"channel.id": channel_ids}},
    ]
    if content_type and content_type != "all":
        filt.append({"term": {"content_type": content_type}})
    return {
        "size": 0,
        "track_total_hits": True,
        "query": {"bool": {"filter": filt}},
        "aggs": {"by_channel": {"terms": {"field": "channel.id", "size": len(channel_ids)}}},
    }


def months_ago_iso(months):
    """ISO date `months` whole months before today (day clamped to <=28)."""
    today = datetime.date.today()
    y, m = today.year, today.month - months
    while m <= 0:
        m += 12
        y -= 1
    return datetime.date(y, m, min(today.day, 28)).isoformat()


def _as_id(key):
    """Terms-agg keys on channel.id come back as strings; channel docs carry
    numeric ids. Coerce so enrichment and share lookups join correctly."""
    if isinstance(key, str) and key.isdigit():
        return int(key)
    return key


def intensity_tier(matches, share, recurring_min, core_share):
    """Classify a channel's RELATIONSHIP to the topic — not a binary.

    core       — the topic is (most of) the channel's identity: recurring AND
                 topic_share >= core_share (needs the totals call for share).
    recurring  — >= recurring_min matching uploads: a channel that keeps
                 returning to the topic. For niche topics with few/no core
                 channels, this tier IS the sponsorship market.
    occasional — 2..recurring_min-1 matches.
    one_off    — a single matching upload: counts for trend math, usually the
                 wrong target for sponsorships.
    """
    if matches >= recurring_min:
        if share is not None and share >= core_share:
            return "core"
        return "recurring"
    if matches == 1:
        return "one_off"
    return "occasional"


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


def render_groups(groups, not_terms, operator):
    """Readable expression for boolean-group mode: groups joined by the filter
    operator, whole-query excludes appended as AND NOT. Not CNF — in-group
    exclusions are scoped to their own arm, which CNF cannot express."""
    expression = f" {operator} ".join(f"({g})" for g in groups)
    for t in not_terms:
        expression += f" AND NOT {_q(t)}"
    return {"expression": expression, "clauses": None, "groups": list(groups)}


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
        "subscribers": doc.get("reach"),
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
    ap.add_argument("--group", action="append", default=[], metavar="SQS",
                    help="A self-contained simple_query_string boolean group, e.g. "
                         "'(\"fable 5\" | fable5) -keto'. Repeatable; groups combine per "
                         "--operator (default OR). This is the delivered keyword_groups "
                         "shape, so the final filter re-runs verbatim.")
    ap.add_argument("--not", dest="exclude", action="append", default=[], metavar="TERMS",
                    help="Comma-separated terms to EXCLUDE (must_not); repeatable. Narrows away a confusable sense.")
    ap.add_argument("--fields", default=DEFAULT_FIELDS,
                    help=f"Comma list of ES fields with optional ^boost (default: {DEFAULT_FIELDS})")
    ap.add_argument("--size", type=int, default=25, help="Number of channels to return (default 25)")
    ap.add_argument("--content-type", choices=list(CONTENT_TYPES), default="longform",
                    help="Video content type filter (default longform — best sponsorable "
                         "signal). 'all' drops the filter (include shorts + live). "
                         "YouTube-only (channel.format 4) is always enforced.")
    ap.add_argument("--since", help="publication_date >= YYYY-MM-DD")
    ap.add_argument("--until", help="publication_date <= YYYY-MM-DD")
    ap.add_argument("--no-enrich", action="store_true", help="Skip name + sponsorability enrichment")
    # Intensity mode — classify every channel's RELATIONSHIP to the topic
    # (core / recurring / occasional / one_off) from 2–3 aggregation calls,
    # instead of ranking by best-matching video.
    ap.add_argument("--intensity", action="store_true",
                    help="Topic-intensity mode: per-channel matching-upload counts "
                         "(all-time + recent) + tier labels, via aggregations — "
                         "2–3 ES calls total regardless of channel count.")
    ap.add_argument("--top", type=int, default=200,
                    help="Intensity mode: how many channels to tier, biggest "
                         "matchers first (default 200; distinct_channels reports "
                         "the full breadth beyond the cut).")
    ap.add_argument("--recency-months", type=int, default=12,
                    help="Intensity mode: window for recent_matching_uploads (default 12).")
    ap.add_argument("--recurring-min", type=int, default=3,
                    help="Intensity mode: matching uploads needed for the "
                         "'recurring' tier (default 3).")
    ap.add_argument("--core-share", type=float, default=0.5,
                    help="Intensity mode: topic_share at/above which a recurring "
                         "channel is 'core' (default 0.5).")
    ap.add_argument("--no-share", action="store_true",
                    help="Intensity mode: skip the totals call (no topic_share, "
                         "so no 'core' tier — saves one ES call).")
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
        bool_q = groups_bool(sqs_groups, not_terms, fields, args.since, args.until,
                             args.operator, args.content_type)
        query_desc = {"mode": "groups", "operator": args.operator,
                      "groups": sqs_groups, "not": not_terms}
        expression = render_groups(sqs_groups, not_terms, args.operator)
    elif any_groups:
        if keywords:  # positional/stdin keywords become a leading required OR-group
            any_groups = [keywords] + any_groups
        bool_q = composed_bool(any_groups, not_terms, fields, args.since, args.until,
                               args.content_type)
        query_desc = {"mode": "composed", "any_groups": any_groups, "not": not_terms}
        expression = render_cnf(any_groups, not_terms)
    else:
        if not keywords:
            sys.exit("provide keywords (positional args / JSON array on stdin), --any groups, or --group")
        bool_q = search_bool(keywords, fields, args.operator, args.since, args.until,
                             not_terms, args.content_type)
        query_desc = {"mode": "flat", "operator": args.operator, "keywords": keywords, "not": not_terms}
        pos_clauses = [keywords] if args.operator == "OR" else [[k] for k in keywords]
        expression = render_cnf(pos_clauses, not_terms)

    scope = {"format": "youtube", "content_type": args.content_type}

    if args.intensity:
        cutoff = months_ago_iso(args.recency_months)
        env = run_es(intensity_envelope(bool_q, args.top, cutoff))
        aggs = env.get("aggregations") or {}
        buckets = (aggs.get("by_channel") or {}).get("buckets") or []
        distinct = (aggs.get("distinct_channels") or {}).get("value")
        channels = [{
            "channel_id": _as_id(b.get("key")),
            "matching_uploads": b.get("doc_count", 0),
            "recent_matching_uploads": (b.get("recent") or {}).get("doc_count", 0),
        } for b in buckets]

        totals = {}
        if channels and not args.no_share:
            tenv = run_es(totals_body([c["channel_id"] for c in channels], args.content_type))
            taggs = tenv.get("aggregations") or {}
            totals = {_as_id(tb.get("key")): tb.get("doc_count", 0)
                      for tb in (taggs.get("by_channel") or {}).get("buckets") or []}

        tiers = {"core": 0, "recurring": 0, "occasional": 0, "one_off": 0}
        for c in channels:
            total_uploads = totals.get(c["channel_id"])
            share = (round(c["matching_uploads"] / total_uploads, 3)
                     if total_uploads else None)
            c["total_uploads"] = total_uploads
            c["topic_share"] = share
            c["tier"] = intensity_tier(c["matching_uploads"], share,
                                       args.recurring_min, args.core_share)
            tiers[c["tier"]] += 1

        if channels and not args.no_enrich:
            meta = {d.get("id"): d for d in
                    run_es(build_enrich([c["channel_id"] for c in channels])).get("results", [])}
            for c in channels:
                doc = meta.get(c["channel_id"], {})
                c["name"] = doc.get("name")
                c["sponsorability"] = sponsorability(doc)

        print(json.dumps({
            "query": query_desc,
            "cnf": expression,      # kept name for back-compat; see OUTPUT_SHAPE
            "expression": expression,
            "fields": args.fields,
            "scope": scope,
            "recency": {"months": args.recency_months, "cutoff": cutoff},
            "total_matching_videos": env.get("total", 0),
            "distinct_channels": distinct,
            "tiers": tiers,
            "channels": channels,
        }, ensure_ascii=False))
        return

    env = run_es(_envelope(bool_q, args.size))
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
        "cnf": expression,          # kept name for back-compat; see OUTPUT_SHAPE
        "expression": expression,
        "fields": args.fields,
        "scope": scope,
        "total_matching_videos": env.get("total", 0),
        "channels": channels,
    }, ensure_ascii=False))


# OUTPUT_SHAPE (ranked mode, the default):
# {"query":{"mode":"flat","operator","keywords","not"} | {"mode":"composed","any_groups":[[...]],"not"}
#          | {"mode":"groups","operator","groups":[...],"not"},
#  "cnf"/"expression": {"expression":"(a OR b) AND (c) AND (NOT x)","clauses":[["a","b"],["c"],["NOT x"]]}
#          — flat/composed render true CNF; groups mode renders the OR-joined
#            boolean groups instead ("clauses": null, "groups": [...]) since
#            in-group scoped exclusions cannot be expressed in CNF.
#  "fields", "scope":{"format":"youtube","content_type":...}, "total_matching_videos",
#  "channels":[{"channel_id","name","score","top_video_id","top_video_title",
#               "sponsorability":{"is_active","is_tpp","is_msn","msn_join_date",
#                                 "has_outreach_email","sponsorship_price","subscribers"}}, ...]}
#
# OUTPUT_SHAPE (--intensity mode):
# {"query","cnf"/"expression","fields","scope","recency":{"months","cutoff"},
#  "total_matching_videos",
#  "distinct_channels": <true breadth — the tiered list is capped at --top>,
#  "tiers":{"core":n,"recurring":n,"occasional":n,"one_off":n},
#  "channels":[{"channel_id","name","matching_uploads","recent_matching_uploads",
#               "total_uploads","topic_share","tier","sponsorability":{...}}, ...]}
# — biggest matchers first; topic_share/"core" need the totals call (absent
#   with --no-share). Tiers: core = recurring AND topic_share >= --core-share;
#   recurring = matching_uploads >= --recurring-min; occasional = 2..min-1;
#   one_off = 1.
#
# sponsorability reads LEGACY ES channel-doc fields (reach, is_tl_channel) and
# emits the renamed vocabulary (subscribers, is_tpp) — ES was not migrated.
if __name__ == "__main__":
    main()
