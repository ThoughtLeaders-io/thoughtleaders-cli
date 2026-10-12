#!/usr/bin/env python3
"""Check every moment a connection map may use, before the map is written.

The map is right the first time when it is written only from moments that
already passed every check. This script reads the candidates (the ledger's
facts and the brand-moments lane's windows), reads each one's upload (its
captions, description, title, date and views) and writes ``moments.json``:
the moments the map may use, and every one it may not, with the reason.

A moment is usable when:

* **its words are in the captions**: a ledger quote matches its upload word
  for word within 20 seconds of its timestamp;
* **it is recent enough to lead**: ``recent`` is true when the upload was
  published within ``RECENT_MONTHS`` of today (by the upload's own date,
  never a later keyword match); older moments are usable only as dated
  backstory and the map says so;
* **nothing near it undercuts the brand**: no rival brand named, and no
  awkward act (stealing, faking a coupon, charging a room), within
  ``SURROUND_SECONDS`` either side of the linked second;
* **its upload is not a rival's**: no description sponsor line, partner tag
  or hashtag names one of the brand's rivals;
* **a plan is still a plan**: a ledger fact superseded by a newer one, or
  ended, never leads a concept; a "will" claim last said more than
  ``PLAN_MONTHS`` ago with no later mention is stale; a recent one is
  usable only with the label ``said <Month YYYY>, not yet confirmed``.

Usable moments also carry what the writer must say about them instead of
guessing: ``premise`` (the venue or partner was in on it: the description
thanks a venue, carries a partner link or says "for entertainment
purposes"), ``staged`` (the title marks a prank, stunt or challenge),
``videos`` (how many uploads say a pattern claim: "every" and "always" are
written only with that count), ``title``, ``published`` and ``views``.

Usage:
    moment_check.py --facts <profiles>/<id>-facts.jsonl \\
        --corpus <corpus> --brand <brand_id> [--today YYYY-MM-DD]

Reads ``<corpus>/category-probe.json`` (the lane's ``windows`` and
``brand_windows``), ``<corpus>/brand-tl.json`` (``rivals``) and
``<corpus>/brand-site.json`` (``competitors``) when present;
writes ``<corpus>/moments-<brand_id>.json``. A query failure raises: a page
must never be built on moments that were not checked.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from datetime import date

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data  # noqa: E402
import fetch_cues  # noqa: E402  sibling: one home for transcript and description fetches
from store_io import read_ledger  # noqa: E402
from verify_quotes import locate  # noqa: E402
from channel_context import TITLE_HINTS  # noqa: E402
from build_html import angle_ineligible_reason  # noqa: E402  one home for what a page may use

RECENT_MONTHS = 24
PLAN_MONTHS = 12
SURROUND_SECONDS = 120
QUOTE_SLACK_SECONDS = 20
META_CHUNK = 50

# Acts a brand should never find a minute away from its pitch.
RISKY = re.compile(r"\b(steal(?:ing)?|stole|stolen|shoplift\w*|fake (?:coupon|id|badge|ticket)s?|"
                   r"room number|without paying|charg\w+ (?:it )?to (?:their|his|her|a) room|"
                   r"trespass\w*)\b", re.I)
# A description line that says the venue or a partner was in on it.
PREMISE = re.compile(r"(letting us film|for letting us|for having us|for hosting us|"
                     r"utm_medium=partnership|in partnership with|for entertainment purposes)", re.I)
# A description line that says who paid for the video.
SPONSOR_LINE = re.compile(r"(sponsor|partner|thank(?:s| you) (?:to )?\S+ for|#\w*(?:partner|ad)\b)", re.I)
# a plan in the creator's own voice: "I will", "we're going to", "I'm not
# stopping until"; never the name Will
FUTURE = re.compile(r"\b(?:(?:i|we|i'm|im|we're|i 39 m|we 39 re)\s+(?:will|'ll|am going to|are going to|"
                    r"going to|gonna|plan(?:ning)? to)|i'll|i 39 ll|we'll|not stopping until|"
                    r"next (?:video|year|month))\b", re.I)
PATTERN = re.compile(r"\b(every|always|each time|whenever|weekly|daily|never miss)\b", re.I)
FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'd|i'll|my|me|we|our|us|mine)\b", re.I)
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]


def months_between(a: str, b: str) -> int:
    """Whole months from date ``a`` to date ``b`` (YYYY-MM-DD)."""
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (yb - ya) * 12 + (mb - ma)


def month_label(d: str) -> str:
    return f"{MONTHS[int(d[5:7]) - 1]} {d[:4]}" if d and len(d) >= 7 else ""


def rival_pattern(rivals: list[str], brand_names: list[str]) -> re.Pattern | None:
    """One pattern for the rival names, spaces optional so a one-word hashtag
    (#celsiusbrandpartner) matches too. The brand's own names never count."""
    own = {b.lower() for b in brand_names if b}
    names = sorted({r.strip() for r in rivals if r and r.strip() and r.strip().lower() not in own},
                   key=len, reverse=True)
    if not names:
        return None
    alts = [r"\s*".join(re.escape(part) for part in n.split()) for n in names]
    return re.compile(r"(?<![a-z])(" + "|".join(alts) + r")", re.I)


def upload_meta(refs: list[str]) -> dict[str, dict]:
    """Title, publish date and views per ``<channel>:<video>`` ref."""
    out: dict[str, dict] = {}
    for i in range(0, len(refs), META_CHUNK):
        rows = tl_data.db_es({"size": META_CHUNK, "query": {"ids": {"values": refs[i:i + META_CHUNK]}},
                              "_source": ["id", "title", "publication_date", "views"]})
        for r in rows:
            out[str(r.get("id"))] = {"title": str(r.get("title") or ""),
                                     "published": str(r.get("publication_date") or "")[:10],
                                     "views": r.get("views")}
    return out


def surroundings(cues: list, start: float, seconds: int = SURROUND_SECONDS) -> str:
    return " ".join(str(t) for s, t in cues if start - seconds <= float(s) <= start + seconds)


def sponsor_rival(summary: str, rx: re.Pattern | None) -> str | None:
    """The rival a description's sponsor line or partner tag names, if any."""
    if not rx:
        return None
    for line in (summary or "").splitlines():
        if SPONSOR_LINE.search(line) or "#" in line:
            m = rx.search(line)
            if m:
                return m.group(0)
    return None


def premise_line(summary: str) -> str | None:
    for line in (summary or "").splitlines():
        if PREMISE.search(line):
            return line.strip()[:160]
    return None


def candidates(facts: list[dict], probe: dict) -> list[dict]:
    """Ledger facts with a quote and a timestamp, and the lane's windows."""
    out: list[dict] = []
    for f in facts:
        vid = str(f.get("video") or "")
        if str(f.get("provenance") or "transcript") != "transcript" or ":" not in vid:
            continue
        out.append({"kind": "fact", "fact": f, "fact_id": f.get("fact_id"), "ref": vid,
                    "video_id": vid.split(":", 1)[1], "start": f.get("start"),
                    "quote": f.get("quote"), "claim": f.get("claim"),
                    "confidence": f.get("confidence"), "staged_only": bool(f.get("staged_only")),
                    "superseded_by": f.get("superseded_by"), "ended": bool(f.get("ended")),
                    "sensitivity": f.get("sensitivity"), "last_seen": f.get("last_seen"),
                    "probe": f.get("probe") or {}, "members": f.get("members") or []})
    for kind in ("windows", "brand_windows"):
        for w in probe.get(kind) or []:
            vid = str(w.get("video_id") or "")
            if not vid:
                continue
            out.append({"kind": kind[:-1], "ref": vid if ":" in vid else f"{probe.get('channel_id', '')}:{vid}",
                        "video_id": vid.split(":", 1)[-1], "start": w.get("start"),
                        "quote": w.get("text"), "term": w.get("term")})
    return out


def judge(c: dict, cues: list, summary: str, meta: dict, rx: re.Pattern | None,
          today: str, index: dict[str, dict] | None = None) -> dict:
    """One candidate's checks: ``usable`` and the reasons it is not."""
    reasons: list[str] = []
    start = float(c.get("start") or 0)
    published = meta.get("published") or ""
    title = meta.get("title") or ""
    rec = {k: c.get(k) for k in ("kind", "fact_id", "video_id", "quote", "claim", "term") if c.get(k) is not None}
    rec.update({"start": int(start), "url": f"https://www.youtube.com/watch?v={c['video_id']}&t={int(start)}s",
                "published": published, "title": title, "views": meta.get("views")})
    rec["recent"] = bool(published) and months_between(published, today) < RECENT_MONTHS

    if c["kind"] == "fact":
        why = angle_ineligible_reason(c["fact"], index)
        if why:
            reasons.append(why)
        hit = locate(cues, str(c.get("quote") or ""), start) if cues else {"match": "none"}
        if hit.get("match") != "exact" or abs(float(hit.get("start", -999)) - start) > QUOTE_SLACK_SECONDS:
            reasons.append("quote not word for word in the captions at its timestamp")
        text = f"{c.get('claim') or ''} {c.get('quote') or ''}"
        tense = "future" if FUTURE.search(text) else "pattern" if PATTERN.search(text) else "past or ongoing"
        rec["tense"] = tense
        if c.get("superseded_by"):
            reasons.append(f"changed: superseded by {c['superseded_by']}")
        if c.get("ended"):
            reasons.append("ended")
        last = str(c.get("last_seen") or published or "")[:10]
        if tense == "future" and not c.get("superseded_by"):
            if last and months_between(last, today) >= PLAN_MONTHS:
                reasons.append(f"stale plan: last said {month_label(last)}, no later mention")
            else:
                rec["label"] = f"said {month_label(last)}, not yet confirmed"
        if tense == "pattern":
            p = c.get("probe") or {}
            own = {str(m.get("video_id") if isinstance(m, dict) else str(m).split(":")[0])
                   for m in c.get("members") or []} or {c["video_id"]}
            rec["videos"] = max(int(p.get("recurring_videos") or 0), len(own))
    else:
        if not FIRST_PERSON.search(str(c.get("quote") or "")):
            reasons.append("not in the creator's own words (no first-person word)")

    near = surroundings(cues, start)
    if rx:
        m = rx.search(near)
        if m:
            reasons.append(f"rival named within {SURROUND_SECONDS} s: {m.group(0)!r}")
    m = RISKY.search(near)
    if m:
        reasons.append(f"awkward act within {SURROUND_SECONDS} s: {m.group(0)!r}")
    rival = sponsor_rival(summary, rx)
    if rival:
        reasons.append(f"upload sponsored by a rival: {rival}")
        rec["rival_sponsored"] = True
    pl = premise_line(summary)
    if pl:
        rec["premise"] = pl
    rec["staged"] = bool(TITLE_HINTS["staged"].search(title))
    rec["usable"] = not reasons
    if reasons:
        rec["reasons"] = reasons
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--facts", required=True, type=pathlib.Path)
    ap.add_argument("--corpus", required=True, type=pathlib.Path)
    ap.add_argument("--brand", required=True)
    ap.add_argument("--today", default=date.today().isoformat())
    a = ap.parse_args()

    _meta, facts = read_ledger(a.facts)
    probe = {}
    pf = a.corpus / "category-probe.json"
    if pf.exists():
        probe = json.loads(pf.read_text(encoding="utf-8"))
    channel = str((_meta or {}).get("channel_id") or "")
    probe.setdefault("channel_id", channel)
    tl = {}
    tf = a.corpus / "brand-tl.json"
    if tf.exists():
        tl = json.loads(tf.read_text(encoding="utf-8"))
    brand = tl.get("brand") or {}
    site = {}
    sf = a.corpus / "brand-site.json"
    if sf.exists():
        site = json.loads(sf.read_text(encoding="utf-8"))
    rival_names = [str(r.get("name") if isinstance(r, dict) else r)
                   for r in [*(tl.get("rivals") or []), *(site.get("competitors") or [])]]
    rx = rival_pattern(rival_names, [str(brand.get("name") or ""),
                                     *[str(x) for x in brand.get("aliases") or []]])

    index = {str(f.get("fact_id")): f for f in facts}
    cands = candidates(facts, probe)
    refs = sorted({c["ref"] for c in cands})
    cues = fetch_cues.fetch_transcripts(refs) if refs else {}
    summaries = fetch_cues.fetch_summaries(refs) if refs else {}
    metas = upload_meta(refs) if refs else {}
    usable, rejected, rival_videos = [], [], set()
    for c in cands:
        rec = judge(c, cues.get(c["ref"]) or [], summaries.get(c["ref"], ""),
                    metas.get(c["ref"], {}), rx, a.today, index)
        (usable if rec["usable"] else rejected).append(rec)
        if rec.get("rival_sponsored"):
            rival_videos.add(rec["video_id"])
    out = {"brand_id": a.brand, "today": a.today, "recent_months": RECENT_MONTHS,
           "usable": usable, "rejected": rejected, "rival_videos": sorted(rival_videos)}
    path = a.corpus / f"moments-{a.brand}.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"usable": len(usable), "rejected": len(rejected),
                      "rival_videos": len(rival_videos), "file": str(path)}))


if __name__ == "__main__":
    main()
