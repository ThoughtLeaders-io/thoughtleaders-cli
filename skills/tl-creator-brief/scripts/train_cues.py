#!/usr/bin/env python3
"""Learn the cue-phrase weights in ``references/cue-phrases.txt`` from labeled
windows, instead of hand-tuning them.

The weight beside each phrase is both the ES boost and the rank score, so it is
the model: a phrase that predicts a gem should pull its passages up, one that
does not should not be queried at all. Commit b7147f7 measured the hand-tuned
ladder flat (rank 3.0 -> 0.47 gems/window, 2.0 -> 0.45, 1.0 -> 0.50), which is
what a knob that is not fitted to anything looks like.

Input is one uncapped ``fetch_cues.py`` corpus per channel (``--windows``, the
``--out`` root: every ``<channel>/batches/*.json`` is read, those are the kept,
widened windows) plus one label per window (``--labels``, JSONL of
``{"id": "<channel>:<video>:<start>", "gem": true|false}``; a bulk-classify
output file is read directly). A sparse logistic regression over one binary
feature per cue phrase, ``generic_density`` and ``host_anchor`` gives each
phrase a coefficient; the positive ones are rescaled by quantile into the
0.5 / 1 / 2 / 3 bands the file already uses, and phrases that predict nothing
(coefficient <= 0) or fire too rarely to tell (support < ``--min-support``) are
dropped from the file. Nothing about the runtime changes: fetch_cues.py reads
the same file in the same format.

A phrase's feature is the firing ``fetch_cues.py`` recorded (``cues_fired``, the
ES match_phrase on the narrow fragment), so the fit sees production's retrieval,
not a re-match over the wider read. Candidate phrases from ``--extra-phrases``
have no recorded firing and are matched as substrings of the window text.

    train_cues.py --labels <jsonl> --windows <corpus dir> --out cue-phrases.txt
                  [--fit-channels 1,2] [--eval-channels 9,10]
                  [--extra-phrases <file>] [--min-support 8] [--report <json>]

Writes the new phrase file, prints the per-phrase table (coefficient, support,
precision, old weight -> new weight) and, with ``--eval-channels``, the held-out
old-vs-new comparison: gem yield by rank-score bucket, gems in the top 150, and
the recall a 150-window cap keeps.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import html
import json
import math
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_cues as fc  # sibling: the phrase file parser and the rank formula

TAG = re.compile(r"<[^>]+>")
WS = re.compile(r"\s+")
DEFAULT_PHRASES = pathlib.Path(__file__).resolve().parent.parent / "references" / "cue-phrases.txt"


def clean(t: str) -> str:
    return WS.sub(" ", TAG.sub(" ", html.unescape(t or ""))).strip()


def load_windows(root: pathlib.Path) -> list[dict]:
    """Every kept window of every channel corpus under ``root``."""
    rows, seen = [], set()
    for cdir in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(glob.glob(str(cdir / "batches" / "*.json"))):
            for w in json.load(open(f)):
                key = (cdir.name, w["video_id"], w["start"])
                if key in seen:
                    continue
                seen.add(key)
                w["wid"] = f"{cdir.name}:{w['video_id']}:{w['start']}"
                w["channel"] = int(cdir.name)
                w["text"] = clean(w["text"])
                rows.append(w)
    return rows


def load_labels(path: pathlib.Path) -> dict[str, int]:
    """``{window id: 0|1}``. Takes this file's own format or a bulk-classify out."""
    out: dict[str, int] = {}
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        rec = json.loads(line)
        if "item" in rec:                      # bulk-classify shape
            item, res = rec.get("item") or {}, rec.get("result")
            if not isinstance(item, dict) or not isinstance(res, dict):
                continue
            wid, gem = item.get("id"), res.get("gem")
        else:
            wid, gem = rec.get("id"), rec.get("gem")
        if wid is None or gem is None:
            continue
        out[wid] = 1 if gem in (True, "true", "yes", 1) else 0
    return out


def density(text: str) -> int:
    """First-person marker hits in the window, fetch_cues.py's own count."""
    return fc.first_person_density(text)


def featurize(rows: list[dict], phrases: list[str], extra: list[str]) -> None:
    """Attach the sparse feature list to every window, in place."""
    index = {p: i for i, p in enumerate(phrases)}
    for w in rows:
        feats: dict[int, float] = {}
        fired = set()
        for c in w.get("cues_fired") or []:
            c = c.lower()
            if c in index:
                feats[index[c]] = 1.0
                fired.add(c)
        for p in extra:                        # mined candidates: no ES record to read
            if f" {p} " in f" {w['text'].lower()} ":
                feats[index[p]] = 1.0
                fired.add(p)
        w["fired"] = fired
        w["density"] = density(w["text"])
        feats[len(phrases)] = w["density"] / float(fc.GENERIC_DENSITY_CAP)
        feats[len(phrases) + 1] = 1.0 if w.get("host_anchor") else 0.0
        w["feats"] = feats


