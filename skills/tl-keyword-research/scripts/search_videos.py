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
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_common  # noqa: E402

DEFAULT_FIELDS = "title^4,summary^2,transcript^1"  # title > summary > transcript
# ES channel docs keep the LEGACY field names (reach …) — the index was not
# migrated in the big rename. Query with legacy names; emit the new
# vocabulary (subscribers) in the output.
ENRICH_SOURCE = ["id", "name", "reach"]
VIDEO_SOURCE = ["id", "title", "url", "publication_date", "views", "likes",
                "duration", "channel.id", "channel.channel_name"]
CONTENT_TYPES = kw_common.CONTENT_TYPES
SORTS = {
    "score": [{"_score": "desc"}],
    "date": [{"publication_date": "desc"}],
    "views": [{"views": "desc"}],
}


def _as_id(value):
    """Channel ids come back as ints on video docs and sometimes as digit
    strings on channel docs — coerce both sides so enrichment joins."""
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return value


def keyword_clauses(keywords, fields):
    """One `multi_match phrase` clause per keyword over the boosted fields."""
    return [
        {"multi_match": {"query": kw, "type": "phrase", "fields": fields}}
        for kw in keywords
    ]


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
    bool_q = {"filter": kw_common.scope_filters(level="topic", content_type=content_type,
                                                since=since, until=until)}
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
    bool_q = {"must": must, "filter": kw_common.scope_filters(level="topic", content_type=content_type,
                                                               since=since, until=until)}
    if not_terms:
        bool_q["must_not"] = keyword_clauses(not_terms, fields)
    return _envelope(bool_q, size, sort, distinct_channels)


def build_groups(groups, not_terms, fields, since, until, size, sort,
                 distinct_channels, operator="OR", content_type="longform",
                 group_fields=None, not_groups=None):
    """Boolean-group mode — each group is a self-contained simple_query_string
    (the delivered keyword_groups shape, so the final filter re-runs verbatim).
    Built via `kw_common.groups_query`, scope via `kw_common.scope_filters`."""
    group_fields = group_fields or {}
    spec_groups = [
        {"text": g, "content_fields": group_fields.get(i), "exclude": False}
        for i, g in enumerate(groups)
    ] + [
        {"text": g["text"], "content_fields": g.get("fields"), "exclude": True}
        for g in (not_groups or [])
    ]
    spec = {"groups": spec_groups, "operator": operator, "default_content_fields": fields}
    bool_q = kw_common.groups_query(spec, operator=operator)
    bool_q["filter"] = kw_common.scope_filters(level="topic", content_type=content_type,
                                               since=since, until=until)
    if not_terms:
        bool_q["must_not"] = list(bool_q.get("must_not") or []) + keyword_clauses(not_terms, fields)
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
    if not kw_common.stdin_is_readable():
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


def _resolve_deadline(deadline_at):
    """`--deadline-at EPOCH_SECONDS` (or `$TL_KW_DEADLINE_AT`) → a `kw_common.Deadline`
    counting down to that moment; unbounded when neither is given."""
    if deadline_at is None:
        raw = os.environ.get("TL_KW_DEADLINE_AT")
        if raw:
            try:
                deadline_at = float(raw)
            except ValueError:
                deadline_at = None
    if deadline_at is None:
        return kw_common.Deadline(None)
    return kw_common.Deadline(max(0.0, deadline_at - time.time()))


def _fatal_es_error(exc):
    """Exit the way the old inline `run_es` did — message + exit code.

    A deadline is NOT routed here: it is a budget outcome, not a broken query,
    and a non-zero exit would break the `&&` chain the skill runs these steps
    in. The caller emits the normal envelope with empty results instead.
    """
    sys.stderr.write(f"{exc}\n")
    sys.exit(1)

def _write_sheet(path, text):
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        sys.exit(f"could not write --sheet {path}: {exc}")


DEADLINE_SHEET = "deadline reached — not run\n"



# -------------------------------------------------------------------- sheet

def scope_line(scope):
    """`youtube longform · 2025-09-19..` — the window the rows were found in."""
    line = f"{scope.get('format') or 'youtube'} {scope.get('content_type') or 'all'}"
    since, until = scope.get("since"), scope.get("until")
    if since or until:
        line += f" · {since or ''}..{until or ''}"
    return line


def compact_views(views):
    """`187K views` / `1.2M views` — readable at a glance."""
    if views is None:
        return "? views"
    if views >= 1_000_000:
        return f"{views / 1_000_000:.1f}M views"
    if views >= 1_000:
        return f"{round(views / 1_000)}K views"
    return f"{views} views"


