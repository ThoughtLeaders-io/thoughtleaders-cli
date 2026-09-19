#!/usr/bin/env python3
"""Turn the keyword-entity-resolver's name list into probe-ready candidates.

The `keyword-entity-resolver` sub-agent does the web reading and returns a
compact JSON of canonical NAMES (entities, aliases, insider terms, hashtags,
collisions). This script does the deterministic glue so the model spends no
tokens on it:

  * generate Elasticsearch tokenization variants for every name (the standard
    analyzer makes spaced / solid / spelled-out forms DISTINCT tokens, so each
    must be probed — see references/elasticsearch-content-search.md → Tokenization),
  * fold a name's variants into one boolean OR group `("fable 5" | fable5)`,
  * pair rename aliases into a single `(old | new)` group spanning the timeline,
  * dedupe every variant against the candidates the model already brainstormed
    (`--existing`) so no probe credit or token is spent twice,
  * pass collisions straight through as a polluter watch-list for the Phase 4
    NOT-rescue.

The `probe_candidates` array it emits is exactly the shape `probe.py` reads on
stdin (per-item `{"sqs"|"phrase", "label"}` dicts), so the two pipe together.

Tokenization rules encoded (from the reference):
  * hyphen tokenizes IDENTICALLY to a space (`fable-5` == `fable 5`) → never
    emitted as a separate candidate,
  * the solid form (`fable5`) is a DISTINCT token → emitted,
  * the spelled-out small-integer form (`fable five`) is DISTINCT → emitted,
  * `#fable5` reduces to the solid token in text fields, so the solid form
    already covers it; hashtags are surfaced separately for optional targeting
    of the `hashtags` content field, not as duplicate text probes.

Usage:
    # resolver.json is the sub-agent's strict JSON reply
    python3 expand_entities.py --existing "cannes lions" "advertising awards" < resolver.json > expanded.json
    # pipe the candidates straight into probe.py:
    python3 expand_entities.py --probe-batch < resolver.json | python3 probe.py --samples 5
"""
import argparse
import json
import re
import sys

MAX_INSIDER_DEFAULT = 40

_ONES = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
         "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
         "sixteen", "seventeen", "eighteen", "nineteen"]
_TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy",
         "eighty", "ninety"]

# A standalone 1-2 digit integer NOT glued to a decimal point or another digit.
_SMALL_INT_RE = re.compile(r"(?<![\d.])\b(\d{1,2})\b(?![\d.])")
_NONWORD_RE = re.compile(r"[\W_]+", re.UNICODE)  # everything but letters/digits


def number_word(n):
    """Spell a 0-99 integer the way people type it in a search ('twenty one')."""
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    return _TENS[tens] if ones == 0 else f"{_TENS[tens]} {_ONES[ones]}"


def spell_out_numbers(text):
    """Replace standalone small integers with words; return None if nothing changed.

    'fable 5' -> 'fable five'; 'cannes lions 2026' -> None (4-digit, left alone);
    'gpt 4.8' -> None (decimal, left alone).
    """
    replaced = _SMALL_INT_RE.sub(lambda m: number_word(int(m.group(1))), text)
    return replaced if replaced != text else None


def solid(text):
    """The single-token handle form: drop all separators AND punctuation.

    'fable 5' / 'fable-5' -> 'fable5'; 'Print & Publishing Lions' ->
    'PrintPublishingLions'; "Palme d'Or" -> 'PalmedOr'. Unicode letters/digits
    are kept (re.UNICODE), so accented names survive.
    """
    return _NONWORD_RE.sub("", text)


def _norm(text):
    """Case/space-insensitive key for dedupe."""
    return re.sub(r"\s+", " ", text.strip().lower())


def _dedupe_ci(items):
    """Order-preserving, case-insensitive unique."""
    out, seen = [], set()
    for it in items:
        k = _norm(it)
        if k and k not in seen:
            seen.add(k)
            out.append(it)
    return out


def text_variants(name):
    """Distinct ES text-field forms to probe for a single name.

    Always the as-given form; the solid form when the name has a separator and
    differs; the spelled-out form when it carries a small integer. The hyphenated
    form is omitted on purpose — it tokenizes identically to the spaced form.
    """
    base = name.strip()
    if not base:
        return []
    forms = [base]
    s = solid(base)
    if s and _norm(s) != _norm(base):
        forms.append(s)
    spelled = spell_out_numbers(base)
    if spelled:
        forms.append(spelled)
    return _dedupe_ci(forms)


def hashtag_form(name):
    """The solid hashtag form of a name, or None for an empty name."""
    s = solid(name.strip())
    return f"#{s}" if s else None


def _quote(form):
    """Quote a multi-word phrase for simple_query_string; leave a single token bare."""
    return f'"{form}"' if re.search(r"\s", form) else form


def group_query(forms):
    """Fold variant forms into one simple_query_string OR group."""
    return "(" + " | ".join(_quote(f) for f in forms) + ")"


def _candidate_from_forms(forms, label):
    """A probe.py stdin item for a family's surviving forms (None if empty)."""
    if not forms:
        return None
    if len(forms) == 1:
        return {"phrase": forms[0], "label": label}
    return {"sqs": group_query(forms), "label": label}


