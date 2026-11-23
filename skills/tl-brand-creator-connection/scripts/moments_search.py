#!/usr/bin/env python3
"""The brand moments lane's searches, done mechanically, so the lane agent only
judges.

The agent decides what to search (one phrase list per occasion, plus the
brand's own terms) and, afterwards, which windows are the creator's own
strongest moments. Everything in between is mechanical and lives here: the
channel-scoped transcript searches, last 24 months first with an older search
only for an occasion that found nothing recent, decoding the timed-text XML
into windows, dropping windows near a sponsored read, dropping uploads the
brand itself sponsored from the brand list, and flagging windows that carry a
discount code or a link.

Usage:
    moments_search.py --channel <id> --brand <id> [--brand <id2>] \\
        --plan <plan.json> --out <corpus>/moments-candidates.json

plan.json:
    {"occasions": [{"occasion": "travel", "phrases": ["airport", "hotel", "packing"]}, ...],
     "brand_terms": ["<brand>", "<product>"]}

Output: the candidates file, a readable copy beside it (moments-candidates.txt,
one window per line, which the agent reads in full), and one JSON summary on
stdout, a FUNNEL line on stderr.

Pick: after judging, the agent names its choices and this script copies the
exact window text into category-probe.json, so no caption is retyped:
    moments_search.py --pick <picks.json> --candidates <corpus>/moments-candidates.json \
        --out <corpus>/category-probe.json

picks.json:
    {"windows": [{"video_id": "abc", "start": 963, "occasion": "travel",
                  "from": "so we got", "to": "the hotel"}],
     "brand_windows": [{"video_id": "def", "start": 120}],
     "note": "what the agent wants coverage.note to say"}
"from" and "to" are optional: a few exact words where one unbroken stretch of
the window starts and ends. Without them the whole window is kept.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import fetch_cues  # noqa: E402  sibling: the transcript fetch and the sponsor-read lookup
from brand_reads import months_ago  # noqa: E402

MAX_QUERIES = 16          # the lane's search budget (SKILL.md)
SIZE = 20                 # uploads per search
BEFORE, AFTER = 6, 18     # a window: 6 s before the hit to 18 s after
GAP = 45                  # a new window only 45 s after the last one in a video
SPONSOR_MARGIN = 60       # no window within 60 s of a sponsored read (any brand)
PER_VIDEO = 3             # windows per upload per occasion
PER_OCCASION = 40         # windows per occasion handed to the agent, first-person then newest first

CODE_OR_LINK = re.compile(r"\b(?:use|my|with) code\b|\bcode [A-Z0-9]{3,}\b|\bdiscount code\b|"
                          r"\blink (?:in|below|down)\b|https?://|www\.|\.com/", re.I)
FIRST_PERSON = re.compile(r"\b(?:i|i'm|im|i've|i'd|i'll|me|my|mine|myself|we|we're|we've|our|us)\b", re.I)


def funnel(**fields) -> None:
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()), file=sys.stderr)


def phrase_rx(phrases: list[str]) -> re.Pattern | None:
    alts = [r"\s+".join(re.escape(w) for w in p.split()) for p in phrases if p.strip()]
    # the search engine matches "holidays" and "episodes" for holiday and
    # episode, so the window finder does too
    return re.compile(r"(?<![\w])((?:" + "|".join(alts) + r")(?:s|es|'s)?)(?![\w])", re.I) if alts else None


def search(channel: int, phrases: list[str], since: str | None, before: str | None,
           terms: dict[str, int]) -> list[dict]:
    """One channel-scoped search: any of the phrases, as phrases. Adds each
    phrase's upload count to ``terms``. Returns the uploads without their
    transcripts; ``with_cues`` fetches each upload's captions once."""
    flt: list[dict] = [{"term": {"channel.id": channel}}]
    if since:
        flt.append({"range": {"publication_date": {"gte": since}}})
    if before:
        flt.append({"range": {"publication_date": {"lt": before}}})
    ph = [p.strip() for p in phrases if p.strip()]
    body = {"size": SIZE, "_source": ["title", "publication_date", "views"],
            "query": {"bool": {"filter": flt, "should": [{"match_phrase": {"transcript": p}} for p in ph],
                               "minimum_should_match": 1}},
            "aggs": {"t": {"filters": {"filters": {p: {"match_phrase": {"transcript": p}} for p in ph}}}}}
    rows, aggs = tl_data.db_es_with_aggs(body)
    buckets = (aggs.get("t") or {}).get("buckets") or {}
    for p, b in buckets.items():
        terms[p.lower()] = terms.get(p.lower(), 0) + int((b or {}).get("doc_count") or 0)
    return rows


