#!/usr/bin/env python3
"""The bio lane: the creator's own written self-description, as evidence.

Bios go first, transcripts verify them. The channel About text (and, when the
opt-in socials lane is on, the profile bios it read) is the most explicit thing
a creator ever says about themselves, and until now it was context to search
from and never a fact. This lane makes it a first-class *candidate* source —
never a trusted one. Three gates stand between an About box and a brand-facing
page, and nothing here is one of them on its own:

1. ``strip_boilerplate`` — regex, no judgment. YouTube's placeholder copy,
   business-inquiry lines, bare emails/URLs/hashtags/handles and subscribe
   calls never reach a model. A segment with no first-person token is NOT
   dropped (a real bio writes "Doctor. Author. Dad of two."); it is flagged
   ``weak_anchor``, which the rubric already knows how to weigh.
2. the existing ``gem-classifier`` rubric — the surviving segments become ONE
   extra batch in the existing window schema, so "the best gaming channel on
   YouTube" and a link list fail the same first-person-with-a-span test every
   transcript window faces.
3. corroboration — ``terms`` derives 1-3 search terms per bio fact for an
   additive ``fetch_cues.py --round N`` pass over the channel's OWN
   transcripts. Only a transcript fact can lift a bio fact to ``confirmed``
   (``merge_pass.py``); uncorroborated non-sensitive facts render in a
   separate "In their own words (unverified)" block, and uncorroborated
   sensitive ones are dropped entirely.

A bio window is not a transcript window and must never be able to pretend it
is: it carries no video and no timestamp, ``assemble_extracts.py`` refuses it
outright, and its excerpt is cut from the stored bio text by the same
mechanical span cutter transcripts use — a model never authors the words that
render as the creator's own.

Usage:
  bio_lane.py batch --from context-full.json --channel <id> --out <dir>
                    [--socials-bio socials-bio.json] [--seen-date YYYY-MM-DD]
  bio_lane.py facts --batch <bio/batch-000.json> --returns <extract.json>
                    --out bio-facts.json
  bio_lane.py terms --facts bio-facts.json --channel <id> --out <dir>
                    [--round 2]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import assemble_extracts as _ax  # noqa: E402  sibling: the mechanical span cutter
import fetch_cues as _fc  # noqa: E402  sibling: the retrieval pass's own query shapes
import tier_hint  # noqa: E402  sibling: the same keyword tier hint transcripts get

DOMAINS = _ax.DOMAINS
SPEAKERS = _ax.SPEAKERS
WITHHELD = _ax.WITHHELD

# --------------------------------------------------------------------------- #
# the boilerplate filter
# --------------------------------------------------------------------------- #
EMAIL_RX = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")
URL_RX = re.compile(r"(?:https?://|www\.)\S+")
HASHTAG_RX = re.compile(r"^#[\w.]+$")
HANDLE_RX = re.compile(r"^@[\w.]+$")
PHONE_RX = re.compile(r"\+?\d[\d\s().-]{7,}\d")
YT_DEFAULT_RX = re.compile(
    r"^(?:welcome to (?:my|our|the)\b|this is (?:the |my |our )?official\b"
    r"|thanks for (?:watching|stopping by|being here)\b|no description(?: available)?\b"
    r"|check out (?:my|our) (?:videos|channel)\b|(?:my|our) (?:official )?youtube channel\b)",
    re.I)
BUSINESS_RX = re.compile(
    r"\b(?:business|bookings?|inquiries|enquiries|sponsorships?|partnerships?"
    r"|collabs?|collaborations?|press|pr|management|manager|agency|representation)\b"
    r"[^.]{0,40}?(?:@|:|\bcontact\b|\bemail\b|\breach\b|\bplease\b)", re.I)
CONTACT_RX = re.compile(r"\b(?:contact|e-?mail|reach|dm) (?:me|us|my team|our team)\b", re.I)
CTA_RX = re.compile(
    r"\b(?:subscribe|hit the bell|turn on notifications|smash that like|like and subscribe"
    r"|comment below|join (?:my|our) (?:patreon|channel|discord|membership)"
    r"|check out (?:my|our) (?:merch|store|shop)|use code|link (?:in|below)"
    r"|new videos? every|uploads? every)\b", re.I)
FIRST_PERSON_RX = re.compile(
    r"\b(?:i|i'?m|i'?ve|i'?ll|i'?d|me|my|mine|myself|we|we'?re|we'?ve|our|ours|us)\b", re.I)
# Personal identifiers never become search terms: SKILL.md's identity lane
# excludes them, and a corroboration query that searches a creator's email
# address or phone number is a different lane's job and a worse idea.
IDENTIFIER_RX = re.compile(
    rf"{EMAIL_RX.pattern}|{URL_RX.pattern}|{PHONE_RX.pattern}|[@#][\w.]+")

MIN_WORDS = 3
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _residual(text: str) -> str:
    """The text with the machine-readable furniture removed."""
    return IDENTIFIER_RX.sub(" ", text)


def drop_reason(segment: str) -> str | None:
    """Why this segment never reaches a model, or ``None`` to keep it.

    Regex only: every rule here is a shape, not a judgment about whether the
    creator is telling the truth or talking about themselves. That question
    belongs to the extractor rubric, which is why a third-person brag and an
    off-topic claim are KEPT here and rejected there."""
    text = segment.strip()
    if not text:
        return "empty"
    words = text.split()
    if YT_DEFAULT_RX.match(text):
        return "youtube_default"
    if BUSINESS_RX.search(text) or CONTACT_RX.search(text):
        return "business_inquiry"
    if words and all(HASHTAG_RX.match(w) for w in words):
        return "hashtags_only"
    if words and all(HANDLE_RX.match(w) for w in words):
        return "handles_only"
    residual_words = _residual(text).split()
    if EMAIL_RX.search(text) and len(residual_words) < 4:
        return "email"
    if URL_RX.search(text) and len(residual_words) < 4:
        return "url_only"
    if CTA_RX.search(text):
        return "cta"
    if len(words) < MIN_WORDS:
        return "too_short"
    return None


def segments(text: str) -> list[tuple[int, str]]:
    """``(character offset, segment)`` for each atomic piece of a bio.

    Lines first, then sentences, because a bio is written as a list as often
    as it is written as prose — and because the rubric's count contract gives
    one window at most one gem, so "I'm a doctor in London with two kids" must
    arrive as its own window or the second and third facts are lost."""
    out: list[tuple[int, str]] = []
    pos = 0
    for line in (text or "").splitlines(keepends=True):
        base = pos
        pos += len(line)
        stripped = line.strip("\n")
        if not stripped.strip():
            continue
        off = base + (len(stripped) - len(stripped.lstrip()))
        for piece in _SENTENCE_SPLIT.split(stripped.strip()):
            if not piece.strip():
                continue
            at = text.find(piece, off)
            out.append((at if at >= 0 else off, piece.strip()))
            off = (at + len(piece)) if at >= 0 else off
    return out


def strip_boilerplate(text: str) -> tuple[list[tuple[int, str]], list[dict]]:
    """``(kept, dropped)``. ``kept`` is ``(offset, segment)``; every dropped
    segment is reported with its reason, so the run summary can show a creator
    exactly what was thrown away and why."""
    kept: list[tuple[int, str]] = []
    dropped: list[dict] = []
    for off, seg in segments(text):
        why = drop_reason(seg)
        if why:
            dropped.append({"offset": off, "text": seg, "reason": why})
        else:
            kept.append((off, seg))
    return kept, dropped


# --------------------------------------------------------------------------- #
# the bio batch
# --------------------------------------------------------------------------- #
def bio_sources(full: dict, socials_bio: list[dict] | None,
                *, seen_date: str) -> tuple[list[dict], list[dict]]:
    """``(sources, refused)``. The channel About text always; the socials
    lane's profile bios only when that lane confirmed the profile belongs to
    this creator — SKILL.md's identity lane owns that question, and a bio from
    an unmatched profile is another person's self-description.

    The ES ``ai.description`` profile is NEVER a source: it describes the
    recent catalogue, and it is not the creator's words."""
    sources: list[dict] = []
    refused: list[dict] = []
    about = str(full.get("about_text") or "").strip()
    if about:
        sources.append({"kind": "about", "platform": "youtube",
                        "url": str(full.get("url") or "").strip(),
                        "seen_date": seen_date, "text": about})
    for rec in socials_bio or []:
        text = str(rec.get("text") or rec.get("bio") or "").strip()
        url = str(rec.get("url") or rec.get("source_url") or "").strip()
        if not text or not url:
            refused.append({"url": url, "reason": "no bio text or no source url"})
            continue
        if not rec.get("match_confirmed"):
            refused.append({"url": url, "reason": "socials lane did not confirm the profile "
                                                  "belongs to this creator"})
            continue
        sources.append({"kind": "social", "platform": str(rec.get("platform") or "").strip()
                        or "social", "url": url,
                        "seen_date": str(rec.get("seen_date") or seen_date), "text": text})
    return sources, refused


