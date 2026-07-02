#!/usr/bin/env python3
"""Turn a validated keyword set into the skill's final deliverable.

Pure string assembly — no Elasticsearch, no `tl` calls, no credits. Takes the
keyword groups that survived probing + relevance validation and emits:

  1. `filter_set`   — the platform-native shape (keywords + per-keyword
                      content-field overrides + per-keyword exclude flags +
                      operator) that the ThoughtLeaders FilterSet stores.
  2. `report_link`  — a clickable inline deep link that opens a report in the
                      web app with this keyword filter already applied (no
                      saved record, no credits); the filter travels in the
                      URL's `keyword_groups` / `term_operator` /
                      `content_fields` params.
  3. `report_config`— a config you can hand to `tl reports create --config-file`
                      to persist a named, shareable report (returns a
                      `?campaign=<id>` link).

Before emitting, it prunes union-redundant *include* keywords — a keyword whose
phrase is fully contained in another kept include keyword adds no documents to
an OR union, so the broader phrase is kept and the redundant one is logged under
`pruned`. (Run this only AFTER over-broad/off-intent keywords are removed by the
validation step — see probe.py's note.) Boolean-group keywords (text using
simple_query_string operators like `|` / `-` / `()`) are left intact — their
document set isn't captured by their tokens, so the pruner can't reason about
them safely (see is_boolean_group).

Input (stdin JSON):
    {
      "operator": "OR",                 # how includes combine (default OR)
      "report_type": "channels",        # channels | videos | brands
      "title": "Crypto channels",       # optional
      "description": "...",             # optional
      "default_content_fields": [...],  # optional; defaults by report_type
      "groups": [
        {"text": "tiktok shop", "content_fields": ["title","summary","transcript"]},
        {"text": "scam", "exclude": true}
      ]
    }

Output (stdout): a single JSON object — see OUTPUT CONTRACT at the bottom.
"""
import argparse
import json
import re
import sys
from urllib.parse import quote

DEFAULT_APP_URL = "https://app.thoughtleaders.io"
_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
# A keyword group's text is a simple_query_string. These characters turn it into
# a *boolean query* — `|` union, `-` negation, `()` grouping, `"` phrase, `*`
# prefix, `~` fuzzy/slop, `+` required — rather than a plain phrase. The pruner's
# token-containment rule only implies a document-subset for plain phrases (where
# tokens ARE the query), so any group carrying one of these is treated as opaque.
_SQS_OPERATOR_RE = re.compile(r'[-+|()"*~]')

# Tokenizer for translating a boolean group's SQS text into the web app's
# keyword syntax: quoted phrases (kept whole), parens, the standalone `|`
# operator, and bare tokens (which may carry a +/- prefix).
_SQS_TOKEN_RE = re.compile(
    r'"(?:[^"\\]|\\.)*"'   # quoted phrase
    r"|\("                  # open paren
    r"|\)"                  # close paren
    r"|\|"                  # OR operator
    r"|[^\s()|\"]+",        # bare token (may start with + or -)
    re.UNICODE,
)

# STRUCTURAL boolean markers — the ones that mean "this text is a boolean
# query, translate it": `|`, parens, quotes, or a +/- PREFIX on a token
# (start-of-text or whitespace/paren before the sign). Deliberately narrower
# than _SQS_OPERATOR_RE: an in-word hyphen/plus (`e-commerce`, `covid-19`,
# `disney+`) is part of the phrase, and rewriting such a phrase into an AND
# of separate terms would silently broaden it beyond what was probed.
_STRUCTURAL_BOOL_RE = re.compile(r'[|()"]|(?:^|(?<=[\s(]))[+-](?=\S)')

# Uppercase word operators in the report-link keyword grammar. A plain phrase
# containing one of these as a standalone word (`rock AND roll`) must ship
# fully quoted, or the word would act as an operator instead of the phrase
# text the probe measured.
_OPERATOR_WORD_RE = re.compile(r"(?<!\S)(AND|OR|NOT)(?!\S)")

