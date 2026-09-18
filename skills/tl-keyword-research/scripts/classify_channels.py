#!/usr/bin/env python3
"""Merge your channel verdicts onto the channel table — in code, not in prose.

Reads the evidence sheet's JSON (`evidence.py`) plus one or more verdict files,
validates every verdict against the evidence, and joins the survivors with the
intensity tiers and the optional relevance ranking.

A verdict file is either a bare JSON array of `{"channel_id", "verdict",
"evidence_quote"?, "adjacent_terms"?, "note"?}` objects, or — cheaper to write —
one TSV line per channel:

    12345<TAB>on_topic<TAB>…«Cannes Lions» Grand Prix…<TAB>young lions

`channel_id<TAB>verdict[<TAB>evidence_quote][<TAB>adjacent_terms comma-separated]`.
Blank lines and `#` comments are ignored; a bad line names its line number. The
format is detected per file (JSON when the first non-blank character is `[`), so
the two can be mixed across `--verdicts` files.

Coverage is enforced: an evidence channel with no verdict is listed under
`missing` and exits 2 unless `--allow-missing`, and channels with no evidence,
no fetch, an `unknown` verdict or a deadline skip are surfaced separately rather
than quietly dropped.

Usage:
    classify_channels.py --apply --evidence evidence.json --verdicts verdicts.json \
        --intensity intensity.json [--ranking ranked.json] [--allow-missing]

Output (stdout): see OUTPUT_SHAPE at the bottom.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_common as kw  # noqa: E402

VERDICTS = ("on_topic", "mixed", "off_topic", "unknown")
KEPT = ("on_topic", "mixed")
TIER_ORDER = {"core": 0, "recurring": 1, "occasional": 2, "one_off": 3, "untiered": 4}
NO_VERDICT_NOTE = "no verdict"


def _record(out, where, cid, verdict, quote, note, terms, allowed_ids):
    """Validate one verdict (whichever format it came in) and keep it."""
    if cid not in allowed_ids:
        sys.exit(f"{where}: channel_id {cid} is not in the evidence file; "
                 f"judged channels are {sorted(allowed_ids)}")
    if verdict not in VERDICTS:
        sys.exit(f"{where}: verdict must be one of {list(VERDICTS)}, got {verdict!r}")
    prior = out.get(cid)
    if prior is not None and prior["verdict"] != verdict:
        sys.exit(f"{where}: channel {cid} is judged twice in the same file with "
                 f"different verdicts ({prior['verdict']} then {verdict})")
    out[cid] = {"verdict": verdict, "evidence_quote": quote or "", "note": note or "",
                "adjacent_terms": [t for t in terms if t]}


def read_verdict_text(path):
    """The raw text of one verdict source (`-` = stdin)."""
    if path == "-":
        if not kw.stdin_is_readable():
            sys.exit("--verdicts -: nothing is piped on stdin")
        return sys.stdin.read()
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError as exc:
        sys.exit(f"could not read verdicts file {path}: {exc}")


def looks_like_json(text):
    """A verdict file is JSON when its first non-blank character is `[` (or `{`,
    which is JSON written wrong and gets the array message, not a TSV one)."""
    stripped = text.lstrip()
    return stripped.startswith("[") or stripped.startswith("{")


def parse_json_verdicts(text, path, allowed_ids):
    """The JSON array shape: `[{"channel_id", "verdict", ...}, ...]`."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        sys.exit(f"{path}: not valid JSON: {exc}")
    if not isinstance(data, list):
        sys.exit(f"{path}: expected a bare JSON array of verdict objects, got "
                 f"{type(data).__name__}")
    out = {}
    for n, item in enumerate(data):
        where = f"{path}[{n}]"
        if not isinstance(item, dict):
            sys.exit(f"{where}: expected an object, got {type(item).__name__}")
        cid = item.get("channel_id")
        if not isinstance(cid, int) or isinstance(cid, bool):
            sys.exit(f"{where}: channel_id must be an integer, got {cid!r}")
        terms = item.get("adjacent_terms")
        if terms is not None and (not isinstance(terms, list)
                                  or not all(isinstance(t, str) for t in terms)):
            sys.exit(f"{where}: adjacent_terms must be a list of strings")
        _record(out, where, cid, item.get("verdict"), item.get("evidence_quote"),
                item.get("note"), list(terms or []), allowed_ids)
    return out