def with_cues(rows: list[dict], cues: dict[str, list]) -> None:
    """Adds each upload's captions, fetching only the uploads not yet in
    ``cues``: an upload found by several searches is downloaded once."""
    refs = [ref(d) for d in rows]
    missing = sorted({r for r in refs if r not in cues})
    if missing:
        got = fetch_cues.fetch_transcripts(missing)
        cues.update({r: got.get(r, []) for r in missing})
    for d, r in zip(rows, refs):
        d["cues"] = cues[r]


def ref(d: dict) -> str:
    return str(d.get("_id") or d.get("id") or "")


def sponsorship(refs: list[str]) -> tuple[dict[str, list[tuple[float, float]]], dict[str, set[str]], set[str]]:
    """Per upload: located sponsored spans, the brands that sponsored it, and
    the uploads whose read has no located position (fetch_cues' lookup)."""
    spans: dict[str, list[tuple[float, float]]] = {}
    sponsors: dict[str, set[str]] = {}
    for i in range(0, len(refs), fetch_cues.IDS_CHUNK):
        for r, found in fetch_cues.sponsor_chunk(refs[i:i + fetch_cues.IDS_CHUNK], sponsors).items():
            spans.setdefault(r, []).extend(found)
    unlocated = {r for r, found in spans.items() if fetch_cues.UNLOCATED in found}
    spans = {r: [x for x in found if x != fetch_cues.UNLOCATED] for r, found in spans.items()}
    return spans, sponsors, unlocated


def windows_for(doc: dict, rx: re.Pattern) -> list[dict]:
    """Every hit in one upload as a window, at most one per GAP seconds."""
    cs = doc.get("cues") or []
    vid = ref(doc).split(":")[-1]
    out, last = [], -1e9
    for i, (s, t) in enumerate(cs):
        joined = t + (" " + cs[i + 1][1] if i + 1 < len(cs) else "")
        m = rx.search(joined)
        if not m or m.start() > len(t):  # a hit wholly inside the next cue is that cue's
            continue
        if s - last < GAP:
            continue
        last = s
        span = [(cs_s, cs_t) for cs_s, cs_t in cs if s - BEFORE <= cs_s <= s + AFTER]
        start = int(span[0][0])
        text = " ".join(x[1] for x in span)
        out.append({"video_id": vid, "start": start, "end": int(span[-1][0]) + 1,
                    "published": str(doc.get("publication_date") or "")[:10],
                    "url": f"https://www.youtube.com/watch?v={vid}&t={start}s",
                    "title": doc.get("title"), "views": doc.get("views"), "text": text,
                    "hit": m.group(1), "first_person": bool(FIRST_PERSON.search(text)),
                    "code_or_link": bool(CODE_OR_LINK.search(text))})
    return out


def by_upload(ws: list[dict]) -> list[dict]:
    """Windows grouped under their upload, so a title is written once."""
    out: dict[str, dict] = {}
    for w in ws:
        u = out.setdefault(w["video_id"], {"video_id": w["video_id"], "title": w["title"],
                                            "published": w["published"], "views": w["views"], "windows": []})
        u["windows"].append({k: w[k] for k in ("start", "text", "hit") }
                            | {k: True for k in ("first_person", "code_or_link", "upload_has_unplaced_read") if w.get(k)})
    return list(out.values())


def near_sponsor(w: dict, spans: list[tuple[float, float]]) -> bool:
    return any(a - SPONSOR_MARGIN <= w["end"] and b + SPONSOR_MARGIN >= w["start"] for a, b in spans)


