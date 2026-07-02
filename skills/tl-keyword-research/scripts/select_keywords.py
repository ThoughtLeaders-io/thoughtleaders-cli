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

Usage:
    python3 probe.py "tiktok shop" "selling on tiktok" > probe.json
    python3 select_keywords.py --emit-batch < probe.json > batch.json
    # ...send batch.json (+ "intent: ..." line) to keyword-relevance-validator → verdict.json...
    python3 select_keywords.py --apply verdict.json < probe.json
"""
import argparse
import json
import sys

# Friendly content keys shown to the validator, by probe level.
BATCH_CONTENT_KEYS = {"topic": ["title", "summary"], "channel": ["name", "topic"]}


def load_probe():
    if sys.stdin.isatty():
        sys.exit("pipe probe.py output JSON on stdin")
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


def emit_batch(probe):
    level = probe.get("level", "topic")
    keys = BATCH_CONTENT_KEYS.get(level, BATCH_CONTENT_KEYS["topic"])
    batch = []
    for i, keyword, sample in build_index(probe):
        item = {"i": i, "keyword": keyword}
        for k in keys:
            item[k] = sample.get(k)
        batch.append(item)
    print(json.dumps(batch, ensure_ascii=False))


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
        maps.append({int(o["i"]): bool(o.get("relevant"))
                     for o in data if isinstance(o, dict) and "i" in o})
    return maps


def relevant_at(i, verdict_maps):
    """Majority vote of `relevant` for sample i across passes (missing = False)."""
    votes = [vm.get(i, False) for vm in verdict_maps]
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

    out = {
        "level": level,
        "operator": probe.get("operator", "OR"),
        "kept": kept,
        "dropped": dropped,
        "unvalidated": unvalidated,
        "groups": [{"text": k["keyword"]} for k in kept],
        "candidate_channels": candidate_channels,
    }
    if level != "channel":
        out["candidate_videos"] = candidate_videos
    print(json.dumps(out, ensure_ascii=False, indent=2))


def main():
    ap = argparse.ArgumentParser(description="Build the validator batch / apply its verdict to probe output.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--emit-batch", action="store_true", help="Print the validator batch from probe output (stdin).")
    g.add_argument("--apply", nargs="+", metavar="VERDICT", help="Apply verdict file(s) to probe output (stdin).")
    ap.add_argument("--allow-missing", action="store_true",
                    help="Warn instead of failing when verdicts don't cover every batch sample "
                         "(missing samples count as not relevant).")
    args = ap.parse_args()

    probe = load_probe()
    if args.emit_batch:
        emit_batch(probe)
    else:
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
#     "candidate_videos":[{"url","title","channel_id"}]   # topic level only
#   }
if __name__ == "__main__":
    main()
