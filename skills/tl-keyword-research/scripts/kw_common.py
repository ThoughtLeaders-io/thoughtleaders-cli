#!/usr/bin/env python3
"""Shared plumbing for every tl-keyword-research script.

This module is the ONE home for the helpers that used to be copy-pasted across
probe.py / search_channels.py / search_videos.py / evidence.py /
select_keywords.py / classify_channels.py: the `tl db es` call, the scope
filters, the boolean-group query, the response accessors, the on-disk response
cache, the run ledger, and the stdin guard. Scripts import it; they do not
re-implement it.

ES call rules (these are the rules the duplicated copies disagreed on — this
module settles them):

  * ONE call gets `ES_TIMEOUT` seconds (default 20, override with the
    `TL_KW_ES_TIMEOUT` env var). The old copies used 90s, which meant a single
    wedged query could eat a quarter of a run's wall clock.
  * A TimeoutExpired is NEVER retried. Retrying a timeout doubles the worst
    case for a query that is, by definition, already too slow. It raises
    `EsError(kind="timeout")` immediately.
  * A RATE-LIMIT failure (see `RATE_LIMIT_MARKERS`, or the CLI's rate-limit /
    server-error exit code `RATE_LIMIT_RETURNCODE`) is retried up to TWICE,
    backing off `RETRY_PAUSE` then `RATE_LIMIT_PAUSE_2` seconds — one pause is
    not enough under sustained contention. Any OTHER transient failure (see
    `TRANSIENT_MARKERS`) is retried EXACTLY ONCE after `RETRY_PAUSE` seconds.
    Anything else fails on the first try with `EsError(kind="error")`. The
    raised message carries the attempt count.
  * A `Deadline` caps the whole step: every call's timeout is
    `min(its own timeout, time left)`, and once the deadline is gone calls
    raise `EsError(kind="deadline")` WITHOUT shelling out. Scripts that want a
    wall-clock budget build one `Deadline` and thread it through.
  * Failure is always an exception, never `sys.exit` — one bad candidate must
    not abort a 60-candidate batch. Callers decide what is fatal.

`tl db es` CLI response shape (what the accessors below paper over):

  * Rows arrive as `data["results"]` (the CLI envelope), not
    `data["hits"]["hits"]`. `hits_of` accepts either.
  * `_source` is FLATTENED into the row, so a row is its own source and nested
    paths may appear either nested (`{"channel": {"id": 5}}`) or flat
    (`{"channel.id": 5}`). Use `source_of` / `get_path`, never `row["_source"]`.
  * Highlight fragments only come back when the call passes `--highlight`;
    without that flag the CLI strips the `highlight` block entirely. Ask for
    highlighting via `run_es(..., highlight=True)` plus a `highlight_clause`
    in the body, then read it with `fragments_of`.
  * `_index` is not exposed on rows; it only leaks through inside a `top_hits`
    aggregation, so index-level facts must be aggregated, not read per row.
"""
import concurrent.futures
import datetime
import hashlib
import html
import json
import os
import re
import stat
import subprocess
import sys
import threading
import time

# --------------------------------------------------------------- constants

# Format = source platform; 4 = YouTube uploads, the only inventory we work
# with. Topic (article) docs nest it under `channel.format`; channel docs carry
# their own `format`.
YOUTUBE_FORMAT = 4

# Article-level (doc_type:article) text fields. `summary` is the creator-written
# video description (links, hashtags, promo), not an AI summary. Article-level
# `description` is empty and `content` is podcast-only; neither belongs here.
TOPIC_FIELDS = ["title", "summary", "transcript"]

# Channel-level (doc_type:channel) text fields. `description.domains` sits
# alongside plain `description` because the delivered report filter searches it
# and it matches domain-shaped terms ("patreon.com") that plain `description`
# undercounts (URLs tokenize into word pieces there).
CHANNEL_FIELDS = ["name", "description", "description.domains", "ai.description",
                  "ai.topic_descriptions"]

# content_type tags a video longform / short / live. It exists ONLY on article
# docs. Default longform (best sponsorable-content signal); "all" drops it.
CONTENT_TYPES = ("longform", "short", "live", "all")

