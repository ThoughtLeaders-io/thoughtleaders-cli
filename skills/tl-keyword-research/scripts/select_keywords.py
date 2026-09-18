#!/usr/bin/env python3
"""Bridge probe output and the keyword-relevance-validator sub-agent.

Two modes, both reading the `probe.py` output JSON on stdin:

  --emit-batch
      Print the flat validation batch the `keyword-relevance-validator` Haiku
      sub-agent expects: a JSON array of `{i, keyword, <content fields>}`, one
      item per sample, with a deterministic `i` ordering. Send this (with a
      leading `intent:` line) to the sub-agent via the Agent tool.

  --apply VERDICT.json [VERDICT2.json ...]
      Re-derive the same batch deterministically, join the sub-agent's
      verdict(s) (`[{i, relevant}]`) by `i` (majority vote across passes), then
      decide each keyword: keep it only if a strict majority of its samples are
      relevant. Emit kept keywords (as build_report groups), dropped keywords
      with reasons, and the on-topic candidate channels/videos pulled from the
      validated samples.

This mirrors the tl-channel-authenticity finalize pattern (build batch → run
sub-agent → finalize), so the keep/drop logic is scripted and testable rather
than left to ad-hoc counting.

Usage (artifact mode — the default the skill uses; files, not pasted JSON):
    python3 probe.py "tiktok shop" "selling on tiktok" > probe.json
    python3 select_keywords.py --emit-batch --probe-file probe.json \
        --intent "<verbatim intent>" --out-dir /tmp/kwrun/val1
      → writes an immutable snapshot, manifest.json and batch_p1_000.json … ;
        prints the manifest path + one line per batch (path, verdict_path, count).
    # spawn one keyword-relevance-validator per batch, ALL IN ONE MESSAGE, giving
    # each only its batch path; each writes its verdict_path and returns the count
    python3 select_keywords.py --apply --manifest /tmp/kwrun/val1
      → validates every verdict file, checks completeness PER PASS; if anything
        is missing it writes repair batches (same pass, sparse ids), prints them
        and exits 2 — spawn validators for those, then --apply again.
    python3 select_keywords.py --add-pass --manifest /tmp/kwrun/val1
      → a second opinion: emits every item again under a new pass id (p2);
        --apply then majority-votes across passes.

Usage (legacy stdin mode — still supported, same rules):
    python3 select_keywords.py --emit-batch < probe.json > batch.json
    python3 select_keywords.py --apply verdict.json < probe.json
"""
import argparse
import json
import os
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kw_batches  # noqa: E402  (sibling module: the shared batch protocol)

_LEDGER = {"run_dir": None, "started": time.monotonic()}


def emit(obj, **kw):
    print(json.dumps(obj, ensure_ascii=False, **kw))
    kw_batches.record_event(_LEDGER["run_dir"], "select_keywords", sys.argv[1:], _LEDGER["started"], obj)

# Friendly content keys shown to the validator, by probe level.
BATCH_CONTENT_KEYS = {"topic": ["title", "summary"], "channel": ["name", "topic"]}


def load_probe(path=None):
    if path:
        try:
            with open(path, encoding="utf-8") as fh:
                probe = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            sys.exit(f"could not read probe file {path}: {exc}")
    else:
        if sys.stdin.isatty():
            sys.exit("pipe probe.py output JSON on stdin (or pass --probe-file)")
        try:
            probe = json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            sys.exit(f"invalid probe JSON on stdin: {exc}")
    if not isinstance(probe, dict) or not isinstance(probe.get("keywords"), list):
        sys.exit("probe JSON must be an object with a 'keywords' list")
    return probe


def build_index(probe):
    """Deterministic [(i, keyword, sample)] over every keyword's samples, in order."""
    index = []
    i = 0
    for kw in probe["keywords"]:
        for sample in kw.get("samples", []):
            index.append((i, kw["keyword"], sample))
            i += 1
    return index


def batch_items(probe):
    level = probe.get("level", "topic")
    keys = BATCH_CONTENT_KEYS.get(level, BATCH_CONTENT_KEYS["topic"])
    batch = []
    for i, keyword, sample in build_index(probe):
        item = {"i": i, "keyword": keyword}
        for k in keys:
            item[k] = sample.get(k)
        batch.append(item)
    return batch


def emit_batch(probe):
    emit(batch_items(probe))


VERDICT_REQUIRED = {"relevant": bool}


