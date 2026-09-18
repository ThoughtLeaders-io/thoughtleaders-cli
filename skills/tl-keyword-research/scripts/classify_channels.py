#!/usr/bin/env python3
"""Merge keyword-context-classifier verdicts onto the channel table — in code.

Reads the context manifest written by `fetch_context.py --emit-batches`,
validates every verdict file (bare array; integer `i` in its batch; the
`channel_id` must match the evidence item; verdict ∈ on_topic|mixed|off_topic),
checks completeness PER PASS and writes repair batches for anything missing
(exit 2), then joins verdicts with the intensity tiers and (optionally) the
relevance ranking into the final tier × verdict × sponsorability table.

Nothing is manufactured: a channel with no intensity row keeps `tier: null`,
an intensity channel that was never fetched is listed separately, and the
excluded (`off_topic`) list is always surfaced. Pooled `adjacent_terms` carry
provenance (which channels said them) and are SUGGESTIONS for Stage 4 — adding
one to the filter is a scope decision for the user, never automatic.

Usage:
    classify_channels.py --manifest /tmp/kwrun/ctx1 --intensity intensity.json [--ranking ranked.json]
    classify_channels.py --manifest /tmp/kwrun/ctx1 --intensity intensity.json --no-repairs

Output (stdout): see OUTPUT_SHAPE at the bottom.
"""
import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_batches  # noqa: E402

_LEDGER = {"run_dir": None, "started": time.monotonic()}


def emit(obj, **kw):
    print(json.dumps(obj, ensure_ascii=False, **kw))
    kw_batches.record_event(_LEDGER["run_dir"], "classify_channels", sys.argv[1:], _LEDGER["started"], obj)

VERDICTS = ("on_topic", "mixed", "off_topic")
CONFIDENCES = ("high", "medium", "low")
VERDICT_REQUIRED = {"channel_id": int, "verdict": str}
TIER_ORDER = {"core": 0, "recurring": 1, "occasional": 2, "one_off": 3, None: 4}
VERDICT_ORDER = {"on_topic": 0, "mixed": 1, "off_topic": 2}


def _validators(items_by_id):
    def channel_matches(val, obj):
        item = items_by_id.get(obj.get("i"))
        if item is not None and val != item["channel_id"]:
            return f"channel_id {val} does not match the evidence item ({item['channel_id']})"
        return None

    def verdict_ok(val, obj):
        return None if val in VERDICTS else f"must be one of {VERDICTS}, got {val!r}"

    def confidence_ok(val, obj):
        if val is None:
            return None
        return None if val in CONFIDENCES else f"must be one of {CONFIDENCES}, got {val!r}"

    def terms_ok(val, obj):
        if val is None:
            return None
        if not isinstance(val, list) or not all(isinstance(t, str) for t in val):
            return "adjacent_terms must be a list of strings"
        return None

    return {"channel_id": channel_matches, "verdict": verdict_ok,
            "confidence": confidence_ok, "adjacent_terms": terms_ok}


def load_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"could not read {what} {path}: {exc}")


def majority(objs):
    """Across passes: the verdict a strict majority agrees on, else the most
    cautious one present (mixed beats on_topic; off_topic only if unanimous)."""
    votes = Counter(o["verdict"] for o in objs)
    top, n = votes.most_common(1)[0]
    if n * 2 > len(objs):
        return top
    return "mixed" if "mixed" in votes or ("on_topic" in votes and "off_topic" in votes) else top


