#!/usr/bin/env python3
"""Apply the orchestrating model's inline keyword verdicts to a probe run.

Read `probe.py`'s JSON and one or more verdict files and emit the kept groups,
the dropped and unsure keywords, the candidate channels/videos the kept samples
name, and a fitness block. Every probed candidate needs a verdict: a missing one
exits 2.

A verdict file is EITHER a bare JSON array of
`{"keyword", "verdict": keep|drop|unsure, "exclude_hint"?, "note"?}` objects, OR
— far cheaper to write — a TSV: one line per candidate,
`keyword<TAB>verdict[<TAB>exclude_hint][<TAB>note]`, with `#` comments and blank
lines ignored. The format is detected from the first non-blank character: `[`
means JSON, anything else is TSV.

A verdict for a keyword the probe DROPPED (0 documents), failed on, or never
reached is not an error — the sheet showed it, so judging it was reasonable. It
is ignored and reported under `ignored_verdicts`. Only a verdict for a keyword
that is not in the probe file at all is fatal.

Usage:
    python3 select_keywords.py --apply --probe-file $RUN/probe1.json \
        --verdicts $RUN/verdicts1.json --run-dir $RUN > $RUN/selected1.json
    python3 select_keywords.py --apply --probe-file p.json --verdicts - < verdicts.json
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kw_common import emit, phrase_if_plain, stdin_is_readable  # noqa: E402

VERDICTS = ("keep", "drop", "unsure")
TSV_COLUMNS = ("keyword", "verdict", "exclude_hint", "note")


def load_probe(path):
    try:
        with open(path, encoding="utf-8") as fh:
            probe = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        sys.exit(f"could not read probe file {path}: {exc}")
    if not isinstance(probe, dict) or not isinstance(probe.get("keywords"), list):
        sys.exit(f"{path}: probe JSON must be an object with a 'keywords' list")
    return probe


def is_tsv(raw):
    """A verdicts file is TSV unless its first non-blank character opens a JSON array."""
    return raw.lstrip()[:1] != "["


def parse_tsv_verdicts(path, raw):
    """A TSV verdict file → the same records a JSON array would give.

    `keyword<TAB>verdict[<TAB>exclude_hint][<TAB>note]`; `#` comments and blank
    lines are skipped. Each record carries its 1-based `_line` so a bad verdict
    can be reported where the model wrote it.
    """
    if raw.lstrip()[:1] == "{":  # a JSON object, not an array and not TSV
        sys.exit(f"{path}: a verdicts file must be a bare JSON array of "
                 '{"keyword", "verdict"} objects, or TSV lines of '
                 "keyword<TAB>verdict[<TAB>exclude_hint][<TAB>note]")
    out = []
    for number, line in enumerate(raw.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # Bounded split: the LAST column is free text, so an embedded tab in it
        # belongs to the note rather than starting a fifth column.
        parts = [part.strip() for part in line.split("\t", len(TSV_COLUMNS) - 1)]
        if len(parts) < 2 or not parts[0]:
            sys.exit(f"{path}: line {number}: expected "
                     f"{'<TAB>'.join(TSV_COLUMNS[:2])}[<TAB>{TSV_COLUMNS[2]}]"
                     f"[<TAB>{TSV_COLUMNS[3]}], got {line!r}")
        item = {"keyword": parts[0], "verdict": parts[1], "_line": number}
        for key, value in zip(TSV_COLUMNS[2:], parts[2:]):
            if value:
                item[key] = value
        out.append(item)
    return out


def read_verdict_file(path):
    """One verdict file as records — JSON array or TSV, detected from its first
    non-blank character. `-` reads stdin (only when something is piped)."""
    if path == "-":
        if not stdin_is_readable():
            sys.exit("--verdicts -: nothing is piped on stdin")
        raw = sys.stdin.read()
        if is_tsv(raw):
            return parse_tsv_verdicts("--verdicts -", raw)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            sys.exit(f"--verdicts -: invalid JSON on stdin: {exc}")
    try:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
    except OSError as exc:
        sys.exit(f"could not read verdicts file {path}: {exc}")
    if is_tsv(raw):
        return parse_tsv_verdicts(path, raw)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        sys.exit(f"could not read verdicts file {path}: {exc}")


def parse_verdict_file(path, data, known, ignorable):
    """Validate one file → ({keyword: record}, [ignored]). Every problem here is fatal.

    A file may repeat a keyword only with the SAME verdict (a re-written list
    is normal); two different verdicts inside one file mean the judgement was
    never settled, and silently picking one would hide that. A keyword in
    `ignorable` (probe dropped/failed/unresolved it) is collected, not applied.
    """
    if not isinstance(data, list):
        sys.exit(f"{path}: a verdicts file must be a bare JSON array of "
                 '{"keyword", "verdict"} objects, or TSV lines of '
                 "keyword<TAB>verdict")
    out, unknown, ignored = {}, [], []
    for item in data:
        if not isinstance(item, dict):
            sys.exit(f"{path}: every entry must be an object, got {item!r}")
        where = f"{path}: line {item['_line']}: " if item.get("_line") else f"{path}: "
        keyword = item.get("keyword")
        if not isinstance(keyword, str) or not keyword.strip():
            sys.exit(f"{where}every entry needs a 'keyword' string: {item!r}")
        keyword = keyword.strip()
        verdict = item.get("verdict")
        if verdict not in VERDICTS:
            sys.exit(f"{where}keyword {keyword!r} has verdict {verdict!r}; "
                     f"it must be one of {', '.join(VERDICTS)}")
        if keyword in ignorable and keyword not in known:
            ignored.append({"keyword": keyword, "why": ignorable[keyword]})
            continue
        if keyword not in known:
            unknown.append(keyword)
            continue
        prior = out.get(keyword)
        if prior and prior["verdict"] != verdict:
            sys.exit(f"{path}: keyword {keyword!r} has two different verdicts "
                     f"({prior['verdict']} and {verdict}) in the same file")
        rec = {"verdict": verdict}
        for key in ("exclude_hint", "note"):
            if item.get(key):
                rec[key] = str(item[key])
        out[keyword] = rec
    if unknown:
        sys.exit(f"{path}: verdicts for keywords that are not in the probe file: "
                 + ", ".join(sorted(set(unknown)))
                 + " — the keyword must be spelled exactly as the probe output spells it")
    return out, ignored


def merge_verdicts(paths, known, ignorable):
    """Verdicts from every file, later files overriding earlier ones per keyword.
    → (verdicts, ignored) — ignored keeps first-seen order, one entry per keyword."""
    merged, ignored = {}, {}
    for path in paths:
        got, skipped = parse_verdict_file(path, read_verdict_file(path), known, ignorable)
        merged.update(got)
        for entry in skipped:
            ignored.setdefault(entry["keyword"], entry)
    return merged, list(ignored.values())


def ignorable_keywords(probe):
    """{keyword: why} for every candidate the probe showed but did not measure.

    `dropped` (0 documents), `failed` and `unresolved` all reach the sample
    sheet, so a verdict for one of them is a reasonable thing to have written —
    it is ignored, never fatal.
    """
    out = {}
    for key in ("dropped", "failed", "unresolved"):
        for entry in probe.get(key) or []:
            keyword = entry.get("keyword") if isinstance(entry, dict) else None
            if isinstance(keyword, str) and keyword.strip():
                out.setdefault(keyword.strip(), key)
    return out


def collect_targets(keywords, level):
    """Candidate channels / videos from the kept keywords' samples (residual too)."""
    seen_channels, seen_videos = set(), set()
    channels, videos = [], []
    for kw in keywords:
        pools = list(kw.get("samples") or [])
        pools += list((kw.get("residual") or {}).get("samples") or [])
        for sample in pools:
            cid = sample.get("channel_id")
            if level == "channel":
                if cid is not None and cid not in seen_channels:
                    seen_channels.add(cid)
                    channels.append({"channel_id": cid, "name": sample.get("name"),
                                     "topic": sample.get("topic")})
                continue
            vid = sample.get("video_id")
            if vid is not None and vid not in seen_videos:
                seen_videos.add(vid)
                videos.append({"video_id": vid, "url": sample.get("url"),
                               "title": sample.get("title"), "channel_id": cid})
            if cid is not None and cid not in seen_channels:
                seen_channels.add(cid)
                channels.append({"channel_id": cid})
    return channels, videos