def emit_artifacts(probe, intent, out_dir, chunk, max_bytes):
    """Artifact mode: snapshot + manifest + batch files for pass p1."""
    if not intent.strip():
        sys.exit("--intent is required with --out-dir (the validator judges against it)")
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)
    snapshot = os.path.join(out_dir, "probe.snapshot.json")
    kw_batches.write_json_atomic(snapshot, probe)
    items = batch_items(probe)
    m = kw_batches.new_manifest("relevance", {"intent": intent.strip()},
                                [it["i"] for it in items], snapshot, out_dir)
    m["_dir"] = out_dir
    if not items:
        emit(kw_batches.summary(m, [], {"note": "no samples to judge"}), indent=1)
        return
    recs = kw_batches.emit_batches(m, out_dir, {it["i"]: it for it in items},
                                   [it["i"] for it in items], "p1", "initial", chunk, max_bytes)
    emit(kw_batches.summary(m, recs), indent=1)


def add_pass(manifest, chunk, max_bytes):
    probe = kw_batches.snapshot_of(manifest)
    items = {it["i"]: it for it in batch_items(probe)}
    pid = kw_batches.next_pass_id(manifest)
    recs = kw_batches.emit_batches(manifest, manifest["_dir"], items, list(items), pid,
                                   "initial", chunk, max_bytes)
    emit(kw_batches.summary(manifest, recs, {"pass_id": pid}), indent=1)


def verdict_maps_from_manifest(manifest, emit_repairs, chunk, max_bytes):
    """One {i: bool} map per pass; repairs for any pass that is incomplete."""
    probe = kw_batches.snapshot_of(manifest)
    items = {it["i"]: it for it in batch_items(probe)}
    maps, repairs, incomplete = [], [], []
    for pid in manifest["passes"]:
        try:
            verdicts, missing, unread = kw_batches.load_pass(manifest, pid, VERDICT_REQUIRED)
        except kw_batches.BatchError as exc:
            sys.exit(str(exc))
        if missing:
            incomplete.append({"pass_id": pid, "missing": len(missing), "unread_batches": unread,
                               "missing_ids": missing[:20]})
            if emit_repairs and not unread:  # don't repair what simply hasn't been judged yet
                repairs += kw_batches.emit_batches(manifest, manifest["_dir"], items, missing,
                                                   pid, "repair", chunk, max_bytes)
        maps.append({i: v["relevant"] for i, v in verdicts.items()})
    if incomplete:
        out = kw_batches.summary(manifest, repairs, {"status": "incomplete", "passes": incomplete})
        emit(out, indent=1)
        sys.stderr.write("verdicts incomplete — run a validator on each repair batch listed, "
                         "then --apply again (unread batches: spawn their validator first)\n")
        sys.exit(2)
    return probe, maps


def load_verdicts(paths):
    """Return a list of {i: bool} maps, one per verdict file."""
    maps = []
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            sys.exit(f"could not read verdict file {p}: {exc}")
        if not isinstance(data, list):
            sys.exit(f"verdict file {p} must be a JSON array of {{i, relevant}}")
        vm = {}
        for o in data:
            if not isinstance(o, dict) or not isinstance(o.get("i"), int) or isinstance(o.get("i"), bool):
                sys.exit(f"verdict file {p}: every entry needs an integer 'i': {o}")
            if not isinstance(o.get("relevant"), bool):
                sys.exit(f"verdict file {p}: i={o['i']} 'relevant' must be a JSON boolean, got {o.get('relevant')!r}")
            if o["i"] in vm and vm[o["i"]] != o["relevant"]:
                sys.exit(f"verdict file {p}: conflicting verdicts for i={o['i']}")
            vm[o["i"]] = o["relevant"]
        maps.append(vm)
    return maps


def relevant_at(i, verdict_maps):
    """Majority vote of `relevant` for sample i across the passes that judged it.

    A file with no verdict for i abstains — it does not vote False. The
    truncation-recovery path merges partial files with disjoint coverage
    (each sample judged by exactly one file), so counting absences as False
    votes would turn every retry-file verdict into a loss. A sample with no
    verdict anywhere (only reachable with --allow-missing) counts as not
    relevant.
    """
    votes = [vm[i] for vm in verdict_maps if i in vm]
    if not votes:
        return False
    return sum(1 for v in votes if v) * 2 > len(votes)


