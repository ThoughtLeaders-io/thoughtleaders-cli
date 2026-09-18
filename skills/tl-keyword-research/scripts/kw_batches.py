#!/usr/bin/env python3
"""Batch protocol shared by the tl-keyword-research judge steps.

The orchestrating model must never be the batch builder, completeness checker
or vote counter. This module owns that bookkeeping for both judge agents
(`keyword-relevance-validator`, `keyword-context-classifier`):

  * an immutable INPUT SNAPSHOT (the probe output / the evidence array) is
    written once; every `i` is global within it and never renumbered;
  * a coordinator-owned MANIFEST records judge context, item ids, and every
    batch ever emitted (initial or repair) with its pass id and verdict path;
  * BATCH FILES are plain JSON the agent Reads (judge context travels inside
    the file — no prose prefix), and the agent Writes a bare JSON array to the
    batch's `verdict_path` and returns `{"verdict_path", "count"}`;
  * a REPAIR batch carries the sparse ids still missing from a pass and fills
    that pass — it never adds a vote. A second opinion is a new pass id.

Invariants enforced on read: verdict files are bare arrays; every `i` must be
an integer in the batch's id set; required keys must be present with the right
JSON types; two judgments for the same `i` within one pass must agree, else
the pass is rejected as conflicting; completeness is checked per pass.

Files (all under --out-dir):
  manifest.json                     coordinator-owned, atomic writes
  <snapshot name>                   immutable input copy
  batch_<pass>_<nnn>.json           batch (initial)   → batch_<pass>_<nnn>.verdict.json
  batch_<pass>_r<nnn>.json          batch (repair)    → ...verdict.json
"""
import datetime
import json
import os
import sys
import time

SCHEMA_VERSION = 1
DEFAULT_CHUNK = 40
DEFAULT_MAX_BATCH_BYTES = 65536
MANIFEST_NAME = "manifest.json"


class BatchError(Exception):
    """A protocol violation the orchestrator must act on (message is user-facing)."""


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def write_json_atomic(path, obj):
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path, what):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise BatchError(f"could not read {what} {path}: {exc}")


# ------------------------------------------------------------------ manifest

def new_manifest(kind, judge_context, item_ids, snapshot_path, out_dir):
    """Create and persist a manifest for one judge run. `kind` names the
    agent ('relevance' | 'context'); `judge_context` is what the agent needs
    (intent / topic / not); `item_ids` are the global ids in the snapshot."""
    m = {
        "schema_version": SCHEMA_VERSION,
        "kind": kind,
        "created": now_iso(),
        "judge_context": dict(judge_context),
        "snapshot": os.path.basename(snapshot_path),
        "item_ids": sorted(int(i) for i in item_ids),
        "passes": [],
        "batches": [],
    }
    save_manifest(out_dir, m)
    return m


def manifest_path(out_dir):
    return os.path.join(out_dir, MANIFEST_NAME)


def save_manifest(out_dir, manifest):
    manifest["updated"] = now_iso()
    write_json_atomic(manifest_path(out_dir), manifest)


def load_manifest(path):
    if os.path.isdir(path):
        path = manifest_path(path)
    m = read_json(path, "manifest")
    if not isinstance(m, dict) or m.get("schema_version") != SCHEMA_VERSION or "batches" not in m:
        raise BatchError(f"{path} is not a v{SCHEMA_VERSION} batch manifest")
    m["_dir"] = os.path.dirname(os.path.abspath(path))
    return m


def snapshot_of(manifest):
    return read_json(os.path.join(manifest["_dir"], manifest["snapshot"]), "input snapshot")


# ------------------------------------------------------------------ emission

def chunk_ids(ids, items_by_id, chunk, max_bytes):
    """Split ids into batches of at most `chunk` items and ~`max_bytes` of JSON."""
    batches, cur, cur_bytes = [], [], 0
    for i in ids:
        size = len(json.dumps(items_by_id[i], ensure_ascii=False)) + 2
        if cur and (len(cur) >= chunk or cur_bytes + size > max_bytes):
            batches.append(cur)
            cur, cur_bytes = [], 0
        cur.append(i)
        cur_bytes += size
    if cur:
        batches.append(cur)
    return batches


