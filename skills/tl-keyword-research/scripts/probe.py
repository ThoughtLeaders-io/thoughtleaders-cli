#!/usr/bin/env python3
"""Probe ES for keyword counts, where the matches live, and match-centred samples.

For each candidate ONE call returns the document total, the distinct-channel
count, the `strata` breakdown (how many documents match in the title, in the
summary only, in the transcript only) and up to N highlighted sample documents
collapsed to distinct channels. A second wave adds transcript-only samples for
candidates whose matches hide in the transcript, plus the residual / exclusion
measurements when they are asked for, and every candidate carries code-computed
`signals` (annotations, never drops).

The JSON on stdout feeds `select_keywords.py` and the downstream scripts;
`--sheet PATH` writes the same evidence as a compact markdown sample sheet —
that is what the orchestrating model reads.

Usage:
    probe.py "tiktok shop" "tiktok affiliate" --sheet /tmp/run/sheet1.md
    probe.py --level channel "cooking" "baking"
    probe.py --mode sqs '("mythos 5" | mythos5) -keto'
    probe.py --groups-file $RUN/groups3.json --sheet /tmp/run/sheet3.md
    echo '["crypto","bitcoin"]' | probe.py

Output (stdout): a single JSON object — see OUTPUT CONTRACT at the bottom.
"""
import argparse
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_common  # noqa: E402
from kw_common import (  # noqa: E402
    CHANNEL_FIELDS,
    COLLAPSE_FIELD,
    CONTENT_TYPES,
    HIGHLIGHT_POST,
    HIGHLIGHT_PRE,
    TOPIC_FIELDS,
    Deadline,
    EsError,
    agg_root,
    clean_text,
    emit,
    extract_total,
    fragments_of,
    get_path,
    highlight_clause,
    hits_of,
    literal_terms,
    load_groups_file,
    months_ago_iso,
    parallel_map,
    reject_option_like,
    required_is_alternation,
    required_terms,
    run_es_cached,
    scope_filters,
    source_of,
    stdin_is_readable,
    valid_date,
    windows,
)

# Sample `_source` per level. Topic samples carry identity + provenance only —
# the readable evidence is the highlight fragment, not a slab of summary text.
TOPIC_SOURCE = ["id", "title", "url", "publication_date", "channel.id", "channel.content_category"]
CHANNEL_SOURCE = ["id", "name", "ai.topic_descriptions", "ai.description"]

DEFAULT_CONTENT_TYPE = "longform"
DEFAULT_SAMPLES = 3
MAX_SAMPLES = 25
SNIPPET_CHARS = 220       # one fragment, cut on a word boundary
SHEET_TITLE_CHARS = 90    # a title-stratum snippet on the sheet
SHEET_TOPIC_CHARS = 160   # a channel's topic text on the sheet
MAX_TOPIC_TEXT = 300      # channel topic text kept in the JSON

PROBE_WORKERS = kw_common.DEFAULT_WORKERS
CACHE_DIR = os.path.join(kw_common.CACHE_ROOT, "probe")
CACHE_TTL_HOURS = 24  # a probe body re-run within this window is served from disk

# The order `stratum` is decided in (first field that highlighted wins) and the
# order a SNIPPET is picked in (the title is already printed, so prefer the rest).
STRATUM_ORDER = ["title", "summary", "transcript"]
# The buckets the standard field set produces — the sheet prints these three
# unlabelled and names anything else.
STANDARD_STRATA = ("title", "summary_only", "transcript_only")
SNIPPET_ORDER = ["summary", "transcript", "title"]
SIGNAL_ORDER = ["empty", "subsumed", "transcript_led", "transcript_dropped", "stale", "thin",
                "redundant", "too_broad", "over_cut", "blocked"]

TRANSCRIPT_DROPPED_NOTE = ("transcript dropped after a 20s timeout; "
                           "counts exclude transcript-only matches")

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_FIELD_RE = re.compile(r"^[\w.]+(\^\d+(\.\d+)?)?$")  # e.g. title, ai.description, title^3
# simple_query_string operators: | + ( ) * ~, and a leading `-` that starts a term
# (at the start of the string or after whitespace, immediately followed by a
# non-space char). A `-` inside a word (`e-commerce`) does not match.
_SQS_OPERATOR_RE = re.compile(r'[|+()*~]|(?:(?<=\s)|^)-(?=\S)')
_MARKED_RE = re.compile(re.escape(HIGHLIGHT_PRE) + r"(.*?)" + re.escape(HIGHLIGHT_POST), re.S)


def tokens(text):
    """Lowercased word tokens — used for lexical subsumption detection."""
    return _TOKEN_RE.findall(text.lower())


def is_contiguous_sublist(needle, haystack):
    """True if `needle` token list appears as a contiguous run inside `haystack`."""
    n, h = len(needle), len(haystack)
    if n == 0 or n >= h:
        return False
    return any(haystack[i:i + n] == needle for i in range(h - n + 1))


def base_field(name):
    """`title^3` -> `title` — the field path without its boost."""
    return str(name).split("^", 1)[0]


def sqs_clause(text, fields):
    """One `simple_query_string` clause over `fields` (in-group `-term` stays safe)."""
    return {"simple_query_string": {"query": text, "fields": list(fields),
                                    "default_operator": "and"}}


def match_clause(candidate, fields):
    """The candidate's own query form, restricted to `fields`.

    `mode="groups"` is the synthetic union candidate: several groups OR'd, each
    over its OWN fields. Restricting it to `fields` keeps only the groups that
    search one of them, so the strata agg can measure the union field by field.
    """
    if candidate["mode"] == "groups":
        wanted = {base_field(f) for f in fields}
        shoulds = [sqs_clause(g["text"], [f for f in g["fields"] if base_field(f) in wanted])
                   for g in candidate["groups"]
                   if any(base_field(f) in wanted for f in g["fields"])]
        if not shoulds:
            return {"bool": {"must_not": [{"match_all": {}}]}}  # this field carries no group
        return {"bool": {"should": shoulds, "minimum_should_match": 1}}
    if candidate["mode"] == "sqs":
        return sqs_clause(candidate["value"], fields)
    return {"multi_match": {"query": candidate["value"], "type": "phrase", "fields": list(fields)}}


def candidate_fields(candidate, fields):
    """The fields a candidate is searched on — its own when it carries them."""
    return list(candidate.get("fields") or fields)


def own_query(candidate):
    """True when a candidate carries its own fields/excludes and so cannot be
    re-expressed as one sqs string (every `--groups-file` candidate)."""
    return bool(candidate.get("fields") or candidate.get("must_not")
                or candidate.get("mode") == "groups")


def probed_text_fields(fields):
    """The text fields actually being probed: the standard article fields in
    title→transcript order first, then any other field the caller asked for."""
    bases = []
    for field in fields:
        name = base_field(field)
        if name not in bases:
            bases.append(name)
    return ([f for f in TOPIC_FIELDS if f in bases]
            + [f for f in bases if f not in TOPIC_FIELDS])


def remainder_fields(fields):
    """The probed fields whose bucket is SUBTRACTED rather than measured.

    `transcript` is one: a boolean clause over it is the slow half of any of
    these queries. So is any field outside the standard article three — a probe
    of `--fields title,hashtags` still has to account for the documents that
    matched only `hashtags`, and the total minus the measured buckets gives them
    for free.
    """
    return [f for f in probed_text_fields(fields)
            if f == "transcript" or f not in TOPIC_FIELDS]


def measured_field_names(fields):
    """The probed fields the strata agg asks about directly."""
    remainder = set(remainder_fields(fields))
    return [f for f in probed_text_fields(fields) if f not in remainder]


def stratum_name(field):
    """`title` stays `title` (it is measured first, so it is not an "only");
    every other measured field is the `<field>_only` bucket."""
    return "title" if field == "title" else f"{field}_only"


def remainder_bucket_name(fields):
    """The name of the subtracted bucket: `transcript_only` for the standard
    three, else the remaining fields joined (`--fields title,hashtags` →
    `hashtags_only`). None when every probed field is measured."""
    remainder = remainder_fields(fields)
    if not remainder:
        return None
    return "_".join(f.replace(".", "_") for f in remainder) + "_only"