def fit(rows: list[dict], n_feat: int, *, epochs: int = 400, lr: float = 0.5,
        l2: float = 1e-3) -> tuple[list[float], float]:
    """Sparse batch gradient descent on the logistic loss. A window fires a
    handful of the ~250 features, so a dense pass would be all zeros."""
    w = [0.0] * n_feat
    b = 0.0
    n = float(len(rows))
    for _ in range(epochs):
        gw: dict[int, float] = {}
        gb = 0.0
        for r in rows:
            z = b + sum(w[i] * v for i, v in r["feats"].items())
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            d = p - r["y"]
            gb += d
            for i, v in r["feats"].items():
                gw[i] = gw.get(i, 0.0) + d * v
        b -= lr * gb / n
        for i, g in gw.items():
            w[i] -= lr * (g / n + l2 * w[i])
    return w, b


def bands(coefs: dict[str, float]) -> dict[str, float]:
    """Positive coefficients into the file's own 0.5 / 1 / 2 / 3 ladder, by quantile."""
    ranked = sorted(coefs.items(), key=lambda kv: kv[1])
    n = len(ranked)
    out = {}
    for i, (p, _) in enumerate(ranked):
        q = (i + 0.5) / n
        out[p] = 0.5 if q < 0.25 else 1.0 if q < 0.5 else 2.0 if q < 0.75 else 3.0
    return out


def rank_score(w: dict, weights: dict[str, float], recurring: set[str],
               fired: set[str] | None = None) -> float:
    """fetch_cues.py's own formula, recomputed offline over a weight table."""
    density_term = fc.DENSITY_WEIGHT * w["density"]
    if w.get("retrieval") == "generic":
        return round(density_term
                     + fc.SELF_NAME_BONUS * (1 if w.get("host_anchor") else 0), 2)
    cues = fired if fired is not None else {c.lower() for c in (w.get("cues_fired") or [])}
    live = [c for c in cues if weights.get(c, 0.0) > 0]
    specific = [c for c in live if c not in recurring]
    rec = [c for c in live if c in recurring]
    return round(density_term
                 + min(sum(weights.get(c, 0.0) for c in specific), fc.RANK_CAP)
                 + 0.5 * min(len(rec), 1)
                 + fc.SELF_NAME_BONUS * (1 if w.get("host_anchor") else 0), 2)


def evaluate(rows: list[dict], weights: dict[str, float], recurring: set[str],
             *, new: bool, cap: int = 150) -> dict:
    scored = []
    for w in rows:
        fired = w["fired"] if new else None
        scored.append((rank_score(w, weights, recurring, fired), w["y"]))
    scored.sort(key=lambda t: -t[0])
    pos = sum(y for _, y in scored)
    buckets: dict[str, list[int]] = {}
    for s, y in scored:
        b = ("0" if s <= 0 else "0-1" if s < 1 else "1-2" if s < 2 else
             "2-3" if s < 3 else "3-4.5" if s < 4.5 else "4.5+")
        buckets.setdefault(b, [0, 0])
        buckets[b][0] += 1
        buckets[b][1] += y
    top = scored[:cap]
    return {"windows": len(scored), "positives": pos,
            "top_cap": cap, "top_gems": sum(y for _, y in top),
            "recall_at_cap": round(sum(y for _, y in top) / pos, 3) if pos else None,
            "buckets": {k: {"windows": v[0], "gems": v[1],
                            "yield": round(v[1] / v[0], 3)} for k, v in buckets.items()}}