# The channel-identity field per level — used to `collapse` samples to distinct
# channels and to count them with a cardinality agg. Channel docs are written
# once per quarterly index, so a channel appears many times in a raw hit total.
COLLAPSE_FIELD = {"topic": "channel.id", "channel": "id"}
FORMAT_FIELD = {"topic": "channel.format", "channel": "format"}

DOC_TYPE = {"topic": "article", "channel": "channel"}


def _env_float(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, TypeError, ValueError):
        return default


ES_TIMEOUT = _env_float("TL_KW_ES_TIMEOUT", 20)  # seconds for ONE `tl db es` call
RETRY_PAUSE = 3  # seconds before the first retry of a transient failure
RATE_LIMIT_PAUSE_2 = 8  # seconds before the SECOND retry, rate limits only
TRANSIENT_MARKERS = ("429", "502", "503", "504", "Rate limited", "Please wait and try again",
                     "Server error", "timed out", "timeout", "Too Many Requests")
# Rate limiting specifically — it is the failure that sustained contention keeps
# producing, so it earns the extra retry the other transient markers do not.
RATE_LIMIT_MARKERS = ("429", "Rate limited", "Please wait", "Too Many Requests")
RATE_LIMIT_RETURNCODE = 3  # the CLI's rate-limit / server-error exit code
WHOAMI_RETRY_PAUSE = 2  # seconds before the single retry of `tl whoami`
SHARED_NS_FALLBACK = "default"  # stands in for an unset $TL_API_URL
HIGHLIGHT_PRE, HIGHLIGHT_POST = "<<", ">>"
DEFAULT_WORKERS = 6  # concurrent `tl db es` calls (each is one short round-trip)
CACHE_ROOT = os.path.join(os.path.expanduser("~"), ".cache", "tl-keyword-research")
CACHE_FORMAT = 1  # bump when the cached response shape changes

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
# An unstructured multi-word group is a phrase; boolean text is left alone.
_STRUCTURAL_BOOL_RE = re.compile(r'[|()"]|(?:^|(?<=[\s(]))[+-](?=\S)')
_DETACHED_SIGN_RE = re.compile(r"(?:^|(?<=\s))[+-](?=\s|$)")
_BOOST_RE = re.compile(r"^(?P<path>[\w.]+)(?P<boost>\^\d+(?:\.\d+)?)?$")

# Report content-field names → ES paths on ARTICLE docs (what these scripts
# search). Channel-level report fields live on channel docs and would need a
# parent-child join ES will not run here — they are refused loudly rather than
# silently matching nothing.
ARTICLE_FIELD_MAP = {"title": "title", "summary": "summary", "transcript": "transcript",
                     "content": "content", "hashtags": "hashtags"}
CHANNEL_ONLY_FIELDS = {"channel_description", "channel_description_ai",
                       "channel_topic_description", "channel.channel_name"}


# ------------------------------------------------------------------ errors

class EsError(Exception):
    """One ES call failed. `.kind` says how, so callers can react per cause.

    kind ∈ {"timeout", "transient", "error", "deadline", "parse"}.
    """

    def __init__(self, message, kind="error"):
        super().__init__(message)
        self.kind = kind


class BatchError(Exception):
    """A protocol violation the orchestrator must act on (message is user-facing)."""


# ---------------------------------------------------------------- deadline

# Less time than this left means the next call is refused outright: anything
# shorter answers nothing and only turns a deadline into a fake timeout.
MIN_CALL_SECONDS = 2.0


class Deadline:
    """A wall-clock budget for a whole step, threaded through its ES calls."""

    def __init__(self, seconds=None):
        self.seconds = seconds
        self._until = None if seconds is None else time.monotonic() + float(seconds)

    @classmethod
    def from_env(cls, env="TL_KW_DEADLINE"):
        """A deadline from `$TL_KW_DEADLINE` seconds, or an unbounded one."""
        raw = os.environ.get(env)
        if raw is None:
            return cls(None)
        try:
            return cls(float(raw))
        except (TypeError, ValueError):
            return cls(None)

    def remaining(self):
        if self._until is None:
            return None
        return self._until - time.monotonic()

    @property
    def expired(self):
        left = self.remaining()
        return left is not None and left <= 0

    def timeout_for(self, default):
        """The timeout for the next call: `min(default, time left)`.

        A call that cannot get `MIN_CALL_SECONDS` is refused as a `deadline`
        rather than attempted: a sub-second ES call lands in `failed: timeout`
        and reads as a broken query, when what actually ran out was the budget.
        """
        left = self.remaining()
        if left is None:
            return default
        if left < MIN_CALL_SECONDS:
            raise EsError(f"deadline exceeded ({self.seconds}s budget)", kind="deadline")
        return min(default, left)