def parse_tsv_verdicts(text, path, allowed_ids):
    """The compact shape: one line per channel,
    `channel_id<TAB>verdict[<TAB>evidence_quote][<TAB>adjacent_terms]`.
    Blank lines and `#` comments are skipped; errors name the line number."""
    out = {}
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        where = f"{path}:{n}"
        # Bounded split: the LAST column is free text, so an embedded tab in it
        # belongs to the note rather than starting a sixth column.
        cells = [c.strip() for c in line.split("\t", 4)]
        if len(cells) < 2 or not cells[1]:
            sys.exit(f"{where}: expected 'channel_id<TAB>verdict[<TAB>evidence_quote]"
                     f"[<TAB>adjacent_terms]', got {raw!r}")
        try:
            cid = int(cells[0])
        except ValueError:
            sys.exit(f"{where}: channel_id must be an integer, got {cells[0]!r}")
        quote = cells[2] if len(cells) > 2 else ""
        terms = ([t.strip() for t in cells[3].split(",")]
                 if len(cells) > 3 and cells[3] else [])
        note = cells[4] if len(cells) > 4 else ""
        _record(out, where, cid, cells[1], quote, note, terms, allowed_ids)
    return out


def load_verdict_file(path, allowed_ids):
    """One verdict file → `{channel_id: verdict object}`. Accepts the JSON array
    or the compact TSV; exits on any violation."""
    text = read_verdict_text(path)
    if looks_like_json(text):
        return parse_json_verdicts(text, path, allowed_ids)
    return parse_tsv_verdicts(text, path, allowed_ids)


def build_row(cid, evidence_row, intensity_row, judgment, rank):
    src = intensity_row or {}
    ev = evidence_row or {}
    return {
        "channel_id": cid,
        "name": ev.get("name") or src.get("name"),
        "tier": ev.get("tier") if ev.get("tier") is not None else src.get("tier"),
        "matching_uploads": ev.get("matching_uploads") if ev.get("matching_uploads") is not None
        else src.get("matching_uploads"),
        "recent_matching_uploads": (ev.get("recent_matching_uploads")
                                    if ev.get("recent_matching_uploads") is not None
                                    else src.get("recent_matching_uploads")),
        "topic_share": ev.get("topic_share") if ev.get("topic_share") is not None
        else src.get("topic_share"),
        "verdict": judgment["verdict"],
        "evidence_quote": judgment["evidence_quote"],
        "note": judgment["note"],
        "sponsorability": ev.get("sponsorability") or src.get("sponsorability"),
        "rank": rank,
    }


def sort_rows(rows):
    rows.sort(key=lambda r: (TIER_ORDER.get(r["tier"] or "untiered", 4),
                             -(r["matching_uploads"] or 0), r["channel_id"]))
    return rows