def apply_verdicts(probe, verdicts, ignored=()):
    level = probe.get("level", "topic")
    candidates = probe["keywords"]
    kept_rows, kept, dropped, unsure, missing = [], [], [], [], []
    for kw in candidates:
        keyword = kw["keyword"]
        rec = verdicts.get(keyword)
        if rec is None:
            # The synthetic `union` row measures the whole filter; it is a
            # measurement, not a candidate to judge.
            if not kw.get("union"):
                missing.append(keyword)
            continue
        signals = kw.get("signals") or []
        if rec["verdict"] == "keep":
            kept_rows.append(kw)
            row = {"keyword": keyword, "mode": kw.get("mode", "phrase"),
                   "documents": kw.get("documents"), "channels": kw.get("channels"),
                   "strata": kw.get("strata"), "transcript_share": kw.get("transcript_share"),
                   "signals": signals}
            if rec.get("exclude_hint"):
                row["exclude_hint"] = rec["exclude_hint"]
            kept.append(row)
        elif rec["verdict"] == "drop":
            row = {"keyword": keyword, "reason": rec.get("note") or "drop"}
            if rec.get("exclude_hint"):
                row["exclude_hint"] = rec["exclude_hint"]
            dropped.append(row)
        else:
            unsure.append({"keyword": keyword, "note": rec.get("note") or "",
                           "signals": signals})

    channels, videos = collect_targets(kept_rows, level)
    flagged = {}
    for row in kept + unsure:
        for signal in row.get("signals") or []:
            flagged[signal] = flagged.get(signal, 0) + 1
    not_probed = ([{"keyword": f.get("keyword"), "reason": f.get("reason") or "error"}
                   for f in probe.get("failed") or []]
                  + [{"keyword": u.get("keyword"), "reason": u.get("reason") or "deadline"}
                     for u in probe.get("unresolved") or []])
    out = {
        "level": level,
        "operator": probe.get("operator", "OR"),
        "kept": kept,
        "dropped": dropped,
        "unsure": unsure,
        "missing": missing,
        "ignored_verdicts": list(ignored),
        "not_probed": not_probed,
        "groups": [{"text": phrase_if_plain(row["keyword"])} for row in kept],
        "candidate_channels": channels,
        "fitness": {
            # The synthetic `union` row measures the whole filter and is never
            # judged, so counting it here would make judged + missing + ignored
            # permanently one short of `candidates`.
            "candidates": sum(1 for c in candidates if not c.get("union")),
            "judged": len(kept) + len(dropped) + len(unsure),
            "kept": len(kept),
            "dropped": len(dropped),
            "unsure": len(unsure),
            "missing": len(missing),
            "ignored_verdicts": len(ignored),
            "transcript_led": flagged.get("transcript_led", 0),
            "flagged": flagged,
        },
    }
    if level != "channel":
        out["candidate_videos"] = videos
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Apply inline keyword verdicts to a probe run.")
    ap.add_argument("--apply", action="store_true", required=True,
                    help="Apply verdicts to the probe file (the only mode).")
    ap.add_argument("--probe-file", metavar="PATH", required=True,
                    help="probe.py output JSON")
    ap.add_argument("--verdicts", action="append", default=[], metavar="PATH",
                    help="Verdicts file — a JSON array, or TSV lines of "
                         "keyword<TAB>verdict[<TAB>exclude_hint][<TAB>note] (repeatable; a "
                         "later file overrides an earlier one per keyword). '-' reads one "
                         "from stdin.")
    ap.add_argument("--allow-missing", action="store_true",
                    help="Exit 0 even when some candidates have no verdict.")
    ap.add_argument("--run-dir", metavar="DIR",
                    help="Run ledger: record this invocation as one event file under DIR/events/")
    args = ap.parse_args()
    started = time.monotonic()
    if not args.verdicts:
        sys.exit("--apply needs at least one --verdicts file (use '-' for stdin)")

    probe = load_probe(args.probe_file)
    known = {kw["keyword"] for kw in probe["keywords"] if isinstance(kw, dict) and "keyword" in kw}
    verdicts, ignored = merge_verdicts(args.verdicts, known, ignorable_keywords(probe))
    out = apply_verdicts(probe, verdicts, ignored)
    emit(out, run_dir=args.run_dir, script="select_keywords", argv=sys.argv[1:], started=started)
    if out["missing"] and not args.allow_missing:
        sys.stderr.write(f"{len(out['missing'])} candidate(s) have no verdict: "
                         + ", ".join(out["missing"][:20])
                         + " — judge them and apply again (or pass --allow-missing)\n")
        sys.exit(2)


# OUTPUT CONTRACT (stdout, single JSON object):
#   {"level","operator",
#    "kept":[{"keyword","mode","documents","channels","strata","transcript_share",
#             "signals",["exclude_hint"]}],
#    "dropped":[{"keyword","reason",["exclude_hint"]}],
#    "unsure":[{"keyword","note","signals"}],
#    "missing":["<candidate with no verdict>"],       # exit 2 unless --allow-missing
#    "ignored_verdicts":[{"keyword","why":"dropped"|"failed"|"unresolved"}],  # not fatal
#    "not_probed":[{"keyword","reason"}],             # probe failed / unresolved
#    "groups":[{"text": <kept keyword, phrase-quoted when unstructured>}],
#    "candidate_channels":[{"channel_id",…}], "candidate_videos":[{…}],  # topic level
#    "fitness":{"candidates","judged","kept","dropped","unsure","missing","ignored_verdicts",
#               "transcript_led","flagged":{<signal>: <count over kept+unsure>}}}
if __name__ == "__main__":
    main()