def build_windows(sources: list[dict], *, channel: int | str,
                  language: str | None = None) -> tuple[list[dict], list[dict]]:
    """The bio batch, in the window schema ``extractor_prompt.py`` renders.

    ``video_id`` is None and ``start`` is a CHARACTER offset into the bio, not
    a timestamp: there is no video behind these words and nothing downstream
    may pretend there is. ``assemble_extracts.py`` refuses a window shaped
    like this, so the only way a bio return becomes a fact is
    ``bio_lane.py facts``, which mints identity-lane records."""
    windows: list[dict] = []
    dropped: list[dict] = []
    for si, src in enumerate(sources):
        kept, gone = strip_boilerplate(src["text"])
        for d in gone:
            d["source"] = src["url"] or src["kind"]
            d["kind"] = src["kind"]
        dropped.extend(gone)
        for off, seg in kept:
            windows.append({
                "id": f"bio:{channel}:{src['kind']}:{si}",
                "video_id": None,
                "start": off,
                "title": f"{src['kind']} text ({src['platform']})",
                "published": src["seen_date"],
                "language": language,
                "format_hint": "bio",
                "cues_fired": [],
                "host_anchor": True,
                "second_voice_hint": None,
                "entity_hits": [],
                # no first-person token: kept, flagged, and left to the rubric
                "weak_anchor": not bool(FIRST_PERSON_RX.search(seg)),
                "in_sponsor_read": False,
                "recurrence_videos": 0,
                "stage_direction": False,
                "boilerplate": False,
                "text": seg,
                "retrieval": "bio",
                "bio_source": {"kind": src["kind"], "platform": src["platform"],
                               "url": src["url"], "seen_date": src["seen_date"]},
            })
    return windows, dropped


