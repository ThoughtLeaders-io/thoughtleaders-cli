#!/usr/bin/env python3
"""Channel identity plus the context brief: format MEASURED from transcripts.

Two jobs, one script:

* **Identity inputs** — the channel row, its About text, and the platform's
  generated profile (``ai.description``), which is usually the better identity
  source because raw About fields are often subscribe-boilerplate. These seed
  the identity & socials lane and the host-terms for the scan.
* **Context stats** — once the corpus is local (``--corpus``), format is
  measured from the transcripts themselves, not guessed from titles:
  first-person window density, interview markers, question density, and
  per-title second-voice hints. Deterministic numbers only; the label
  (solo / interview / multi-host / faceless-scripted) is called by a model
  read of a small sample WITH this evidence, per references/transcript-mining.md.

Nothing here is a gate. Near-zero first-person density flags "likely faceless"
early so model tokens are spent accordingly — but nothing exits early, and a
faceless channel with one personal Q&A upload still gets scanned.

Usage:
    channel_context.py --channel <id>
    channel_context.py --channel <id> \\
        --corpus tl-creator-profiles/.corpus/<id>/corpus.jsonl.gz \\
        [--per-video-out <dir>/per-video.jsonl] > <dir>/context-full.json
    channel_context.py --from <dir>/context-full.json \\
        --format-label solo --format-evidence "fp density 41/1k words" \\
        [--host-names "Ali,Abdaal"] [--known-facts "ex-doctor;lives in London"] \\
        --write-context <dir>/context.json
    channel_context.py --set-socials <dir>/context-full.json \\
        --social-read "https://instagram.com/x" \\
        --social-unread "https://tiktok.com/@x,https://x.com/x"

The third form is the step between the stats and the extractor prompts: the
model reads ``context-full.json``, calls the format label from it, and hands
the label back here, which writes the compact ``context.json`` every
``extractor_prompt.py`` render takes (``channel_name``, ``host_names``,
``known_facts``, ``format_label``, ``format_evidence``). No network: it reads
the full context from the file, so nothing is typed by hand and every run
writes the same shape.

Output (stdout): one JSON object.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data
from store_io import open_corpus  # sibling module

FIRST_PERSON = re.compile(r"\b(i|i'm|i've|i'd|i'll|my|me|myself)\b", re.I)

INTERVIEW = re.compile(
    r"\b(my guest|our guest|today'?s guest|welcome (back )?to the (show|"
    r"podcast)|please welcome|thanks for (coming on|joining|having me)|"
    r"joining me today|great to have you|tell (us|me) about yourself)\b", re.I)

# The ONE home for title -> format hints. `fetch_cues.format_hint` reads
# this dict too, so a title that counts as a collab here is the same title
# whose windows carry `format_hint` into the extractor and the merge pass.
# "with <Name>" counts only when what follows is shaped like a person: an
# @handle, a CamelCase handle (PythonGB, JaidenAnimations), a name list
# ("Jaiden, AntiDarkHeart and Alice", "Pedguin and PythonGB"), "The <Group>"
# ("The Developers", "The Yogscast") or a possessive title ("Terraria's
# Creator"). That branch is case-sensitive on purpose: "with this mod",
# "With These Mods", "with Calamity's latest update", "with DEATH mode" are
# things, not voices, and the rest of the pattern stays case-insensitive.
#
# `staged` is the third hint and comes LAST so a "reaction" or collab title
# keeps its second-voice hint. It marks a video whose premise is a set-up:
# pranks, challenges, 24-hour stunts, fake or pretend scenarios, dating shows,
# skits. One voice still holds the transcript, so attribution is unchanged;
# what changes is that a relationship, marriage, move or job stated inside
# the premise may be the bit, not the person. Alexa Rivera (2026-09-09): 37
# PRANK, 21 CHALLENGE and 20 "24 HOURS" titles among 355 windowed videos, and
# a "my husband" line from a fake-honeymoon video reached the page as fact.
# The hint never drops a window: the extractor reports the claim with the
# hint in its evidence, `merge_pass.py prepare` has `authenticate.py` look
# for the same claim in non-staged uploads, and the merge shard decides with
# that evidence in front of it.
TITLE_HINTS = {
    "reaction": re.compile(
        r"(\breact(s|ing|ion|ions)?\b|\breact to\b|\bwatching\b|\bresponds? to\b|"
        r"\bfirst time (watching|hearing|playing|seeing)\b)", re.I),
    "interview_or_collab": re.compile(
        r"(?i:\binterview(s|ed|ing)?\b|\bpodcast\b|\bcollab(s|oration)?\b|\bguests?\b|"
        r"\bq&a with\b|\bsits down with\b|\bin conversation with\b|"
        r"\bft\.?\s|\bfeat\.?\s|\bfeaturing\b|\bw/\s?\w|\bwith @\w|\bvs\.?\s)"
        r"|\b[Ww]ith (?:[A-Z][a-z]+[A-Z]\w*|[A-Z]\w+(?:,| and | & )|The [A-Z]\w+"
        r"|[A-Z]\w+['’]s [A-Z]\w+)"),
    "staged": re.compile(
        r"(\bpranks?\b|\bpranked\b|\bpranking\b|\bchallenges?\b|\b24 hours?\b|"
        r"\b\d+ hours? (in|at|inside|overnight)\b|\bovernight\b|\bfake\b|"
        r"\bpretend(s|ed|ing)?\b|\bsocial experiment\b|\bdating show\b|"
        r"\blast to (leave|stop|fall)\b|\bskit\b|\brole ?play\b|"
        r"\b(married|adopted|dated|was a \w+) for (a|24) (day|week|hours?)\b|"
        r"\bfor 24 hours\b|\bfor a (day|week)\b|\bsurprising my\b|"
        # life-event titles are the classic stunt premise on prank channels
        # ("CAN'T BELIEVE THIS HAPPENED ON OUR HONEYMOON!!" was a bit); a
        # genuine one is probed and confirmed by its recurrence, never dropped
        r"\bhoneymoon\b|\bgot married\b|\bwedding\b|\bbroke up\b|\bpregnant\b|"
        r"\bmoving (away|out)\b|\bquitting\b|\bwe eloped\b|\bnew boyfriend\b|"
        r"\bnew girlfriend\b)", re.I),
}
# The old name, kept so a script written against it keeps importing.
TITLE_SECOND_VOICE = TITLE_HINTS


def channel_row(channel_id: int) -> dict:
    rows = tl_data.db_pg(
        "SELECT id, channel_name, url, external_channel_id, subscribers, "
        "total_views, num_uploads, country, language, last_published, social_links "
        f"FROM thoughtleaders_channel WHERE id = {channel_id}"
    )
    if not rows:
        sys.exit(f"no channel record for id {channel_id}")
    return rows[0]


def channel_doc(channel_id: int) -> dict:
    # Channel documents are duplicated in the index; collapse on id or every
    # copy comes back.
    rows = tl_data.db_es({
        "size": 1,
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "channel"}},
            {"term": {"id": channel_id}},
        ]}},
        "_source": ["name", "description", "ai.description",
                    "ai.topic_descriptions", "social_links"],
        "collapse": {"field": "id"},
    })
    return rows[0] if rows else {}


def _bare(link: str) -> str:
    """``https://www.instagram.com/airrack/`` -> ``instagram.com/airrack``, the
    form the index keeps, so the two sources dedupe against each other."""
    link = re.sub(r"^https?://", "", str(link or "").strip(), flags=re.I)
    link = re.sub(r"^www\.", "", link, flags=re.I)
    return link.rstrip("/").lower()


def websites_and_socials(pg_links, es_links) -> tuple[list[dict], list[str]]:
    """The creator's own websites and their platform links, from both stores.

    Postgres ``social_links`` is a dict: platform keys (``instagram``,
    ``tiktok`` …) and an ``_other`` dict of the LABELLED links the creator put
    in their channel header (``"Get In Touch": "https://pauljlipsky.com"``,
    ``"Turn Anything Into Pizza": "https://pizzafy.com/"``). Those labelled
    links are the creator's websites, and they are where the identity lane
    starts: the site says who the person is and links the socials worth
    reading. ``_emails`` is dropped here; a contact address is not a fact
    about the person. The index's ``social_links`` is a flat list, kept and
    unioned with the platform links so nothing linked is silently missing.
    YouTube links are not websites; ``second_channel_candidates`` owns them.

    Both stores come back empty on plenty of channels (Alexa Rivera, 2026-09-10:
    ``{}`` in Postgres and ``[]`` in the index), so an empty result is a real
    answer and the identity lane is told to expect it: it then has the channel
    name, the About text and the AI profile to work from, and nothing else.
    """
    websites: list[dict] = []
    socials: list[str] = [str(x) for x in (es_links or []) if x]
    seen = {_bare(x) for x in socials}
    if isinstance(pg_links, dict):
        for label, link in (pg_links.get("_other") or {}).items():
            if not link or YT_LINK.search(str(link)) or "youtu.be/" in str(link):
                continue
            websites.append({"label": str(label).strip(), "url": str(link).strip()})
        for key, link in pg_links.items():
            if key.startswith("_") or not isinstance(link, str) or not link:
                continue
            if _bare(link) not in seen:
                socials.append(link.strip())
                seen.add(_bare(link))
    return websites, socials


def _nested(doc: dict, path: str):
    """Read ``ai.description`` whether the CLI flattened the key or nested it."""
    if path in doc:
        return doc[path]
    cur = doc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


SECOND_CHANNEL_PHRASE = re.compile(
    r"(second channel|other channel|vlog channel|clips channel|gaming "
    r"channel|podcast channel|main channel)", re.I)
# Channel URL forms only: a youtu.be shortlink identifies a VIDEO, so it
# must never be surfaced as a second-channel candidate.
YT_LINK = re.compile(
    r"youtube\.com/(?:@[\w.-]+|channel/UC[\w-]+|c/[\w.-]+|user/[\w.-]+)",
    re.I)


def second_channel_candidates(row: dict, doc: dict) -> list[dict]:
    """Other YouTube channels this creator points at — often the gem mine.

    A big channel's smaller vlog/second channel is frequently where the
    personal material lives. Candidates come from the channel's own pointers:
    YouTube links among its social links, and YouTube links or "my second
    channel" phrasing in the About text. Detection only — resolving a
    candidate to a TL channel id (`tl channels find`) and deciding to scan it
    belongs to the identity & socials lane.
    """
    # Compare exact channel identities, never substrings: the second channel
    # is routinely a derivative handle (@foo -> @fooVlogs), so a substring
    # test against the main URL would reject exactly the channels we want.
    def _identity(link: str) -> str:
        s = link.lower().rstrip("/")
        for marker in ("/channel/", "/@", "/c/", "/user/"):
            if marker in s:
                return s.split(marker, 1)[1].split("/")[0].split("?")[0]
        if "youtu.be/" in s:
            return s.split("youtu.be/", 1)[1].split("/")[0].split("?")[0]
        return s

    own = {str(row.get("external_channel_id") or "").lower()} | {
        _identity(str(u)) for u in (row.get("url"),) if u
    }
    own.discard("")
    seen: set[str] = set()
    out: list[dict] = []

    def add(link: str, source: str) -> None:
        key = _identity(link)
        if not key or key in seen or key in own:
            return
        seen.add(key)
        out.append({"link": link, "source": source})

    for link in doc.get("social_links") or []:
        if isinstance(link, str) and YT_LINK.search(link):
            add(link, "social_links")
    about = doc.get("description") or ""
    for m in YT_LINK.finditer(about):
        add(m.group(0), "about_text")
    phrases = sorted({m.group(0).lower()
                      for m in SECOND_CHANNEL_PHRASE.finditer(about)})
    if phrases and not out:
        # The About text names another channel without linking it: still a
        # lead, handed to the lane as a phrase to chase, never dropped.
        out.append({"link": None, "source": "about_text_phrase",
                    "phrases": phrases})
    return out


# The creator's OTHER names, harvested from their own cue passages. A channel
# titled "Alexa Rivera" is searched for as "Alexa Rivera", and the audience,
# the press and her own Instagram all call her Lexi: the identity lane cannot
# find a profile under a name nobody uses. These are SEARCH TERMS, never facts;
# a name reaches the ledger only as a transcript fact with its own quote.
#
# Alexa Rivera (2026-09-10) is the case this exists for. Both link stores were
# empty, so the lane had the channel name and the AI profile, searched "Alexa
# Rivera", drowned in a same-named creator, and rejected the right person. The
# nickname was in the corpus the run had already fetched, in seven videos:
# "my nicknames ... Lexi ... my real name's Alexa", and a garbled reading of
# her handle, "Brooke Lexie Rivera Brooke is my username" (the real handle is
# @lexibrookerivera).
NAME_CUE = re.compile(
    r"\b(?:my (?:real |full |middle |first )?names?'?s?"
    r"|call me"
    r"|my nick ?names?"
    r"|user ?name|handle"
    r"|my (?:instagram|insta|tiktok|twitter|snapchat|snap|socials?)"
    r"|follow me|tag me|dm me)\b", re.I)
# A name said outright carries further than one that merely sits near a cue.
NAME_EXPLICIT = re.compile(
    r"\b(?:my (?:real |full |middle |first )?names?'?s?(?: is)?|call me)\s+"
    r"([A-Za-z]{2,20})", re.I)
# Function words and channel-intro filler that sit beside every naming cue.
NAME_STOP = frozenset("""
about actually add after all also and another any are around away back because been
before being best better big but call called came can cause come comes coming could
day did didn does doing don down each even ever every everyone first for from get gets
getting girl give goes going gonna good got great guys had half has have her here hey
him his how i've if insta instagram into it's its just keep kind know last let life
like likes little look looking lot love make me mean media might mine more most much
my myself name names never new next nick nickname nicknames not now off oh okay one
only other our out over own people please post posted posting pretty put really right
said same say says see she should show social socials some something started stories
story such super sure take tell than that thats the their them then there these they
thing things think this those three through time today too two use user username very
want was watch way welcome well were what when where which while who whole why will
with would yeah year years yes yet you your yours youtube channel video videos
followers follow tag
""".split())


def name_candidates(corpus_path: pathlib.Path, channel_name: str | None,
                    span: int = 80, cap: int = 8) -> list[dict]:
    """Other names for the creator, ranked, from their own cue passages.

    Each row carries `channel_name_variant`: true when the token is a short
    relative of the channel name (``Alexa`` -> ``Lexi``, ``Patterrz`` -> ``pat``,
    and the ASR spellings of both), which is the signal that it is the creator
    rather than a guest introducing themselves in a challenge video. A name
    that is neither a variant nor said across four or more uploads is dropped,
    because "my name is Sienna" is usually not the host.
    """
    ch_tokens = [t.lower() for t in re.findall(r"[A-Za-z]{3,}", channel_name or "")]

    def variant(tok: str) -> bool:
        for ct in ch_tokens:
            if tok == ct:
                return True
            # a nickname is a SHORT relative of the name, so a longer word that
            # merely contains three of its letters ("Rivera" -> "arrived") is not
            if len(tok) > len(ct):
                continue
            if any(tok[i:i + 3] in ct for i in range(len(tok) - 2)):
                return True
        return False

    videos: dict[str, set[str]] = {}
    cue_example: dict[str, str] = {}
    explicit: set[str] = set()
    with open_corpus(corpus_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            v = json.loads(line)
            vid = str(v.get("id") or "")
            cues = v.get("cues") or []
            if not cues:
                continue
            text = re.sub(r"\s+", " ", " ".join(c[1] for c in cues))
            for m in NAME_EXPLICIT.finditer(text):
                tok = m.group(1).lower()
                if tok not in NAME_STOP and len(tok) >= 3:
                    explicit.add(tok)
            for m in NAME_CUE.finditer(text):
                lo, hi = max(0, m.start() - span), min(len(text), m.end() + span)
                window = text[lo:hi]
                for tok in re.findall(r"\b[A-Za-z]{3,20}\b", window):
                    tok = tok.lower()
                    if tok in NAME_STOP:
                        continue
                    videos.setdefault(tok, set()).add(vid)
                    cue_example.setdefault(tok, window[:140])

    rows = []
    for tok, seen in videos.items():
        var, exp = variant(tok), tok in explicit
        # a variant still has to recur or be stated outright, or common words
        # sitting inside the surname ("Rivera" -> "drive") ride in
        if not ((var and (exp or len(seen) >= 2)) or (exp and len(seen) >= 4)):
            continue
        rows.append({"name": tok, "videos": len(seen),
                     "channel_name_variant": var, "said_outright": exp,
                     "cue": cue_example[tok]})
    rows.sort(key=lambda r: (not (r["said_outright"] and r["channel_name_variant"]),
                             not r["channel_name_variant"],
                             -r["videos"], r["name"]))
    return rows[:cap]


def corpus_stats(corpus_path: pathlib.Path) -> dict:
    per_video = []
    with open_corpus(corpus_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            v = json.loads(line)
            cues = v.get("cues") or []
            if not cues:
                continue
            text = " ".join(c[1] for c in cues)
            words = max(len(text.split()), 1)
            lang = str(v.get("transcript_language") or "").lower()
            per_video.append({
                "id": str(v.get("id")),
                "title": v.get("title"),
                "language": lang or None,
                "fp_per_1k_words": round(
                    1000 * len(FIRST_PERSON.findall(text)) / words, 1),
                "interview_markers": len(INTERVIEW.findall(text)),
                "questions_per_1k_words": round(
                    1000 * text.count("?") / words, 1),
                "title_hint": next(
                    (fmt for fmt, rx in TITLE_HINTS.items()
                     if v.get("title") and rx.search(v["title"])), None),
            })
    if not per_video:
        return {"videos_measured": 0}
    # The first-person stats are English regex counts; on other languages
    # (pro-drop Spanish, subject-omitting Japanese) they measure nothing, so
    # they are computed over English-language videos only — and a channel
    # with no English videos gets null, never "likely faceless".
    en_videos = [v for v in per_video
                 if not v["language"] or v["language"].startswith("en")]
    langs: dict[str, int] = {}
    for v in per_video:
        key = v["language"] or "unknown"
        langs[key] = langs.get(key, 0) + 1
    fp = [v["fp_per_1k_words"] for v in en_videos]
    if not fp:
        return {
            "videos_measured": len(per_video),
            "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
            "fp_per_1k_words_median": None,
            "fp_per_1k_words_p10": None,
            "likely_faceless": None,
            "language_note": ("no English-language videos: first-person "
                              "density is not meaningful here — format and "
                              "faceless calls belong to the model read of a "
                              "sample, with no lexical prior"),
            "videos_with_interview_markers": sum(
                1 for v in per_video if v["interview_markers"] >= 2),
            "questions_per_1k_words_median": round(statistics.median(
                v["questions_per_1k_words"] for v in per_video), 1),
            "title_hints": {
                fmt: sum(1 for v in per_video if v["title_hint"] == fmt)
                for fmt in TITLE_HINTS
            },
            "staged_share": round(
                sum(1 for v in per_video if v["title_hint"] == "staged")
                / len(per_video), 2),
            "per_video": per_video,
        }
    return {
        "videos_measured": len(per_video),
        "languages": dict(sorted(langs.items(), key=lambda kv: -kv[1])),
        "fp_videos_measured": len(en_videos),
        "fp_per_1k_words_median": round(statistics.median(fp), 1),
        "fp_per_1k_words_p10": round(sorted(fp)[len(fp) // 10], 1),
        "videos_with_interview_markers": sum(
            1 for v in per_video if v["interview_markers"] >= 2),
        "questions_per_1k_words_median": round(statistics.median(
            v["questions_per_1k_words"] for v in per_video), 1),
        "title_hints": {
            fmt: sum(1 for v in per_video if v["title_hint"] == fmt)
            for fmt in TITLE_HINTS
        },
        # share of measured videos whose title reads as a staged premise; the
        # format call names it ("solo, 22% staged premises") so the merge
        # shard knows how much of the channel is a set-up
        "staged_share": round(
            sum(1 for v in per_video if v["title_hint"] == "staged")
            / len(per_video), 2),
        "likely_faceless": statistics.median(fp) < 2.0,
        "per_video": per_video,
    }


FORMAT_LABELS = ("solo", "interview", "multi_host", "faceless_scripted")


def funnel(**fields) -> None:
    """One machine-parseable stage line for debugging (stderr)."""
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def funnel_fields(out: dict, elapsed: float) -> dict:
    """The stage line for a ``--channel`` run, as an ordered field dict.

    Two shapes, because this script runs at two points in the pipeline and one
    stage name for both would put two different lines under one label:
    ``stage=identity`` before the fetch (the links the identity lane starts
    from), ``stage=context`` after it (the measured stats the format call is
    made from). The second carries every number that call needs, so the
    orchestrator reads the line instead of opening ``context-full.json`` in a
    turn of its own.
    """
    stats = out.get("context_stats")
    if not stats:
        return {
            "stage": "identity",
            "channel": out.get("channel_id"),
            "websites": len(out.get("websites") or []),
            "social_links": len(out.get("social_links") or []),
            "second_channels": len(out.get("second_channel_candidates") or []),
            "elapsed_s": elapsed,
        }
    return {
        "stage": "context",
        "channel": out.get("channel_id"),
        "videos": stats.get("videos_measured"),
        "fp_density_median": stats.get("fp_per_1k_words_median"),
        "interview_marker_videos": stats.get("videos_with_interview_markers"),
        "question_density": stats.get("questions_per_1k_words_median"),
        "title_hint_videos": sum((stats.get("title_hints") or {}).values()),
        "staged_share": stats.get("staged_share"),
        "likely_faceless": stats.get("likely_faceless"),
        "name_candidates": len(out.get("name_candidates") or []),
        "elapsed_s": elapsed,
    }


def _split(raw: str | None, sep: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(sep) if x.strip()]


def write_context(full: dict, *, format_label: str, format_evidence: str,
                  host_names: list[str] | None = None,
                  known_facts: list[str] | None = None) -> dict:
    """The compact context block ``extractor_prompt.py`` renders into every
    batch message, built from this script's own full output plus the format
    call the model made from it."""
    if format_label not in FORMAT_LABELS:
        raise SystemExit(f"--format-label must be one of {', '.join(FORMAT_LABELS)}, "
                         f"got {format_label!r}")
    name = full.get("name") or full.get("channel_name") or ""

    def clip(text, n):
        text = re.sub(r"\s+", " ", str(text or "")).strip()
        return (text[: n - 1].rstrip() + "…") if len(text) > n else (text or None)

    # what the channel says it is, so an extractor can tell a find from the
    # premise and recognise the host's name or business through caption errors
    return {
        "channel_name": name,
        "host_names": host_names or ([name] if name else []),
        "known_facts": known_facts or [],
        "channel_about": clip(full.get("about_text"), 700),
        "channel_ai_profile": clip(full.get("generated_profile"), 900),
        "format_label": format_label,
        "format_evidence": format_evidence,
    }


def set_socials(path: pathlib.Path, read: list[str], unread: list[str]) -> dict:
    """Record which of the channel's linked platforms the socials lane
    actually opened, into the ``context-full.json`` this script emits.

    It patches that file rather than taking an argument at write time,
    because only the lane knows the answer and the lane finishes long after
    the context is written. ``context-full.json`` is the right home because
    it is the file that carries ``social_links`` in the first place, and the
    file ``ledger_meta.py write --context`` is pointed at. Both it and
    ``build_html.py`` read
    ``social_links_read`` / ``social_links_unread`` from here; with neither
    key the page falls back to an all-or-nothing label off the `lanes` flag
    and reports every linked platform as read whenever the lane ran at all,
    including pages it never opened. A time-boxed lane is not a lane that
    read everything, so the honesty strip needs the per-link truth."""
    if not path.exists():
        raise SystemExit(f"no context file at {path}: write the full context "
                         "first (`--channel <id> ... > context-full.json`)")
    ctx = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(ctx, dict):
        raise SystemExit(f"{path} is not a context object")
    ctx["social_links_read"] = read
    ctx["social_links_unread"] = unread
    path.write_text(json.dumps(ctx, ensure_ascii=False, indent=1), encoding="utf-8")
    return ctx


def main() -> None:
    t0 = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", type=int, default=None,
                    help="internal TL channel id, from `tl channels find`")
    ap.add_argument("--from", dest="from_file", default=None,
                    help="a saved context-full.json (this script's own stdout); "
                         "with --write-context, no lookup is made")
    ap.add_argument("--write-context", dest="write_context", default=None,
                    help="write the compact extractor context block here "
                         "(needs --format-label; --format-evidence recommended)")
    ap.add_argument("--set-socials", dest="set_socials", default=None,
                    help="patch an existing context-full.json (this script's "
                         "own --channel output, the file ledger_meta.py write "
                         "--context reads) with which linked platforms the "
                         "socials lane read; pass the lane's answer as "
                         "--social-read / --social-unread")
    ap.add_argument("--social-read", dest="social_read", default=None,
                    help="comma-separated links the socials lane opened")
    ap.add_argument("--social-unread", dest="social_unread", default=None,
                    help="comma-separated links it did not open")
    ap.add_argument("--format-label", dest="format_label", default=None,
                    choices=FORMAT_LABELS,
                    help="the format the model called from the stats")
    ap.add_argument("--format-evidence", dest="format_evidence", default="",
                    help="one line of evidence for the label")
    ap.add_argument("--host-names", dest="host_names", default=None,
                    help="comma-separated; default: the channel name")
    ap.add_argument("--known-facts", dest="known_facts", default=None,
                    help="semicolon-separated facts already known about the host")
    ap.add_argument("--corpus", default=None,
                    help="corpus.jsonl.gz from fetch_cues.py (a plain "
                         ".jsonl corpus is read too); adds measured "
                         "format stats")
    ap.add_argument("--per-video-out", dest="per_video_out", default=None,
                    help="write the per-video stat rows to this JSON file "
                         "(they never go to stdout: on a large channel the "
                         "array is megabytes, and stdout is read by the "
                         "orchestrating session)")
    a = ap.parse_args()

    if a.set_socials:
        read = _split(a.social_read, ",")
        unread = _split(a.social_unread, ",")
        if not read and not unread:
            ap.error("--set-socials needs --social-read and/or --social-unread; "
                     "with neither the page cannot tell read from unread")
        path = pathlib.Path(a.set_socials)
        ctx = set_socials(path, read, unread)
        print(json.dumps({"context": str(path),
                          "social_links_read": ctx["social_links_read"],
                          "social_links_unread": ctx["social_links_unread"]},
                         ensure_ascii=False))
        return

    if a.write_context:
        if not a.format_label:
            ap.error("--write-context needs --format-label")
        if a.from_file:
            full = json.loads(pathlib.Path(a.from_file).read_text(encoding="utf-8"))
        elif a.channel is not None:
            full = {"name": channel_row(a.channel).get("channel_name")}
        else:
            ap.error("--write-context needs --from <context-full.json> or --channel")
        ctx = write_context(full, format_label=a.format_label,
                            format_evidence=a.format_evidence,
                            host_names=_split(a.host_names, ","),
                            known_facts=_split(a.known_facts, ";"))
        path = pathlib.Path(a.write_context)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(ctx, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({"context": str(path), **ctx}, ensure_ascii=False))
        return

    if a.channel is None:
        ap.error("--channel is required")
    row = channel_row(a.channel)
    doc = channel_doc(a.channel)
    websites, socials = websites_and_socials(row.get("social_links"), doc.get("social_links"))

    out = {
        "channel_id": a.channel,
        "name": row.get("channel_name") or doc.get("name"),
        "url": row.get("url"),
        "external_channel_id": row.get("external_channel_id"),
        "subscribers": row.get("subscribers"),
        "total_views": row.get("total_views"),
        "num_uploads": row.get("num_uploads"),
        "country": row.get("country"),
        "language": row.get("language"),
        "last_published": str(row.get("last_published") or "")[:10] or None,
        "generated_profile": _nested(doc, "ai.description"),
        "about_text": doc.get("description"),
        # the links on the creator's YouTube page: the labelled header links
        # (their websites) and the platform links; the identity lane reads
        # these directly. A profile that cannot be read is reported "linked
        # but unread", never silently skipped
        "websites": websites,
        "social_links": socials,
        "second_channel_candidates": second_channel_candidates(row, doc),
        "topic_descriptions": _nested(doc, "ai.topic_descriptions"),
        "note": ("format label is called by a model read of a small sample "
                 "WITH these stats as evidence; the stats are inputs, not a "
                 "verdict, and nothing here exits the pipeline early"),
    }
    if a.corpus:
        stats = corpus_stats(pathlib.Path(a.corpus))
        per_video = stats.pop("per_video", None)
        if per_video is not None and a.per_video_out:
            path = pathlib.Path(a.per_video_out)
            path.write_text(json.dumps(per_video, default=str),
                            encoding="utf-8")
            stats["per_video_file"] = str(path)
        out["context_stats"] = stats
        # search terms for the identity lane, from the passages just fetched:
        # the names the creator calls themselves, which are often not the
        # name on the channel
        out["name_candidates"] = name_candidates(
            pathlib.Path(a.corpus), out.get("name"))
    print(json.dumps(out, indent=1, default=str))
    funnel(**funnel_fields(out, round(time.monotonic() - t0, 1)))


if __name__ == "__main__":
    main()