def run(channel: int, brands: list[int], plan: dict, today: str, max_queries: int = MAX_QUERIES) -> dict:
    since = months_ago(today, 24)
    occasions = [o for o in plan.get("occasions") or [] if o.get("occasion") and o.get("phrases")]
    brand_terms = [t for t in plan.get("brand_terms") or [] if str(t).strip()]
    queries, skipped = 0, []
    terms: dict[str, int] = {}
    found: dict[str, dict] = {}
    docs: dict[str, dict] = {}
    cues: dict[str, list] = {}

    def budget() -> bool:
        return queries < max_queries

    brand_docs: list[dict] = []
    if brand_terms and budget():
        brand_docs = search(channel, brand_terms, None, None, terms)
        queries += 1
    for o in occasions:
        if not budget():
            skipped.append(o["occasion"])
            continue
        rows = search(channel, o["phrases"], since, None, terms)
        queries += 1
        found[o["occasion"]] = {"rows": rows, "recent": True}
    with_cues(brand_docs + [r for f in found.values() for r in f["rows"]], cues)
    for d in brand_docs + [r for f in found.values() for r in f["rows"]]:
        docs[ref(d)] = d

    def build(o: dict, rows: list[dict]) -> list[dict]:
        rx = phrase_rx(o["phrases"])
        ws = []
        for d in rows:
            ws += [dict(w, occasion=o["occasion"]) for w in windows_for(d, rx)][:PER_VIDEO]
        return ws

    raw = {o["occasion"]: build(o, found[o["occasion"]]["rows"]) for o in occasions if o["occasion"] in found}
    # older uploads only for an occasion with no recent window
    for o in occasions:
        if o["occasion"] in raw and not raw[o["occasion"]] and budget():
            rows = search(channel, o["phrases"], None, since, terms)
            queries += 1
            with_cues(rows, cues)
            for d in rows:
                docs[ref(d)] = d
            found[o["occasion"]] = {"rows": rows, "recent": False}
            raw[o["occasion"]] = build(o, rows)
    brx = phrase_rx(brand_terms)
    braw = [w for d in brand_docs for w in windows_for(d, brx)[:PER_VIDEO]] if brx else []

    spans, sponsors, unlocated = sponsorship(sorted(docs))
    own = {str(b) for b in brands}
    dropped_sponsor = dropped_brand_upload = trimmed = 0
    out_occ = []
    for o in occasions:
        if o["occasion"] not in raw:
            continue
        keep = []
        for w in raw[o["occasion"]]:
            r = f"{channel}:{w['video_id']}"
            if near_sponsor(w, spans.get(r, [])):
                dropped_sponsor += 1
                continue
            keep.append(dict(w, upload_has_unplaced_read=r in unlocated))
        keep.sort(key=lambda w: (not w["first_person"], -int(w["published"].replace("-", "") or 0)))
        trimmed += max(0, len(keep) - PER_OCCASION)
        out_occ.append({"occasion": o["occasion"], "phrases": o["phrases"],
                        "recent": found[o["occasion"]]["recent"], "uploads": len(found[o["occasion"]]["rows"]),
                        "windows_total": len(keep[:PER_OCCASION]), "uploads_with_windows": by_upload(keep[:PER_OCCASION])})
    bkeep = []
    for w in braw:
        r = f"{channel}:{w['video_id']}"
        if sponsors.get(r, set()) & own:
            dropped_brand_upload += 1
            continue
        if near_sponsor(w, spans.get(r, [])):
            dropped_sponsor += 1
            continue
        bkeep.append(dict(w, upload_has_unplaced_read=r in unlocated))
    return {"channel": channel, "brands": brands, "since": since, "queries": queries,
            "budget_skipped_occasions": skipped, "terms": dict(sorted(terms.items())),
            "occasions": out_occ, "brand_windows_total": len(bkeep), "brand_uploads": by_upload(bkeep),
            "dropped_near_sponsored_read": dropped_sponsor,
            "dropped_brand_sponsored_uploads": dropped_brand_upload, "trimmed": trimmed,
            "notes": "Windows are mechanical: the agent judges whose words they are and which are strongest. "
                     "first_person and code_or_link are hints, not verdicts. A window's link is "
                     "https://www.youtube.com/watch?v=<video_id>&t=<start>s."}


def render_text(out: dict) -> str:
    """The candidates as plain lines the agent reads whole with Read: one line
    per window, grouped under its occasion and upload, every word kept."""
    lines = [f"# {out.get('queries', 0)} searches. Each window line: [video_id start] flags | words. "
             "Pick by video_id and start."]

    def uploads(ups):
        for up in ups or []:
            lines.append(f"## {up.get('published') or ''} {up.get('title') or ''} ({up.get('views') or 0} views)")
            for w in up.get("windows") or []:
                flags = " ".join(k for k in ("first_person", "code_or_link", "upload_has_unplaced_read") if w.get(k))
                lines.append(f"[{up['video_id']} {w['start']}] {flags} | {_norm(w['text'])}")

    for occ in out.get("occasions") or []:
        lines.append("")
        lines.append(f"=== OCCASION: {occ['occasion']} ({occ.get('windows_total', 0)} windows, "
                     f"{'last 24 months' if occ.get('recent') else 'older uploads'})")
        uploads(occ.get("uploads_with_windows"))
    lines.append("")
    lines.append(f"=== BRAND NAMED ({out.get('brand_windows_total', 0)} windows)")
    uploads(out.get("brand_uploads"))
    return "\n".join(lines) + "\n"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _stretch(text: str, first: str | None, last: str | None) -> str | None:
    """One unbroken stretch of the window, cut at exact words; None when the
    words are not in the window (the pick is reported, never guessed)."""
    t = _norm(text)
    low = t.lower()
    a = 0
    if first:
        a = low.find(_norm(first).lower())
        if a < 0:
            return None
    b = len(t)
    if last:
        k = low.find(_norm(last).lower(), a)
        if k < 0:
            return None
        b = k + len(_norm(last))
    return t[a:b]