def _collect_names(resolver, max_insider):
    """Ordered (name, label, kind) families from the resolver JSON, minus aliases.

    Aliases are handled separately so old+new fold into one group.
    """
    fams = []
    for e in resolver.get("entities", []) or []:
        if isinstance(e, dict) and str(e.get("name", "")).strip():
            fams.append((e["name"].strip(), e["name"].strip(), e.get("kind", "other")))
    insider = [t for t in (resolver.get("insider_terms", []) or []) if str(t).strip()]
    for t in insider[:max_insider]:
        fams.append((t.strip(), t.strip(), "insider"))
    return fams


def expand(resolver, existing, max_insider):
    """Build probe candidates + family detail from a resolver JSON object."""
    seen = {_norm(x) for x in existing}          # forms already covered → skip
    deduped = []

    def keep_new(forms):
        """Drop forms already in `existing` or already emitted; record drops."""
        kept = []
        for f in forms:
            k = _norm(f)
            if k in seen:
                deduped.append(f)
                continue
            seen.add(k)
            kept.append(f)
        return kept

    probe_candidates, families = [], []

    # Entity + insider families.
    for name, label, kind in _collect_names(resolver, max_insider):
        forms = keep_new(text_variants(name))
        ht = hashtag_form(name)
        fam = {"label": label, "kind": kind,
               "forms": forms, "hashtag": ht,
               "query": group_query(forms) if len(forms) > 1 else (forms[0] if forms else None)}
        families.append(fam)
        cand = _candidate_from_forms(forms, label)
        if cand:
            probe_candidates.append(cand)

    # Rename aliases → one (old | new) group spanning the timeline.
    aliases = []
    for a in resolver.get("aliases", []) or []:
        if not isinstance(a, dict):
            continue
        old, new = str(a.get("old", "")).strip(), str(a.get("new", "")).strip()
        names = [n for n in (old, new) if n]
        if not names:
            continue
        forms = keep_new(_dedupe_ci([v for n in names for v in text_variants(n)]))
        label = f"rename: {old or '?'} -> {new or '?'}"
        rec = {"old": old or None, "new": new or None, "since": a.get("since"),
               "forms": forms, "query": group_query(forms) if forms else None}
        aliases.append(rec)
        cand = _candidate_from_forms(forms, label)
        if cand:
            probe_candidates.append(cand)

    hashtags = _dedupe_ci(
        [h for h in (resolver.get("hashtags", []) or []) if str(h).strip()]
        + [f["hashtag"] for f in families if f["hashtag"]]
    )
    collisions = [c for c in (resolver.get("collisions", []) or []) if isinstance(c, dict)]

    return {
        "probe_candidates": probe_candidates,
        "families": families,
        "aliases": aliases,
        "hashtags": hashtags,
        "collisions": collisions,          # passthrough → Phase 4 polluter watch-list
        "deduped": deduped,
        "recency": resolver.get("recency"),
        "notes": resolver.get("notes"),
        "sources": resolver.get("sources", []),
        "counts": {
            "families": len(families),
            "aliases": len(aliases),
            "probe_candidates": len(probe_candidates),
            "deduped": len(deduped),
        },
    }


def load_resolver():
    if sys.stdin.isatty():
        sys.exit("pipe the keyword-entity-resolver JSON on stdin")
    raw = sys.stdin.read().strip()
    if not raw:
        sys.exit("empty stdin; expected the resolver JSON object")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"invalid resolver JSON on stdin: {exc}")
    if not isinstance(data, dict):
        sys.exit("resolver JSON must be an object")
    return data


def main():
    ap = argparse.ArgumentParser(
        description="Expand resolver names into ES tokenization variants + probe-ready candidates."
    )
    ap.add_argument("--existing", nargs="*", default=[],
                    help="Candidates the model already brainstormed; web variants matching these are dropped.")
    ap.add_argument("--max-insider", type=int, default=MAX_INSIDER_DEFAULT,
                    help=f"Cap on insider_terms folded in (default {MAX_INSIDER_DEFAULT}).")
    ap.add_argument("--probe-batch", action="store_true",
                    help="Print ONLY the probe_candidates array (pipe straight into probe.py).")
    args = ap.parse_args()
    if args.max_insider < 0:
        sys.exit("--max-insider must be >= 0")

    out = expand(load_resolver(), args.existing, args.max_insider)
    if args.probe_batch:
        print(json.dumps(out["probe_candidates"], ensure_ascii=False))
    else:
        print(json.dumps(out, ensure_ascii=False, indent=2))


# OUTPUT CONTRACT
#   default (stdout): {
#     "probe_candidates": [{"sqs"|"phrase": str, "label": str}, ...],  # pipe to probe.py stdin
#     "families":   [{"label","kind","forms":[...],"hashtag","query"}],
#     "aliases":    [{"old","new","since","forms":[...],"query"}],
#     "hashtags":   ["#...", ...],          # for optional `hashtags` content-field targeting
#     "collisions": [{"term","other_meaning"}],  # passthrough -> Phase 4 NOT-rescue watch-list
#     "deduped":    ["form already covered by --existing", ...],
#     "recency","notes","sources","counts"
#   }
#   --probe-batch (stdout): [{"sqs"|"phrase": str, "label": str}, ...]   # the array only
if __name__ == "__main__":
    main()