def emit_batches(manifest, out_dir, items_by_id, ids, pass_id, kind="initial",
                 chunk=DEFAULT_CHUNK, max_bytes=DEFAULT_MAX_BATCH_BYTES):
    """Write batch files for `ids` under `pass_id`, record them in the manifest,
    return the new batch records. `kind` is 'initial' or 'repair'."""
    ids = sorted(int(i) for i in ids)
    if pass_id not in manifest["passes"]:
        manifest["passes"].append(pass_id)
    existing = [b for b in manifest["batches"] if b["pass_id"] == pass_id and b["kind"] == kind]
    prefix = "r" if kind == "repair" else ""
    records = []
    for n, batch_ids in enumerate(chunk_ids(ids, items_by_id, chunk, max_bytes), start=len(existing)):
        batch_id = f"{pass_id}_{prefix}{n:03d}"
        path = os.path.join(out_dir, f"batch_{batch_id}.json")
        verdict_path = os.path.join(out_dir, f"batch_{batch_id}.verdict.json")
        body = {
            "schema_version": SCHEMA_VERSION,
            "judge": manifest["kind"],
            **manifest["judge_context"],
            "pass_id": pass_id,
            "batch_id": batch_id,
            "kind": kind,
            "count": len(batch_ids),
            "ids": batch_ids,
            "first_id": batch_ids[0],
            "last_id": batch_ids[-1],
            "verdict_path": verdict_path,
            "items": [items_by_id[i] for i in batch_ids],
        }
        write_json_atomic(path, body)
        rec = {"batch_id": batch_id, "pass_id": pass_id, "kind": kind, "path": path,
               "verdict_path": verdict_path, "ids": batch_ids, "count": len(batch_ids),
               "first_id": batch_ids[0], "last_id": batch_ids[-1], "created": now_iso()}
        manifest["batches"].append(rec)
        records.append(rec)
    save_manifest(out_dir, manifest)
    return records


def summary(manifest, records, extra=None):
    """The small JSON the emitting script prints instead of the batches."""
    out = {
        "manifest": manifest_path(manifest.get("_dir") or os.path.dirname(records[0]["path"]) if records else manifest.get("_dir", "")),
        "judge": manifest["kind"],
        "item_count": len(manifest["item_ids"]),
        "batches": [{"batch_id": r["batch_id"], "pass_id": r["pass_id"], "kind": r["kind"],
                     "path": r["path"], "verdict_path": r["verdict_path"], "count": r["count"]}
                    for r in records],
    }
    if extra:
        out.update(extra)
    return out


# ------------------------------------------------------------------ verdicts

def _validate_item(obj, batch, required, validators):
    if not isinstance(obj, dict):
        raise BatchError(f"{batch['batch_id']}: verdict entries must be objects, got {type(obj).__name__}")
    i = obj.get("i")
    if not isinstance(i, int) or isinstance(i, bool):
        raise BatchError(f"{batch['batch_id']}: verdict entry has no integer 'i': {obj}")
    if i not in batch["_idset"]:
        raise BatchError(f"{batch['batch_id']}: verdict for i={i} which is not in this batch")
    for key, typ in required.items():
        val = obj.get(key)
        if typ is bool:
            ok = isinstance(val, bool)
        elif typ is int:
            ok = isinstance(val, int) and not isinstance(val, bool)
        else:
            ok = isinstance(val, typ)
        if not ok:
            raise BatchError(f"{batch['batch_id']}: i={i} needs JSON {typ.__name__} '{key}', got {val!r}")
    for key, fn in (validators or {}).items():
        err = fn(obj.get(key), obj)
        if err:
            raise BatchError(f"{batch['batch_id']}: i={i} {key}: {err}")
    return i


def load_pass(manifest, pass_id, required, validators=None, compare_keys=None):
    """Read every verdict file of one pass. Returns (verdicts, missing_ids,
    unread_batches). `verdicts` maps i -> the verdict object. A batch whose
    verdict file does not exist yet is reported, not fatal; a malformed file
    or a conflicting duplicate is fatal (BatchError)."""
    verdicts, unread = {}, []
    compare_keys = compare_keys or list(required)
    for batch in manifest["batches"]:
        if batch["pass_id"] != pass_id:
            continue
        batch = dict(batch, _idset=set(batch["ids"]))
        if not os.path.exists(batch["verdict_path"]):
            unread.append(batch["batch_id"])
            continue
        data = read_json(batch["verdict_path"], "verdict file")
        if not isinstance(data, list):
            raise BatchError(f"{batch['verdict_path']} must be a bare JSON array")
        for obj in data:
            i = _validate_item(obj, batch, required, validators)
            if i in verdicts:
                same = all(verdicts[i].get(k) == obj.get(k) for k in compare_keys)
                if not same:
                    raise BatchError(f"pass {pass_id}: conflicting judgments for i={i} "
                                     f"({verdicts[i]} vs {obj}) — re-run that batch")
                continue  # identical repeat: idempotent
            verdicts[i] = obj
    missing = [i for i in manifest["item_ids"] if i not in verdicts]
    return verdicts, missing, unread


def next_pass_id(manifest):
    n = len(manifest["passes"]) + 1
    while f"p{n}" in manifest["passes"]:
        n += 1
    return f"p{n}"


# ------------------------------------------------------------------ run ledger

def record_event(run_dir, script, argv, started_monotonic, output, elapsed_fn=None):
    """One event file per script invocation under <run_dir>/events/ — the run
    ledger the skill's self-check reads. No shared file, no concurrent writers:
    each process writes only its own event. Never raises."""
    if not run_dir:
        return None
    try:
        events = os.path.join(run_dir, "events")
        os.makedirs(events, exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = os.path.join(events, f"{stamp}-{script}-{os.getpid()}.json")
        write_json_atomic(path, {
            "script": script,
            "argv": list(argv),
            "started": now_iso(),
            "elapsed_seconds": round(time.monotonic() - started_monotonic, 1),
            "output": output,
        })
        return path
    except OSError:
        return None