def pick(candidates: dict, picks: dict) -> tuple[dict, list[str]]:
    """category-probe.json from the agent's picks, with every text copied
    from the candidates file. Returns the file and the picks it could not find."""
    index: dict[tuple[str, int], tuple[dict, dict]] = {}
    for occ in candidates.get("occasions") or []:
        for up in occ.get("uploads_with_windows") or []:
            for w in up.get("windows") or []:
                index.setdefault((str(up["video_id"]), int(w["start"])), (up, w))
    brand_index = {(str(up["video_id"]), int(w["start"])): (up, w)
                   for up in candidates.get("brand_uploads") or [] for w in up.get("windows") or []}
    missing: list[str] = []

    def build(entries, where, brand):
        out = []
        for e in entries or []:
            key = (str(e.get("video_id")), int(e.get("start") or 0))
            found = where.get(key)
            text = _stretch(found[1]["text"], e.get("from"), e.get("to")) if found else None
            if not text:
                missing.append(f"{key[0]}@{key[1]}" + ("" if found else " (no such window)"))
                continue
            up = found[0]
            row = {"video_id": key[0], "start": key[1], "published": up.get("published"),
                   "url": f"https://www.youtube.com/watch?v={key[0]}&t={key[1]}s",
                   "title": up.get("title"), "views": up.get("views"), "text": text}
            if not brand:
                row["occasion"] = e.get("occasion") or ""
            out.append(row)
        return out

    older = [o["occasion"] for o in candidates.get("occasions") or [] if not o.get("recent")]
    facts = (f"{candidates.get('queries', 0)} searches"
             + (f"; older uploads searched for: {', '.join(older)}" if older else "")
             + (f"; not reached within the search budget: {', '.join(candidates['budget_skipped_occasions'])}"
                if candidates.get("budget_skipped_occasions") else "")
             + f"; dropped {candidates.get('dropped_near_sponsored_read', 0)} windows near a sponsored read"
             + f" and {candidates.get('dropped_brand_sponsored_uploads', 0)} brand-sponsored uploads")
    probe = {"terms": candidates.get("terms") or {},
             "windows": build(picks.get("windows"), index, False),
             "brand_windows": build(picks.get("brand_windows"), brand_index, True),
             "coverage": {"note": _norm(f"{picks.get('note') or ''} ({facts})")}}
    return probe, missing


def main() -> int:
    if "--pick" in sys.argv:
        ap = argparse.ArgumentParser(description="copy the agent's picks into category-probe.json")
        ap.add_argument("--pick", required=True)
        ap.add_argument("--candidates", type=pathlib.Path, required=True)
        ap.add_argument("--out", type=pathlib.Path, required=True)
        a = ap.parse_args()
        pp = pathlib.Path(a.pick)
        picks = json.loads(pp.read_text(encoding="utf-8") if pp.exists() else a.pick)
        # a failed search leaves no candidates file: the picks are empty and the note says why
        cands = json.loads(a.candidates.read_text(encoding="utf-8")) if a.candidates.exists() else {}
        probe, missing = pick(cands, picks)
        a.out.write_text(json.dumps(probe, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"file": str(a.out), "windows": len(probe["windows"]),
                          "brand_windows": len(probe["brand_windows"]), "not_found": missing}))
        return 0

    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--channel", type=int, required=True)
    ap.add_argument("--brand", type=int, action="append", default=[])
    ap.add_argument("--plan", required=True, help="plan JSON file, or the JSON itself")
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--today", default=time.strftime("%Y-%m-%d"))
    a = ap.parse_args()
    p = pathlib.Path(a.plan)
    plan = json.loads(p.read_text(encoding="utf-8") if p.exists() else a.plan)
    t0 = time.time()
    out = run(a.channel, a.brand, plan, a.today)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    txt = a.out.with_suffix(".txt")
    body = render_text(out)
    txt.write_text(body, encoding="utf-8")
    summary = {"file": str(a.out), "read_this": str(txt), "lines": len(body.splitlines()), "queries": out["queries"],
               "windows_per_occasion": {o["occasion"]: o["windows_total"] for o in out["occasions"]},
               "older_search_used": [o["occasion"] for o in out["occasions"] if not o["recent"]],
               "brand_windows": out["brand_windows_total"],
               "dropped_near_sponsored_read": out["dropped_near_sponsored_read"],
               "dropped_brand_sponsored_uploads": out["dropped_brand_sponsored_uploads"],
               "budget_skipped_occasions": out["budget_skipped_occasions"],
               "windows_over_cap": out["trimmed"]}
    print(json.dumps(summary, indent=1))
    funnel(stage="moments_search", queries=out["queries"], occasions=len(out["occasions"]),
           windows=sum(o["windows_total"] for o in out["occasions"]), brand_windows=out["brand_windows_total"],
           seconds=round(time.time() - t0, 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
