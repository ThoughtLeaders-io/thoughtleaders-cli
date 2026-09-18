#!/usr/bin/env python3
"""Fetch keyword-in-context evidence for candidate channels (for Haiku validation).

For each channel, pulls its top-scoring matching videos and extracts the text
window around each keyword occurrence, so a cheap classifier can judge whether
the channel uses the keyword in the INTENDED sense (e.g. financial "investing"
vs. "sports investing" / "investing in your faith").

`transcript` is stored as YouTube caption XML
(`<?xml ...?><transcript><text start=".." dur="..">cue</text>...`), so tags are
stripped and entities unescaped before windowing — highlight fragments of it
would be full of markup anyway. `title` / `summary` are windowed as-is.

Usage:
    # the skill's path: the SAME filter the searches ran, batches for the classifier
    fetch_context.py --groups-file /tmp/kw_groups.json --channels-file intensity.json \
        --emit-batches --topic "…" --not "…" --out-dir /tmp/kwrun/ctx1
    # then spawn one keyword-context-classifier per batch (ALL IN ONE MESSAGE),
    # each gets only its batch path and writes its verdict_path; merge with
    # classify_channels.py --manifest /tmp/kwrun/ctx1
    fetch_context.py --retry-failed /tmp/kwrun/ctx1     # re-fetch only the channels that errored,
                                                        # with the run's saved query settings
    # ad-hoc: plain keywords, JSON array on stdout
    fetch_context.py --channels 466311,199308 investing
    fetch_context.py --channels 5607 --samples 5 --window 200 "tiktok shop"

Evidence is selected under the same scope as the searches (YouTube uploads,
content_type, dates) and, with --groups-file, the same boolean groups with
their per-group fields — so the classifier judges what the link will select.
Snippet windows anchor on the LITERAL terms of each group (quoted phrases and
positive bare words), never on the boolean expression itself.

Output (stdout, ad-hoc): a JSON array, one object per channel:
    [{"channel_id","match_count","sampled","snippets":[
        {"video_id","title","field","keyword","text"}, ...],
      "error": "…"}]     # only when that channel's fetch failed (snippets empty)
Output (stdout, --emit-batches): {"manifest","judge":"context","item_count",
    "batches":[{"batch_id","pass_id","kind","path","verdict_path","count"}],
    "failed_channels":[{"channel_id","error"}]}
"""
import argparse
import concurrent.futures
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_batches  # noqa: E402

_LEDGER = {"run_dir": None, "started": time.monotonic()}


def emit(obj, **kw):
    print(json.dumps(obj, ensure_ascii=False, **kw))
    kw_batches.record_event(_LEDGER["run_dir"], "fetch_context", sys.argv[1:], _LEDGER["started"], obj)

DEFAULT_FIELDS = ["title", "summary", "transcript"]
ES_TIMEOUT = 90
RETRY_PAUSE = 3  # seconds before the single retry of a transient tl db es failure
CONTEXT_WORKERS = 6  # concurrent per-channel ES calls
TRANSIENT_MARKERS = ("429", "502", "503", "504", "Rate limited", "Please wait and try again",
                     "Server error", "timed out", "timeout", "Too Many Requests")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