def check_completeness(index, verdict_maps, allow_missing):
    """Every batch sample must have a verdict in at least one pass.

    Cheap validators silently drop the tail of a long list, so a missing `i`
    usually means truncation, not judgement. Default: fail loudly and list
    the missing indices so the caller re-sends just those samples to a fresh
    validator run. `--allow-missing` downgrades to a stderr warning (missing
    samples then count as not-relevant, which biases toward dropping).
    """
    covered = set()
    for vm in verdict_maps:
        covered.update(vm)
    missing = sorted(i for i, _, _ in index if i not in covered)
    if not missing:
        return
    msg = (f"{len(missing)} of {len(index)} batch samples have no verdict "
           f"(missing i: {missing[:20]}{'…' if len(missing) > 20 else ''}) — "
           f"the validator likely truncated; re-send those samples and merge.")
    if allow_missing:
        sys.stderr.write(f"warning: {msg}\n")
    else:
        sys.exit(msg + " (or pass --allow-missing to treat them as not relevant)")


def apply_verdicts(probe, verdict_maps, allow_missing=False):
    index = build_index(probe)
    level = probe.get("level", "topic")
    check_completeness(index, verdict_maps, allow_missing)
    finals = {i: relevant_at(i, verdict_maps) for i, _, _ in index}

    per_kw = {}  # keyword -> {"relevant": n, "total": n, "samples":[(rel, sample)]}
    for i, keyword, sample in index:
        bucket = per_kw.setdefault(keyword, {"relevant": 0, "total": 0, "samples": []})
        rel = finals[i]
        bucket["total"] += 1
        bucket["relevant"] += 1 if rel else 0
        bucket["samples"].append((rel, sample))

    kept, dropped, unvalidated = [], [], []
    seen_channels, candidate_channels, candidate_videos = set(), [], []
    seen_kw = set()  # the same text probed under two modes merges into one bucket
    for kw in probe["keywords"]:
        keyword = kw["keyword"]
        if keyword in seen_kw:
            continue
        seen_kw.add(keyword)
        b = per_kw.get(keyword)
        if not b or b["total"] == 0:
            unvalidated.append({"keyword": keyword, "reason": "no_samples"})
            continue
        stats = {"keyword": keyword, "relevant": b["relevant"], "total": b["total"]}
        if b["relevant"] * 2 > b["total"]:  # strict majority on-topic
            kept.append(stats)
            for rel, sample in b["samples"]:
                if not rel:
                    continue
                cid = sample.get("channel_id")
                if level == "channel":
                    if cid not in seen_channels:
                        seen_channels.add(cid)
                        candidate_channels.append({
                            "channel_id": cid, "name": sample.get("name"),
                            "topic": sample.get("topic"),
                        })
                else:
                    candidate_videos.append({
                        "url": sample.get("url"), "title": sample.get("title"),
                        "channel_id": cid,
                    })
                    if cid not in seen_channels:
                        seen_channels.add(cid)
                        candidate_channels.append({"channel_id": cid})
        else:
            dropped.append({**stats, "reason": "off_intent"})

    judged = [i for i, _, _ in index if any(i in vm for vm in verdict_maps)]
    on_topic = sum(1 for i in judged if finals[i])
    offenders = sorted((s for s in kept + dropped if s["total"] >= 2),
                       key=lambda s: (s["relevant"] / s["total"], -s["total"]))[:5]
    fitness = {  # what the verdicts support, nothing more: pooled samples, not filter precision
        "samples": len(index),
        "judged": len(judged),
        "unjudged": len(index) - len(judged),
        "on_topic": on_topic,
        "relevance_share": round(on_topic / len(judged), 3) if judged else None,
        "keywords_kept": len(kept),
        "keywords_dropped": len(dropped),
        "worst_offenders": [{"keyword": s["keyword"], "relevant": s["relevant"], "total": s["total"]}
                            for s in offenders],
    }
    out = {
        "level": level,
        "operator": probe.get("operator", "OR"),
        "kept": kept,
        "dropped": dropped,
        "unvalidated": unvalidated,
        "groups": [{"text": k["keyword"]} for k in kept],
        "candidate_channels": candidate_channels,
        "fitness": fitness,
    }
    if level != "channel":
        out["candidate_videos"] = candidate_videos
    emit(out, indent=2)