# report_type name -> (app hash-route slug, FilterSet report_type int).
# "videos" and "content" are synonyms for the same content report.
REPORT_TYPES = {
    "videos": ("content", 1),
    "content": ("content", 1),
    "brands": ("brands", 2),
    "channels": ("thoughtleaders", 3),
}

# Valid ContentField enum values (what the FilterSet / report link accept). Both
# article and channel fields are allowed on any report type — cross-field search
# (a topic in the video AND in the channel description) is intentional. We
# validate only that fields are real enum values, to catch typos / wrong names.
VALID_CONTENT_FIELDS = {
    "content", "title", "summary", "transcript", "channel.channel_name", "hashtags",
    "channel_description", "channel_description_ai", "channel_topic_description",
    "channel_outreach_email", "channel_social_links",
}

# Default content fields (ContentField enum values) by report type.
DEFAULT_FIELDS = {
    "videos": ["title", "summary", "transcript"],
    "content": ["title", "summary", "transcript"],
    "channels": ["title", "summary", "transcript", "channel_description", "channel_topic_description"],
    "brands": ["title", "summary", "transcript"],
}


def tokens(text):
    return _TOKEN_RE.findall(text.lower())


def is_contiguous_sublist(needle, haystack):
    n, h = len(needle), len(haystack)
    if n == 0 or n >= h:
        return False
    return any(haystack[i:i + n] == needle for i in range(h - n + 1))


def _strip_quoted_spans(text):
    """Text with double-quoted spans replaced by a placeholder token — for
    operator checks that only apply outside quotes (quoted content is always
    literal phrase text). The placeholder is a word char so a `-` glued to a
    quoted phrase does not read as detached."""
    return re.sub(r'"(?:[^"\\]|\\.)*"', "q", text)