# ------------------------------------------------------------------ run_es

def _transient(text):
    return any(m in (text or "") for m in TRANSIENT_MARKERS)


def _rate_limited(text, returncode):
    """True when a failure is the CLI saying "slow down" — by marker or exit code."""
    return (returncode == RATE_LIMIT_RETURNCODE
            or any(m in (text or "") for m in RATE_LIMIT_MARKERS))


def run_es(body, *, highlight=False, timeout=None, deadline=None, retry=True):
    """Run `tl db es - --json` with `body` on stdin; return the parsed response.

    `highlight=True` adds `--highlight` so the CLI keeps the `highlight` block.
    Raises `EsError` (see the module docstring for the rules) — never exits.
    """
    cmd = ["tl", "db", "es", "-", "--json"]
    if highlight:
        cmd.append("--highlight")
    base = ES_TIMEOUT if timeout is None else timeout
    payload = json.dumps(body)
    proc = None
    attempt = 0
    while True:
        attempt += 1
        effective = deadline.timeout_for(base) if deadline is not None else base
        try:
            proc = subprocess.run(cmd, input=payload, capture_output=True, text=True,
                                  timeout=effective)
        except subprocess.TimeoutExpired:
            # Never retried: a query that already blew its budget will not be
            # faster the second time, and the retry doubles the worst case.
            raise EsError(f"tl db es timed out after {effective:g}s", kind="timeout")
        if proc.returncode == 0:
            break
        detail = (proc.stderr or proc.stdout or "").strip()
        limited = _rate_limited(detail, proc.returncode)
        pauses = (RETRY_PAUSE, RATE_LIMIT_PAUSE_2) if limited else (RETRY_PAUSE,)
        transient = limited or _transient(detail)
        if retry and transient and attempt <= len(pauses):
            time.sleep(pauses[attempt - 1])
            continue
        raise EsError(f"tl db es failed (rc={proc.returncode}) after {attempt} "
                      f"attempt{'' if attempt == 1 else 's'}: {detail[:300]}",
                      kind="transient" if transient else "error")
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise EsError(f"could not parse tl db es output: {exc}: {(proc.stdout or '')[:300]}",
                      kind="parse")


# ------------------------------------------------------------------ queries

def scope_filters(*, level="topic", content_type="longform", since=None, until=None,
                  channel_ids=None):
    """The filter clauses every keyword-research query is scoped by.

    Topic level: YouTube article docs, `content_type` (unless "all"), an
    optional publication-date range and an optional channel-id restriction.
    Channel level: YouTube channel docs — channel docs carry no content type,
    no date and no parent channel, so those arguments do not apply.
    """
    filters = [
        {"term": {"doc_type": DOC_TYPE[level]}},
        {"term": {FORMAT_FIELD[level]: YOUTUBE_FORMAT}},
    ]
    if level != "topic":
        return filters
    if content_type and content_type != "all":
        filters.append({"term": {"content_type": content_type}})
    if since or until:
        rng = {}
        if since:
            rng["gte"] = since
        if until:
            rng["lte"] = until
        filters.append({"range": {"publication_date": rng}})
    if channel_ids:
        filters.append({"terms": {"channel.id": list(channel_ids)}})
    return filters


def valid_date(value):
    """The date back when it is a real `YYYY-MM-DD`, `""` when it is not.

    Truthy/falsey either way, so `if not valid_date(x): ...` reads the same as
    it did when this returned a bool.
    """
    try:
        datetime.datetime.strptime(value, "%Y-%m-%d")
        return value
    except (ValueError, TypeError):
        return ""