def strata_names(level, fields):
    """The strata buckets a probe of `fields` can report — topic level only."""
    if level != "topic":
        return []
    names = [stratum_name(f) for f in measured_field_names(fields)]
    remainder = remainder_bucket_name(fields)
    if remainder:
        names.append(remainder)
    return names


def measured_strata_names(names, remainder="transcript_only"):
    """The strata the agg actually asks for — everything but the remainder
    (`transcript_only` for the standard field set; see remainder_bucket_name)."""
    return [n for n in names if n != remainder]


def strata_agg(candidate, fields):
    """A `filters` agg splitting the matches by WHERE they matched.

    `title` = matches in the title; `summary_only` = matches the summary but not
    the title. The strata are mutually exclusive, so `transcript_only` is the
    remainder (documents − title − summary_only) and is computed locally: a
    transcript clause is the slow half of any of these queries, and one inside
    the agg can push a borderline probe past its timeout for a number we can
    subtract for free.
    """
    present = measured_field_names(fields)
    if not present:
        return None
    buckets = {}
    for idx, field in enumerate(present):
        name = stratum_name(field)
        clause = {"bool": {"must": [match_clause(candidate, [field])]}}
        earlier = present[:idx]
        if earlier:
            clause["bool"]["must_not"] = [match_clause(candidate, [e]) for e in earlier]
        buckets[name] = clause
    return {"filters": {"filters": buckets}}


def build_body(candidate, *, fields, level, samples, source_paths, since=None, until=None,
               recency_cutoff=None, content_type="longform", strata=False,
               highlight_fields=None, must_not=None):
    """One ES body: counts + optional strata + optional highlighted samples.

    Always scoped to YouTube uploads, and at topic level to `content_type` and
    any date window. `collapse` keeps samples on distinct channels so one
    prolific channel cannot flood them; `distinct_channels` counts the channels
    the candidate actually reaches. When recency is on, an extra agg measures
    active content WITHOUT re-scoping the query (a date window at topic level,
    a posting-frequency window at channel level).
    """
    own = candidate.get("fields")
    if own:
        # A `--groups-file` group carries its own content_fields: they decide the
        # query, the strata agg AND what the highlighter is allowed to mark.
        fields = list(own)
        if highlight_fields:
            highlight_fields = [base_field(f) for f in own]
    collapse_field = COLLAPSE_FIELD[level]
    matched = match_clause(candidate, fields)
    query = {"bool": {"filter": scope_filters(level=level, content_type=content_type,
                                              since=since, until=until),
                      "must": [matched]}}
    if must_not:
        query["bool"]["must_not"] = list(must_not)
    aggs = {"distinct_channels": {"cardinality": {"field": collapse_field}}}
    if level == "topic" and recency_cutoff:
        aggs["recent_window"] = {
            "filter": {"range": {"publication_date": {"gte": recency_cutoff}}},
            "aggs": {"recent_channels": {"cardinality": {"field": collapse_field}}},
        }
    elif level == "channel" and recency_cutoff:
        # channel docs carry no date; "posting in the last 90 days" is the
        # liveness proxy. recency_cutoff is a sentinel here ("active"), not a date.
        aggs["active_window"] = {
            "filter": {"range": {"posts_per_90_days": {"gt": 0}}},
            "aggs": {"active_channels": {"cardinality": {"field": collapse_field}}},
        }
    if strata and level == "topic":
        agg = strata_agg(candidate, fields)
        if agg:
            aggs["strata"] = agg
    body = {
        "size": samples,
        "track_total_hits": True,
        "_source": list(source_paths),
        "collapse": {"field": collapse_field},
        "aggs": aggs,
        "query": query,
    }
    if highlight_fields:
        # Highlight the candidate's OWN clause, not the whole query: the scope
        # filters must never decide what a snippet marks.
        body["highlight"] = highlight_clause(highlight_fields, fragment_size=SNIPPET_CHARS,
                                             fragments=1, highlight_query=matched)
    return body


def mentions_transcript(obj):
    """True when an ES body references the `transcript` field anywhere."""
    if isinstance(obj, dict):
        return any(k == "transcript" or mentions_transcript(v) for k, v in obj.items())
    if isinstance(obj, list):
        return any(mentions_transcript(v) for v in obj)
    return isinstance(obj, str) and base_field(obj) == "transcript"


def without_transcript(obj):
    """A copy of `obj` with every `transcript` field reference removed."""
    if isinstance(obj, dict):
        out = {}
        for key, val in obj.items():
            if key in ("transcript", "transcript_only"):
                continue
            if key == "fields" and isinstance(val, list):
                out[key] = [f for f in val if base_field(f) != "transcript"]
                continue
            out[key] = without_transcript(val)
        return out
    if isinstance(obj, list):
        return [without_transcript(v) for v in obj]
    return obj


def _has_empty_fields(obj):
    if isinstance(obj, dict):
        if "fields" in obj and not obj["fields"]:
            return True
        return any(_has_empty_fields(v) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_empty_fields(v) for v in obj)
    return False


def drop_transcript(body):
    """The same body aimed at the remaining fields, or None when there isn't one.

    None means the body either never touched the transcript or asks only about
    it (the transcript-only sample query), so a reduced re-run would answer a
    different question.
    """
    if not mentions_transcript(body):
        return None
    reduced = without_transcript(body)
    return None if _has_empty_fields(reduced) else reduced


def note_transcript_dropped(row, fields):
    """Record that this candidate's numbers came from a transcript-free retry.

    `fields` are the CANDIDATE's own fields, not the run's: a field-narrowed
    group that only ever searched `title,transcript` did not fall back to the
    run's `title,summary`.
    """
    row["transcript_dropped"] = True
    row["fields_used"] = [base_field(f) for f in fields if base_field(f) != "transcript"]
    row["note"] = TRANSCRIPT_DROPPED_NOTE


def extract_distinct(data):
    """Read the `distinct_channels` cardinality agg (distinct channels reached).

    Cardinality is HyperLogLog++ — approximate, but exact at the low counts that
    matter for a niche check. 0 when the agg is absent."""
    dc = agg_root(data).get("distinct_channels")
    if isinstance(dc, dict) and isinstance(dc.get("value"), (int, float)):
        return int(dc["value"])
    return 0


def extract_recent(data):
    """Topic-level recency: (recent_documents, recent_channels). (0, 0) when absent."""
    rw = agg_root(data).get("recent_window")
    if not isinstance(rw, dict):
        return 0, 0
    docs = rw.get("doc_count", 0) or 0
    rc = rw.get("recent_channels", {})
    chans = rc.get("value", 0) if isinstance(rc, dict) else 0
    return int(docs), int(chans or 0)


def extract_active(data):
    """Channel-level recency: distinct channels posting in the last 90 days. 0 when absent."""
    aw = agg_root(data).get("active_window")
    if not isinstance(aw, dict):
        return 0
    ac = aw.get("active_channels", {})
    return int(ac.get("value", 0) or 0) if isinstance(ac, dict) else 0


def extract_strata(data, names):
    """Document counts per requested stratum bucket; 0 for anything missing."""
    buckets = (agg_root(data).get("strata") or {}).get("buckets")
    got = buckets if isinstance(buckets, dict) else {}
    return {n: int((got.get(n) or {}).get("doc_count", 0) or 0) for n in names}


def cut(text, limit):
    """Trim to `limit` characters on a word boundary, ellipsis included."""
    t = (text or "").strip()
    if len(t) <= limit:
        return t
    head = t[:max(1, limit - 1)]
    space = head.rfind(" ")
    if space > 0:
        head = head[:space]
    return head.rstrip(" ,.;:-") + "…"


def to_snippet(text, limit=SNIPPET_CHARS):
    """One highlight fragment as readable evidence: «» around the match, cut."""
    clean = clean_text(str(text or ""), keep_markers=True)
    return cut(clean.replace(HIGHLIGHT_PRE, "«").replace(HIGHLIGHT_POST, "»"), limit)