def main():
    ap = argparse.ArgumentParser(description="Merge classifier verdicts onto the channel table.")
    ap.add_argument("--manifest", required=True, metavar="PATH", help="context manifest.json (or its directory)")
    ap.add_argument("--intensity", metavar="PATH", help="search_channels.py --intensity output (tiers)")
    ap.add_argument("--ranking", metavar="PATH", help="search_channels.py ranked output (relevance order)")
    ap.add_argument("--no-repairs", action="store_true", help="report incompleteness without writing repair batches")
    ap.add_argument("--chunk", type=int, default=kw_batches.DEFAULT_CHUNK)
    ap.add_argument("--max-batch-bytes", type=int, default=kw_batches.DEFAULT_MAX_BATCH_BYTES)
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: record this invocation (argv, elapsed, output) as one event file under DIR/events/")
    args = ap.parse_args()
    _LEDGER["run_dir"] = args.run_dir

    try:
        manifest = kw_batches.load_manifest(args.manifest)
    except kw_batches.BatchError as exc:
        sys.exit(str(exc))
    if manifest["kind"] != "context":
        sys.exit(f"{args.manifest} is a {manifest['kind']} manifest, not a context one")
    snapshot = kw_batches.snapshot_of(manifest)
    evidence = snapshot.get("channels", [])
    items_by_id = {i: {"i": i, "channel_id": ch["channel_id"], "snippets": ch["snippets"]}
                   for i, ch in enumerate(evidence)}
    # --retry-failed appends channels with fresh ids at the end of the snapshot, in order.
    if len(items_by_id) != len(manifest["item_ids"]):
        sys.exit("manifest item_ids and evidence snapshot disagree; the run directory was edited by hand")

    per_pass, repairs, incomplete = [], [], []
    for pid in manifest["passes"]:
        try:
            verdicts, missing, unread = kw_batches.load_pass(
                manifest, pid, VERDICT_REQUIRED, _validators(items_by_id),
                compare_keys=["channel_id", "verdict"])
        except kw_batches.BatchError as exc:
            sys.exit(str(exc))
        if missing:
            incomplete.append({"pass_id": pid, "missing": len(missing), "unread_batches": unread,
                               "missing_ids": missing[:20]})
            if not args.no_repairs and not unread:
                repairs += kw_batches.emit_batches(manifest, manifest["_dir"], items_by_id, missing, pid,
                                                   "repair", args.chunk, args.max_batch_bytes)
        per_pass.append(verdicts)
    if incomplete:
        emit(kw_batches.summary(manifest, repairs, {"status": "incomplete", "passes": incomplete}), indent=1)
        sys.stderr.write("classifier verdicts incomplete — run a classifier on each repair batch listed, "
                         "then run this again\n")
        sys.exit(2)

    intensity = load_json(args.intensity, "intensity file") if args.intensity else {}
    tiers = {c["channel_id"]: c for c in intensity.get("channels", [])}
    ranking = load_json(args.ranking, "ranking file") if args.ranking else {}
    rank_of = {c["channel_id"]: n for n, c in enumerate(ranking.get("channels", []), start=1)}
    rank_rows = {c["channel_id"]: c for c in ranking.get("channels", [])}

    rows, excluded, terms = [], [], defaultdict(list)
    for i, item in items_by_id.items():
        objs = [vm[i] for vm in per_pass if i in vm]
        cid = item["channel_id"]
        verdict = majority(objs)
        first = objs[0]
        t = tiers.get(cid) or {}
        r = rank_rows.get(cid) or {}
        row = {
            "channel_id": cid,
            "name": t.get("name") or r.get("name"),
            "tier": t.get("tier"),
            "matching_uploads": t.get("matching_uploads"),
            "recent_matching_uploads": t.get("recent_matching_uploads"),
            "topic_share": t.get("topic_share"),
            "relevance_rank": rank_of.get(cid),
            "verdict": verdict,
            "confidence": first.get("confidence"),
            "evidence_quote": first.get("evidence_quote", ""),
            "notes": first.get("notes", ""),
            "votes": [o["verdict"] for o in objs],
            "snippets": len(item["snippets"]),
            "sponsorability": t.get("sponsorability") or r.get("sponsorability"),
        }
        for term in first.get("adjacent_terms") or []:
            terms[term.strip().lower()].append(cid)
        (excluded if verdict == "off_topic" else rows).append(row)

    rows.sort(key=lambda x: (VERDICT_ORDER[x["verdict"]], TIER_ORDER.get(x["tier"], 4),
                             -(x["matching_uploads"] or 0), x["relevance_rank"] or 10**9))
    failed = manifest.get("failed_channels", [])
    seen = {it["channel_id"] for it in items_by_id.values()} | {f["channel_id"] for f in failed}
    not_fetched = [{"channel_id": c["channel_id"], "name": c.get("name"), "tier": c.get("tier")}
                   for c in intensity.get("channels", []) if c["channel_id"] not in seen]
    verdict_counts = Counter(r["verdict"] for r in rows + excluded)
    by_tier = defaultdict(Counter)
    for r in rows + excluded:
        by_tier[r["tier"] or "untiered"][r["verdict"]] += 1

    emit({
        "passes": manifest["passes"],
        "judged": len(items_by_id),
        "verdicts": dict(verdict_counts),
        "by_tier": {k: dict(v) for k, v in by_tier.items()},
        "channels": rows,                      # on_topic + mixed, kept and labelled
        "excluded": excluded,                  # off_topic — surfaced, never silent
        "not_validated": {"fetch_failed": failed, "not_fetched": not_fetched},
        "adjacent_terms": [{"term": k, "channels": v, "mentions": len(v)}
                           for k, v in sorted(terms.items(), key=lambda kv: -len(kv[1]))],
        "sponsorability_summary": {
            "reachable": sum(1 for r in rows if (r["sponsorability"] or {}).get("has_outreach_email")
                             or (r["sponsorability"] or {}).get("is_msn") or (r["sponsorability"] or {}).get("is_tpp")),
            "msn": sum(1 for r in rows if (r["sponsorability"] or {}).get("is_msn")),
            "tpp": sum(1 for r in rows if (r["sponsorability"] or {}).get("is_tpp")),
        },
    }, indent=1)


# OUTPUT_SHAPE:
# {"passes":[...], "judged": n, "verdicts": {"on_topic":n,"mixed":n,"off_topic":n},
#  "by_tier": {"core":{...},"recurring":{...},"occasional":{...},"one_off":{...},"untiered":{...}},
#  "channels": [{"channel_id","name","tier","matching_uploads","recent_matching_uploads","topic_share",
#                "relevance_rank","verdict","confidence","evidence_quote","notes","votes","snippets",
#                "sponsorability":{...}}],          # on_topic first, then mixed; core → one_off within
#  "excluded": [same rows, verdict off_topic],
#  "not_validated": {"fetch_failed":[{"channel_id","error"}], "not_fetched":[{"channel_id","name","tier"}]},
#  "adjacent_terms": [{"term","channels":[ids],"mentions"}],   # suggestions with provenance, NOT filter changes
#  "sponsorability_summary": {"reachable","msn","tpp"}}
# Incomplete (exit 2): the manifest summary with "status":"incomplete" and the repair batches to judge.
if __name__ == "__main__":
    main()