def render_sheet(out, title_chars=90):
    """One line per video — the readable twin of the JSON."""
    videos = out["videos"]
    lines = [f"# Videos · {out['sort']} · {scope_line(out['scope'])} · "
             f"{out['total_matching_videos']} matching · showing {len(videos)}"]
    for v in videos:
        title = v.get("title") or "(untitled)"
        if len(title) > title_chars:
            title = title[:title_chars - 1].rstrip() + "…"
        lines.append(" · ".join([
            f"- {v.get('publication_date') or '????-??-??'}",
            compact_views(v.get("views")),
            f"{v.get('channel_name') or '(unknown)'} ({v.get('channel_id')})",
            title,
        ]))
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Find matching videos/uploads for a topic filter (trend lane).")
    ap.add_argument("keywords", nargs="*", help="Keywords (or pipe a JSON array on stdin)")
    ap.add_argument("--operator", choices=["AND", "OR"], default=None,
                    help="How to combine flat keywords / --group groups (default OR).")
    ap.add_argument("--any", action="append", default=[], metavar="TERMS",
                    help="A comma-separated OR-group. Repeat to AND groups. Enables composed mode.")
    ap.add_argument("--group", action="append", default=[], metavar="SQS",
                    help="A self-contained simple_query_string boolean group (the delivered "
                         "keyword_groups shape). Repeatable; groups combine per --operator.")
    ap.add_argument("--groups-file", metavar="PATH",
                    help="JSON file of boolean groups — build_report.py's {\"groups\": "
                         "[{\"text\": ...}]} shape, or a list of strings. Appended to "
                         "--group; skips shell quoting for large filters.")
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
    ap.add_argument("--sheet", metavar="PATH",
                    help="Also write a readable one-line-per-video sheet here (read this "
                         "instead of the JSON).")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: append this invocation (argv, elapsed, output) as one event file under DIR/events/")
    ap.add_argument("--deadline-at", type=float, default=None, metavar="EPOCH_SECONDS",
                    help="Unix epoch seconds after which no new ES call starts (env "
                         "TL_KW_DEADLINE_AT as a fallback). A call that would start past "
                         "this emits the normal envelope with no results and "
                         "\"unresolved\": \"deadline\", and exits 0.")
    args = ap.parse_intermixed_args()
    kw_common.reject_option_like(ap, args.keywords)

    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    _ledger_started = time.monotonic()
    deadline = _resolve_deadline(args.deadline_at)

    def emit(obj):
        kw_common.emit(obj, run_dir=args.run_dir, script="search_videos",
                       argv=sys.argv[1:], started=_ledger_started)
    if not fields:
        sys.exit("--fields must list at least one ES field")

    def parse_group(raw):
        return [t.strip() for t in raw.split(",") if t.strip()]

    keywords = dedupe(collect_keywords(args.keywords))
    any_groups = [g for g in (parse_group(r) for r in args.any) if g]
    sqs_groups = [kw_common.phrase_if_plain(g) for g in args.group if g.strip()]
    group_fields, not_groups = {}, []
    if args.groups_file:
        loaded = kw_common.load_groups_file(args.groups_file)
        file_groups, file_default, file_operator = (
            loaded["groups"], loaded["default_content_fields"], loaded["operator"])
        if file_operator not in (None, "AND", "OR"):
            sys.exit(f"--groups-file: unknown operator {file_operator!r}")
        if args.operator is None:
            args.operator = file_operator or "OR"  # the file's operator, unless overridden
        elif file_operator and file_operator != args.operator:
            sys.stderr.write(f"--groups-file: file operator {file_operator} differs from "
                             f"explicit --operator {args.operator}; --operator governs this search\n")
        for g in file_groups:
            text = kw_common.phrase_if_plain(g["text"])
            per = g["content_fields"] or file_default
            if g["exclude"]:  # an excluded group keeps its own field scope
                not_groups.append({"text": text, "fields": per or fields})
                continue
            if per:
                group_fields[len(sqs_groups)] = per
            sqs_groups.append(text)
    if args.operator is None:
        args.operator = "OR"
    not_terms = dedupe([t for r in args.exclude for t in parse_group(r)])

    if not_groups and not sqs_groups:
        sys.exit("--groups-file holds only excluded groups; nothing to search")
    if sqs_groups and any_groups:
        sys.exit("--group and --any are different composition modes; use one or the other")

    if sqs_groups:
        if keywords:  # positional/stdin keywords become plain-phrase groups
            sqs_groups = [f'"{k}"' if " " in k else k for k in keywords] + sqs_groups
            group_fields = {i + len(keywords): f for i, f in group_fields.items()}
        body = build_groups(sqs_groups, not_terms, fields, args.since, args.until,
                            args.size, args.sort, args.distinct_channels,
                            args.operator, args.content_type, group_fields, not_groups)
        query_desc = {"mode": "groups", "operator": args.operator,
                      "groups": sqs_groups, "not": not_terms}
        expression = render_groups(sqs_groups, not_terms, args.operator)
        if not_groups or group_fields:
            query_desc["not_groups"] = [g["text"] for g in not_groups]
            query_desc["group_fields"] = {str(i): f for i, f in group_fields.items()}
            for g in not_groups:
                expression["expression"] += f" AND NOT ({g['text']})"
    elif any_groups:
        if keywords:
            any_groups = [keywords] + any_groups
        body = build_composed(any_groups, not_terms, fields, args.since, args.until,
                              args.size, args.sort, args.distinct_channels,
                              args.content_type)
        query_desc = {"mode": "composed", "any_groups": any_groups, "not": not_terms}
        expression = render_cnf(any_groups, not_terms)
    else:
        if not keywords:
            sys.exit("provide keywords (positional args / JSON array on stdin), --any groups, or --group")
        body = build_search(keywords, fields, args.operator, args.since, args.until,
                            args.size, args.sort, args.distinct_channels,
                            not_terms, args.content_type)
        query_desc = {"mode": "flat", "operator": args.operator, "keywords": keywords, "not": not_terms}
        pos_clauses = [keywords] if args.operator == "OR" else [[k] for k in keywords]
        expression = render_cnf(pos_clauses, not_terms)

    unresolved = None
    try:
        env = kw_common.run_es(body, deadline=deadline)

        videos = []
        for row in env.get("results", []):
            # Channel identity lives at the TOP level of every row (and is
            # mirrored under "channel") so nothing downstream has to dig.
            cid = _as_id(kw_common.get_path(row, "channel.id"))
            name = kw_common.get_path(row, "channel.channel_name")
            videos.append({
                "video_id": row.get("id") or row.get("_id"),
                "title": row.get("title"),
                "url": row.get("url"),
                "publication_date": row.get("publication_date"),
                "views": row.get("views"),
                "likes": row.get("likes"),
                "duration": row.get("duration"),
                "score": round(row.get("_score") or 0.0, 3) if row.get("_score") is not None else None,
                "channel_id": cid,
                "channel_name": name,
                "subscribers": None,
                "channel": {"channel_id": cid, "name": name, "subscribers": None},
            })

        if videos and not args.no_enrich:
            ids = sorted({v["channel_id"] for v in videos if v["channel_id"] is not None})
            if ids:
                meta = {_as_id(d.get("id")): d for d in
                        kw_common.run_es(build_enrich(ids), deadline=deadline).get("results", [])}
                for v in videos:
                    doc = meta.get(v["channel_id"], {})
                    v["channel_name"] = doc.get("name") or v["channel_name"]
                    v["subscribers"] = doc.get("reach")
                    v["channel"]["name"] = v["channel_name"]
                    v["channel"]["subscribers"] = v["subscribers"]
    except kw_common.EsError as exc:
        if exc.kind != "deadline":
            _fatal_es_error(exc)
        env, videos, unresolved = {}, [], "deadline"

    scope = {"format": "youtube", "content_type": args.content_type,
             "since": args.since, "until": args.until}
    out = {
        "query": query_desc,
        "expression": expression,
        "fields": args.fields,
        "scope": scope,
        "sort": args.sort,
        "distinct_channels": args.distinct_channels,
        "total_matching_videos": env.get("total", 0),
        "videos": videos,
    }
    if unresolved:
        out["unresolved"] = unresolved
    if args.sheet:
        _write_sheet(args.sheet, DEADLINE_SHEET if unresolved else render_sheet(out))
    emit(out)


