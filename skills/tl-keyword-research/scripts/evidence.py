#!/usr/bin/env python3
"""One evidence call for a whole channel list — the sheet you judge from.

Runs the DELIVERED filter once per 100 channels (a `terms` filter on the
channel ids plus `collapse` on channel) and returns each channel's
best-matching upload with a highlight snippet from the field that matched, so
the orchestrating model can read compact evidence instead of paging documents.

`--per-channel 2` adds a second pass that excludes the first pass's videos —
a second data point for the channels whose first snippet did not settle it.
Channels the filter no longer reaches come back under `missing`, chunks that
errored under `failed`, and channels skipped for the deadline under
`unresolved`: nothing is silently dropped.

Usage:
    evidence.py --groups-file groups.json --channels-file intensity.json \
        --tiers core,recurring --max-channels 200 --sheet evidence.md > evidence.json
    evidence.py --group '"cannes lions"' --channels 12345,2345 --per-channel 2

Output (stdout): see OUTPUT_SHAPE at the bottom.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_common as kw  # noqa: E402

DEFAULT_FIELDS = "title,summary,transcript"
DEFAULT_CHUNK = 100
DEFAULT_MAX_CHANNELS = 200
DEFAULT_FRAGMENT_SIZE = 220
TITLE_LIMIT = 90
CACHE_DIR = os.path.join(kw.CACHE_ROOT, "evidence")
CACHE_TTL_HOURS = 24
TIER_ORDER = ["core", "recurring", "occasional", "one_off", "untiered"]
TIER_RANK = {t: i for i, t in enumerate(TIER_ORDER)}
# The highlight field we most want to show, in order. `title` is already on the
# line, so a title fragment is the last resort rather than the first.
FIELD_PREFERENCE = ("summary", "transcript", "title")
MARK_PRE, MARK_POST = "«", "»"
SOURCE = ["id", "title", "url", "publication_date", "channel.id", "channel.name"]


# ------------------------------------------------------------------ helpers

def cut(text, limit):
    """`text` trimmed to at most `limit` chars, on a word boundary when one is
    reasonably close to the end."""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    head = text[: max(1, limit - 1)]
    space = head.rfind(" ")
    if space > limit * 0.5:
        head = head[:space]
    return head.rstrip() + "…"


def tidy(fragment, limit):
    """A highlight fragment as it appears on the sheet: markers swapped for
    guillemets, entities decoded, whitespace collapsed, length capped."""
    text = kw.clean_text(fragment, keep_markers=True)
    text = text.replace(kw.HIGHLIGHT_PRE, MARK_PRE).replace(kw.HIGHLIGHT_POST, MARK_POST)
    return cut(text, limit)


def build_spec(args, fields):
    """The groups spec + rendered expression for whichever filter form was given."""
    if args.groups_file:
        spec = kw.load_groups_file(args.groups_file)
        if not spec["groups"]:
            raise kw.BatchError(f"--groups-file {args.groups_file}: no groups in the file")
        if not spec.get("default_content_fields"):
            spec["default_content_fields"] = list(fields)
    elif args.group:
        spec = {"groups": [{"text": g, "content_fields": None, "exclude": False}
                           for g in args.group],
                "operator": None, "default_content_fields": list(fields)}
    elif args.keywords:
        spec = {"groups": [{"text": kw.phrase_if_plain(k), "content_fields": None,
                            "exclude": False} for k in args.keywords],
                "operator": None, "default_content_fields": list(fields)}
    else:
        raise kw.BatchError("give a filter: --groups-file, one or more --group, or keywords")
    operator = (args.operator or spec.get("operator") or "OR").upper()
    positives = [g["text"] for g in spec["groups"] if not g["exclude"]]
    negatives = [g["text"] for g in spec["groups"] if g["exclude"]]
    expression = f" {operator} ".join(f"({g})" for g in positives)
    for text in negatives:
        expression += f" AND NOT ({text})"
    return spec, operator, {"expression": expression, "groups": positives,
                            "excludes": negatives, "operator": operator}


def select_channels(args):
    """The requested channels, in request order → `[{channel_id, name, tier, …}]`."""
    if args.channels_file:
        data = kw.read_json(args.channels_file, "channels file")
        rows = data.get("channels") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise kw.BatchError(f"--channels-file {args.channels_file}: no 'channels' list")
        wanted = {t.strip() for t in (args.tiers or "").split(",") if t.strip()}
        out = []
        for row in rows:
            if not isinstance(row, dict) or row.get("channel_id") is None:
                continue
            if wanted and (row.get("tier") or "untiered") not in wanted:
                continue
            picked = {"channel_id": row["channel_id"], "name": row.get("name"),
                      "tier": row.get("tier"),
                      "matching_uploads": row.get("matching_uploads"),
                      "recent_matching_uploads": row.get("recent_matching_uploads"),
                      "topic_share": row.get("topic_share")}
            if row.get("sponsorability") is not None:
                picked["sponsorability"] = row["sponsorability"]
            out.append(picked)
        return out[: args.max_channels]
    ids = []
    for part in (args.channels or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            raise kw.BatchError(f"--channels: {part!r} is not a channel id")
    if not ids:
        raise kw.BatchError("give channels: --channels 1,2,3 or --channels-file intensity.json")
    return [{"channel_id": i, "name": None, "tier": None, "matching_uploads": None,
             "recent_matching_uploads": None, "topic_share": None}
            for i in ids[: args.max_channels]]


def build_body(spec, operator, chunk, args, fields, exclude_video_ids=None):
    """One chunk's query: the delivered filter, pinned to these channels,
    collapsed to the single best upload per channel, with highlighting on."""
    bool_q = kw.groups_query(spec, operator=operator)
    # The groups ALONE decide what a snippet marks — a scope filter that
    # highlights turns `channel.format: 4` into "PlayStation «4»".
    highlight_query = {"bool": dict(bool_q)}
    bool_q["filter"] = kw.scope_filters(level="topic", content_type=args.content_type,
                                        since=args.since, until=args.until,
                                        channel_ids=chunk)
    if exclude_video_ids:
        bool_q.setdefault("must_not", [])
        bool_q["must_not"] = list(bool_q["must_not"]) + [
            {"terms": {"id": list(exclude_video_ids)}}]
    return {
        "size": len(chunk),
        "track_total_hits": False,
        "query": {"bool": bool_q},
        "collapse": {"field": "channel.id"},
        "sort": [{"_score": "desc"}],
        "_source": list(SOURCE),
        "highlight": kw.highlight_clause(fields, fragment_size=args.fragment_size,
                                         fragments=2, highlight_query=highlight_query),
    }


def evidence_item(row, literals, fragment_size):
    """One result row → the compact evidence entry, or None without an id."""
    src = kw.source_of(row)
    video_id = src.get("id") or row.get("_id")
    title = kw.clean_text(src.get("title") or "")
    field, snippet = None, None
    frags = kw.fragments_of(row)
    if frags:
        # The fragment carrying the most marked hits is the best evidence; ties
        # go to FIELD_PREFERENCE, then to the order ES returned them in.
        rank = {f: i for i, f in enumerate(FIELD_PREFERENCE)}
        best = min(enumerate(frags),
                   key=lambda pair: (-pair[1].get("hits", 0),
                                     rank.get(pair[1]["field"], len(FIELD_PREFERENCE)),
                                     pair[0]))[1]
        field, snippet = best["field"], best["text"]
    if field is None:
        field = "title"
        found = kw.windows(title, literals, window=max(20, fragment_size // 2),
                           max_snippets=1)
        snippet = found[0] if found else title
    date = str(src.get("publication_date") or "")[:10]
    return {"video_id": video_id, "title": cut(title, TITLE_LIMIT), "date": date,
            "url": src.get("url"), "field": field,
            "snippet": tidy(snippet, fragment_size)}


# -------------------------------------------------------------------- sheet

def _tier_counts(channels):
    counts = {}
    for ch in channels:
        counts[ch.get("tier") or "untiered"] = counts.get(ch.get("tier") or "untiered", 0) + 1
    return counts


def scope_line(scope):
    """`youtube longform · 2025-09-19..` — the window the evidence was drawn
    from, so a verdict is never judged against a wider corpus than intended."""
    line = f"{scope.get('format') or 'youtube'} {scope.get('content_type') or 'all'}"
    since, until = scope.get("since"), scope.get("until")
    if since or until:
        line += f" · {since or ''}..{until or ''}"
    return line


def render_sheet(out, topic):
    """The evidence sheet: one line per channel, grouped by tier."""
    fetched = [c for c in out["channels"] if c["evidence"]]
    counts = _tier_counts(fetched)
    parts = [f"{t} {counts[t]}" for t in TIER_ORDER if counts.get(t)]
    head = (f"# Evidence sheet · topic: {topic or '(none)'} · "
            f"{out['fetched']}/{out['requested']} channels")
    if parts:
        head += " (" + " · ".join(parts) + ")"
    head += (f" · {out['timing']['es_calls']} calls · "
             f"{out['timing']['elapsed_seconds']}s")
    lines = [head,
             f"scope: {scope_line(out.get('scope') or {})}",
             "one line per channel: id · name · matching uploads (recent) · "
             "topic share · [field] snippet (date · title)"]
    for tier in TIER_ORDER:
        group = [c for c in fetched if (c.get("tier") or "untiered") == tier]
        if not group:
            continue
        lines.append("")
        lines.append(f"## {tier}")
        for ch in group:
            bits = [str(ch["channel_id"]), ch.get("name") or "(unknown)"]
            if ch.get("matching_uploads") is not None:
                bits.append(f"{ch['matching_uploads']} up "
                            f"({ch.get('recent_matching_uploads') or 0} rec)")
            if ch.get("topic_share") is not None:
                bits.append(f"{round(ch['topic_share'] * 100)}%")
            first = ch["evidence"][0]
            bits.append(f"[{first['field']}] {first['snippet']} "
                        f"({first['date']} · {first['title']})")
            lines.append("- " + " · ".join(bits))
            for extra in ch["evidence"][1:]:
                lines.append(f"  + [{extra['field']}] {extra['snippet']} "
                             f"({extra['date']} · {extra['title']})")
    if out["missing"]:
        lines.append("")
        lines.append("## missing (no upload matches the filter): "
                     + ", ".join(str(i) for i in out["missing"]))
    if out["unresolved"]:
        lines.append("")
        lines.append("## unresolved (deadline reached): "
                     + ", ".join(str(i) for i in out["unresolved"]))
    if out.get("pass2_incomplete"):
        lines.append("")
        lines.append("## second upload not fetched: "
                     + ", ".join(str(i) for i in out["pass2_incomplete"]))
    for fail in out["failed"]:
        lines.append("")
        ids = ", ".join(str(i) for i in fail["channel_ids"])
        lines.append(f"## failed: chunk {fail['chunk_index']} "
                     f"({len(fail['channel_ids'])} ids: {ids}) — {fail['kind']}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------- main

def _deadline(raw):
    if raw is None:
        raw = os.environ.get("TL_KW_DEADLINE_AT")
    if raw in (None, ""):
        return kw.Deadline(None)
    try:
        return kw.Deadline(max(0, float(raw) - time.time()))
    except (TypeError, ValueError):
        return kw.Deadline(None)


def main():
    ap = argparse.ArgumentParser(
        description="One evidence call per 100 channels → a sheet you judge from.")
    ap.add_argument("keywords", nargs="*", help="Keywords (each phrased if plain) when no "
                                                "--groups-file/--group is given.")
    ap.add_argument("--groups-file", metavar="PATH", help="Boolean groups JSON (the delivered filter).")
    ap.add_argument("--group", action="append", metavar="SQS",
                    help="One boolean group (repeatable).")
    ap.add_argument("--operator", choices=["AND", "OR"],
                    help="How positive groups combine (default: the file's, else OR).")
    ap.add_argument("--fields", default=DEFAULT_FIELDS,
                    help=f"Highlighted fields, also the default group fields (default {DEFAULT_FIELDS}).")
    ap.add_argument("--channels", metavar="IDS", help="Comma-separated channel ids.")
    ap.add_argument("--channels-file", metavar="PATH",
                    help="search_channels.py --intensity output; channels come from its rows.")
    ap.add_argument("--tiers", metavar="LIST",
                    help="With --channels-file: keep only these tiers (default: all).")
    ap.add_argument("--max-channels", type=int, default=DEFAULT_MAX_CHANNELS,
                    help=f"Cap after the tier filter, in file order (default {DEFAULT_MAX_CHANNELS}).")
    ap.add_argument("--content-type", default="longform", choices=list(kw.CONTENT_TYPES))
    ap.add_argument("--since", metavar="YYYY-MM-DD")
    ap.add_argument("--until", metavar="YYYY-MM-DD")
    ap.add_argument("--per-channel", type=int, default=1, choices=[1, 2],
                    help="Uploads per channel; 2 runs a second pass excluding the first.")
    ap.add_argument("--chunk", type=int, default=DEFAULT_CHUNK,
                    help=f"Channels per ES call (default {DEFAULT_CHUNK}).")
    ap.add_argument("--fragment-size", type=int, default=DEFAULT_FRAGMENT_SIZE,
                    help=f"Snippet length in characters (default {DEFAULT_FRAGMENT_SIZE}).")
    ap.add_argument("--sheet", metavar="PATH", help="Also write the readable evidence sheet here.")
    ap.add_argument("--topic", metavar="TEXT", help="Echoed on the sheet header only.")
    ap.add_argument("--workers", type=int, default=kw.DEFAULT_WORKERS,
                    help=f"Concurrent ES calls (default {kw.DEFAULT_WORKERS}; 1 = sequential).")
    ap.add_argument("--cache-dir", default=CACHE_DIR,
                    help=f"Directory for the evidence response cache (default {CACHE_DIR}).")
    ap.add_argument("--cache-ttl-hours", type=float, default=CACHE_TTL_HOURS,
                    help=f"Serve an identical call from cache if younger than this (default {CACHE_TTL_HOURS}).")
    ap.add_argument("--no-cache", action="store_true", help="Always hit ES, and don't write the cache.")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: record this invocation (argv, elapsed, output) as one event file under DIR/events/")
    ap.add_argument("--deadline-at", metavar="EPOCH_SECONDS",
                    help="Stop starting calls at this epoch time (env TL_KW_DEADLINE_AT).")
    args = ap.parse_intermixed_args()
    kw.reject_option_like(ap, args.keywords)
    if args.workers < 1:
        sys.exit("--workers must be >= 1")
    if args.chunk < 1:
        sys.exit("--chunk must be >= 1")

    started = time.monotonic()
    fields = [f.strip() for f in args.fields.split(",") if f.strip()]
    try:
        spec, operator, expression = build_spec(args, fields)
        requested = select_channels(args)
    except kw.BatchError as exc:
        sys.exit(str(exc))

    literals = []
    for group in spec["groups"]:
        if group["exclude"]:
            continue
        for term in kw.literal_terms(group["text"]):
            if term not in literals:
                literals.append(term)

    deadline = _deadline(args.deadline_at)
    cache_dir = None if args.no_cache else args.cache_dir
    stats = {"es_calls": 0, "cache_hits": 0}
    ids = [c["channel_id"] for c in requested]

    def run_pass(groups_of_ids, excludes_by_chunk):
        """Run one pass over pre-chunked channel ids → (rows, failed, unresolved)."""
        def one(index):
            chunk = groups_of_ids[index]
            if deadline.expired:
                return {"index": index, "ids": chunk, "status": "unresolved", "kind": "deadline",
                        "reason": "deadline reached before the call started"}
            try:
                body = build_body(spec, operator, chunk, args, fields,
                                  exclude_video_ids=excludes_by_chunk[index])
                data, cached = kw.run_es_cached(body, cache_dir=cache_dir,
                                                ttl_hours=args.cache_ttl_hours,
                                                no_cache=args.no_cache, highlight=True,
                                                deadline=deadline)
            except kw.EsError as exc:
                status = "unresolved" if exc.kind == "deadline" else "failed"
                return {"index": index, "ids": chunk, "status": status,
                        "kind": exc.kind, "reason": str(exc)}
            except Exception as exc:  # noqa: BLE001 — the chunk fails, the batch does not
                # Anything else here is still THIS chunk's failure: returning it
                # with the chunk's ids keeps its channels out of `missing`,
                # which would otherwise read as "the filter no longer reaches
                # them" when in fact they were never asked about.
                return {"index": index, "ids": chunk, "status": "failed",
                        "kind": "error", "reason": str(exc)}
            return {"index": index, "ids": chunk, "status": "ok", "cached": cached,
                    "rows": kw.hits_of(data)}

        rows, failed, unresolved = [], [], []
        for result in kw.parallel_map(one, range(len(groups_of_ids)), workers=args.workers):
            if isinstance(result, Exception):  # parallel_map captures, never raises
                failed.append({"chunk_index": 0, "channel_ids": [], "kind": "error",
                               "reason": str(result)})
                continue
            if result["status"] == "ok":
                stats["cache_hits" if result["cached"] else "es_calls"] += 1
                rows.extend(result["rows"])
            elif result["status"] == "unresolved":
                unresolved.extend(result["ids"])
            else:
                failed.append({"chunk_index": result["index"], "channel_ids": result["ids"],
                               "kind": result["kind"], "reason": result["reason"]})
        return rows, failed, unresolved

    chunks = [ids[i:i + args.chunk] for i in range(0, len(ids), args.chunk)]
    rows, failed, unresolved = run_pass(chunks, [None] * len(chunks))
    pass2_incomplete = []

    found = {}
    for row in rows:
        cid = kw.get_path(kw.source_of(row), "channel.id")
        if cid is None:
            continue
        item = evidence_item(row, literals, args.fragment_size)
        found.setdefault(cid, {"items": [], "name": kw.get_path(kw.source_of(row), "channel.name")})
        found[cid]["items"].append(item)

    if args.per_channel > 1 and found:
        hit_ids = [i for i in ids if i in found]
        second = [hit_ids[i:i + args.chunk] for i in range(0, len(hit_ids), args.chunk)]
        excludes = [[it["video_id"] for cid in chunk for it in found[cid]["items"]
                     if it["video_id"] is not None] for chunk in second]
        rows2, failed2, unresolved2 = run_pass(second, excludes)
        # Pass 2 only ever asks for a SECOND upload from channels pass 1 already
        # answered for. A failure there costs one extra data point, not the
        # channel — folding it into failed/unresolved would retract evidence the
        # judge already has.
        incomplete = {i for f in failed2 for i in f["channel_ids"]} | set(unresolved2)
        pass2_incomplete = [i for i in ids if i in incomplete]
        for row in rows2:
            cid = kw.get_path(kw.source_of(row), "channel.id")
            if cid in found:
                found[cid]["items"].append(evidence_item(row, literals, args.fragment_size))

    failed_ids = {i for f in failed for i in f["channel_ids"]}
    unresolved_set = set(unresolved)
    channels, missing = [], []
    for row in requested:
        cid = row["channel_id"]
        hit = found.get(cid)
        out_row = dict(row)
        out_row["name"] = row.get("name") or (hit or {}).get("name")
        out_row["evidence"] = (hit or {}).get("items", [])
        channels.append(out_row)
        if not hit and cid not in failed_ids and cid not in unresolved_set:
            missing.append(cid)

    out = {
        "scope": {"format": "youtube", "content_type": args.content_type,
                  "since": args.since, "until": args.until},
        "fields": fields,
        "expression": expression,
        "requested": len(requested),
        "fetched": sum(1 for c in channels if c["evidence"]),
        "channels": channels,
        "missing": missing,
        "pass2_incomplete": pass2_incomplete,
        "failed": failed,
        "unresolved": [i for i in ids if i in unresolved_set],
        "timing": {"elapsed_seconds": round(time.monotonic() - started, 1),
                   "es_calls": stats["es_calls"], "cache_hits": stats["cache_hits"],
                   "workers": args.workers},
    }
    if args.sheet:
        try:
            with open(args.sheet, "w", encoding="utf-8") as fh:
                fh.write(render_sheet(out, args.topic))
        except OSError as exc:
            sys.exit(f"could not write --sheet {args.sheet}: {exc}")
    kw.emit(out, run_dir=args.run_dir, script="evidence", started=started)


# OUTPUT_SHAPE:
# {"scope":{"format","content_type","since","until"}, "fields":[...],
#  "expression":{"expression":"(a) OR (b) AND NOT (c)","groups":[...],"excludes":[...],"operator"},
#  "requested": n, "fetched": n,
#  "channels":[{"channel_id","name","tier","matching_uploads","recent_matching_uploads",
#               "topic_share","sponsorability":{...},                 # passed through from --channels-file
#               "evidence":[{"video_id","title","date","url","field","snippet"}, ...]}],
#  "missing":[ids with no upload under the filter],
#  "pass2_incomplete":[ids whose --per-channel 2 second upload was not fetched],
#  "failed":[{"chunk_index","channel_ids","kind","reason"}],
#  "unresolved":[ids skipped for the deadline],
#  "timing":{"elapsed_seconds","es_calls","cache_hits","workers"}}
# Channel order is request order. Snippets carry «» around what matched.
if __name__ == "__main__":
    main()