def sqs_to_app_syntax(text):
    """Translate a boolean group's SQS text into the report-link keyword grammar.

    Keyword text in a report link / saved FilterSet uses the platform's own
    grammar — uppercase word operators AND / OR / NOT, parentheses for
    precedence, double-quoted phrases. Raw SQS operator characters (`|`, `+`,
    a bare `-`) are NOT operators there: they fold into the surrounding
    phrase and match nothing useful. So the deliverable must speak that
    grammar, not SQS.

    Mapping (input is the SQS the probes ran, i.e. `--mode sqs` semantics with
    default_operator "and"):
      * `a | b`            -> `"a" OR "b"`
      * `+a`, bare-adjacent `a b` -> explicit `AND` joins (in link grammar a
        bare word run is one adjacent phrase, so every join must be spelled out)
      * `-a` / `-(...)`    -> `AND NOT "a"` / `AND NOT (...)` (leading `-`
        becomes a bare `NOT`)
      * quoted phrases pass through unchanged; bare terms are double-quoted so
        nothing is ever re-interpreted
    Plain-phrase text (no STRUCTURAL operators — `|`, parens, quotes, or a
    +/- prefixing a token; an in-word `-`/`+` like `e-commerce` is just part
    of the phrase) is returned unchanged, except that a plain phrase carrying
    a standalone uppercase AND/OR/NOT word is wrapped in quotes so the word
    stays phrase text instead of acting as an operator.

    Raises ValueError for `*` (prefix), `~` (fuzzy/slop) and `\\` (escape)
    outside quotes, and for a detached `-`/`+` (`crypto - scam`) — link/filter
    text does not support the first three, and a detached minus was a NO-OP in
    the probe (SQS drops it), so shipping it as an exclusion would invert the
    validated semantics. Glue the sign (`-scam`) and re-probe, or enumerate
    variants (`retire*` -> `(retire | retiring | retirement)`).
    """
    unquoted = _strip_quoted_spans(text)
    if "*" in unquoted or "~" in unquoted:
        raise ValueError(
            "prefix (*) / fuzzy-slop (~) operators cannot ship in a report "
            "filter. Enumerate the variants instead, e.g. "
            "retire* -> (retire | retiring | retirement)."
        )
    if "\\" in text:
        raise ValueError(
            "backslash escapes do not survive in report-filter text — "
            "rewrite the group without them."
        )

    if not _STRUCTURAL_BOOL_RE.search(text):
        # Plain phrase — ships as-is (a bare word run is one adjacent phrase,
        # matching the phrase-mode probe). Quote it whole if it carries a
        # standalone uppercase operator word, so the word stays phrase text.
        if _OPERATOR_WORD_RE.search(text):
            return f'"{text}"'
        return text

    # Boolean group — a detached minus was a NO-OP in the probe (SQS drops
    # it), so shipping it as an exclusion would invert validated semantics.
    if re.search(r"(?:^|\s)-(?:\s|$)", unquoted):
        raise ValueError(
            "detached '-' (minus followed by whitespace) was a no-op in the "
            "probe — glue it to its term (e.g. -scam) and re-probe before delivery."
        )

    out = []          # emitted app-syntax pieces
    pending_not = False

    def emit(piece, *, joinable):
        """Append a piece, inserting an explicit AND join when two joinable
        pieces (terms / groups) sit adjacent with no operator between them."""
        nonlocal pending_not
        if joinable and out and out[-1] not in ("OR", "AND", "NOT", "("):
            out.append("AND")
        if pending_not:
            out.append("NOT")
            pending_not = False
        out.append(piece)

    for match in _SQS_TOKEN_RE.finditer(text):
        tok = match.group(0)
        if tok == "|":
            out.append("OR")
        elif tok == "(":
            emit("(", joinable=True)
        elif tok == ")":
            out.append(")")
        elif tok.startswith('"'):
            emit(tok, joinable=True)
        else:
            # bare token; +/- count as operators only when they PREFIX it
            if tok == "+":
                # detached '+' is the infix AND operator in SQS
                out.append("AND")
                continue
            negate = False
            while tok and tok[0] in "+-" and len(tok) > 1:
                negate = negate or tok[0] == "-"
                tok = tok[1:]
            if tok == "-":
                # a lone '-' glued to a following paren: `-(a | b)`
                negate, tok = True, ""
            if negate:
                # `-x` means AND NOT x. Add the join now, then arm NOT for the
                # next emitted piece — this token, or the `(` of `-(a | b)`.
                if out and out[-1] not in ("OR", "AND", "NOT", "("):
                    out.append("AND")
                pending_not = True
            if not tok:
                continue
            emit(f'"{tok}"', joinable=not negate)
    return " ".join(out)


def is_boolean_group(text):
    """True when text uses simple_query_string operators (so it's a boolean query,
    not a plain phrase).

    A boolean group's document set is NOT characterised by its token bag: `|`
    unions in extra docs and `-` removes docs, neither of which token-containment
    can see. So prune_redundant must treat such groups as opaque — never prune
    one, and never use one to prune another — or it silently drops documents
    (e.g. `("tiktok shop" | dropshipping)` flattens to the same tokens as the
    plain phrase `tiktok shop` and would be wrongly pruned, losing every
    `dropshipping` video).
    """
    return bool(_SQS_OPERATOR_RE.search(text))