def months_ago_iso(months):
    """ISO date `months` whole months before today (day clamped to <=28 to avoid
    month-length edge cases). Used as the topic-level recency cutoff."""
    today = datetime.date.today()
    y, m = today.year, today.month - months
    while m <= 0:
        m += 12
        y -= 1
    return datetime.date(y, m, min(today.day, 28)).isoformat()


def highlight_clause(fields, *, fragment_size=250, fragments=2, highlight_query=None):
    """A `highlight` block over `fields` with the shared `<<`/`>>` markers.

    `require_field_match: true` so only the clauses that actually searched a
    field highlight it — with it off, a scope filter leaks into the snippets
    (a `channel.format: 4` scope came back as `PlayStation <<4>>`).
    `highlight_query` narrows it further to the terms we are gathering evidence
    for, so a boolean group marks its anchor terms and not just whichever
    alternative the scoring clause fired on.
    """
    block = {
        "fields": {f: {"fragment_size": fragment_size, "number_of_fragments": fragments}
                   for f in fields},
        "pre_tags": [HIGHLIGHT_PRE],
        "post_tags": [HIGHLIGHT_POST],
        "require_field_match": True,
    }
    if highlight_query is not None:
        block["highlight_query"] = highlight_query
    return block


def phrase_if_plain(text):
    """Quote an unstructured multi-word group as one phrase; leave boolean text alone."""
    t = str(text).strip()
    if " " in t and not (_STRUCTURAL_BOOL_RE.search(t) or _DETACHED_SIGN_RE.search(t)):
        return f'"{t}"'
    return t


def es_field(name):
    """One report content-field name → its ES path, carrying any `^boost`.

    Channel-level names are refused: they cannot be searched from article docs.
    """
    m = _BOOST_RE.match(str(name).strip())
    path, boost = (m.group("path"), m.group("boost") or "") if m else (str(name).strip(), "")
    if path in CHANNEL_ONLY_FIELDS or str(name).strip() in CHANNEL_ONLY_FIELDS:
        raise BatchError(f"content field {name!r} lives on channel docs and cannot be searched at "
                         "video level; measure it with probe.py --level channel instead")
    mapped = ARTICLE_FIELD_MAP.get(path)
    if mapped is None:
        raise BatchError(f"unknown content field {name!r} in groups file; known: "
                         f"{sorted(ARTICLE_FIELD_MAP)} (channel-level fields are not searchable here)")
    return mapped + boost


def es_fields(names):
    return [es_field(n) for n in names]


