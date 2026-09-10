#!/usr/bin/env python3
"""Authenticate the claims a merge shard should not have to guess about.

Two kinds of candidate leave the extractor looking exactly like a fact and
are not one, or not yet one:

* **A claim stated inside a staged premise.** A prank, challenge or skit
  upload (``format_hint: staged`` on the window) can put "my husband" or
  "we just moved" in the host's own mouth as the bit. The words are hers; the
  fact may not be.
* **Two clusters that contradict each other in a durable domain.** "We live
  in the desert of Idaho" (2020-01) and "we live in northern Utah" (2020-04)
  cannot both be current. Latest-wins between those two videos is not the
  whole answer when the 300-window sample never reached the 2024 upload
  that says Idaho again.

Both used to be settled by the merge shard on the strength of two lines of
compact input, and the 2026-09-09 runs showed it settling them wrong in both
directions: dropping two "husband" lines as premise while keeping and
selecting a third, and superseding Idaho with Utah while the identity lane
said Idaho. The instruction from the review of those runs: **do not drop,
demote or supersede a fact because the pipeline is unsure; go and check.**

So this script checks. For each flagged cluster it runs ONE channel-scoped
Elasticsearch phrase query, the cue phrase the window fired plus the claim's
entity (``"we live in"`` + ``Idaho``; ``"my husband"`` alone when there is
no entity), and attaches what the whole catalogue says to the merge-input
line as ``probe``::

    {"videos": 4, "newest": "2024-06-02", "oldest": "2020-01-10",
     "staged_videos": 1, "non_staged_videos": 3, "staged_share": 0.25,
     "sample": [{"video_id": "...", "title": "...", "published": "..."}],
     "query": "\"we live in\" + idaho"}

Contradicting clusters also get ``conflicts_with: ["c058"]`` on both lines.
The shard reads that evidence and decides; ``merge_pass.py expand`` refuses
only a decision that points against the dated evidence (a supersession whose
target has newer evidence than the superseder), and it refuses it as a
re-ask, never as a silent edit.

What the evidence means, for the shard (also in ``agents/merge-shard.md``):

* found in at least one non-staged upload: the claim is the person's, keep
  it at the confidence the format gives it;
* found only in staged uploads: keep it, ``unconfirmed``, and expand marks it
  ``staged_only`` so it never reaches a brand-facing page; never drop it for
  being uncertain;
* nothing found either side of a conflict: keep both, ``unconfirmed``;
* newest dated evidence wins a conflict, and the identity lane's
  ``seen_date`` is evidence too when its source is the creator's own profile.

Budget: one query per flagged cluster, ``--max-queries`` (default 30) per
run, ``size`` 50, foreground, no deepening. It runs inside ``merge_pass.py
prepare`` when ``--channel`` is given, or standalone::

    authenticate.py --channel <id> --in <corpus>/merge-input.jsonl [--in ...]
        [--clustered <corpus>/gems-clustered.jsonl] [--out-json <corpus>/probe.json]

``--in`` files are rewritten in place with ``probe`` / ``conflicts_with`` /
``staged`` added; ``probe.json`` (one object keyed by cluster id) is what
``expand`` reads for its dated-evidence check. Exit 0 always: a failed query
is recorded on the line as ``probe: {"error": ...}`` and the shard is told
to treat it as "nothing found".
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data  # noqa: E402
from channel_context import TITLE_HINTS  # noqa: E402

# Domains where a claim is durable enough that a staged premise or a
# contradiction matters. A taste stated in a prank is still a taste.
DURABLE_DOMAINS = {"home", "relationships", "family", "work", "origin", "health"}
# Words that make a relationships/family claim a status, not an anecdote.
PARTNER_NOUNS = {"husband", "wife", "boyfriend", "girlfriend", "fiance", "fiancé",
                 "fiancee", "fiancée", "partner", "spouse", "ex", "married",
                 "engaged", "divorced", "single", "dating", "pregnant", "baby"}
HOME_VERBS = re.compile(r"\b(live[sd]? in|living in|moved? to|moving to|based in|"
                        r"grew up in|from)\b", re.I)
# Cue phrases worth searching on their own; the shortest ones (i, my) are not.
MIN_CUE_WORDS = 2
STOP_ENTITIES = {"I", "My", "The", "A", "An", "In", "On", "At", "We", "She", "He",
                 "They", "It", "Youtube", "YouTube", "Instagram", "TikTok", "Chef"}
MAX_SAMPLE = 5
QUERY_SIZE = 50
APOSTROPHE_TOKEN = " 39 "


def _phrase_variants(phrase: str) -> list[str]:
    out = [phrase]
    if "'" in phrase:
        out.append(re.sub(r"\s*'\s*", APOSTROPHE_TOKEN, phrase).strip())
    return out


def cue_phrase(line: dict, cluster: dict | None) -> str | None:
    """The phrase to search on: the longest multi-word cue the window fired
    that also appears IN THE QUOTE (a cue fired elsewhere in the window, or
    the channel's recurring greeting, says nothing about this claim). Falls
    back to a partner word or a home verb found in the quote."""
    quote = str(line.get("quote") or "").lower()
    cues: list[str] = []
    recurring = ""
    if cluster:
        w = cluster.get("window") or {}
        cues = [str(c) for c in (w.get("cues_fired") or []) if c]
        recurring = str(w.get("recurring_phrase") or "").lower()
    cues = [c for c in cues
            if len(c.split()) >= MIN_CUE_WORDS and c.lower() != recurring
            and c.lower() in quote]
    if cues:
        return max(cues, key=len)
    for noun in sorted(PARTNER_NOUNS, key=len, reverse=True):
        if re.search(rf"\bmy {noun}\b", quote):
            return f"my {noun}"
    m = HOME_VERBS.search(quote)
    if m:
        return m.group(0).lower()
    for word in ("got married", "married", "engaged", "pregnant", "divorced",
                 "broke up", "moved", "quit my job", "diagnosed"):
        if re.search(rf"\b{word}\b", quote):
            return word
    return None


def entities(text: str) -> list[str]:
    """Capitalised tokens in a claim that look like a name or a place."""
    out: list[str] = []
    for tok in re.findall(r"\b[A-Z][a-zA-Z'’-]{2,}\b", text or ""):
        if tok in STOP_ENTITIES or tok.lower() in out:
            continue
        out.append(tok.lower())
    return out


def partner_noun(text: str) -> str | None:
    words = set(re.findall(r"[a-zà-ÿ'’-]+", (text or "").lower()))
    # "ex-boyfriend" tokenises whole, so a plain "boyfriend" test never fires on it
    for noun in ("ex-boyfriend", "ex-girlfriend", "ex-husband", "ex-wife",
                 "husband", "wife", "fiance", "fiancé", "fiancee", "fiancée",
                 "boyfriend", "girlfriend", "partner", "spouse",
                 "married", "engaged", "divorced", "single", "pregnant"):
        if noun in words:
            return noun
    return None


def is_staged(line: dict) -> bool:
    return str(line.get("format_hint") or "") == "staged"


def wants_probe(line: dict) -> bool:
    """A staged window in a durable domain, or a line already marked as
    conflicting (set by ``find_conflicts`` before this runs)."""
    if line.get("conflicts_with"):
        return True
    return is_staged(line) and str(line.get("domain") or "") in DURABLE_DOMAINS


def find_conflicts(lines: list[dict]) -> int:
    """Mark pairs that cannot both be current: two ``home`` claims naming
    different places, or two relationship claims with different partner
    nouns. Same-claim pairs (same place, same noun) are folds, not conflicts,
    and are left to the shard."""
    marked = 0
    by_domain: dict[str, list[dict]] = {}
    for line in lines:
        by_domain.setdefault(str(line.get("domain") or ""), []).append(line)

    def link(a: dict, b: dict) -> None:
        nonlocal marked
        for x, y in ((a, b), (b, a)):
            lst = x.setdefault("conflicts_with", [])
            if y["c"] not in lst:
                lst.append(y["c"])
                marked += 1

    homes = [ln for ln in by_domain.get("home", [])
             if HOME_VERBS.search(str(ln.get("claim") or "") + " " + str(ln.get("quote") or ""))]
    for i, a in enumerate(homes):
        ea = set(entities(a.get("claim") or "")) | set(entities(a.get("quote") or ""))
        if not ea:
            continue
        for b in homes[i + 1:]:
            eb = set(entities(b.get("claim") or "")) | set(entities(b.get("quote") or ""))
            if eb and not (ea & eb):
                link(a, b)

    rel = [ln for ln in by_domain.get("relationships", []) + by_domain.get("family", [])
           if partner_noun(str(ln.get("claim") or "") + " " + str(ln.get("quote") or ""))]
    # an ex is compatible with a husband; a current boyfriend is not
    committed = {"husband", "wife", "married", "spouse", "fiance", "fiancé",
                 "fiancee", "fiancée", "engaged"}
    uncommitted = {"boyfriend", "girlfriend", "dating", "single"}
    for i, a in enumerate(rel):
        na = partner_noun(str(a.get("claim") or "") + " " + str(a.get("quote") or ""))
        for b in rel[i + 1:]:
            nb = partner_noun(str(b.get("claim") or "") + " " + str(b.get("quote") or ""))
            if na == nb:
                continue
            if (na in committed and nb in uncommitted) or (na in uncommitted and nb in committed):
                link(a, b)
    return marked


def es_body(channel: int, phrase: str, entity: str | None) -> dict:
    must: list[dict] = [{"bool": {"should": [
        {"match_phrase": {"transcript": {"query": v}}} for v in _phrase_variants(phrase)
    ], "minimum_should_match": 1}}]
    if entity:
        must.append({"match": {"transcript": {"query": entity, "operator": "and"}}})
    return {
        "size": QUERY_SIZE,
        "_source": ["id", "title", "publication_date", "transcript_language"],
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "article"}},
            {"term": {"channel.id": channel}},
            {"exists": {"field": "transcript"}},
        ], "must": must}},
        "sort": [{"publication_date": "desc"}, {"id": "asc"}],
    }


def probe(channel: int, line: dict, cluster: dict | None) -> dict:
    phrase = cue_phrase(line, cluster)
    if not phrase:
        return {"skipped": "no cue phrase to search on"}
    ents = entities(str(line.get("claim") or ""))
    entity = ents[0] if ents else None
    label = f"\"{phrase}\"" + (f" + {entity}" if entity else "")
    try:
        rows = tl_data.db_es(es_body(channel, phrase, entity))
    except Exception as exc:  # recorded, never raised: the shard treats it as nothing found
        return {"query": label, "error": str(exc)[:300]}
    seen: dict[str, dict] = {}
    for r in rows:
        vid = str(r.get("id") or "")
        if not vid or vid in seen:
            continue
        title = str(r.get("title") or "")
        seen[vid] = {"video_id": vid.split(":", 1)[-1], "title": title,
                     "published": str(r.get("publication_date") or "")[:10],
                     "staged": bool(TITLE_HINTS["staged"].search(title))
                     and not any(TITLE_HINTS[k].search(title) for k in ("reaction", "interview_or_collab"))}
    vids = list(seen.values())
    dates = sorted(v["published"] for v in vids if v["published"])
    staged_n = sum(1 for v in vids if v["staged"])
    return {
        "query": label,
        "videos": len(vids),
        "newest": dates[-1] if dates else None,
        "oldest": dates[0] if dates else None,
        "staged_videos": staged_n,
        "non_staged_videos": len(vids) - staged_n,
        "staged_share": round(staged_n / len(vids), 2) if vids else None,
        "sample": [{k: v[k] for k in ("video_id", "title", "published", "staged")}
                   for v in vids[:MAX_SAMPLE]],
    }


def run(channel: int, files: list[pathlib.Path], clustered: pathlib.Path | None,
        max_queries: int) -> dict:
    t0 = time.monotonic()
    clusters_by_c: dict[str, dict] = {}
    if clustered and clustered.exists():
        with open(clustered, encoding="utf-8") as fh:
            for i, raw in enumerate(fh):
                raw = raw.strip()
                if raw:
                    clusters_by_c[f"c{i + 1:03d}"] = json.loads(raw)
    per_file: dict[pathlib.Path, list[dict]] = {}
    lines: list[dict] = []
    for f in files:
        rows = [json.loads(x) for x in open(f, encoding="utf-8") if x.strip()]
        per_file[f] = rows
        lines.extend(rows)
    for line in lines:
        if is_staged(line):
            line["staged"] = True
    conflicts = find_conflicts(lines)
    queried = 0
    results: dict[str, dict] = {}
    for line in lines:
        if not wants_probe(line):
            continue
        if queried >= max_queries:
            line["probe"] = {"skipped": f"query budget of {max_queries} reached"}
            continue
        line["probe"] = probe(channel, line, clusters_by_c.get(str(line.get("c"))))
        queried += 1
        results[str(line.get("c"))] = {
            "probe": line["probe"], "staged": bool(line.get("staged")),
            "conflicts_with": list(line.get("conflicts_with") or []),
            "published": line.get("published"), "domain": line.get("domain"),
            "claim": line.get("claim")}
    for f, rows in per_file.items():
        with open(f, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False, default=str,
                                    separators=(",", ":")) + "\n")
    elapsed = round(time.monotonic() - t0, 1)
    summary = {"channel": channel, "lines": len(lines),
               "staged_lines": sum(1 for x in lines if x.get("staged")),
               "conflict_marks": conflicts,
               "conflict_lines": sum(1 for x in lines if x.get("conflicts_with")),
               "queries": queried, "max_queries": max_queries,
               "found_non_staged": sum(1 for r in results.values()
                                       if (r["probe"].get("non_staged_videos") or 0) > 0),
               "staged_only": sum(1 for r in results.values()
                                  if r["probe"].get("videos") and not r["probe"].get("non_staged_videos")),
               "nothing_found": sum(1 for r in results.values()
                                    if r["probe"].get("videos") == 0),
               "errors": sum(1 for r in results.values() if r["probe"].get("error")),
               "results": results, "elapsed_s": elapsed}
    print(f"FUNNEL stage=authenticate lines={len(lines)} staged={summary['staged_lines']} "
          f"conflicts={summary['conflict_lines']} queries={queried} "
          f"found_non_staged={summary['found_non_staged']} staged_only={summary['staged_only']} "
          f"nothing_found={summary['nothing_found']} errors={summary['errors']} "
          f"elapsed_s={elapsed}", file=sys.stderr)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", type=int, required=True)
    ap.add_argument("--in", dest="infiles", action="append", required=True,
                    help="merge-input*.jsonl, rewritten in place; repeatable")
    ap.add_argument("--clustered", default=None,
                    help="gems-clustered.jsonl, for the cue phrases the windows fired")
    ap.add_argument("--out-json", default=None,
                    help="probe.json for expand's dated-evidence check "
                         "(default: probe.json beside the first --in)")
    ap.add_argument("--max-queries", type=int, default=30)
    a = ap.parse_args()
    files = [pathlib.Path(p) for p in a.infiles]
    summary = run(a.channel, files, pathlib.Path(a.clustered) if a.clustered else None,
                  a.max_queries)
    out = pathlib.Path(a.out_json) if a.out_json else files[0].parent / "probe.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    slim = {k: v for k, v in summary.items() if k != "results"}
    slim["probe_file"] = str(out)
    print(json.dumps(slim, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