# The refusal that keeps a bio window out of the transcript ledger lives with
# the assembly it protects, so the two can never drift apart.
is_bio_window = _ax.is_bio_window


def cmd_batch(a: argparse.ArgumentParser) -> int:
    full = json.loads(pathlib.Path(a.from_file).read_text(encoding="utf-8")) if a.from_file else {}
    if a.about_text:
        full = dict(full)
        full["about_text"] = a.about_text
    socials = None
    if a.socials_bio:
        socials = json.loads(pathlib.Path(a.socials_bio).read_text(encoding="utf-8"))
        if isinstance(socials, dict):
            socials = socials.get("profiles") or socials.get("bios") or []
    seen = a.seen_date or _dt.date.today().isoformat()
    channel = a.channel or full.get("channel_id")
    if channel is None:
        print("--channel is required (or a context file carrying channel_id)", file=sys.stderr)
        return 2
    sources, refused = bio_sources(full, socials, seen_date=seen)
    windows, dropped = build_windows(sources, channel=channel, language=full.get("language"))
    out = pathlib.Path(a.out) / str(channel) / "bio"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("batch-*.json"):
        old.unlink()
    batch_path = out / "batch-000.json"
    summary = {
        "channel": channel,
        "seen_date": seen,
        "sources": [{k: v for k, v in s.items() if k != "text"} | {"chars": len(s["text"])}
                    for s in sources],
        "refused_sources": refused,
        "windows": len(windows),
        "dropped": len(dropped),
        "dropped_by_reason": {r: sum(1 for d in dropped if d["reason"] == r)
                              for r in sorted({d["reason"] for d in dropped})},
        "dropped_segments": dropped,
        "batch": str(batch_path) if windows else None,
        "batches": [str(batch_path)] if windows else [],
    }
    if windows:
        batch_path.write_text(json.dumps(windows, ensure_ascii=False), encoding="utf-8")
    summary_path = out / "bio.json"
    summary["summary_file"] = str(summary_path)
    summary_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    print(f"FUNNEL stage=bio_lane channel={channel} sources={len(sources)} "
          f"windows={len(windows)} dropped={len(dropped)}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# the identity-lane records
# --------------------------------------------------------------------------- #
def facts_from_returns(windows: list[dict], returns: dict) -> tuple[list[dict], list[dict]]:
    """``(facts, skipped)``. The classifier's gems become identity-lane records
    the merge pass already knows how to hold — never transcript candidates.

    Two things are deliberately NOT taken from the model: the words and the
    tier. The excerpt is cut from the stored bio by ``extract_span``, the same
    mechanical cutter that makes every transcript quote verbatim by
    construction, so a model can never author text that renders as the
    creator's own; and the sensitivity comes from ``tier_hint.tier_for``, the
    same keyword hint the transcript assembly applies, because the extractor
    does not tier and a bio fact that reached the ledger untiered would default
    to ``none`` and publish a diagnosis."""
    facts: list[dict] = []
    skipped: list[dict] = []
    seen: set[int] = set()
    for v in returns.get("gems") or []:
        i = v.get("i")
        if not isinstance(i, int) or not (0 <= i < len(windows)):
            skipped.append({"i": i, "reason": "index"})
            continue
        if i in seen:
            skipped.append({"i": i, "reason": "duplicate index"})
            continue
        seen.add(i)
        w = windows[i]
        src = w.get("bio_source") or {}
        if v.get("start") != w.get("start"):
            skipped.append({"i": i, "reason": "start does not match the window"})
            continue
        if v.get("speaker_guess") not in SPEAKERS:
            skipped.append({"i": i, "reason": "speaker"})
            continue
        if v.get("speaker_guess") not in ("host", "unclear"):
            # a bio quoting someone else about the creator is not the creator
            skipped.append({"i": i, "reason": f"voice {v.get('speaker_guess')}"})
            continue
        if v.get("life_domain") not in DOMAINS:
            skipped.append({"i": i, "reason": "domain"})
            continue
        claim = str(v.get("claim") or "").strip()
        if not claim:
            skipped.append({"i": i, "reason": "no claim"})
            continue
        excerpt = _ax.extract_span(w.get("text") or "", v.get("quote_span"))
        if excerpt is None:
            skipped.append({"i": i, "reason": "span"})
            continue
        tier = v.get("sensitivity")
        if tier is None:
            tier = tier_hint.tier_for(claim, v.get("notable"), excerpt)
            tier_source = "heuristic"
        elif tier in _ax.SENSITIVITY:
            tier_source = "extractor"
        else:
            # an unresolved tier never publishes: defaulting it to `none` is
            # how a clinical fact reaches a page
            skipped.append({"i": i, "reason": f"sensitivity {tier!r}"})
            continue
        if not str(src.get("url") or "").strip():
            skipped.append({"i": i, "reason": "the window carries no bio source url"})
            continue
        facts.append({
            "ref": f"b{len(facts) + 1}",
            "provenance": "bio",
            "claim": claim,
            "domain": v.get("life_domain"),
            "sensitivity": tier,
            "sensitivity_source": tier_source,
            "source_url": str(src.get("url")).strip(),
            "seen_date": str(src.get("seen_date") or "").strip(),
            "source_excerpt": excerpt,
            "source_kind": src.get("kind"),
            "corroborates": None,
            "window_index": i,
        })
    return facts, skipped


def cmd_facts(a: argparse.Namespace) -> int:
    windows = json.loads(pathlib.Path(a.batch).read_text(encoding="utf-8"))
    returns = json.loads(pathlib.Path(a.returns).read_text(encoding="utf-8"))
    facts, skipped = facts_from_returns(windows, returns)
    out = {"batch": str(a.batch), "returns": str(a.returns),
           "windows": len(windows), "facts": facts, "skipped": skipped,
           "counts": {"facts": len(facts), "skipped": len(skipped),
                      "sensitive": sum(1 for f in facts if f["sensitivity"] in WITHHELD)}}
    if a.out:
        pathlib.Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
        out["facts_file"] = str(a.out)
    print(json.dumps(out, indent=1, ensure_ascii=False))
    print(f"FUNNEL stage=bio_facts windows={len(windows)} facts={len(facts)} "
          f"skipped={len(skipped)}", file=sys.stderr)
    return 0


# --------------------------------------------------------------------------- #
# corroboration: the terms, the probe, and the round that runs them
# --------------------------------------------------------------------------- #
# Words that cannot narrow a search on one channel's own transcripts: pronouns
# (every transcript matches), auxiliaries, and the nouns every creator says.
TERM_STOP = {
    "i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "he", "him", "his",
    "she", "her", "hers", "they", "them", "their", "theirs", "it", "its", "you", "your",
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "do", "does", "did", "will", "would", "can", "could", "should", "may", "might",
    "the", "a", "an", "and", "or", "but", "if", "then", "than", "as", "at", "by",
    "for", "from", "in", "into", "of", "on", "to", "with", "about", "after", "before",
    "since", "during", "while", "when", "where", "who", "that", "this", "these", "those",
    "now", "still", "also", "very", "more", "most", "own", "same", "just", "back",
    "channel", "channels", "video", "videos", "youtube", "content", "subscribers",
    "people", "thing", "things", "time", "times", "year", "years", "day", "days",
    "started", "starting", "started", "make", "makes", "making", "made", "get", "gets",
    "like", "likes", "love", "loves", "really", "always", "never", "every",
}
_WORD_RX = re.compile(r"[A-Za-z][A-Za-z'’-]*")
MAX_TERMS = 3
MIN_TERM_LEN = 4


def corroboration_terms(claim: str, *, limit: int = MAX_TERMS) -> list[str]:
    """1 to ``limit`` search terms for one bio fact, derived from its claim.

    What a corroboration query needs is the specific noun the creator would say
    out loud: the place, the job, the diagnosis, the family word, the
    milestone. Proper nouns first (they are the least ambiguous thing in a
    claim), then adjacent content pairs — "pottery studio" finds the passage
    "pottery" alone would bury — then the remaining content words, longest
    first. Pronouns are excluded by construction: on a single channel's
    transcripts they match everything. Personal identifiers are scrubbed before
    any of this, because a query for a creator's email address is a different
    lane's business and a worse idea.

    A claim that yields nothing is reported, never guessed at: that fact simply
    cannot be corroborated, so it stays unverified or is dropped."""
    text = IDENTIFIER_RX.sub(" ", claim or "")
    tokens = _WORD_RX.findall(text)
    content_ix = [i for i, t in enumerate(tokens)
                  if t.lower() not in TERM_STOP and len(t) >= MIN_TERM_LEN]
    proper = [(0, -len(t), i, t) for i, t in enumerate(tokens)
              if i in set(content_ix) and (t[:1].isupper() or t.isupper())]
    pairs = [(1, -len(f"{tokens[i]} {tokens[i + 1]}"), i, f"{tokens[i]} {tokens[i + 1]}")
             for i in content_ix if (i + 1) in content_ix]
    singles = [(2, -len(tokens[i]), i, tokens[i]) for i in content_ix]
    out: list[str] = []
    for _, _, _, term in sorted(proper + pairs + singles):
        low = term.lower()
        if any(low == o.lower() or low in o.lower() for o in out):
            continue
        # a single word already covered by a chosen pair adds nothing
        out.append(term)
        if len(out) == limit:
            break
    return out


def probe_body(channel: int | str, terms: list[str], *, size: int = 5) -> dict:
    """One narrow ES body for a fact's terms, in the shape the retrieval pass
    uses: the same ``doc_type``/``channel.id``/``exists: transcript`` filter and
    the same apostrophe-variant expansion, so a probe that finds nothing means
    the channel never said it — not that the query was spelled differently.

    No year bucketing: a probe answers "is this anywhere in this channel", and
    the round that follows is what actually fetches windows."""
    should = [{"match_phrase": {"transcript": {"query": v}}}
              for t in terms for v in _fc.phrase_variants(t)]
    return {
        "size": size,
        "_source": ["id", "title", "publication_date"],
        "query": {"bool": {
            "filter": [
                {"term": {"doc_type": "article"}},
                {"term": {"channel.id": int(channel)}},
                {"exists": {"field": "transcript"}},
            ],
            "must": [{"bool": {"should": should, "minimum_should_match": 1}}],
        }},
    }


def cmd_terms(a: argparse.Namespace) -> int:
    data = json.loads(pathlib.Path(a.facts).read_text(encoding="utf-8"))
    records = data.get("facts") if isinstance(data, dict) else data
    out = pathlib.Path(a.out) / str(a.channel) / "bio"
    out.mkdir(parents=True, exist_ok=True)
    per_fact, no_terms, all_terms = [], [], []
    for rec in records or []:
        terms = corroboration_terms(str(rec.get("claim") or ""))
        entry = {"ref": rec.get("ref"), "claim": rec.get("claim"), "terms": terms,
                 "sensitivity": rec.get("sensitivity")}
        if not terms:
            entry["note"] = "no term survives the stoplist: this fact cannot be corroborated"
            no_terms.append(rec.get("ref"))
        else:
            entry["probe"] = probe_body(a.channel, terms)
            all_terms.extend(t for t in terms if t not in all_terms)
        per_fact.append(entry)
    # A generated phrases file, not an edit to the cue list: `fetch_cues.py
    # --phrases` is the existing way terms reach retrieval (`--host-terms` is
    # read off window text and never queried), and references/cue-phrases.txt
    # is a shared, hand-weighted file this lane has no business touching.
    phrases_path = out / f"bio-terms-r{a.round}.txt"
    phrases_path.write_text(
        "# generated by bio_lane.py terms — corroboration round for this channel's\n"
        "# bio facts. Weight 3 = a specific, durable fact about the person.\n"
        + "".join(f"{t} | 3\n" for t in all_terms), encoding="utf-8")
    corpus = f"{a.out}/{a.channel}"
    recipe = [
        f"python3 fetch_cues.py --channel {a.channel} --out {a.out} --round {a.round} "
        f"--phrases {phrases_path} --exclude {corpus}/classified.jsonl --generic-floor 0",
        "# then the usual extractor fan-out over batches-r"
        f"{a.round}/, and:",
        f"python3 assemble_extracts.py --batches {corpus}/batches-r{a.round} "
        f"--returns {corpus}/returns-r{a.round} --out {corpus} --append",
        "# --append is REQUIRED: without it the round replaces classified.jsonl "
        "and round 1's ledger is lost.",
    ]
    summary = {"channel": a.channel, "round": a.round, "facts": len(per_fact),
               "with_terms": len(per_fact) - len(no_terms), "no_terms": no_terms,
               "terms": all_terms, "per_fact": per_fact,
               "phrases_file": str(phrases_path), "recipe": recipe}
    probe_path = out / "bio-probe.json"
    probe_path.write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    summary["probe_file"] = str(probe_path)
    print(json.dumps(summary, indent=1, ensure_ascii=False))
    print(f"FUNNEL stage=bio_terms channel={a.channel} round={a.round} "
          f"facts={len(per_fact)} with_terms={summary['with_terms']} "
          f"terms={len(all_terms)}", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("batch", help="filter the bio and write the one extractor batch")
    b.add_argument("--from", dest="from_file", default=None,
                   help="context-full.json from channel_context.py --channel")
    b.add_argument("--about-text", default=None, help="bio text directly, instead of --from")
    b.add_argument("--socials-bio", default=None,
                   help="JSON list of profile bios from the socials lane; each needs "
                        "match_confirmed, url and text")
    b.add_argument("--channel", default=None)
    b.add_argument("--out", default="tl-creator-profiles/.corpus",
                   help="PARENT directory; the run writes <out>/<channel>/bio/")
    b.add_argument("--seen-date", default=None)

    f = sub.add_parser("facts", help="the classifier's returns as identity-lane records")
    f.add_argument("--batch", required=True, help="the bio batch those returns judged")
    f.add_argument("--returns", required=True, help="batch-000.extract.json from the extractor")
    f.add_argument("--out", default=None, help="write the records here as well as stdout")

    t = sub.add_parser("terms", help="corroboration terms, the probe, and the round recipe")
    t.add_argument("--facts", required=True, help="bio-facts.json from `bio_lane.py facts`")
    t.add_argument("--channel", required=True)
    t.add_argument("--out", default="tl-creator-profiles/.corpus",
                   help="the same PARENT directory the corpus uses")
    t.add_argument("--round", type=int, default=2,
                   help="the additive fetch_cues round this feeds; never 1, which "
                        "would clear the existing corpus")

    a = ap.parse_args(argv)
    if a.cmd == "batch":
        return cmd_batch(a)
    if a.cmd == "facts":
        return cmd_facts(a)
    if a.cmd == "terms":
        if a.round < 2:
            print("--round must be 2 or higher: round 1 clears the corpus this lane "
                  "is trying to deepen", file=sys.stderr)
            return 2
        return cmd_terms(a)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