def prune_redundant(groups, operator):
    """Drop include groups subsumed by a broader kept include group (OR only).

    Returns (kept_groups, pruned). A group G is redundant when another kept
    include group H has H-tokens as a contiguous run inside G-tokens (so G's
    docs are a subset of H's). Exclude groups are never pruned.

    Pruning only ever happens between two **plain phrases**, where token
    containment really does imply a document subset. Boolean groups (their text
    uses simple_query_string operators — see is_boolean_group) are opaque: never
    pruned, never used as the broader pruner.
    """
    if operator != "OR":
        return groups, []
    includes = [g for g in groups if not g.get("exclude")]
    excludes = [g for g in groups if g.get("exclude")]
    tok = {id(g): tokens(g["text"]) for g in includes}
    kept, pruned = [], []
    for g in includes:
        if is_boolean_group(g["text"]):
            kept.append(g)                       # opaque: never pruned
            continue
        broader = next(
            (h for h in includes
             if h is not g
             and not is_boolean_group(h["text"])  # opaque: never prunes another
             and is_contiguous_sublist(tok[id(h)], tok[id(g)])),
            None,
        )
        if broader is not None:
            pruned.append({"text": g["text"], "redundant_with": broader["text"]})
        else:
            kept.append(g)
    return kept + excludes, pruned


def render_expression(groups, operator):
    """Human-readable boolean rendering of the whole filter (app syntax).

    Recorded alongside saved reports so the filter is reproducible at a
    glance: include groups joined by the filter operator, whole-filter
    excludes appended as `AND NOT (...)`.
    """
    def wrap(text):
        return f"({text})" if (is_boolean_group(text) or " " in text) else text

    includes = [wrap(g["text"]) for g in groups if not g.get("exclude")]
    excludes = [wrap(g["text"]) for g in groups if g.get("exclude")]
    expr = f" {operator} ".join(includes)
    for e in excludes:
        expr += f" AND NOT {e}"
    return expr


def build_filter_set(groups, operator, default_fields):
    """Platform FilterSet shape: keywords + positional per-keyword maps.

    `keyword_content_fields_map` / `keyword_exclude_map` are LISTS indexed by
    keyword position (null / false where a keyword uses the defaults) — the
    shape a saved FilterSet stores. Both lists are always emitted full-length:
    a truthy content-fields map is also what keeps a saved report from
    re-deriving a legacy combined-content filter on top of the keyword groups
    (which would AND an excluded keyword back in and zero the results).
    """
    keywords, cf_list, ex_list = [], [], []
    for g in groups:
        keywords.append(g["text"])
        fields = g.get("content_fields")
        cf_list.append(list(fields) if fields and list(fields) != list(default_fields) else None)
        ex_list.append(bool(g.get("exclude")))
    return {
        "keywords": keywords,
        "keyword_operator": operator,
        "content_fields": list(default_fields),
        "keyword_content_fields_map": cf_list,
        "keyword_exclude_map": ex_list,
    }


def build_inline_link(groups, operator, slug, default_fields, app_url):
    """Inline deep link: encodes keyword_groups/term_operator/content_fields in the URL."""
    kg = []
    for g in groups:
        entry = {"text": g["text"]}
        fields = g.get("content_fields")
        if fields and list(fields) != list(default_fields):
            entry["content_fields"] = list(fields)
        if g.get("exclude"):
            entry["exclude"] = True
        kg.append(entry)
    kg_json = json.dumps(kg, ensure_ascii=False, separators=(",", ":"))
    params = (
        f"keyword_groups={quote(kg_json, safe='')}"
        f"&term_operator={operator}"
        f"&content_fields={quote(','.join(default_fields), safe='')}"
    )
    return f"{app_url}/#/{slug}?{params}"


def build_report_config(filter_set, report_type_int, title, description):
    """Config for `tl reports create --config-file` (persists a named report)."""
    return {
        "type": 2,
        "report_type": report_type_int,
        "report_title": title,
        "report_description": description,
        "filterset": filter_set,
    }


