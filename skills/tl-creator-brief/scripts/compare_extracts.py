#!/usr/bin/env python3
"""Compare two assembled extraction runs over the same windows.

Both sides are ``--out`` directories of ``assemble_extracts.py``, each holding
a ``classified.jsonl`` of ``{"window", "verdict", "error"}`` rows. Windows are
keyed by ``(window id, start)`` so the same window judged by two transports
(or two models) lines up.

The report answers: how often the two sides agree that a window is a gem at
all (a 2×2 matrix, plus the windows only one side judged), and on the gems
they share — do they name the same speaker, the same life domain, the same
sensitivity, do their quotes overlap, and how close are their claims (token
Jaccard, with a histogram).

The sample file is what a human or a judge agent reads: every disagreement
first (gem-vs-not either way, and shared gems with a different speaker),
then 10 agree-gem and 10 agree-not-gem windows picked deterministically by
even stride over the sorted keys, each entry carrying the window text and
both sides' whole verdicts under the two labels.

Usage:
    compare_extracts.py --a <dirA> --b <dirB> --label-a agents
                        --label-b api --out report.json
                        --sample sample.json [--sample-size 60]

The report JSON also goes to stdout.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

QUOTE_BUCKETS = ("identical", "contains", "overlapping", "disjoint")
JACCARD_BINS = ("0-0.2", "0.2-0.5", "0.5-0.8", "0.8-1")
AGREE_SAMPLE = 10          # per agree bucket in the sample file
OVERLAP_WORDS = 4          # consecutive words that count as "overlapping"


def load(dirpath: str | pathlib.Path) -> dict[tuple, dict]:
    """``classified.jsonl`` keyed by (window id, start)."""
    p = pathlib.Path(dirpath) / "classified.jsonl"
    rows: dict[tuple, dict] = {}
    if not p.is_file():
        return rows
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        w = row.get("window") or {}
        rows[(w.get("id") or w.get("video_id"), w.get("start"))] = row
    return rows


def is_gem(row: dict | None) -> bool:
    return bool(((row or {}).get("verdict") or {}).get("self_disclosure"))


def tokens(s: str | None) -> set[str]:
    return {t for t in "".join(
        c.lower() if c.isalnum() else " " for c in (s or "")).split() if t}


def jaccard(a: str | None, b: str | None) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def words(s: str | None) -> list[str]:
    return "".join(c.lower() if c.isalnum() else " "
                   for c in (s or "")).split()


def quote_bucket(a: str | None, b: str | None) -> str:
    wa, wb = words(a), words(b)
    if wa and wa == wb:
        return "identical"
    sa, sb = " ".join(wa), " ".join(wb)
    if sa and sb and (sa in sb or sb in sa):
        return "contains"
    if len(wa) >= OVERLAP_WORDS and len(wb) >= OVERLAP_WORDS:
        grams = {" ".join(wb[i:i + OVERLAP_WORDS])
                 for i in range(len(wb) - OVERLAP_WORDS + 1)}
        for i in range(len(wa) - OVERLAP_WORDS + 1):
            if " ".join(wa[i:i + OVERLAP_WORDS]) in grams:
                return "overlapping"
    return "disjoint"


def jaccard_bin(x: float) -> str:
    if x < 0.2:
        return "0-0.2"
    if x < 0.5:
        return "0.2-0.5"
    if x < 0.8:
        return "0.5-0.8"
    return "0.8-1"


def stride_pick(keys: list, n: int) -> list:
    """``n`` items evenly strided over ``keys`` — deterministic, no sampling."""
    if len(keys) <= n:
        return list(keys)
    if n <= 0 or not keys:
        return []
    step = len(keys) / n
    return [keys[int(i * step)] for i in range(n)]


def entry(key, a_row: dict, b_row: dict, label_a: str, label_b: str,
          kind: str) -> dict:
    w = (a_row or b_row).get("window") or {}
    return {"kind": kind, "video_id": w.get("id") or w.get("video_id"),
            "start": w.get("start"), "title": w.get("title"),
            "format_hint": w.get("format_hint"),
            "in_sponsor_read": w.get("in_sponsor_read"),
            "text": w.get("text"),
            label_a: (a_row or {}).get("verdict"),
            label_b: (b_row or {}).get("verdict")}


def compare(a: dict, b: dict, label_a: str, label_b: str,
            sample_size: int) -> tuple[dict, list]:
    keys_a, keys_b = set(a), set(b)
    both = sorted(keys_a & keys_b, key=lambda k: (str(k[0]), k[1] or 0))
    matrix = {"a_gem_b_gem": 0, "a_gem_b_not": 0,
              "a_not_b_gem": 0, "a_not_b_not": 0}
    buckets = dict.fromkeys(QUOTE_BUCKETS, 0)
    hist = dict.fromkeys(JACCARD_BINS, 0)
    speaker_same = domain_same = sens_same = 0
    jsum = 0.0
    shared_gems = 0
    disagreements: list = []
    agree_gem: list = []
    agree_not: list = []
    for k in both:
        ra, rb = a[k], b[k]
        ga, gb = is_gem(ra), is_gem(rb)
        if ga and gb:
            matrix["a_gem_b_gem"] += 1
        elif ga:
            matrix["a_gem_b_not"] += 1
        elif gb:
            matrix["a_not_b_gem"] += 1
        else:
            matrix["a_not_b_not"] += 1
        if ga != gb:
            disagreements.append(entry(k, ra, rb, label_a, label_b,
                                       "a_gem_b_not" if ga else "a_not_b_gem"))
            continue
        if not ga:
            agree_not.append(k)
            continue
        shared_gems += 1
        va, vb = ra["verdict"], rb["verdict"]
        speaker_ok = va.get("speaker_guess") == vb.get("speaker_guess")
        speaker_same += speaker_ok
        domain_same += va.get("life_domain") == vb.get("life_domain")
        sens_same += va.get("sensitivity") == vb.get("sensitivity")
        buckets[quote_bucket(va.get("quote"), vb.get("quote"))] += 1
        j = jaccard(va.get("claim"), vb.get("claim"))
        jsum += j
        hist[jaccard_bin(j)] += 1
        if speaker_ok:
            agree_gem.append(k)
        else:
            disagreements.append(entry(k, ra, rb, label_a, label_b,
                                       "speaker_mismatch"))

    def rate(n: int) -> float | None:
        return round(n / shared_gems, 4) if shared_gems else None

    report = {
        "label_a": label_a, "label_b": label_b,
        "windows_a": len(keys_a), "windows_b": len(keys_b),
        "windows_both": len(both),
        "judged_by_one_side_only": len(keys_a ^ keys_b),
        "matrix": matrix,
        "shared_gems": shared_gems,
        "speaker_agreement": rate(speaker_same),
        "domain_agreement": rate(domain_same),
        "sensitivity_agreement": rate(sens_same),
        "quote_relation": buckets,
        "claim_jaccard_mean": round(jsum / shared_gems, 4) if shared_gems else None,
        "claim_jaccard_histogram": hist,
        "disagreements": len(disagreements),
    }
    sample = disagreements[:sample_size]
    room = sample_size - len(sample)
    for keys, kind in ((agree_gem, "agree_gem"), (agree_not, "agree_not_gem")):
        take = stride_pick(keys, min(AGREE_SAMPLE, max(0, room)))
        sample.extend(entry(k, a[k], b[k], label_a, label_b, kind)
                      for k in take)
        room = sample_size - len(sample)
    report["sample_entries"] = len(sample)
    return report, sample


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--a", required=True, help="assembled out dir, side A")
    ap.add_argument("--b", required=True, help="assembled out dir, side B")
    ap.add_argument("--label-a", default="a")
    ap.add_argument("--label-b", default="b")
    ap.add_argument("--out", required=True, help="report JSON path")
    ap.add_argument("--sample", required=True, help="sample JSON path")
    ap.add_argument("--sample-size", type=int, default=60)
    a = ap.parse_args()
    report, sample = compare(load(a.a), load(a.b), a.label_a, a.label_b,
                             a.sample_size)
    report["a"] = str(a.a)
    report["b"] = str(a.b)
    pathlib.Path(a.out).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    pathlib.Path(a.sample).write_text(
        json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