def marked_required(text, required, required_any=False):
    """How many DISTINCT required terms the fragment actually marked.

    A fragment that marks only the alternative a clause happened to fire on
    (`croisette +(advertising|marketing)` showing just «marketing») is not
    evidence for the candidate; one that marks the anchor is. Marked spans are
    joined before matching so a phrase split across two marks still counts.

    `required_any` says the terms are ALTERNATIVES (a top-level `|`, e.g.
    `"cannes lions" | canneslions`): a match carries one of them, so the score
    saturates at 1 and a longer alternative never outranks a shorter one.
    """
    if not required:
        return 0
    marks = " ".join(m.group(1).lower() for m in _MARKED_RE.finditer(text or ""))
    hits = sum(1 for term in required if term and term.lower() in marks)
    return min(1, hits) if required_any else hits


def pick_fragment(frags, required=None, required_any=False):
    """(stratum, field, text) from a row's fragments.

    The stratum is the first field that highlighted (title first). The SNIPPET
    is ranked by how many of the candidate's REQUIRED terms it marks (see
    kw_common.required_terms), then by total marked hits — a group whose anchor
    lands in the transcript should show the transcript, not the one alternative
    that also appears in the summary. Ties go to `SNIPPET_ORDER` (the title is
    printed anyway), then to the order `fragments_of` returned. Channel-level
    fields (name, description, ai.*) are not strata fields, so they sort last
    and keep their original order.
    """
    if not frags:
        return None, None, None
    seen = []
    for frag in frags:
        if frag["field"] not in seen:
            seen.append(frag["field"])
    stratum = next((f for f in STRATUM_ORDER if f in seen), None)
    rank = {f: i for i, f in enumerate(SNIPPET_ORDER)}
    best = min(enumerate(frags),
               key=lambda pair: (-marked_required(pair[1].get("text"), required, required_any),
                                 -pair[1].get("hits", 0),
                                 rank.get(pair[1]["field"], len(SNIPPET_ORDER)),
                                 pair[0]))[1]
    return stratum, best["field"], best["text"]


def sample_from_row(row, *, level, terms, force_stratum=None, required=None,
                    required_any=False):
    """One result row → the sample shape the sheet and the next script read."""
    src = source_of(row)
    stratum, field, text = pick_fragment(fragments_of(row), required, required_any)
    if level == "channel":
        snippet = to_snippet(text) if text else ""
        return {"channel_id": get_path(src, "id"),
                "name": clean_text(str(get_path(src, "name") or "")),
                "topic": cut(clean_text(str(get_path(src, "ai.topic_descriptions") or "")),
                             MAX_TOPIC_TEXT),
                "field": field, "snippet": snippet}
    title = clean_text(str(src.get("title") or ""))
    if text is None:
        # No fragments (no --highlight, or the match is not in a stored field):
        # fall back to a local KWIC window over the title.
        local = windows(title, terms, window=100, max_snippets=1)
        stratum, field, text = "title", "title", (local[0] if local else title)
    date = str(src.get("publication_date") or "")[:10]
    return {
        "video_id": get_path(src, "id"),
        "channel_id": get_path(src, "channel.id"),
        "title": title,
        "date": date,
        "url": src.get("url"),
        "category": get_path(src, "channel.content_category"),
        "stratum": force_stratum or stratum or "title",
        "field": field,
        "snippet": to_snippet(text),
    }


def samples_of(data, *, level, terms, force_stratum=None, required=None,
               required_any=False):
    return [sample_from_row(row, level=level, terms=terms, force_stratum=force_stratum,
                            required=required, required_any=required_any)
            for row in hits_of(data)]


def required_of(candidate):
    """The candidate's required terms — a phrase candidate is its own anchor, and
    the synthetic union requires nothing in particular (any group satisfies it)."""
    if candidate.get("mode") == "phrase":
        return [candidate["value"]]
    if candidate.get("mode") == "groups":
        return []
    return required_terms(candidate["value"])


def required_any_of(candidate):
    """True when the candidate's required terms are alternatives, not conjuncts
    (a top-level unparenthesised `|`) — see marked_required."""
    if candidate.get("mode") in ("phrase", "groups"):
        return False
    return required_is_alternation(candidate["value"])


def collect_candidates(argv_words):
    """Read candidates from argv (preferred) or stdin (JSON array / newlines).

    argv and stdin are not merged — if argv is non-empty, stdin is ignored.
    """
    if argv_words:
        return [w for w in argv_words if w.strip()]
    if not stdin_is_readable():
        return []
    raw = sys.stdin.read().strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if isinstance(parsed, list):
        return parsed
    sys.exit("stdin JSON must be a list")


def looks_like_sqs(value):
    """True if `value` contains a simple_query_string operator (see _SQS_OPERATOR_RE)."""
    return bool(_SQS_OPERATOR_RE.search(value))


def normalize(raw_items, default_mode, deduped=None):
    """Turn raw argv/stdin items into {label, value, mode} dicts, deduped.

    A plain string candidate (or a `{"value": …}` / `{"keyword": …}` item with no
    explicit `mode`) that contains a simple_query_string operator is auto-promoted
    to `mode="sqs"` regardless of `--mode`, so a boolean group like
    `cannes +lions +(advertising | agency) -"film festival"` is probed as a boolean
    query without needing `--mode sqs`. An explicit `sqs`/`phrase` key or an
    explicit `mode` field is never overridden. `--mode sqs` still forces sqs for
    every plain candidate anyway.
    """
    out, seen = [], {}
    for item in raw_items:
        explicit_mode = False
        if isinstance(item, dict):
            if "sqs" in item:
                value, mode = item["sqs"], "sqs"
                explicit_mode = True
            elif "phrase" in item:
                value, mode = item["phrase"], "phrase"
                explicit_mode = True
            elif "value" in item:
                value, mode = item["value"], item.get("mode", default_mode)
                explicit_mode = "mode" in item
            elif "keyword" in item:
                value, mode = item["keyword"], item.get("mode", default_mode)
                explicit_mode = "mode" in item
            else:
                sys.exit(f"candidate object missing value/sqs/phrase/keyword: {item}")
            value = str(value).strip()
            label = str(item.get("label", value)).strip() or value
        else:
            value = str(item).strip()
            label = value
            mode = default_mode
        if not value:
            continue
        if not explicit_mode and mode != "sqs" and looks_like_sqs(value):
            mode = "sqs"
        key = (mode, value.lower())
        if key in seen:
            # A case-only duplicate is dropped, not searched twice — but a
            # caller who wrote both spellings gets told which one survived.
            if deduped is not None and value != seen[key]:
                deduped.append({"keyword": value, "kept_as": seen[key]})
            continue
        seen[key] = value
        out.append({"label": label, "value": value, "mode": mode})
    return out


def mark_subsumed(results, operator):
    """Annotate each candidate with the broader phrases that subsume it (info only).

    A *phrase* candidate A is subsumed by phrase candidate B when B's tokens are
    a contiguous run inside A's tokens — every doc matching phrase A also matches
    phrase B, so A adds ~0 new documents to an OR union *that keeps B*. We record
    this (`subsumed_by` = broader present phrases, shortest first); we do NOT drop
    A. Union-redundancy pruning runs AFTER intent validation, otherwise the
    broadest term always wins the union and the precise term gets dropped.
    """
    if operator != "OR":
        return
    phrase = [r for r in results if r["_mode"] == "phrase" and r["count"] > 0]
    tok = {r["keyword"]: tokens(r["keyword"]) for r in phrase}
    for a in phrase:
        broader = [b for b in phrase
                   if b is not a and is_contiguous_sublist(tok[b["keyword"]], tok[a["keyword"]])]
        broader.sort(key=lambda b: len(tok[b["keyword"]]))
        a["subsumed_by"] = [b["keyword"] for b in broader]