def main():
    ap = argparse.ArgumentParser(
        description="Build the keyword-research deliverable (filter set + report link) from validated groups."
    )
    ap.add_argument("--app-url", default=DEFAULT_APP_URL, help=f"App base URL (default {DEFAULT_APP_URL})")
    args = ap.parse_args()

    if sys.stdin.isatty():
        sys.exit("pipe a JSON spec on stdin (see module docstring)")
    try:
        spec = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        sys.exit(f"invalid JSON on stdin: {exc}")

    operator = (spec.get("operator") or "OR").upper()
    if operator not in ("AND", "OR"):
        sys.exit("operator must be AND or OR")
    report_type = (spec.get("report_type") or "channels").lower()
    if report_type not in REPORT_TYPES:
        sys.exit(f"report_type must be one of {sorted(REPORT_TYPES)}")
    slug, report_type_int = REPORT_TYPES[report_type]
    default_fields = spec.get("default_content_fields") or DEFAULT_FIELDS[report_type]

    groups = spec.get("groups") or []
    groups = [g for g in groups if isinstance(g, dict) and str(g.get("text", "")).strip()]
    if not groups:
        sys.exit("provide at least one group with non-empty 'text'")
    for g in groups:
        g["text"] = str(g["text"]).strip()

    # Validate every content field is a real ContentField enum value (catches
    # typos / ES-path names like 'ai.topic_descriptions' used by mistake).
    used_fields = set(default_fields)
    for g in groups:
        used_fields.update(g.get("content_fields") or [])
    unknown = sorted(f for f in used_fields if f not in VALID_CONTENT_FIELDS)
    if unknown:
        sys.exit(
            f"unknown content_fields {unknown}; use ContentField enum values "
            f"(e.g. title, summary, transcript, channel_description, "
            f"channel_topic_description) — not raw ES paths. Valid: {sorted(VALID_CONTENT_FIELDS)}"
        )

    kept, pruned = prune_redundant(groups, operator)

    # Translate boolean-group SQS text (what the probes ran) into the
    # report-link keyword grammar (uppercase AND/OR/NOT + parens + quoted
    # atoms). Raw SQS operator characters are literal text in a link, so an
    # untranslated group would silently match nothing useful.
    translated = []
    for g in kept:
        try:
            app_text = sqs_to_app_syntax(g["text"])
        except ValueError as exc:
            sys.exit(f"group {g['text']!r}: {exc}")
        if app_text != g["text"]:
            translated.append({"from": g["text"], "to": app_text})
            g["text"] = app_text

    filter_set = build_filter_set(kept, operator, default_fields)
    report_link = build_inline_link(kept, operator, slug, default_fields, args.app_url)
    title = spec.get("title") or f"{report_type.title()} — keyword search"
    description = spec.get("description") or ""
    report_config = build_report_config(filter_set, report_type_int, title, description)

    print(json.dumps({
        "report_type": report_type,
        "operator": operator,
        "expression": render_expression(kept, operator),
        "filter_set": filter_set,
        "report_link": report_link,
        "report_config": report_config,
        "pruned": pruned,
        "translated": translated,
    }, ensure_ascii=False, indent=2))


# OUTPUT CONTRACT (stdout, single JSON object):
# {
#   "report_type": "channels"|"videos"|"brands",
#   "operator": "OR"|"AND",
#   "expression": "(g1) OR (g2) AND NOT (x)",   # whole-filter rendering (app syntax) — record with saved reports
#   "filter_set": { keywords, keyword_operator, content_fields,
#                   keyword_content_fields_map?, keyword_exclude_map? },
#   "report_link": "https://app.thoughtleaders.io/#/<slug>?keyword_groups=...&term_operator=...",
#   "report_config": { ... pass to `tl reports create --config-file` ... },
#   "pruned": [ {"text": "...", "redundant_with": "..."} ],
#   "translated": [ {"from": "<sqs text>", "to": "<app-syntax text>"} ]
# }
# Group text in filter_set / report_link / report_config is the report-link
# keyword grammar: uppercase AND / OR / NOT, parentheses, double-quoted atoms.
# Input group text written as simple_query_string (probe `--mode sqs` form) is
# translated automatically; `*` prefix and `~` fuzzy/slop are not supported in
# link/filter text and are rejected — enumerate the variants instead.
# keyword_content_fields_map / keyword_exclude_map are positional LISTS
# (null / false = defaults), one entry per keyword.
if __name__ == "__main__":
    main()