def load_groups_file(path):
    """Read boolean groups from a JSON file into the one shared groups spec.

    Accepts build_report.py's `{"groups": [{"text", "content_fields", "exclude"}],
    "default_content_fields": [...], "operator": "AND"|"OR"}` object, a bare
    list of such objects, or a bare list of strings. Returns

        {"groups": [{"text", "content_fields" | None, "exclude": bool}],
         "operator": "AND" | "OR" | None,
         "intent": "" | "<the run intent the file carries>",
         "default_content_fields": [...] | None}

    with every content-field name already translated to its ES path (boosts
    preserved) and channel-level names refused. `text` is kept verbatim — call
    `phrase_if_plain` when you want an unstructured group quoted.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(f"--groups-file {path}: {exc}")
    default_fields, operator, intent = None, None, ""
    if isinstance(data, dict):
        default_fields = data.get("default_content_fields") or None
        operator = data.get("operator") or None
        intent = str(data.get("intent") or "").strip()
        data = data.get("groups", [])
    if not isinstance(data, list):
        raise BatchError(f"--groups-file {path}: expected a list of groups or an object "
                         "with a 'groups' list")
    groups = []
    for item in data:
        if isinstance(item, dict):
            text, cf, ex = item.get("text"), item.get("content_fields"), bool(item.get("exclude"))
        else:
            text, cf, ex = item, None, False
        text = str(text or "").strip()
        if not text:
            continue
        groups.append({"text": text, "content_fields": es_fields(cf) if cf else None,
                       "exclude": ex})
    return {"groups": groups,
            "operator": str(operator).upper() if operator else None,
            "intent": intent,
            "default_content_fields": es_fields(default_fields) if default_fields else None}


def groups_query(groups_spec, *, operator=None):
    """The `bool` body for a groups spec — the delivered filter, verbatim.

    Each group is a self-contained `simple_query_string` over its own fields
    (`default_operator: "and"` keeps an in-group `-term` safe). Positive groups
    combine per `operator` (argument first, then the file's, else OR); excluded
    groups become `must_not`. Scope is NOT included — merge
    `{"filter": scope_filters(...)}` into the result.
    """
    spec = groups_spec if isinstance(groups_spec, dict) else {"groups": groups_spec}
    fallback = spec.get("default_content_fields") or spec.get("fields") or list(TOPIC_FIELDS)
    op = (operator or spec.get("operator") or "OR").upper()
    clauses, excludes = [], []
    for g in spec.get("groups") or []:
        if isinstance(g, dict):
            text, fields, ex = g.get("text"), g.get("content_fields") or g.get("fields"), g.get("exclude")
        else:
            text, fields, ex = g, None, False
        clause = {"simple_query_string": {"query": text, "fields": list(fields or fallback),
                                          "default_operator": "and"}}
        (excludes if ex else clauses).append(clause)
    bool_q = {}
    if op == "AND":
        bool_q["must"] = clauses
    else:
        bool_q["should"] = clauses
        bool_q["minimum_should_match"] = 1
    if excludes:
        bool_q["must_not"] = excludes
    return bool_q


# -------------------------------------------------------------- accessors

def hits_of(data):
    """The result rows, from the CLI envelope (`results`) or a raw ES body."""
    rows = data.get("results") if isinstance(data, dict) else None
    if isinstance(rows, list):
        return rows
    hits = (data or {}).get("hits") if isinstance(data, dict) else None
    if isinstance(hits, dict) and isinstance(hits.get("hits"), list):
        return hits["hits"]
    return []


def source_of(row):
    """The document body — the CLI flattens `_source` into the row itself."""
    src = row.get("_source") if isinstance(row, dict) else None
    return src if isinstance(src, dict) else (row if isinstance(row, dict) else {})


def get_path(obj, dotted):
    """A dotted lookup that works nested (`{"channel": {"id": 5}}`) or flat
    (`{"channel.id": 5}`) — the CLI emits both shapes."""
    if not isinstance(obj, dict):
        return None
    if dotted in obj:
        return obj[dotted]
    head, _, rest = dotted.partition(".")
    if head not in obj:
        return None
    return obj[head] if not rest else get_path(obj[head], rest)


def agg_root(data):
    return (data or {}).get("aggregations") or (data or {}).get("aggs") or {}


def extract_total(data):
    total = (data or {}).get("total")
    if isinstance(total, int):
        return total
    hits = (data or {}).get("hits")
    if isinstance(hits, dict):
        ht = hits.get("total")
        if isinstance(ht, dict) and isinstance(ht.get("value"), int):
            return ht["value"]
        if isinstance(ht, int):
            return ht
    return 0


def fragments_of(hit):
    """ES highlight fragments off one row → `[{"field", "text", "hits"}, ...]`.

    `hits` counts the marked matches inside the fragment, so a caller can show
    the fragment that carries the most of what it searched for instead of
    whichever field happened to come first.

    Works on a CLI row (highlight alongside the flattened source) or a raw ES
    hit. Fields come back in TOPIC_FIELDS order first, then whatever else
    highlighted. Text is tag-free, entity-unescaped and whitespace-collapsed;
    the `<<`/`>>` markers are KEPT so the caller can see what matched.
    """
    hl = (hit or {}).get("highlight") if isinstance(hit, dict) else None
    if not isinstance(hl, dict):
        return []
    ordered = [f for f in TOPIC_FIELDS if f in hl] + [f for f in hl if f not in TOPIC_FIELDS]
    out = []
    for field in ordered:
        frags = hl[field]
        if isinstance(frags, str):
            frags = [frags]
        if not isinstance(frags, list):
            continue
        for frag in frags:
            text = clean_text(frag, keep_markers=True)
            if text:
                out.append({"field": field, "text": text,
                            "hits": text.count(HIGHLIGHT_PRE)})
    return out


# ------------------------------------------------------------------- text

def clean_text(value, *, keep_markers=False):
    """Strip XML/HTML tags, unescape entities, collapse whitespace.

    Caption text is YouTube caption XML and is sometimes double-escaped
    (`&amp;#39;`), so a single unescape leaves `&#39;` behind — unescape to a
    fixed point. `keep_markers` protects the `<<`/`>>` highlight markers from
    the tag stripper.
    """
    if not isinstance(value, str):
        return ""
    text = value
    if keep_markers:
        text = text.replace(HIGHLIGHT_PRE, "\x00PRE\x00").replace(HIGHLIGHT_POST, "\x00POST\x00")
    text = TAG_RE.sub(" ", text)
    for _ in range(3):
        unescaped = html.unescape(text)
        if unescaped == text:
            break
        text = unescaped
    text = WS_RE.sub(" ", text).strip()
    if keep_markers:
        text = text.replace("\x00PRE\x00", HIGHLIGHT_PRE).replace("\x00POST\x00", HIGHLIGHT_POST)
    return text


def literal_terms(expression):
    """The literal anchors of a boolean group: quoted phrases and positive bare
    words. Anything negated — `-word`, `-"a phrase"`, `-(a | b)` and every
    token inside a negated group — is an excluded sense, never an anchor.
    Escaped quotes inside a phrase are decoded so the anchor matches plain
    text. Snippet windows are cut around these, so evidence never depends on
    the boolean expression itself."""
    terms, i, n = [], 0, len(expression)
    depth, negated_depth, negate_next = 0, None, False
    while i < n:
        c = expression[i]
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
            while j < n and expression[j] != '"':
                if expression[j] == "\\" and j + 1 < n:
                    buf.append(expression[j + 1])
                    j += 2
                    continue
                buf.append(expression[j])
                j += 1
            tok, i = "".join(buf).strip(), j + 1
        else:
            j = i
            while j < n and not expression[j].isspace() and expression[j] not in '()|"':
                j += 1
            tok, i = expression[i:j], j
        excluded = negate_next or negated_depth is not None
        negate_next = False
        if tok and not excluded and tok not in terms:
            terms.append(tok)
    return terms


def required_terms(expression):
    """The literal terms an sqs expression REQUIRES every match to carry.

    `simple_query_string` runs here with `default_operator: "and"`, so a bare
    word or quoted phrase at the top level is required, and so is any
    `+`-prefixed term. A term that only appears inside a parenthesised `|`
    group is NOT required (any one alternative satisfies it), and a `-` negated
    term — or anything inside a negated group — never is. Order follows the
    expression; duplicates collapse.

    Snippet ranking uses this: a fragment that marks the anchor every match
    shares is evidence, one that marks only the alternative that happened to
    fire is not.
    """
    terms, _, _ = _required_scan(str(expression or ""), 0, False)
    out = []
    for term in terms:
        if term not in out:
            out.append(term)
    return out


def required_is_alternation(expression):
    """True when the top level of an sqs expression is an unparenthesised `|`.

    Every term `required_terms` returned is then an ALTERNATIVE rather than a
    conjunct (`"cannes lions" | canneslions` anchors on either), so marking any
    one of them is full required evidence — see probe.marked_required.
    """
    _, has_or, _ = _required_scan(str(expression or ""), 0, False)
    return has_or


def _required_scan(expr, i, negated):
    """One parenthesised level → (required terms, whether it held a `|`, index after it)."""
    terms, has_or, n = [], False, len(expr)
    negate_next = negated
    while i < n:
        c = expr[i]
        if c.isspace():
            i += 1
            continue
        if c in "+-":
            negate_next = negated or c == "-"
            i += 1
            continue
        if c == "(":
            sub, sub_or, i = _required_scan(expr, i + 1, negate_next)
            if not sub_or and not negate_next:
                terms.extend(sub)
            negate_next = negated
            continue
        if c == ")":
            return terms, has_or, i + 1
        if c == "|":
            has_or = True
            negate_next = negated
            i += 1
            continue
        if c == '"':
            j, buf = i + 1, []
            while j < n and expr[j] != '"':
                if expr[j] == "\\" and j + 1 < n:
                    buf.append(expr[j + 1])
                    j += 2
                    continue
                buf.append(expr[j])
                j += 1
            tok, i = "".join(buf).strip(), j + 1
        else:
            j = i
            while j < n and not expr[j].isspace() and expr[j] not in '()|"':
                j += 1
            tok, i = expr[i:j], j
        if tok and not negate_next:
            terms.append(tok)
        negate_next = negated
    return terms, has_or, i


def windows(text, terms, *, window=160, max_snippets=3):
    """Up to `max_snippets` non-overlapping ±`window`-char KWIC windows.

    The local fallback for when a query ran without `--highlight`. Terms are
    tried in order and share the snippet budget.
    """
    if not text or not terms:
        return []
    if isinstance(terms, str):
        terms = [terms]
    out = []
    for term in terms:
        if len(out) >= max_snippets:
            break
        out.extend(_windows_one(text, term, window, max_snippets - len(out)))
    return out


def _windows_one(text, keyword, half, max_snips):
    if not text or not keyword or max_snips <= 0:
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


# ------------------------------------------------------------------ cache

_CACHE_NS = None
_CACHE_NS_LOCK = threading.Lock()


def _whoami_identity():
    """The authenticated id/email `tl whoami --json` reports, or "" on any failure."""
    try:
        proc = subprocess.run(["tl", "whoami", "--json"], capture_output=True,
                              text=True, timeout=ES_TIMEOUT)
        user = (json.loads(proc.stdout).get("user") or {}) if proc.returncode == 0 else {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, AttributeError):
        user = {}
    return user.get("id") or user.get("email") or ""


def cache_namespace():
    """Sub-directory that isolates cache entries per API endpoint and
    authenticated identity. Credentials live in the OS keyring, so the only
    reliable identity is what the CLI itself reports: one `tl whoami` per run
    (~1s), retried once after `WHOAMI_RETRY_PAUSE` seconds because the same
    rate limit that slows a probe also answers that call.

    When both attempts fail the cache is NOT disabled — it falls back to a
    namespace shared by every account on this machine that talks to the same
    endpoint, and says so once on stderr. The trade-off: for the 24h TTL, two
    identities on one machine can read each other's cached responses. That is
    acceptable because these are corpus-wide content queries whose answers do
    not depend on who asked; disabling the cache instead cost a whole run its
    re-runs (every probe of the run paid full price).
    Resolved once under a lock so concurrent workers never see a half-set value."""
    global _CACHE_NS
    with _CACHE_NS_LOCK:
        if _CACHE_NS is None:
            ident = _whoami_identity()
            if not ident:
                time.sleep(WHOAMI_RETRY_PAUSE)
                ident = _whoami_identity()
            if ident:
                h = hashlib.sha256()
                h.update(f"format={CACHE_FORMAT}\n".encode())
                h.update(f"url={os.environ.get('TL_API_URL', '')}\n".encode())
                h.update(f"user={ident}\n".encode())
                _CACHE_NS = h.hexdigest()[:16]
            else:
                endpoint = os.environ.get("TL_API_URL") or SHARED_NS_FALLBACK
                _CACHE_NS = "shared-" + hashlib.sha1(endpoint.encode()).hexdigest()[:12]
                sys.stderr.write("probe cache: tl whoami unavailable, using the shared "
                                 "namespace\n")
        return _CACHE_NS or None


def _reset_cache_namespace():
    """Test hook — forget the resolved namespace so the next call re-runs `tl whoami`."""
    global _CACHE_NS
    with _CACHE_NS_LOCK:
        _CACHE_NS = None


def cache_key(body, *, highlight=False):
    """A response's cache key. `highlight` is part of it: the same body run with
    and without `--highlight` comes back with different content."""
    payload = json.dumps(body, sort_keys=True, ensure_ascii=False)
    if highlight:
        payload = "highlight\n" + payload
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _cache_path(cache_dir, body, highlight):
    ns = cache_namespace() if cache_dir else None
    if not ns:
        return None
    return os.path.join(cache_dir, ns, cache_key(body, highlight=highlight) + ".json")


def cache_load(cache_dir, body, ttl_hours, *, highlight=False):
    """The cached response for `body` when it is younger than the TTL."""
    path = _cache_path(cache_dir, body, highlight)
    if not path:
        return None
    try:
        if time.time() - os.path.getmtime(path) > ttl_hours * 3600:
            return None
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def cache_store(cache_dir, body, data, *, highlight=False):
    path = _cache_path(cache_dir, body, highlight)
    if not path:
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass  # the cache is an accelerator, never a failure


def run_es_cached(body, *, cache_dir, ttl_hours, no_cache=False, **run_kwargs):
    """`run_es`, served from disk when a fresh copy is there. → (data, cache_hit)."""
    highlight = bool(run_kwargs.get("highlight"))
    if not no_cache:
        data = cache_load(cache_dir, body, ttl_hours, highlight=highlight)
        if data is not None:
            return data, True
    data = run_es(body, **run_kwargs)
    if not no_cache:
        cache_store(cache_dir, body, data, highlight=highlight)
    return data, False


# --------------------------------------------------------------- parallel

def reject_option_like(parser, values, what="keyword"):
    """Refuse positional values that start with `--` — a mistyped flag.

    Positionals are parsed intermixed with options, so a typo like `--sinse`
    would otherwise be searched for as a keyword instead of being reported.
    """
    bad = [str(v) for v in (values or []) if str(v).startswith("--")]
    if bad:
        parser.error(f"unknown option(s) {', '.join(bad)}: "
                     f"a positional {what} cannot start with '--'")


def parallel_map(fn, items, *, workers=DEFAULT_WORKERS):
    """`fn` over `items` concurrently; results in INPUT order.

    An item that raises has its exception captured as that slot's result, so
    one bad candidate never aborts the batch. Nothing is raised to the caller.
    """
    items = list(items)
    if not items:
        return []
    if workers is None or workers <= 1 or len(items) == 1:
        out = []
        for it in items:
            try:
                out.append(fn(it))
            except Exception as exc:  # noqa: BLE001 — captured per item, by contract
                out.append(exc)
        return out
    results = [None] * len(items)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = {pool.submit(fn, it): i for i, it in enumerate(items)}
        for fut in concurrent.futures.as_completed(futures):
            i = futures[fut]
            try:
                results[i] = fut.result()
            except Exception as exc:  # noqa: BLE001 — captured per item, by contract
                results[i] = exc
    return results


# ---------------------------------------------------------------- run I/O

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def write_json_atomic(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path, what="file"):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(f"could not read {what} {path}: {exc}")


def record_event(run_dir, script, argv, started, output_summary):
    """One event file per script invocation under `<run_dir>/events/` — the run
    ledger the skill's self-check reads. No shared file, no concurrent writers:
    each process writes only its own event. Never raises."""
    if not run_dir:
        return None
    try:
        events = os.path.join(run_dir, "events")
        os.makedirs(events, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = os.path.join(events, f"{stamp}-{script}-{os.getpid()}.json")
        record = {
            "script": script,
            "argv": list(argv or []),
            "started": now_iso(),
            "elapsed_seconds": round(time.monotonic() - started, 1) if started else None,
            "output": output_summary,
        }
        # Every script reports its own cost under `output.timing`, in its own
        # output shape. Copying the three shared numbers to the top level lets a
        # ledger summary add up a run without knowing any of those shapes.
        timing = output_summary.get("timing") if isinstance(output_summary, dict) else None
        if isinstance(timing, dict):
            for key in ("elapsed_seconds", "es_calls", "cache_hits"):
                if timing.get(key) is not None:
                    record[key] = timing[key]
        write_json_atomic(path, record)
        return path
    except OSError:
        return None


def stdin_is_readable():
    """True only when stdin is a real pipe or regular file.

    Agent harnesses (Claude Code's Bash tool among them) hand scripts a stdin
    that is an open unix socket: not a TTY, never at EOF. `sys.stdin.read()`
    on it blocks forever — before any ES call, with nothing on stderr. Only
    read stdin when someone actually piped or redirected something into it.
    """
    try:
        mode = os.fstat(sys.stdin.fileno()).st_mode
    except (OSError, ValueError, AttributeError):
        return False
    return stat.S_ISFIFO(mode) or stat.S_ISREG(mode)


def emit(obj, *, run_dir=None, script=None, argv=None, started=None):
    """Print one JSON object on stdout and append it to the run ledger."""
    print(json.dumps(obj, ensure_ascii=False))
    if script:
        record_event(run_dir, script, argv if argv is not None else sys.argv[1:], started, obj)