def main():
    ap = argparse.ArgumentParser(description="Merge channel verdicts onto the channel table.")
    ap.add_argument("--apply", action="store_true", required=True,
                    help="Apply the verdicts (the only mode).")
    ap.add_argument("--evidence", required=True, metavar="PATH", help="evidence.py output")
    ap.add_argument("--verdicts", action="append", required=True, metavar="PATH",
                    help="Verdicts — a JSON array or TSV lines "
                         "'channel_id<TAB>verdict[<TAB>quote][<TAB>adjacent_terms]' "
                         "(repeatable; later files override earlier ones; - = stdin)")
    ap.add_argument("--intensity", required=True, metavar="PATH",
                    help="search_channels.py --intensity output (tiers)")
    ap.add_argument("--ranking", metavar="PATH",
                    help="search_channels.py ranked output (relevance order)")
    ap.add_argument("--allow-missing", action="store_true",
                    help="Exit 0 even when evidence channels have no verdict.")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: record this invocation (argv, elapsed, output) as one event file under DIR/events/")
    args = ap.parse_args()
    started = time.monotonic()

    try:
        evidence = kw.read_json(args.evidence, "evidence file")
        intensity = kw.read_json(args.intensity, "intensity file")
        ranking = kw.read_json(args.ranking, "ranking file") if args.ranking else {}
    except kw.BatchError as exc:
        sys.exit(str(exc))

    ev_rows = {}
    for row in evidence.get("channels") or []:
        if isinstance(row, dict) and row.get("channel_id") is not None:
            ev_rows[row["channel_id"]] = row
    intensity_rows = {c["channel_id"]: c for c in (intensity.get("channels") or [])
                      if isinstance(c, dict) and c.get("channel_id") is not None}
    rank_of = {c["channel_id"]: n for n, c in enumerate(ranking.get("channels") or [], start=1)
               if isinstance(c, dict) and c.get("channel_id") is not None}

    judgments = {}
    for path in args.verdicts:
        judgments.update(load_verdict_file(path, set(ev_rows)))

    no_evidence = list(evidence.get("missing") or [])
    unresolved = list(evidence.get("unresolved") or [])
    failed_ids = [i for f in (evidence.get("failed") or []) for i in (f.get("channel_ids") or [])]
    # A channel whose evidence call found nothing, errored, or never ran carries
    # no snippets to judge, so it is not a coverage gap and never an `unknown`
    # row: it is reported once, under the not_validated bucket that explains it.
    unjudgeable = set(no_evidence) | set(unresolved) | set(failed_ids)

    missing = [cid for cid in ev_rows if cid not in judgments and cid not in unjudgeable]
    for cid in missing:
        judgments[cid] = {"verdict": "unknown", "evidence_quote": "",
                          "note": NO_VERDICT_NOTE, "adjacent_terms": []}

    kept, excluded, unknown, terms = [], [], [], defaultdict(list)
    for cid in ev_rows:
        judgment = judgments.get(cid)
        if judgment is None:
            continue
        row = build_row(cid, ev_rows[cid], intensity_rows.get(cid), judgment, rank_of.get(cid))
        for term in {t.strip().lower() for t in judgment["adjacent_terms"] if t.strip()}:
            terms[term].append(cid)
        if judgment["verdict"] in KEPT:
            kept.append(row)
        elif judgment["verdict"] == "off_topic":
            excluded.append(row)
        else:
            unknown.append(row)

    requested = set(ev_rows) | set(no_evidence) | set(unresolved) | set(failed_ids)
    not_fetched = [cid for cid in intensity_rows if cid not in requested]

    all_rows = kept + excluded + unknown
    verdict_counts = Counter(r["verdict"] for r in all_rows)
    by_tier = defaultdict(Counter)
    for row in all_rows:
        by_tier[row["tier"] or "untiered"][row["verdict"]] += 1

    out = {
        "judged": len(all_rows),
        "verdicts": {v: verdict_counts.get(v, 0) for v in VERDICTS},
        "by_tier": {t: dict(c) for t, c in sorted(
            by_tier.items(), key=lambda kv: TIER_ORDER.get(kv[0], 4))},
        "channels": sort_rows(kept),
        "excluded": sort_rows(excluded),
        "not_validated": {
            "unknown": sort_rows(unknown),
            "no_evidence": no_evidence,
            "not_fetched": not_fetched,
            "unresolved": unresolved,
            "failed": failed_ids,
        },
        "missing": missing,
        "adjacent_terms": [{"term": t, "channels": sorted(ids)}
                           for t, ids in sorted(terms.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
        "sponsorability_summary": {
            "reachable": sum(1 for r in kept if (r["sponsorability"] or {}).get("has_outreach_email")
                             or (r["sponsorability"] or {}).get("is_msn")
                             or (r["sponsorability"] or {}).get("is_tpp")),
            "msn": sum(1 for r in kept if (r["sponsorability"] or {}).get("is_msn")),
            "tpp": sum(1 for r in kept if (r["sponsorability"] or {}).get("is_tpp")),
        },
    }
    kw.emit(out, run_dir=args.run_dir, script="classify_channels", started=started)
    if missing and not args.allow_missing:
        sys.stderr.write(f"{len(missing)} evidence channels have no verdict "
                         f"({', '.join(str(i) for i in missing[:20])}) — judge them and apply "
                         "again, or pass --allow-missing\n")
        sys.exit(2)


# OUTPUT_SHAPE:
# {"judged": n, "verdicts": {"on_topic":n,"mixed":n,"off_topic":n,"unknown":n},
#  "by_tier": {"core":{verdict:n}, ..., "untiered":{...}},
#  "channels": [{"channel_id","name","tier","matching_uploads","recent_matching_uploads",
#                "topic_share","verdict","evidence_quote","note","sponsorability":{...},
#                "rank"}],                       # on_topic + mixed, tier order then size
#  "excluded": [same rows, verdict off_topic],   # surfaced, never silent
#  "not_validated": {"unknown":[rows], "no_evidence":[ids], "not_fetched":[ids],
#                    "unresolved":[ids], "failed":[ids]},
#  "missing": [evidence channel ids with no verdict],   # exit 2 unless --allow-missing
#            — channels with no evidence to read (no_evidence/failed/unresolved)
#              are not counted here: they cannot be judged
#  "adjacent_terms": [{"term","channels":[ids]}],       # suggestions, NOT filter changes
#  "sponsorability_summary": {"reachable","msn","tpp"}}
if __name__ == "__main__":
    main()