def annotate_recency(row, data, *, level, min_recent_channels, min_share):
    """Layer recency / active-content fields + a `stale` flag onto a result row.

    Headline `count` / `channels` stay all-time. Stale is ABSOLUTE-FIRST: a keyword
    is stale only when BOTH its recent (topic) / active (channel) distinct-channel
    count is below the floor AND its share of all-time channels is below the
    threshold — so a high-volume evergreen term (large recent reach, small share)
    is never mislabeled. Annotation only; staleness never drops a keyword here.
    """
    channels = row["channels"]
    if level == "topic":
        recent_docs, recent_n = extract_recent(data)
        share = (recent_n / channels) if channels else 0.0
        row["recent_documents"] = recent_docs
        row["recent_channels"] = recent_n
        row["recent_channel_share"] = round(share, 4)
        word = "recent"
    else:
        recent_n = extract_active(data)
        share = (recent_n / channels) if channels else 0.0
        row["active_channels"] = recent_n
        row["active_channel_share"] = round(share, 4)
        word = "active"
    below_floor = recent_n < min_recent_channels
    stale = below_floor and share < min_share
    row["stale"] = stale
    row["stale_reason"] = (
        f"{word}_channels {recent_n} < {min_recent_channels} and "
        f"{word}_share {share:.0%} < {min_share:.0%}" if stale else ""
    )
    # THIN: below the absolute floor but share rescued it from "stale" — a narrow
    # niche that's still proportionally active. Surface it; don't drop it.
    row["thin"] = below_floor and not stale


def pct_drop(before, after):
    """What excluding something cost, as a percent of the original count."""
    return round((before - after) * 100.0 / before, 1) if before else None


def normalized_text(value):
    """`value` lowercased with runs of whitespace collapsed — the form two
    candidate strings are compared in."""
    return " ".join(str(value or "").lower().split())


def compute_signals(row, args):
    """Code-computed triage annotations. Signals never drop anything."""
    sig = []
    if row.get("documents", 0) == 0:
        sig.append("empty")
    if row.get("subsumed_by"):
        sig.append("subsumed")
    share = row.get("transcript_share")
    if share is not None and share >= args.transcript_led_min:
        sig.append("transcript_led")
    if row.get("transcript_dropped"):
        sig.append("transcript_dropped")
    if row.get("stale"):
        sig.append("stale")
    if row.get("thin"):
        sig.append("thin")
    marginal, breadth = row.get("marginal_share"), row.get("breadth_vs_core")
    # A candidate that IS the --residual-vs core adds nothing to itself and is
    # exactly as broad as itself, so `redundant` / `too_broad` would fire on
    # every core and mean nothing. The row is marked `is_core` instead.
    if not row.get("is_core"):
        if marginal is not None and marginal < args.redundant_max:
            sig.append("redundant")
        if (breadth is not None and marginal is not None
                and breadth >= args.broad_ratio and marginal >= args.broad_residual):
            sig.append("too_broad")
    # over_cut / blocked are NOT candidate signals. They describe what ONE
    # exclusion costs the CORE, so stamping them on every candidate that carries
    # the exclusion said nothing about the candidate and made "signals cleared"
    # meaningless. They live in the top-level `exclusions[].signals` only.
    return [s for s in SIGNAL_ORDER if s in sig]


# ------------------------------------------------------------------- sheet

def _n(value):
    return f"{int(value):,}" if isinstance(value, (int, float)) else "?"


def _sample_line(sample, level, indent=""):
    if level == "channel":
        return (f"{indent}- ch {sample.get('channel_id')} · {sample.get('name') or ''} · "
                f"{cut(sample.get('topic') or '', SHEET_TOPIC_CHARS)}")
    snippet = sample.get("snippet") or ""
    if sample.get("field") == "title":
        snippet = cut(snippet, SHEET_TITLE_CHARS)
    return (f"{indent}- [{sample.get('field') or '?'}] ch {sample.get('channel_id')} · "
            f"{sample.get('date') or ''} · {snippet}")


def _core_exclusion_line(entry):
    """One top-level exclusion as it reads on the `core:` line: `-"x" −2.8% (over_cut)`."""
    phrase = entry.get("phrase", "")
    quoted = f'"{phrase}"' if " " in phrase else phrase
    delta = entry.get("core_delta_pct")
    if isinstance(delta, (int, float)):
        text = f"{'−' if delta >= 0 else '+'}{abs(delta):.1f}%"
    else:
        text = "n/a"
    signals = entry.get("signals") or []
    if signals:
        text += " (" + ", ".join(signals) + ")"
    return f"-{quoted} {text}"