def main():
    ap = argparse.ArgumentParser(description="Build the validator batches / apply their verdicts to probe output.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit-batch", action="store_true",
                   help="Emit the validator batch(es). With --out-dir: snapshot + manifest + batch files. "
                        "Without: print one JSON array (legacy).")
    g.add_argument("--apply", nargs="*", metavar="VERDICT",
                   help="Apply verdicts. With --manifest: read every pass's verdict files from it. "
                        "Without: VERDICT files against probe JSON on stdin (legacy).")
    g.add_argument("--add-pass", action="store_true",
                   help="With --manifest: emit all items again under a new pass id for a second opinion.")
    ap.add_argument("--probe-file", metavar="PATH", help="probe.py output (default: stdin)")
    ap.add_argument("--intent", default="", help="Verbatim intent the validator judges against (artifact mode)")
    ap.add_argument("--out-dir", metavar="DIR", help="Artifact mode: where snapshot, manifest and batches go")
    ap.add_argument("--manifest", metavar="PATH", help="Artifact mode: manifest.json (or its directory)")
    ap.add_argument("--chunk", type=int, default=kw_batches.DEFAULT_CHUNK,
                    help=f"Max samples per batch file (default {kw_batches.DEFAULT_CHUNK})")
    ap.add_argument("--max-batch-bytes", type=int, default=kw_batches.DEFAULT_MAX_BATCH_BYTES,
                    help=f"Approximate JSON size cap per batch (default {kw_batches.DEFAULT_MAX_BATCH_BYTES})")
    ap.add_argument("--no-repairs", action="store_true",
                    help="--apply --manifest: report incompleteness without writing repair batches")
    ap.add_argument("--allow-missing", action="store_true",
                    help="Warn instead of failing when verdicts don't cover every batch sample "
                         "(missing samples count as not relevant).")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: record this invocation (argv, elapsed, output) as one event file under DIR/events/")
    args = ap.parse_args()
    _LEDGER["run_dir"] = args.run_dir
    if args.chunk < 1:
        sys.exit("--chunk must be >= 1")

    if args.manifest:
        try:
            manifest = kw_batches.load_manifest(args.manifest)
        except kw_batches.BatchError as exc:
            sys.exit(str(exc))
        if manifest["kind"] != "relevance":
            sys.exit(f"{args.manifest} is a {manifest['kind']} manifest, not a relevance one")
        if args.add_pass:
            add_pass(manifest, args.chunk, args.max_batch_bytes)
        elif args.apply is not None:
            if args.apply:
                sys.exit("--apply with --manifest takes no verdict paths; they come from the manifest")
            probe, maps = verdict_maps_from_manifest(manifest, not args.no_repairs,
                                                     args.chunk, args.max_batch_bytes)
            apply_verdicts(probe, maps, allow_missing=args.allow_missing)
        else:
            sys.exit("--emit-batch does not take --manifest; use --out-dir to start a run")
        return
    if args.add_pass:
        sys.exit("--add-pass needs --manifest")

    probe = load_probe(args.probe_file)
    if args.emit_batch:
        if args.out_dir:
            emit_artifacts(probe, args.intent, args.out_dir, args.chunk, args.max_batch_bytes)
        else:
            emit_batch(probe)
    else:
        if not args.apply:
            sys.exit("--apply needs verdict file(s), or --manifest")
        apply_verdicts(probe, load_verdicts(args.apply), allow_missing=args.allow_missing)


# OUTPUT CONTRACT
#   --emit-batch (stdout): [{"i":int,"keyword":str,"title":str,"summary":str}, ...]   # topic
#                          [{"i":int,"keyword":str,"name":str,"topic":str}, ...]       # channel
#   --apply (stdout): {
#     "level","operator",
#     "kept":[{"keyword","relevant","total"}],            # strict-majority on-topic
#     "dropped":[{"keyword","relevant","total","reason":"off_intent"}],
#     "unvalidated":[{"keyword","reason":"no_samples"}],
#     "groups":[{"text": <kept keyword>}],                # feed to build_report.py
#     "candidate_channels":[{"channel_id", ...}],
#     "candidate_videos":[{"url","title","channel_id"}],  # topic level only
#     "fitness":{"samples","judged","unjudged","on_topic","relevance_share",
#                "keywords_kept","keywords_dropped","worst_offenders":[{"keyword","relevant","total"}]}
#   }
#   --emit-batch --out-dir (stdout): {"manifest","judge":"relevance","item_count",
#                                     "batches":[{"batch_id","pass_id","kind","path","verdict_path","count"}]}
#   --apply --manifest, incomplete (stdout, exit 2): same shape + "status":"incomplete",
#                                     "passes":[{"pass_id","missing","unread_batches","missing_ids"}]
#                                     with "batches" = the REPAIR batches to judge next
if __name__ == "__main__":
    main()