def write_phrase_file(src: pathlib.Path, out: pathlib.Path, new_w: dict[str, float],
                      dropped: set[str], added: dict[str, float], n_rows: int,
                      n_chan: int) -> None:
    """Rewrite the file in place-order: the header and every section comment stay,
    a kept phrase takes its learned weight, a dropped phrase leaves."""
    lines = [f"# trained {dt.date.today().isoformat()} on {n_rows} labeled windows, "
             f"{n_chan} channels (scripts/train_cues.py; see references/cue-training.md)"]
    for raw in src.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            lines.append(raw)
            continue
        body = s.split("|", 1)[0].strip()
        mark = "~" if body.startswith("~") else ""
        phrase = body.lstrip("~").strip().lower()
        if phrase in dropped:
            continue
        lines.append(f"{mark}{phrase} | {fc_fmt(new_w[phrase])}")
    if added:
        lines.append("")
        lines.append(f"# mined {dt.date.today().isoformat()} from positive windows the "
                     f"phrase list missed (train_cues.py step 6)")
        for p, wt in sorted(added.items(), key=lambda kv: -kv[1]):
            lines.append(f"{p} | {fc_fmt(wt)}")
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fc_fmt(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else str(x)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", required=True)
    ap.add_argument("--windows", required=True, help="fetch_cues.py --out root")
    ap.add_argument("--out", default=str(DEFAULT_PHRASES))
    ap.add_argument("--phrases", default=str(DEFAULT_PHRASES))
    ap.add_argument("--fit-channels", default="", help="comma-separated ids; default all but --eval-channels")
    ap.add_argument("--eval-channels", default="")
    ap.add_argument("--extra-phrases", default="", help="one mined candidate phrase per line")
    ap.add_argument("--min-support", type=int, default=8)
    ap.add_argument("--report", default="")
    a = ap.parse_args()

    phrases, recurring, old_w = fc.load_phrases(pathlib.Path(a.phrases))
    phrases = [p.lower() for p in phrases]
    extra = []
    if a.extra_phrases:
        extra = [ln.strip().lower() for ln in open(a.extra_phrases) if ln.strip()
                 and not ln.startswith("#") and ln.strip().lower() not in phrases]
    all_phrases = phrases + extra

    rows = load_windows(pathlib.Path(a.windows))
    labels = load_labels(pathlib.Path(a.labels))
    rows = [r for r in rows if r["wid"] in labels]
    for r in rows:
        r["y"] = labels[r["wid"]]
    featurize(rows, all_phrases, extra)

    ev_ids = {int(x) for x in a.eval_channels.split(",") if x.strip()}
    fit_ids = ({int(x) for x in a.fit_channels.split(",") if x.strip()}
               or {r["channel"] for r in rows} - ev_ids)
    fit_rows = [r for r in rows if r["channel"] in fit_ids]
    ev_rows = [r for r in rows if r["channel"] in ev_ids]
    if not fit_rows:
        sys.exit("no labeled windows in the fit channels")

    coef, bias = fit(fit_rows, len(all_phrases) + 2)
    support = {p: 0 for p in all_phrases}
    hits = {p: 0 for p in all_phrases}
    for r in fit_rows:
        for p in r["fired"]:
            support[p] += 1
            hits[p] += r["y"]
    base = sum(r["y"] for r in fit_rows) / len(fit_rows)

    keep = {p: coef[i] for i, p in enumerate(all_phrases)
            if coef[i] > 0 and support[p] >= a.min_support}
    new_bands = bands(keep) if keep else {}
    dropped = {p for p in phrases if p not in new_bands}
    added = {p: new_bands[p] for p in extra if p in new_bands}
    new_w = dict(new_bands)

    print(f"labeled windows={len(rows)} fit={len(fit_rows)} eval={len(ev_rows)} "
          f"base gem rate={base:.3f} bias={bias:.3f}")
    print(f"{'phrase':<34}{'coef':>8}{'supp':>7}{'prec':>7}{'old':>6}{'new':>6}")
    for p in sorted(all_phrases, key=lambda q: -coef[all_phrases.index(q)]):
        i = all_phrases.index(p)
        prec = hits[p] / support[p] if support[p] else 0.0
        old = old_w.get(p, "")
        new = new_w.get(p, "DROP")
        print(f"{p:<34}{coef[i]:>8.3f}{support[p]:>7}{prec:>7.2f}{str(old):>6}{str(new):>6}")
    print(f"generic_density coef={coef[len(all_phrases)]:.3f}  "
          f"host_anchor coef={coef[len(all_phrases) + 1]:.3f}")
    print(f"dropped={len(dropped)} kept={len(new_bands) - len(added)} added={len(added)}")

    report = {"fit_channels": sorted(fit_ids), "eval_channels": sorted(ev_ids),
              "labeled_windows": len(rows), "fit_windows": len(fit_rows),
              "base_gem_rate": round(base, 4),
              "dropped": sorted(dropped), "added": added,
              "weights": {p: new_w[p] for p in sorted(new_w)},
              "coef": {p: round(coef[i], 4) for i, p in enumerate(all_phrases)},
              "support": support, "precision": {p: round(hits[p] / support[p], 3)
                                                for p in all_phrases if support[p]},
              "generic_density_coef": round(coef[len(all_phrases)], 4),
              "host_anchor_coef": round(coef[len(all_phrases) + 1], 4)}

    for cid in sorted(ev_ids):
        rws = [r for r in ev_rows if r["channel"] == cid]
        if not rws:
            continue
        old_eval = evaluate(rws, old_w, recurring, new=False)
        new_eval = evaluate(rws, new_w, recurring, new=True)
        report.setdefault("holdout", {})[str(cid)] = {"old": old_eval, "new": new_eval}
        print(f"\n--- held out {cid}: {old_eval['windows']} windows, "
              f"{old_eval['positives']} positives")
        print(f"    top150 gems old={old_eval['top_gems']} new={new_eval['top_gems']}  "
              f"recall@150 old={old_eval['recall_at_cap']} new={new_eval['recall_at_cap']}")
        for tag, ev in (("old", old_eval), ("new", new_eval)):
            row = "  ".join(f"{k}:{v['gems']}/{v['windows']}={v['yield']}"
                            for k, v in sorted(ev["buckets"].items()))
            print(f"    {tag}: {row}")

    write_phrase_file(pathlib.Path(a.phrases), pathlib.Path(a.out), new_w, dropped,
                      added, len(fit_rows), len(fit_ids))
    if a.report:
        pathlib.Path(a.report).write_text(json.dumps(report, indent=1))
    print(f"\nwrote {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