def render_sheet(out, *, intent, since, until, content_type):
    """The compact markdown sample sheet — the orchestrating model's read."""
    level = out["level"]
    dates = f"{since or ''}..{until or ''}" if (since or until) else "all dates"
    scope = f"youtube {content_type}" if level == "topic" else "youtube channels"
    lines = [
        f"# Sample sheet · intent: {intent or '(none)'}",
        (f"scope: {scope} · {dates} · fields {','.join(out['fields'])} · "
         f"{len(out['keywords'])} candidates · {out['timing']['elapsed_seconds']}s · "
         f"{len(out['failed'])} failed · {len(out['unresolved'])} unresolved"),
        "docs/ch = documents / distinct channels · strata = title / summary-only / "
        "transcript-only docs · «» marks the match",
    ]
    core = out.get("core")
    if core and "documents" in core:
        line = (f"core: {core.get('query', '')} — {_n(core['documents'])} docs / "
                f"{_n(core.get('channels', 0))} ch")
        # over_cut / blocked belong to the EXCLUSION, not to any candidate that
        # carries it, so they are read here, once, next to the core they cut.
        rendered = [_core_exclusion_line(e) for e in out.get("exclusions") or []]
        if rendered:
            line += " · exclusions on core: " + " · ".join(rendered)
        lines.append(line)
    lines.append("")
    # The union of a `--groups-file` measures the whole delivered filter, so it
    # is the row to read first — numbered 0 to keep the candidates at 1..n.
    rows = out["keywords"]
    numbered = ([(0, k) for k in rows if k.get("union")]
                + list(enumerate([k for k in rows if not k.get("union")], 1)))
    for i, kw in numbered:
        name = "union" if kw.get("union") else kw["keyword"]
        if kw.get("is_core"):
            name += " (core)"
        head = f"## {i}. {name} — {_n(kw['documents'])} docs / {_n(kw['channels'])} ch"
        strata = kw.get("strata")
        if strata:
            names = list(strata)
            if names == list(STANDARD_STRATA):
                head += " · strata " + "/".join(_n(strata.get(k, 0)) for k in names)
            else:
                # A non-standard field set has non-standard buckets, so the sheet
                # names them instead of printing three unlabelled numbers.
                head += " · strata " + "/".join(f"{n} {_n(strata.get(n, 0))}" for n in names)
            share = kw.get("transcript_share")
            if isinstance(share, (int, float)):
                head += f" · transcript {round(share * 100)}%"
            elif "transcript_only" in strata:
                head += " · transcript ?"
        own = kw.get("fields")
        if own and own != out.get("fields"):
            head += f" · fields {','.join(own)}"
        used = kw.get("fields_used")
        if used:
            head += f" · fields {','.join(used)} (transcript dropped: timeout)"
        if any(isinstance(e, str) and e.startswith("transcript_samples")
               for e in kw.get("measurement_errors") or []):
            head += " · transcript samples: failed"
        head += " · flags: " + (", ".join(kw.get("signals") or []) or "—")
        lines.append(head)
        for sample in kw.get("samples", []):
            lines.append(_sample_line(sample, level))
        residual = kw.get("residual") or {}
        if "documents" in residual:
            line = (f"  residual vs core: {_n(residual['documents'])} docs / "
                    f"{_n(residual.get('channels', 0))} ch")
            if kw.get("marginal_share") is not None:
                line += f" ({round(kw['marginal_share'] * 100)}%)"
            if kw.get("breadth_vs_core") is not None:
                line += f" · breadth {kw['breadth_vs_core']:.1f}×"
            lines.append(line)
            for sample in residual.get("samples", []):
                lines.append(_sample_line(sample, level, indent="  "))
        checks = kw.get("exclusion_checks") or []
        rendered = []
        for check in checks:
            phrase = check.get("phrase", "")
            quoted = f'"{phrase}"' if " " in phrase else phrase
            removes = check.get("removes_pct")
            removes_str = f"{removes:.1f}%" if isinstance(removes, (int, float)) else "?"
            core_delta = check.get("core_delta_pct")
            if isinstance(core_delta, (int, float)):
                sign = "−" if core_delta >= 0 else "+"
                core_str = f"core {sign}{abs(core_delta):.1f}%"
            else:
                core_str = "core n/a"
            rendered.append(f"-{quoted} → removes {removes_str} of this candidate · {core_str}")
        if rendered:
            lines.append("  exclusions: " + " · ".join(rendered))
    # Zero-document candidates are listed, not silently absent: a candidate that
    # vanished from the sheet came back as an unknown keyword at --apply time.
    if out.get("dropped"):
        lines.append("## no matches (0 docs)")
        for d in out["dropped"]:
            lines.append(f"- \"{d.get('keyword')}\" · 0 docs")
    if out["failed"] or out["unresolved"]:
        lines.append("## failed / unresolved")
        for f in out["failed"]:
            lines.append(f"- \"{f['keyword']}\" — {f.get('reason') or 'error'}")
        for u in out["unresolved"]:
            lines.append(f"- \"{u['keyword']}\" — {u.get('reason') or 'deadline'}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------- main

def parse_args(argv=None):
    ap = argparse.ArgumentParser(
        description="Probe ES for keyword counts, strata and highlighted samples."
    )
    ap.add_argument("keywords", nargs="*", help="Candidates (or pipe a JSON array on stdin)")
    ap.add_argument("--operator", choices=["AND", "OR"], default="OR",
                    help="How the caller will combine survivors downstream (default OR). "
                         "Echoed in output and drives subsumption annotation (OR only).")
    ap.add_argument("--level", choices=["topic", "channel"], default="topic",
                    help="topic = videos (default); channel = whole channels (no strata).")
    ap.add_argument("--mode", choices=["phrase", "sqs"], default="phrase",
                    help="How to interpret plain candidates: phrase match (default) "
                         "or simple_query_string (Boolean: + | - \"phrase\" () field^boost).")
    ap.add_argument("--fields", default=None,
                    help="Comma-separated ES fields to search (defaults by --level).")
    ap.add_argument("--samples", type=int, default=DEFAULT_SAMPLES,
                    help=f"Highlighted sample docs per candidate (default {DEFAULT_SAMPLES}, "
                         f"max {MAX_SAMPLES}; 0 = count only).")
    ap.add_argument("--no-highlight", action="store_true",
                    help="Skip ES highlighting; snippets fall back to a window over the title.")
    ap.add_argument("--content-type", choices=list(CONTENT_TYPES), default=None,
                    help="Topic-level video content type filter (default longform). "
                         "'all' drops the filter. Ignored at channel level. "
                         "YouTube-only is always enforced.")
    ap.add_argument("--since", help="publication_date >= YYYY-MM-DD (topic level only)")
    ap.add_argument("--until", help="publication_date <= YYYY-MM-DD (topic level only)")
    ap.add_argument("--intent", default="", help="Verbatim intent — echoed on the sheet only.")
    ap.add_argument("--sheet", metavar="PATH", help="Write the markdown sample sheet here.")
    # Recency validation: headline counts stay ALL-TIME; this layers an extra
    # "is the content still active?" signal on the SAME query (no extra round-trip).
    ap.add_argument("--no-recency", action="store_true",
                    help="Skip the recency/active-content check (pure all-time counts).")
    ap.add_argument("--recency-months", type=int, default=12,
                    help="Topic-level recency window in months (default 12).")
    ap.add_argument("--min-recent-channels", type=int, default=5,
                    help="STALE floor: fewer than this many recent/active distinct channels (default 5).")
    ap.add_argument("--min-recent-share", type=float, default=0.10,
                    help="Topic STALE share threshold (default 0.10).")
    ap.add_argument("--min-active-share", type=float, default=0.33,
                    help="Channel STALE share threshold (default 0.33).")
    ap.add_argument("--transcript-share-min", type=float, default=0.2,
                    help="Fetch transcript-only samples when that stratum is at least this "
                         "share of the documents (default 0.2).")
    ap.add_argument("--transcript-samples", type=int, default=2,
                    help="Transcript-only samples fetched in the second wave (default 2).")
    ap.add_argument("--groups-file", metavar="PATH",
                    help="Measure the DELIVERED filter: every include group in this groups "
                         "JSON becomes a candidate searched on its own content_fields, every "
                         "exclude group becomes a must_not on all of them, and a synthetic "
                         "`union` candidate measures the whole filter. Combinable with "
                         "positional candidates and --residual-vs.")
    ap.add_argument("--residual-vs", metavar="SQS",
                    help="Measurement: also probe each candidate MINUS this core query "
                         "and report what it reaches that the core does not.")
    ap.add_argument("--residual-samples", type=int, default=2,
                    help="Highlighted samples fetched for each residual (default 2).")
    ap.add_argument("--exclude-phrase", action="append", default=[], metavar="TEXT",
                    help="Measurement (repeatable): also probe each candidate with this phrase "
                         "excluded and report the document/channel drop (delta_pct).")
    ap.add_argument("--no-transcript-fallback", action="store_true",
                    help="Don't retry a timed-out probe without the `transcript` field; "
                         "report it under `failed` instead.")
    ap.add_argument("--transcript-led-min", type=float, default=0.8,
                    help="transcript_share at or above this flags `transcript_led` (default 0.8).")
    ap.add_argument("--redundant-max", type=float, default=0.05,
                    help="marginal_share below this flags `redundant` (default 0.05).")
    ap.add_argument("--broad-ratio", type=float, default=10.0,
                    help="breadth_vs_core at or above this (with --broad-residual) flags "
                         "`too_broad` (default 10).")
    ap.add_argument("--broad-residual", type=float, default=0.8,
                    help="marginal_share at or above this (with --broad-ratio) flags "
                         "`too_broad` (default 0.8).")
    ap.add_argument("--over-cut-pct", type=float, default=2.0,
                    help="An exclusion costing more than this percent flags `over_cut` (default 2).")
    ap.add_argument("--block-cut-pct", type=float, default=5.0,
                    help="An exclusion costing more than this percent flags `blocked` (default 5).")
    ap.add_argument("--deadline-at", type=int, default=None, metavar="EPOCH_SECONDS",
                    help="Wall-clock budget: a call that would start after this epoch second is "
                         "reported under `unresolved` instead of run. Env: TL_KW_DEADLINE_AT.")
    ap.add_argument("--workers", type=int, default=PROBE_WORKERS,
                    help=f"Concurrent ES probes (default {PROBE_WORKERS}; 1 = sequential).")
    ap.add_argument("--cache-dir", default=CACHE_DIR,
                    help=f"Directory for the probe response cache (default {CACHE_DIR}).")
    ap.add_argument("--cache-ttl-hours", type=float, default=CACHE_TTL_HOURS,
                    help=f"Serve an identical probe from cache if younger than this (default {CACHE_TTL_HOURS}).")
    ap.add_argument("--no-cache", action="store_true",
                    help="Always hit ES, and don't write the cache.")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: append this invocation as one event file under DIR/events/")
    args = ap.parse_intermixed_args(argv)
    reject_option_like(ap, args.keywords, "candidate")
    return args


def groups_file_candidates(path, fields):  # noqa: D401
    """A groups file → the candidates that measure the filter it delivers.

    Returns `(candidates, intent)` — the file may carry the run `intent` the
    sheet header echoes, so a groups-file round is not left reading `(none)`.

    Every include group is one candidate carrying its OWN fields (the group's
    `content_fields`, else the file's `default_content_fields`, else the run's
    `--fields`) so a round is measured on exactly what the report will search.
    Every exclude group becomes a `must_not` on all of them, and a synthetic
    `union` candidate (all includes OR'd, minus the excludes, each group on its
    own fields) measures the whole filter in one number.
    """
    try:
        spec = load_groups_file(path)
    except kw_common.BatchError as exc:
        sys.exit(str(exc))
    fallback = spec.get("default_content_fields") or list(fields)
    includes, excludes = [], []
    for group in spec["groups"]:
        entry = {"text": group["text"], "fields": list(group["content_fields"] or fallback)}
        (excludes if group["exclude"] else includes).append(entry)
    if not includes:
        sys.exit(f"--groups-file {path}: no include groups to probe")
    must_not = [sqs_clause(g["text"], g["fields"]) for g in excludes]
    out = [{"label": "union", "value": " | ".join(f"({g['text']})" for g in includes),
            "mode": "groups", "groups": includes, "union": True,
            "fields": list(dict.fromkeys(f for g in includes for f in g["fields"])),
            "must_not": must_not}]
    for group in includes:
        out.append({"label": group["text"], "value": group["text"], "mode": "sqs",
                    "fields": list(group["fields"]), "must_not": list(must_not)})
    return out, spec.get("intent") or ""


def resolve_deadline(args):
    raw = args.deadline_at
    if raw is None:
        raw = os.environ.get("TL_KW_DEADLINE_AT")
    if raw in (None, ""):
        return None
    try:
        epoch = float(raw)
    except (TypeError, ValueError):
        sys.exit(f"--deadline-at must be an epoch second, got {raw!r}")
    return Deadline(max(0, epoch - time.time()))


def classify_failure(exc, cand, failed, unresolved):
    kind = getattr(exc, "kind", "error")
    if kind == "deadline":
        unresolved.append({"keyword": cand["value"], "reason": "deadline"})
        return
    sys.stderr.write(f"probe failed for {cand['value']!r}: {exc}\n")
    failed.append({"keyword": cand["value"], "label": cand["label"],
                   "reason": "timeout" if kind == "timeout" else "error", "error": str(exc)})


def main():
    args = parse_args()
    if args.workers < 1:
        sys.exit("--workers must be >= 1")
    if args.recency_months < 1:
        sys.exit("--recency-months must be >= 1")
    ledger_started = time.monotonic()
    cache_dir = args.cache_dir

    # Date windowing and content type only mean something for articles — channel
    # docs have no publication_date or content_type, so a filter there silently
    # zeroes every count. They are ACCEPTED and ignored rather than refused, so
    # one scope string can be passed to every call of a run uniformly.
    if args.level != "topic":
        if args.since or args.until or args.content_type is not None:
            sys.stderr.write("--since/--until/--content-type ignored at --level channel\n")
        args.since = args.until = None
    if args.content_type is None:
        args.content_type = DEFAULT_CONTENT_TYPE
    for flag, val in (("--since", args.since), ("--until", args.until)):
        if val and not valid_date(val):
            sys.exit(f"{flag} must be YYYY-MM-DD, got {val!r}")

    fields = ([f.strip() for f in args.fields.split(",") if f.strip()] if args.fields
              else (TOPIC_FIELDS if args.level == "topic" else CHANNEL_FIELDS))
    if not fields:
        sys.exit("--fields must list at least one ES field")
    bad = [f for f in fields if not _FIELD_RE.match(f)]
    if bad:
        sys.exit(f"invalid --fields entries {bad}; use ES field paths, optionally boosted (e.g. title^3)")

    source_paths = TOPIC_SOURCE if args.level == "topic" else CHANNEL_SOURCE
    samples = min(MAX_SAMPLES, max(0, args.samples))
    highlight = bool(samples) and not args.no_highlight
    hl_fields = [base_field(f) for f in fields] if highlight else None

    deduped = []
    candidates = normalize(collect_candidates(args.keywords), args.mode, deduped)
    intent = args.intent
    if args.groups_file:
        from_file, file_intent = groups_file_candidates(args.groups_file, fields)
        candidates = from_file + candidates
        intent = intent or file_intent
    if not candidates:
        sys.exit("provide at least one candidate (positional args, a JSON array on stdin, "
                 "or --groups-file)")

    recency = not args.no_recency
    recency_cutoff = None
    if recency:
        recency_cutoff = months_ago_iso(args.recency_months) if args.level == "topic" else "active"

    deadline = resolve_deadline(args)
    counters = {"es_calls": 0, "cache_hits": 0}
    counters_lock = threading.Lock()   # wave 1 and 2 count from --workers threads

    def count(key):
        with counters_lock:
            counters[key] += 1

    def call(body, *, want_highlight=False):
        """One (possibly cached) ES call, counted whether or not it answered.

        `es_calls` is what the run spent, so a call that failed or timed out
        counts: a probe that only ever errored used to report `es_calls: 0`.
        A deadline refusal never shells out, so it is not a call.
        """
        try:
            data, hit = run_es_cached(body, cache_dir=cache_dir, ttl_hours=args.cache_ttl_hours,
                                      no_cache=args.no_cache, highlight=want_highlight,
                                      deadline=deadline)
        except EsError as exc:
            if exc.kind != "deadline":
                count("es_calls")
            raise
        count("cache_hits" if hit else "es_calls")
        return data

    def probe_call(body, *, want_highlight=False):
        """One ES call → `(data, transcript_dropped)`.

        A boolean query over `transcript` is the slow one, and a timeout there
        loses the candidate entirely. The same body without `transcript`
        answers in seconds, so it is worth exactly one reduced retry (still
        under the deadline) with the reduction recorded on the keyword.
        """
        try:
            return call(body, want_highlight=want_highlight), False
        except EsError as exc:
            reduced = (None if args.no_transcript_fallback or exc.kind != "timeout"
                       else drop_transcript(body))
            if reduced is None:
                raise
        return call(reduced, want_highlight=want_highlight), True

    started = time.monotonic()
    if not args.no_cache:
        kw_common.cache_namespace()  # resolve the identity once, before the workers start

    # ---- wave 1: counts + strata + highlighted samples, one call per candidate
    wave1_bodies = [
        build_body(cand, fields=fields, level=args.level, samples=samples,
                   source_paths=source_paths, since=args.since, until=args.until,
                   recency_cutoff=recency_cutoff, content_type=args.content_type,
                   strata=True, highlight_fields=hl_fields, must_not=cand.get("must_not"))
        for cand in candidates
    ]
    wave1 = parallel_map(lambda b: probe_call(b, want_highlight=highlight), wave1_bodies,
                         workers=args.workers)

    results, failed, unresolved = [], [], []
    by_keyword = {}
    for cand, result in zip(candidates, wave1):
        if isinstance(result, Exception):
            classify_failure(result, cand, failed, unresolved)
            continue
        outcome, dropped = result
        documents = extract_total(outcome)
        channels = extract_distinct(outcome)
        terms = literal_terms(cand["value"]) or [cand["value"]]
        cand_fields = candidate_fields(cand, fields)
        buckets = strata_names(args.level, cand_fields)
        required = required_of(cand)
        required_any = required_any_of(cand)
        row = {
            "keyword": cand["value"],
            "label": cand["label"],
            "mode": cand["mode"],
            "count": documents if args.level == "topic" else channels,
            "documents": documents,
            "channels": channels,
            "samples": (samples_of(outcome, level=args.level, terms=terms, required=required,
                                   required_any=required_any)
                        if samples else []),
            "_mode": cand["mode"],
            "_terms": terms,
            "_required": required,
            "_required_any": required_any,
            "_cand": cand,
            "subsumed_by": [],
        }
        if cand.get("union"):
            row["union"] = True
        if cand.get("fields"):
            row["fields"] = [base_field(f) for f in cand["fields"]]
        if args.residual_vs:
            row["is_core"] = normalized_text(row["keyword"]) == normalized_text(args.residual_vs)
        if dropped:
            note_transcript_dropped(row, cand_fields)
        if buckets:
            remainder = remainder_bucket_name(cand_fields)
            strata = extract_strata(outcome, measured_strata_names(buckets, remainder))
            if remainder and dropped:
                # The retry never looked at the transcript, so the remainder is
                # unknown — not zero.
                strata[remainder] = None
            elif remainder:
                strata[remainder] = max(0, documents - sum(strata.values()))
            # The transcript-only share is only readable when the transcript is
            # probed AND owns the subtracted bucket on its own.
            if remainder != "transcript_only" or dropped:
                row["transcript_share"] = None
            else:
                row["transcript_share"] = (round(strata[remainder] / documents, 4)
                                           if documents else 0)
            row["strata"] = strata
        if recency:
            annotate_recency(row, outcome, level=args.level,
                             min_recent_channels=args.min_recent_channels,
                             min_share=(args.min_recent_share if args.level == "topic"
                                        else args.min_active_share))
        results.append(row)
        by_keyword[(cand["mode"], cand["value"])] = row

    # ---- wave 2: transcript-only samples + residual / exclusion / core measurements
    jobs = []  # (kind, row, phrase, body, highlight)
    for row in results:
        if (args.level != "topic" or not samples or args.transcript_samples < 1
                or not row.get("strata") or "transcript_only" not in row["strata"]):
            continue
        share = row.get("transcript_share") or 0
        if share < args.transcript_share_min:
            continue
        cand = row["_cand"]
        cand_fields = candidate_fields(cand, fields)
        transcript_fields = [f for f in cand_fields if base_field(f) == "transcript"]
        if not transcript_fields:
            continue
        earlier = [f for f in probed_text_fields(cand_fields) if f != "transcript"]
        body = build_body({**cand, "fields": transcript_fields}, fields=transcript_fields,
                          level=args.level,
                          samples=min(MAX_SAMPLES, args.transcript_samples),
                          source_paths=source_paths, since=args.since, until=args.until,
                          recency_cutoff=None, content_type=args.content_type,
                          highlight_fields=["transcript"] if highlight else None,
                          must_not=[match_clause(cand, [f]) for f in earlier]
                                   + list(cand.get("must_not") or []))
        jobs.append(("transcript", row, None, body, highlight))

    core_row = None
    for row in results:
        base_cand = row["_cand"]
        cand_fields = candidate_fields(base_cand, fields)
        as_sqs = f'"{row["keyword"]}"' if row["_mode"] == "phrase" else f'({row["keyword"]})'
        # A groups-file candidate has per-group fields and its own excludes, so it
        # cannot be re-expressed as one `<candidate> -<thing>` string: the thing
        # being subtracted becomes another must_not on the same candidate instead.
        if args.residual_vs:
            if own_query(base_cand):
                # The core is ONE thing: it is subtracted on the run-level fields,
                # not on whatever narrower fields this group happens to search.
                cand, extra = base_cand, [sqs_clause(args.residual_vs, fields)]
            else:
                cand = {"label": row["label"], "value": f"{as_sqs} -({args.residual_vs})",
                        "mode": "sqs"}
                extra = []
            body = build_body(cand, fields=cand_fields, level=args.level,
                              samples=max(0, args.residual_samples), source_paths=source_paths,
                              since=args.since, until=args.until, recency_cutoff=None,
                              content_type=args.content_type,
                              highlight_fields=hl_fields if args.residual_samples else None,
                              must_not=list(cand.get("must_not") or []) + extra or None)
            jobs.append(("residual", row, None, body, highlight and args.residual_samples > 0))
        for phrase in args.exclude_phrase:
            q = f'"{phrase}"' if " " in phrase else phrase
            if own_query(base_cand):
                cand, extra = base_cand, [sqs_clause(q, cand_fields)]
            else:
                cand = {"label": row["label"], "value": f"{as_sqs} -{q}", "mode": "sqs"}
                extra = []
            body = build_body(cand, fields=cand_fields, level=args.level, samples=0,
                              source_paths=source_paths, since=args.since, until=args.until,
                              recency_cutoff=None, content_type=args.content_type,
                              must_not=list(cand.get("must_not") or []) + extra or None)
            jobs.append(("exclusion", row, phrase, body, False))
    if args.residual_vs and results:
        core_row = {"query": args.residual_vs}
        body = build_body({"label": "core", "value": args.residual_vs, "mode": "sqs"},
                          fields=fields, level=args.level, samples=0,
                          source_paths=source_paths, since=args.since, until=args.until,
                          recency_cutoff=None, content_type=args.content_type)
        jobs.append(("core", core_row, None, body, False))
        # One extra probe per --exclude-phrase measured against the CORE (not per
        # candidate): "does this exclusion cut the on-topic core?" is a property of
        # the phrase, not of any one candidate that happens to carry it.
        for phrase in args.exclude_phrase:
            q = f'"{phrase}"' if " " in phrase else phrase
            cand = {"label": "core exclusion", "value": f"({args.residual_vs}) -{q}", "mode": "sqs"}
            cbody = build_body(cand, fields=fields, level=args.level, samples=0,
                               source_paths=source_paths, since=args.since, until=args.until,
                               recency_cutoff=None, content_type=args.content_type)
            jobs.append(("core_exclusion", core_row, phrase, cbody, False))

    core_exclusion_docs = {}  # phrase -> (documents, channels) of CORE AND NOT phrase

    waves = 1
    if jobs:
        waves = 2
        outcomes = parallel_map(lambda j: probe_call(j[3], want_highlight=j[4]), jobs,
                                workers=args.workers)
        for (kind, row, phrase, _body, _hl), result in zip(jobs, outcomes):
            if isinstance(result, Exception):
                if kind == "core":
                    row["error"] = str(result)
                elif kind == "transcript":
                    # A failed transcript-sample call leaves the row's evidence
                    # one-sided, so it is recorded rather than silently skipped.
                    row.setdefault("measurement_errors", []).append(
                        f"transcript_samples: {getattr(result, 'kind', 'error')}")
                elif kind == "core_exclusion":
                    continue
                else:
                    row.setdefault("measurement_errors", []).append(
                        {"kind": kind, "phrase": phrase, "error": str(result)})
                continue
            outcome, dropped = result
            if dropped:
                note_transcript_dropped(row, candidate_fields(row.get("_cand") or {}, fields))
            if kind == "transcript":
                row["samples"].extend(samples_of(outcome, level=args.level, terms=row["_terms"],
                                                 force_stratum="transcript",
                                                 required=row["_required"],
                                                 required_any=row.get("_required_any", False)))
            elif kind == "core":
                row["documents"] = extract_total(outcome)
                row["channels"] = extract_distinct(outcome)
            elif kind == "core_exclusion":
                core_exclusion_docs[phrase] = (extract_total(outcome), extract_distinct(outcome))
            elif kind == "residual":
                docs, chans = extract_total(outcome), extract_distinct(outcome)
                row["residual"] = {"vs": args.residual_vs, "documents": docs, "channels": chans,
                                   "samples": samples_of(outcome, level=args.level,
                                                         terms=row["_terms"],
                                                         required=row["_required"],
                                                         required_any=row.get("_required_any",
                                                                              False))}
                row["marginal_share"] = (round(docs / row["documents"], 3)
                                         if row["documents"] else None)
            else:  # kind == "exclusion" — cost to the CANDIDATE itself
                docs, chans = extract_total(outcome), extract_distinct(outcome)
                removes_pct = pct_drop(row["documents"], docs)
                rec = {"phrase": phrase, "documents": docs, "channels": chans,
                       "removes_pct": removes_pct,
                       "removes_pct_channels": pct_drop(row["channels"], chans),
                       "delta_pct": removes_pct,  # deprecated alias of removes_pct; same value
                       "core_delta_pct": None, "core_delta_pct_channels": None}
                row.setdefault("exclusion_checks", []).append(rec)

    # Fold the core-level measurement into every exclusion_checks entry that
    # carries the matching phrase, and build the top-level `exclusions` summary —
    # one row per --exclude-phrase, not per candidate. Without --residual-vs (or
    # if the core-exclusion probe errored) core_delta_pct stays null and no
    # over_cut/blocked signal is ever emitted for it.
    exclusions_summary = []
    if args.residual_vs and core_row and core_row.get("documents") is not None:
        core_before_docs, core_before_chans = core_row["documents"], core_row["channels"]
        for phrase in args.exclude_phrase:
            after = core_exclusion_docs.get(phrase)
            core_documents = core_delta = core_delta_chans = None
            if after is not None:
                core_documents, core_chans = after
                core_delta = pct_drop(core_before_docs, core_documents)
                core_delta_chans = pct_drop(core_before_chans, core_chans)
            sig = []
            if isinstance(core_delta, (int, float)):
                if core_delta > args.over_cut_pct:
                    sig.append("over_cut")
                if core_delta > args.block_cut_pct:
                    sig.append("blocked")
            exclusions_summary.append({
                "phrase": phrase, "core_documents": core_documents,
                "core_delta_pct": core_delta, "core_delta_pct_channels": core_delta_chans,
                "signals": [s for s in SIGNAL_ORDER if s in sig],
            })
            for row in results:
                for rec in row.get("exclusion_checks", []):
                    if rec["phrase"] == phrase:
                        rec["core_delta_pct"] = core_delta
                        rec["core_delta_pct_channels"] = core_delta_chans

    if core_row and core_row.get("documents"):
        for row in results:
            row["breadth_vs_core"] = (round(row["documents"] / core_row["documents"], 2)
                                      if row["documents"] else None)
    elif args.residual_vs:
        for row in results:
            row["breadth_vs_core"] = None

    mark_subsumed(results, args.operator)

    # `count` is 0 exactly when the document total is 0 (a non-empty match always
    # reaches >=1 distinct channel), so it is the single no-match gate.
    recency_keys = (("recent_documents", "recent_channels", "recent_channel_share")
                    if args.level == "topic" else ("active_channels", "active_channel_share"))
    survivors, dropped = [], []
    for r in results:
        r["signals"] = compute_signals(r, args)
        if r["count"] == 0:
            dropped.append({"keyword": r["keyword"], "count": 0, "reason": "no_matches",
                            "signals": r["signals"]})
            continue
        kept = {"keyword": r["keyword"], "mode": r["mode"], "count": r["count"],
                "documents": r["documents"], "channels": r["channels"],
                "subsumed_by": r["subsumed_by"], "samples": r["samples"]}
        for extra in ("strata", "transcript_share", "fields_used", "note", "residual",
                      "marginal_share", "breadth_vs_core", "exclusion_checks",
                      "measurement_errors", "fields", "union", "is_core"):
            if extra in r:
                kept[extra] = r[extra]
        if recency:
            for k in (*recency_keys, "stale", "stale_reason", "thin"):
                kept[k] = r[k]
        kept["signals"] = r["signals"]
        survivors.append(kept)

    survivors.sort(key=lambda r: r["count"], reverse=True)

    # Echo the always-on scope so the caller (and user) sees what was filtered.
    scope = {"format": "youtube"}
    if args.level == "topic":
        scope["content_type"] = args.content_type
    out = {
        "operator": args.operator,
        "level": args.level,
        "fields": fields,
        "scope": scope,
        "keywords": survivors,
        "dropped": dropped,
        "deduped": deduped,
        "failed": failed,
        "unresolved": unresolved,
        "timing": {"elapsed_seconds": round(time.monotonic() - started, 1),
                   "es_calls": counters["es_calls"], "cache_hits": counters["cache_hits"],
                   "workers": args.workers, "waves": waves, "unresolved": len(unresolved)},
    }
    if core_row:
        out["core"] = core_row
    if exclusions_summary:
        out["exclusions"] = exclusions_summary
    if recency:
        out["recency"] = ({"months": args.recency_months, "cutoff": recency_cutoff}
                          if args.level == "topic" else {"signal": "posts_per_90_days>0"})
    if args.sheet:
        sheet = render_sheet(out, intent=intent, since=args.since, until=args.until,
                             content_type=args.content_type)
        try:
            with open(args.sheet, "w", encoding="utf-8") as fh:
                fh.write(sheet)
        except OSError as exc:
            sys.stderr.write(f"could not write --sheet {args.sheet}: {exc}\n")
    emit(out, run_dir=args.run_dir, script="probe", argv=sys.argv[1:], started=ledger_started)
    if failed and not results:
        sys.exit(1)  # every candidate failed — the batch itself is broken


# OUTPUT CONTRACT (stdout, single JSON object, no prose/fences):
# {
#   "operator": "OR" | "AND", "level": "topic" | "channel",
#   "fields": [<es fields searched>],
#   "scope": {"format": "youtube"[, "content_type": …]},
#   "keywords": [                      # documents>0, sorted desc by count
#     {"keyword", "mode", "count", "documents", "channels", "subsumed_by": [...],
#      "strata": {"title", "summary_only", "transcript_only"},   # topic level only
#      #   the LAST bucket is a subtraction (documents minus the measured ones)
#      #   and is named after the fields left over, so `--fields title,hashtags`
#      #   reports {"title", "hashtags_only"}
#      "transcript_share": <0-1>,   # topic level only; null unless `transcript` is
#      #   probed AND owns the subtracted bucket on its own
#      "signals": ["transcript_led", "too_broad", …],             # annotations, never drops
#      # after a transcript timeout (unless --no-transcript-fallback):
#      #   "fields_used": ["title","summary"], "note": <what was dropped>,
#      #   signal `transcript_dropped`, strata.transcript_only / transcript_share null
#      "samples": [{"video_id","channel_id","title","date","url","category",
#                   "stratum","field","snippet"}],                # channel level:
#                  # {"channel_id","name","topic","field","snippet"}
#      # with --residual-vs: "residual": {"vs","documents","channels","samples"},
#      #                     "marginal_share", "breadth_vs_core", "is_core"
#      #   is_core: this candidate's text IS the core (whitespace/case-insensitive),
#      #   so it never carries `redundant` / `too_broad` and the sheet reads `(core)`
#      # "measurement_errors": entries for wave-2 measurements that did not answer —
#      #   {"kind","phrase","error"} for a residual/exclusion, or the string
#      #   "transcript_samples: <kind>" when the transcript-sample call failed
#      # with --exclude-phrase: "exclusion_checks": [{"phrase","documents","channels",
#      #   "removes_pct","removes_pct_channels",       # cost to THIS CANDIDATE
#      #   "delta_pct",                                # deprecated alias of removes_pct
#      #   "core_delta_pct","core_delta_pct_channels"}] # cost to the CORE; null without
#      #                                                 # --residual-vs (or on a probe error)
#      # RECENCY (unless --no-recency): topic "recent_documents"/"recent_channels"/
#      #   "recent_channel_share"; channel "active_channels"/"active_channel_share";
#      #   both "stale", "stale_reason", "thin"
#      # with --groups-file: "fields" (the group's own content_fields, when they
#      #   differ from the run default), and on the synthetic whole-filter row
#      #   "union": true — the sheet prints that one first, as `## 0. union`
#     }],
#   "dropped": [{"keyword","count":0,"reason":"no_matches","signals":["empty"]}],
#   "deduped": [{"keyword","kept_as"}],   # case-only repeats normalize() removed
#                  # every one of these is listed on the sheet under
#                  # `## no matches (0 docs)` — a candidate that silently
#                  # vanished came back as an unknown keyword at --apply time
#   "failed": [{"keyword","label","reason":"timeout"|"error","error"}],   # not retried
#   "unresolved": [{"keyword","reason":"deadline"}],                      # never called
#   "core": {"query","documents","channels"},                             # with --residual-vs
#   "exclusions": [{"phrase","core_documents","core_delta_pct",           # with --residual-vs
#                   "core_delta_pct_channels","signals"}],                # + --exclude-phrase;
#                  # one entry per --exclude-phrase (not per candidate); over_cut/blocked
#                  # live HERE only (they describe what the exclusion costs the core,
#                  # not the candidate), and the sheet reads them on the `core:` line.
#                  # core_delta_pct is echoed onto every candidate's matching
#                  # exclusion_checks entry; the signals are not
#   "timing": {"elapsed_seconds","es_calls","cache_hits","workers","waves","unresolved"},
#   "recency": {"months","cutoff"} | {"signal": "posts_per_90_days>0"}
# }
# Headline counts are ALL-TIME. `subsumed_by`, `stale` and `signals` are
# informational: nothing here is a verdict, the judging happens on the sheet.
if __name__ == "__main__":
    main()