# OUTPUT_SHAPE:
# {"query":{"mode":"flat"|"composed"|"groups", ...},
#  "expression":{"expression","clauses"|null[,"groups"]},
#  "fields","scope":{"format":"youtube","content_type":...,"since","until"},
#  "sort","distinct_channels","total_matching_videos",
#  "videos":[{"video_id","title","url","publication_date","views","likes","duration",
#             "score","channel_id","channel_name","subscribers",
#             "channel":{"channel_id","name","subscribers"}}, ...]}
# Channel identity is top-level on every row (channel_id / channel_name /
# subscribers) and mirrored under "channel" for older readers.
# subscribers is read from the LEGACY ES field `reach` (the index was
# not migrated in the big rename) and emitted under the new vocabulary.
# --sheet writes the same rows as one readable line each:
#   # Videos · date · youtube longform · 2025-09-19.. · 3120 matching · showing 25
#   - 2026-06-20 · 187K views · AI Explained (2105) · Fable 5 first look
# Sorting by date/views still applies the same topic filter; `score` is null
# when ES omits scoring under a non-score sort.
#
# Errors: an ES call that fails writes a message to stderr and exits non-zero.
# A call that would start past --deadline-at is NOT an error: the normal
# envelope is emitted with "videos": [] and "unresolved": "deadline", exit 0
# (a --sheet then holds one line, "deadline reached — not run"), so the
# && chain the skill runs these steps in survives a budget miss.
if __name__ == "__main__":
    main()