YOUTUBE_FORMAT = 4
CONTENT_TYPES = ("longform", "short", "live", "all")
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "tl-keyword-research", "context")
CACHE_TTL_HOURS = 24
# Mirror search_channels.py: an unstructured multi-word group is a phrase.
_STRUCTURAL_BOOL_RE = re.compile(r'[|()"]|(?:^|(?<=[\s(]))[+-](?=\S)')
_DETACHED_SIGN_RE = re.compile(r"(?:^|(?<=\s))[+-](?=\s|$)")
_SQS_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|[^\s()|"]+', re.UNICODE)
ARTICLE_FIELD_MAP = {"title": "title", "summary": "summary", "transcript": "transcript",
                     "content": "content", "hashtags": "hashtags"}
CHANNEL_ONLY_FIELDS = {"channel_description", "channel_description_ai",
                       "channel_topic_description", "channel.channel_name"}


class ContextError(Exception):
    """One channel's ES call failed; the batch continues without it."""


def run_es(body):
    """POST an ES body via `tl db es`; one retry on a transient failure."""
    proc = None
    for attempt in (1, 2):
        try:
            proc = subprocess.run(
                ["tl", "db", "es", "-", "--json"],
                input=json.dumps(body), capture_output=True, text=True, timeout=ES_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            if attempt == 1:
                time.sleep(RETRY_PAUSE)
                continue
            raise ContextError(f"timed out twice after {ES_TIMEOUT}s each")
        if proc.returncode == 0:
            break
        detail = (proc.stderr or proc.stdout).strip()
        if attempt == 1 and any(m in detail for m in TRANSIENT_MARKERS):
            time.sleep(RETRY_PAUSE)
            continue
        raise ContextError(f"tl db es failed (rc={proc.returncode}): {detail[:300]}")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ContextError(f"could not parse tl db es output: {exc}")


def clean_text(value):
    """Strip XML/HTML tags, unescape entities, collapse whitespace.

    Caption text is sometimes double-escaped (e.g. `&amp;#39;`), so a single
    unescape leaves `&#39;` behind — unescape to a fixed point.
    """
    if not isinstance(value, str):
        return ""
    text = TAG_RE.sub(" ", value)
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    return WS_RE.sub(" ", text).strip()


def windows(text, keyword, half, max_snips):
    """Up to `max_snips` non-overlapping ±`half`-char windows around `keyword`."""
    if not text or not keyword:
        return []
    hay, needle = text.lower(), keyword.lower()
    out, start, last_end = [], 0, -1
    while len(out) < max_snips:
        idx = hay.find(needle, start)
        if idx == -1:
            break
        lo, hi = max(0, idx - half), min(len(text), idx + len(keyword) + half)
        if lo <= last_end:  # overlaps previous window — skip ahead
            start = idx + len(keyword)
            continue
        snip = text[lo:hi].strip()
        out.append(("…" + snip if lo > 0 else snip) + ("…" if hi < len(text) else ""))
        last_end = hi
        start = hi
    return out


def phrase_if_plain(text):
    t = text.strip()
    if " " in t and not (_STRUCTURAL_BOOL_RE.search(t) or _DETACHED_SIGN_RE.search(t)):
        return f'"{t}"'
    return t


def literal_terms(group_text):
    """The literal anchors of a boolean group: quoted phrases and positive bare
    words. Anything negated — `-word`, `-"a phrase"`, `-(a | b)` and every
    token inside a negated group — is an excluded sense, never an anchor.
    Escaped quotes inside a phrase are decoded so the anchor matches plain
    text. Snippet windows are cut around these, so evidence never depends on
    the boolean expression itself."""
    terms, i, n = [], 0, len(group_text)
    depth, negated_depth, negate_next = 0, None, False
    while i < n:
        c = group_text[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-":
            negate_next = c == "-"  # the sign applies to the next token, phrase or group
            i += 1
            continue
        if c == "(":
            depth += 1
            if negate_next and negated_depth is None:
                negated_depth = depth
            negate_next = False
            i += 1
            continue
        if c == ")":
            if negated_depth == depth:
                negated_depth = None
            depth = max(0, depth - 1)
            negate_next = False
            i += 1
            continue
        if c == "|":
            negate_next = False
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and group_text[j] != '"':
                if group_text[j] == "\\" and j + 1 < n:
                    buf.append(group_text[j + 1])
                    j += 2
                    continue
                buf.append(group_text[j])
                j += 1
            tok, i = "".join(buf).strip(), j + 1
        else:
            j = i
            while j < n and not group_text[j].isspace() and group_text[j] not in '()|"':
                j += 1
            tok, i = group_text[i:j], j
        excluded = negate_next or negated_depth is not None
        negate_next = False
        if tok and not excluded and tok not in terms:
            terms.append(tok)
    return terms


def load_groups_file(path, default_fields):
    """build_report.py's groups shape → (include groups [{text, fields}], exclude groups, operator)."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"--groups-file {path}: {exc}")
    file_default, operator = None, None
    if isinstance(data, dict):
        file_default = data.get("default_content_fields") or None
        operator = (data.get("operator") or None)
        data = data.get("groups", [])
    if not isinstance(data, list):
        sys.exit(f"--groups-file {path}: expected a list of groups or an object with a 'groups' list")

    def es_fields(names):
        out = []
        for n in names:
            if n in CHANNEL_ONLY_FIELDS:
                sys.exit(f"content field {n!r} lives on channel docs; evidence is video-level")
            if n not in ARTICLE_FIELD_MAP:
                sys.exit(f"unknown content field {n!r} in groups file; known: {sorted(ARTICLE_FIELD_MAP)}")
            out.append(ARTICLE_FIELD_MAP[n])
        return out

    inc, exc = [], []
    for item in data:
        text = (item.get("text") if isinstance(item, dict) else item) or ""
        text = str(text).strip()
        if not text:
            continue
        cf = (item.get("content_fields") if isinstance(item, dict) else None) or file_default
        rec = {"text": phrase_if_plain(text), "fields": es_fields(cf) if cf else list(default_fields)}
        (exc if isinstance(item, dict) and item.get("exclude") else inc).append(rec)
    if not inc:
        sys.exit("--groups-file holds no positive groups; nothing to fetch evidence for")
    return inc, exc, (str(operator).upper() if operator else None)


def scope_filters(channel_id, content_type, since, until):
    filt = [{"term": {"doc_type": "article"}},
            {"term": {"channel.format": YOUTUBE_FORMAT}},
            {"term": {"channel.id": channel_id}}]
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


def build_query(channel_id, keywords, fields, operator, since, until, samples, content_type="longform"):
    """Ad-hoc mode: plain keyword phrases over `fields`."""
    clauses = [
        {"multi_match": {"query": kw, "type": "phrase", "fields": fields}}
        for kw in keywords
    ]
    bool_q = {"filter": scope_filters(channel_id, content_type, since, until)}
    if operator == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    return {
        "size": samples,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "sort": [{"_score": "desc"}],
        "_source": ["id"] + fields,
    }


def build_groups_query(channel_id, groups, not_groups, operator, since, until, samples, content_type):
    """Filter mode: the delivered boolean groups verbatim, per-group fields,
    excluded groups as must_not — the same clauses search_channels.py runs."""
    clauses = [{"simple_query_string": {"query": g["text"], "fields": g["fields"], "default_operator": "and"}}
               for g in groups]
    bool_q = {"filter": scope_filters(channel_id, content_type, since, until)}
    if operator == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    if not_groups:
        bool_q["must_not"] = [{"simple_query_string": {"query": g["text"], "fields": g["fields"],
                                                       "default_operator": "and"}} for g in not_groups]
    source_fields = sorted({f for g in groups for f in g["fields"]})
    return {
        "size": samples,
        "track_total_hits": True,
        "query": {"bool": bool_q},
        "sort": [{"_score": "desc"}],
        "_source": ["id"] + source_fields,
    }


def cache_key(body):
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


_NS = None


def cache_namespace():
    """Per authenticated identity (tl whoami) + endpoint, like probe.py's cache;
    None disables the cache for this run."""
    global _NS
    if _NS is None:
        _NS = False
        try:
            proc = subprocess.run(["tl", "whoami", "--json"], capture_output=True, text=True, timeout=ES_TIMEOUT)
            user = (json.loads(proc.stdout).get("user") or {}) if proc.returncode == 0 else {}
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
            user = {}
        ident = user.get("id") or user.get("email")
        if ident:
            _NS = hashlib.sha256(f"ctx1\n{os.environ.get('TL_API_URL', '')}\n{ident}".encode()).hexdigest()[:16]
    return _NS or None


def run_es_cached(body, cache_dir, ttl_hours):
    ns = cache_namespace() if cache_dir else None
    path = os.path.join(cache_dir, ns, cache_key(body) + ".json") if ns else None
    if path:
        try:
            if time.time() - os.path.getmtime(path) <= ttl_hours * 3600:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    env = run_es(body)
    if path:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            kw_batches.write_json_atomic(path, env)
        except OSError:
            pass
    return env


def channel_evidence(channel_id, keywords, fields, operator, since, until, samples, half, max_snips,
                     content_type="longform", groups=None, not_groups=None, cache_dir=None,
                     ttl_hours=CACHE_TTL_HOURS):
    if groups:
        body = build_groups_query(channel_id, groups, not_groups, operator, since, until, samples, content_type)
        fields = sorted({f for g in groups for f in g["fields"]})
        # Each literal anchors only in the fields ITS group searches — a
        # title-only group's terms never produce summary snippets.
        anchors = []
        for g in groups:
            for t in literal_terms(g["text"]):
                if all(t != a[0] for a in anchors):
                    anchors.append((t, set(g["fields"])))
                else:
                    next(a for a in anchors if a[0] == t)[1].update(g["fields"])
    else:
        body = build_query(channel_id, keywords, fields, operator, since, until, samples, content_type)
        anchors = [(kw, set(fields)) for kw in keywords]
    env = run_es_cached(body, cache_dir, ttl_hours)
    snippets = []
    for row in env.get("results", []):
        vid = row.get("id") or row.get("_id")
        title = clean_text(row.get("title")) or None
        per_video = 0
        for field in fields:
            if per_video >= max_snips:
                break
            text = clean_text(row.get(field))
            if not text:
                continue
            for kw, allowed in anchors:
                if field not in allowed:
                    continue
                for snip in windows(text, kw, half, max_snips - per_video):
                    snippets.append({"video_id": vid, "title": title, "field": field, "keyword": kw, "text": snip})
                    per_video += 1
                    if per_video >= max_snips:
                        break
                if per_video >= max_snips:
                    break
    return {
        "channel_id": channel_id,
        "match_count": env.get("total", 0),
        "sampled": len(env.get("results", [])),
        "snippets": snippets,
    }


def load_channels_file(path, tiers=None, max_channels=None):
    """Channel ids from a JSON file: a bare list of ids, or any search_channels.py
    output ({"channels":[{"channel_id":…}]}), so the intensity output feeds in
    directly. `tiers` keeps only rows whose `tier` is listed (bare ids have no
    tier and are kept); `max_channels` truncates after that, in file order."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"--channels-file {path}: {exc}")
    if isinstance(data, dict):
        data = data.get("channels", [])
    ids = []
    for item in data:
        if tiers and isinstance(item, dict) and item.get("tier") not in tiers:
            continue
        cid = item.get("channel_id") if isinstance(item, dict) else item
        try:
            ids.append(int(cid))
        except (TypeError, ValueError):
            sys.exit(f"--channels-file {path}: bad channel id {cid!r}")
    if max_channels is not None:
        ids = ids[:max_channels]
    return ids


VERDICT_REQUIRED = {"channel_id": int, "verdict": str}


def emit_context_batches(out, topic, not_topic, out_dir, chunk, max_bytes, extra):
    """Evidence snapshot + manifest + indexed classifier batches. Channels whose
    fetch failed are left OUT of the batches and listed in the summary."""
    out_dir = os.path.abspath(out_dir)
    if os.path.exists(kw_batches.manifest_path(out_dir)):
        sys.exit(f"{out_dir} already holds a judge run (manifest.json); use a fresh --out-dir — "
                 "re-emitting over existing verdict files would let stale verdicts pass as new ones")
    os.makedirs(out_dir, exist_ok=True)
    good = [o for o in out if not o.get("error")]
    failed = [{"channel_id": o["channel_id"], "error": o["error"]} for o in out if o.get("error")]
    items = [{"i": i, "channel_id": o["channel_id"], "snippets": o["snippets"]} for i, o in enumerate(good)]
    snapshot = os.path.join(out_dir, "evidence.snapshot.json")
    kw_batches.write_json_atomic(snapshot, {"channels": good, "failed": failed, **extra})
    ctx = {"topic": topic.strip()}
    if not_topic and not_topic.strip():
        ctx["not"] = not_topic.strip()
    m = kw_batches.new_manifest("context", ctx, [it["i"] for it in items], snapshot, out_dir)
    m["_dir"] = out_dir
    m["failed_channels"] = failed
    kw_batches.save_manifest(out_dir, m)
    recs = kw_batches.emit_batches(m, out_dir, {it["i"]: it for it in items}, [it["i"] for it in items],
                                   "p1", "initial", chunk, max_bytes) if items else []
    emit(kw_batches.summary(m, recs, {"failed_channels": failed}), indent=1)


def main():
    ap = argparse.ArgumentParser(description="Fetch keyword-in-context evidence per channel.")
    ap.add_argument("keywords", nargs="*", help="Keyword(s) to locate in context (ad-hoc mode)")
    ap.add_argument("--groups-file", metavar="PATH",
                    help="The delivered filter (build_report.py's groups shape): evidence is selected by "
                         "these boolean groups with their per-group fields; snippets anchor on their literals")
    ap.add_argument("--channels", help="Comma-separated channel ids")
    ap.add_argument("--channels-file", metavar="PATH",
                    help="JSON list of ids, or search_channels.py output (its 'channels' ids are used)")
    ap.add_argument("--tiers", metavar="T1,T2",
                    help="With --channels-file from --intensity: keep only these tiers "
                         "(e.g. core,recurring) — the budget decision, made before any fetch")
    ap.add_argument("--max-channels", type=int, metavar="N",
                    help="With --channels-file: at most N channels, in file order (biggest matchers first)")
    ap.add_argument("--operator", choices=["AND", "OR"], default=None,
                    help="How groups/keywords combine (default: the groups file's operator, else OR)")
    ap.add_argument("--content-type", choices=list(CONTENT_TYPES), default="longform",
                    help="Same scope as the searches (default longform; 'all' drops the filter)")
    ap.add_argument("--emit-batches", action="store_true",
                    help="Write evidence snapshot + manifest + classifier batch files to --out-dir")
    ap.add_argument("--topic", default="", help="TOPIC line for the classifier (with --emit-batches)")
    ap.add_argument("--not", dest="not_topic", default="", help="NOT line for the classifier (optional)")
    ap.add_argument("--out-dir", metavar="DIR")
    ap.add_argument("--chunk", type=int, default=kw_batches.DEFAULT_CHUNK,
                    help=f"Max channels per classifier batch (default {kw_batches.DEFAULT_CHUNK})")
    ap.add_argument("--max-batch-bytes", type=int, default=kw_batches.DEFAULT_MAX_BATCH_BYTES)
    ap.add_argument("--retry-failed", metavar="MANIFEST",
                    help="Re-fetch only the channels listed as failed in this manifest and append them "
                         "to its evidence as a new batch (same pass)")
    ap.add_argument("--cache-dir", default=CACHE_DIR)
    ap.add_argument("--cache-ttl-hours", type=float, default=CACHE_TTL_HOURS)
    ap.add_argument("--no-cache", action="store_true")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: record this invocation (argv, elapsed, output) as one event file under DIR/events/")
    ap.add_argument("--fields", default=",".join(DEFAULT_FIELDS),
                    help=f"Comma list of fields to search+extract (default: {','.join(DEFAULT_FIELDS)})")
    ap.add_argument("--samples", type=int, default=4, help="Videos sampled per channel (default 4)")
    ap.add_argument("--window", type=int, default=160, help="Context chars on each side of the keyword (default 160)")
    ap.add_argument("--max-snippets", type=int, default=3, help="Max snippets per video (default 3)")
    ap.add_argument("--since", help="publication_date >= YYYY-MM-DD")
    ap.add_argument("--until", help="publication_date <= YYYY-MM-DD")
    ap.add_argument("--workers", type=int, default=CONTEXT_WORKERS,
                    help=f"Concurrent per-channel ES calls (default {CONTEXT_WORKERS}; 1 = sequential).")
    args = ap.parse_args()
    _LEDGER["run_dir"] = args.run_dir
    if args.workers < 1:
        sys.exit("--workers must be >= 1")
    if args.chunk < 1:
        sys.exit("--chunk must be >= 1")
    cache_dir = None if args.no_cache else args.cache_dir

    manifest = None
    if args.retry_failed:
        # The retry must run the SAME query as the original fetch: restore every
        # setting from the evidence snapshot and ignore the CLI's fresh defaults.
        try:
            manifest = kw_batches.load_manifest(args.retry_failed)
        except kw_batches.BatchError as exc:
            sys.exit(str(exc))
        if manifest["kind"] != "context":
            sys.exit(f"{args.retry_failed} is not a context manifest")
        snap = kw_batches.snapshot_of(manifest)
        for key in ("groups_file", "keywords", "since", "until"):
            if getattr(args, key):
                sys.stderr.write(f"--retry-failed: --{key.replace('_', '-')} ignored; "
                                 "the run's saved query settings are used\n")
        groups, not_groups = snap.get("groups"), snap.get("not_groups")
        args.keywords = snap.get("keywords") or []
        fields = snap.get("fields") or [f.strip() for f in args.fields.split(",") if f.strip()]
        args.operator = snap.get("operator") or "OR"
        args.since, args.until = snap.get("since"), snap.get("until")
        args.content_type = (snap.get("scope") or {}).get("content_type", args.content_type)
        channel_ids = [f["channel_id"] for f in manifest.get("failed_channels", [])]
        if not channel_ids:
            emit({"manifest": kw_batches.manifest_path(manifest["_dir"]), "retried": 0})
            return
    else:
        fields = [f.strip() for f in args.fields.split(",") if f.strip()]
        if not fields:
            sys.exit("--fields must list at least one ES field")
        groups = not_groups = None
        if args.groups_file:
            groups, not_groups, file_op = load_groups_file(args.groups_file, fields)
            if args.operator is None:
                args.operator = file_op or "OR"
        elif not args.keywords:
            sys.exit("provide keywords, or --groups-file with the delivered filter")
        args.operator = args.operator or "OR"
        channel_ids = []
        if args.channels:
            try:
                channel_ids += [int(c) for c in args.channels.split(",") if c.strip()]
            except ValueError:
                sys.exit("--channels must be comma-separated integer channel ids")
        if args.channels_file:
            tiers = [t.strip() for t in args.tiers.split(",") if t.strip()] if args.tiers else None
            channel_ids += load_channels_file(args.channels_file, tiers, args.max_channels)
        channel_ids = list(dict.fromkeys(channel_ids))
        if not channel_ids:
            sys.exit("provide channel ids via --channels and/or --channels-file")
    if args.emit_batches and not (args.out_dir and args.topic.strip()):
        sys.exit("--emit-batches needs --out-dir and --topic")

    def one(cid):
        try:
            return channel_evidence(cid, args.keywords, fields, args.operator,
                                    args.since, args.until, args.samples, args.window, args.max_snippets,
                                    args.content_type, groups, not_groups, cache_dir, args.cache_ttl_hours)
        except ContextError as exc:
            sys.stderr.write(f"context fetch failed for channel {cid}: {exc}\n")
            return {"channel_id": cid, "match_count": 0, "sampled": 0, "snippets": [], "error": str(exc)}

    if cache_dir and cache_namespace() is None:
        sys.stderr.write("context cache disabled: could not establish the tl identity (tl whoami failed)\n")
        cache_dir = None
    # One ES call per channel, `--workers` at a time; output keeps input order.
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.workers, len(channel_ids))) as pool:
        out = list(pool.map(one, channel_ids))

    if manifest is not None:  # --retry-failed: append successes as a new batch of the same pass
        snap = kw_batches.snapshot_of(manifest)
        good = [o for o in out if not o.get("error")]
        still_failed = [{"channel_id": o["channel_id"], "error": o["error"]} for o in out if o.get("error")]
        start = max(manifest["item_ids"], default=-1) + 1
        items = [{"i": start + n, "channel_id": o["channel_id"], "snippets": o["snippets"]}
                 for n, o in enumerate(good)]
        snap["channels"] = snap.get("channels", []) + good
        snap["failed"] = still_failed
        kw_batches.write_json_atomic(os.path.join(manifest["_dir"], manifest["snapshot"]), snap)
        manifest["item_ids"] = sorted(manifest["item_ids"] + [it["i"] for it in items])
        manifest["failed_channels"] = still_failed
        pid = manifest["passes"][0] if manifest["passes"] else "p1"
        recs = kw_batches.emit_batches(manifest, manifest["_dir"], {it["i"]: it for it in items},
                                       [it["i"] for it in items], pid, "initial",
                                       args.chunk, args.max_batch_bytes) if items else []
        kw_batches.save_manifest(manifest["_dir"], manifest)
        emit(kw_batches.summary(manifest, recs, {"retried": len(out), "failed_channels": still_failed}), indent=1)
        return

    if args.emit_batches:
        extra = {"scope": {"format": "youtube", "content_type": args.content_type},
                 "operator": args.operator, "groups": groups, "not_groups": not_groups,
                 "keywords": args.keywords, "fields": fields, "since": args.since, "until": args.until}
        emit_context_batches(out, args.topic, args.not_topic, args.out_dir, args.chunk, args.max_batch_bytes, extra)
        return
    emit(out)


if __name__ == "__main__":
    main()
