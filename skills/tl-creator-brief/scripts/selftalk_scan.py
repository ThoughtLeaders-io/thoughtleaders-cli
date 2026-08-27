#!/usr/bin/env python3
"""Cut transcripts down to candidate self-reference lines, and say whose they are.

Two jobs, and they are different questions:

1. **Is this passage personal at all?** A first-person search is not the test.
   "I think you should buy gold" and "I'll show you in a second" are both first
   person and neither is worth anything. So a passage is kept only if it carries
   a first-person marker AND a self-disclosure cue AND no exclusion. The
   exclusions are the two failure modes: stage directions, which exist only
   because the video exists, and opinions about the world, which are not facts
   about the speaker.

2. **Whose mouth did it come out of?** Captions carry no speaker labels, so
   wherever a second voice is in the transcript, its self-disclosure is
   indistinguishable from the host's. "My father was a salesman his whole life"
   is perfect self-disclosure belonging to the wrong person. The second voice
   might be an interview guest, a co-host, or narration from material being
   reacted to. Where only one voice is present there is nothing to separate, and
   these signals are ranking information rather than a test to pass. Four signals
   are attached to every passage so the judgement step is not guessing:

   * ``host_anchor`` (strong): matches a distinctive fact about the host, from
     ``--host-terms``. Their surname, their companies, their funds, a named
     former role.
   * ``weak_anchor``: first-person talk about running a show or a business
     ("my podcast", "my company"). Only about half of these are the host, since
     anyone speaking can have a podcast or a company. They are kept and LABELLED
     rather than discarded, because dropping them was measured twice and was a
     mistake both times: the judging step rejects the misattributed half
     reliably, so the label loses nothing and the deletion lost real findings.
   * ``in_sponsor_read``: falls inside a detected sponsored segment. Ad reads are
     spoken by the host, never by a guest or by reacted material, so this is
     close to proof in any format.
   * ``recurrence_videos``: how many DIFFERENT videos share a distinctive phrase
     with this passage. Whoever else is in the transcript changes between uploads
     and the host does not, so a personal claim appearing in three uploads is not
     three different visitors saying the same thing about themselves. A phrase
     counts as distinctive only if at least one of its words is rare across the
     corpus; without that test the signal returns conversational filler.
The whole first job is plain pattern matching, with no model involved. Passages
arrive carrying their video, timestamp and link, reusing
``quote_timestamp.fetch_cues``, so nothing needs timestamping later.

Usage:
    build_corpus.py --channel <id> | selftalk_scan.py \\
        --host-terms "<surname>,<company>,<former role>"
    build_corpus.py --channel <id> | selftalk_scan.py \\
        --host-terms "<surname>" --domain-terms team,squad,roster

Output (stdout): one JSON object, passages ranked by attribution strength.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict

from quote_timestamp import fetch_cues  # sibling script, same directory

FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'd|i'll|my|me|myself|mine)\b", re.I)

# Self-disclosure: a fact about the speaker that exists off camera.
DISCLOSURE = [
    ("life_verb", re.compile(
        r"\b(founded|co-?founded|started (my|a|the)|built (my|a)|launched|"
        r"grew up|was raised|raised in|taught myself|self-?taught|studied|"
        r"majored|dropped out|graduated|got fired|was fired|quit|left school|"
        r"moved to|grew my|used to (be|work|play|live|do)|worked (at|as|for)|"
        r"trained as|apprenticed|my first job|when i was (a|\d)|"
        r"i was born|i've always|i have always|i never went)\b", re.I)),
    ("own_life", re.compile(
        r"\bmy (dad|mum|mom|father|mother|parents|wife|husband|partner|"
        r"girlfriend|boyfriend|kid|kids|son|daughter|child|children|brother|"
        r"sister|family|dog|cat|pet|house|home|flat|hometown|village|school|"
        r"university|college|degree|company|companies|business|businesses|"
        r"agency|startup|team|staff|job|career|background|routine|morning|"
        r"diet|training|therapist|doctor|accountant|co-?founder|investors|"
        r"podcast|studio|office|book|friends|best friend)\b", re.I)),
    ("self_characterisation", re.compile(
        r"\b(i consider myself|i see myself|i'?m the kind of|i'?m the type of|"
        r"i'?ve always been|i'?m not really a|i'?m quite|i tend to|"
        r"my favou?rite|i'?m obsessed with|i'?m terrible at|i'?m useless at|"
        r"i can'?t stand|i genuinely (love|hate)|i'?m a big fan of|"
        r"personally i|for me personally)\b", re.I)),
]

# Both of these are first person and neither is a find.
# Half-signals. First-person talk about running a show or a business: often the
# host, frequently whoever else is in the transcript. Worth a look, never worth
# trusting on its own.
# A possessive is only self-disclosure if the thing possessed belongs to the
# speaker's life. On a gaming channel "my team" is almost always the in-game team
# for that match, and it was the single largest drop reason in a real run, roughly
# 12 of every 41 passages judged. Pass --domain-terms team,squad,roster there to
# stop it counting. Off by default, because on a business channel "my team" is a
# real fact about the speaker. Suppression needs EVERY possessive in the passage
# to be a domain object, so "my team and my wife" still counts.
WEAK_ANCHOR = re.compile(
    r"\b(my|our) (podcast|show|channel|company|companies|business|businesses|"
    r"agency|startup|fund|team|book|brand|investors|co-?founder|"
    r"business partner)\b", re.I)

EXCLUDE = re.compile(
    r"\b(i'?ll show you|let me show|i want to (talk|show|tell you about)|"
    r"i'?m going to (show|talk|explain|walk)|as i (said|mentioned)|"
    r"i'?ll come back|i'?ll explain|coming up|in this video|in today'?s video|"
    r"before we (start|begin|get into)|make sure you|don'?t forget to|"
    r"let'?s (get|jump|dive|talk|look)|we'?ll (look|see|talk|cover)|"
    r"stay tuned|link (in|below)|subscribe|"
    r"i think you should|i believe you should|you should probably|if i were you|"
    r"in my opinion|i would argue|i'?d argue|my point is|my argument)\b", re.I)

WINDOW_CHARS = 260

# An ad read runs well past the seconds the detector flags, so the window is
# padded generously in both directions.
SPONSOR_PAD = 75

_STOP = set("""a an the and or but if of to in on at by for with from as is are was
were be been being it its it's this that these those i me my myself we our you
your he she they them his her their there here what which who whom when where
how why not no nor so than then too very can will just don't should now do does
did doing have has had having would could about up down out over under again
know knew think thought like really thing things get got getting going gone one
two three also because said say says saying see saw seen want wanted way ways
lot lots much many more most little bit kind sort actually maybe probably
always never often sometimes yeah okay right well even still back come came
make made take took give gave put good bad great big small new old first last
time times year years day days people person life live lived feel felt felt
look looked looking talk talked talking tell told mean meant need needed
wonder wondered wondering guess suppose reckon quite pretty very""".split())


def _tl_es(body: dict) -> list[dict]:
    proc = subprocess.run(["tl", "db", "es", json.dumps(body)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    try:
        return json.loads(proc.stdout).get("results") or []
    except json.JSONDecodeError:
        return []


def sponsor_segments(refs: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Spoken sponsored segments per video, in one query for the whole corpus."""
    if not refs:
        return {}
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for row in _tl_es({
        "size": len(refs),
        "query": {"ids": {"values": refs}},
        "_source": ["id", "brand_mentions"],
    }):
        mentions = row.get("brand_mentions") or []
        if isinstance(mentions, dict):
            mentions = [mentions]
        for m in mentions:
            if m.get("type") != "sponsored" or m.get("field") != "transcript":
                continue
            start, end = m.get("start_ts"), m.get("end_ts")
            if not isinstance(start, (int, float)):
                continue
            if not isinstance(end, (int, float)) or end < start:
                end = start
            # A (0, 0) segment is a detection with no located position. Padded,
            # it would wrongly claim the opening of the video as an ad read.
            if start <= 0 and end <= 0:
                continue
            out[str(row.get("id"))].append((float(start), float(end)))
    return dict(out)


def _content_words(text: str) -> list[str]:
    words = re.findall(r"[a-z']+", text.lower())
    return [w for w in words if w not in _STOP and len(w) > 2]


def _phrases(text: str, n: int = 4) -> set[str]:
    """n-grams of content words. Distinctiveness is applied later, in one pass
    over the whole corpus, because it depends on how rare a word is here."""
    words = _content_words(text)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


# A phrase is distinctive only if one of its words appears in at most this share
# of the corpus's videos. Filler vocabulary is everywhere; a real personal claim
# carries at least one word that is not.
RARE_SHARE = 0.30


def add_recurrence(cands: list[dict]) -> None:
    """How many different videos share a distinctive phrase with each passage.

    Whoever else is in the transcript changes between uploads and the host does
    not, so a personal claim
    that turns up in several episodes belongs to the host.
    """
    videos = {c["id"] for c in cands}
    word_videos: dict[str, set[str]] = defaultdict(set)
    for c in cands:
        for w in set(_content_words(c["text"])):
            word_videos[w].add(c["id"])
    ceiling = max(1, int(len(videos) * RARE_SHARE))
    rare = {w for w, vids in word_videos.items() if len(vids) <= ceiling}

    phrase_videos: dict[str, set[str]] = defaultdict(set)
    for c in cands:
        for ph in c["_phrases"]:
            if any(w in rare for w in ph.split()):
                phrase_videos[ph].add(c["id"])
    for c in cands:
        best, best_ph = 1, None
        for ph in c["_phrases"]:
            n = len(phrase_videos.get(ph, ()))
            if n > best:
                best, best_ph = n, ph
        c["recurrence_videos"] = best
        c["recurring_phrase"] = best_ph



def windows(cues: list[dict]) -> list[tuple[int, str]]:
    """Group cues into readable windows, each keyed to its opening offset."""
    out, buf, start = [], [], None
    for cue in cues:
        text = (cue.get("text") or "").strip()
        if not text:
            continue
        if start is None:
            start = int(cue["start"])
        buf.append(text)
        if sum(len(x) + 1 for x in buf) >= WINDOW_CHARS:
            out.append((start, " ".join(buf)))
            # one cue of overlap, so a sentence split across a boundary survives
            buf, start = [text], int(cue["start"])
    if buf and start is not None:
        out.append((start, " ".join(buf)))
    return out


def _possessive_nouns(rx: re.Pattern, text: str) -> list[str]:
    """The possessive nouns a cue matched, lowercased. The noun is the last
    capture group in both own_life and WEAK_ANCHOR."""
    return [m.groups()[-1].lower().replace("-", "") for m in rx.finditer(text)]


def _all_domain(nouns: list[str], domain: frozenset[str]) -> bool:
    """True when every possessive in the passage is a domain object, so the cue
    says nothing about the speaker's life."""
    return bool(nouns) and all(n in domain for n in nouns)


def judge(text: str, domain: frozenset[str] = frozenset()) -> list[str] | None:
    """Return which disclosure cues fired, or None if the passage is rejected."""
    if not FIRST_PERSON.search(text):
        return None
    if EXCLUDE.search(text):
        return None
    fired = []
    for name, rx in DISCLOSURE:
        if not rx.search(text):
            continue
        if domain and name == "own_life" \
                and _all_domain(_possessive_nouns(rx, text), domain):
            continue
        fired.append(name)
    return fired or None


def weak_anchor(text: str, domain: frozenset[str] = frozenset()) -> bool:
    if not WEAK_ANCHOR.search(text):
        return False
    if domain and _all_domain(_possessive_nouns(WEAK_ANCHOR, text), domain):
        return False
    return True


def _in_sponsor(start: int, segments: list[tuple[float, float]]) -> bool:
    return any(s - SPONSOR_PAD <= start <= e + SPONSOR_PAD for s, e in segments)


def host_signal_count(c: dict) -> int:
    """Strong signals score 2, the half-signal scores 1, so ranking prefers the
    attributable material without discarding the rest."""
    n = 0
    if c["host_anchor"]:
        n += 2
    if c["in_sponsor_read"]:
        n += 2
    if c["recurrence_videos"] >= 3:
        n += 2
    if c["weak_anchor"]:
        n += 1
    return n


def _rank(c: dict) -> tuple:
    """Best-attributed, most-disclosing passages first, so the caps bite last."""
    return (-c["host_signals"], -len(c["cues_fired"]), c["start"])


def scan_video(video: dict, host_rx,
               segments: list[tuple[float, float]],
               domain: frozenset[str] = frozenset()) -> dict:
    ref = video["id"]
    try:
        cues = fetch_cues(ref)
    except SystemExit:
        # fetch_cues exits on a missing document; a coverage gap, not an error.
        return {"id": ref, "transcript": False, "candidates": []}
    if not cues:
        return {"id": ref, "transcript": False, "candidates": []}

    vid = video.get("video_id") or str(ref).split(":")[-1]
    found = []
    for start, text in windows(cues):
        fired = judge(text, domain)
        if not fired:
            continue
        found.append({
            "id": ref,
            "video_id": vid,
            "title": video.get("title"),
            "published": video.get("published"),
            "start": start,
            "url": f"https://www.youtube.com/watch?v={vid}&t={start}s",
            "cues_fired": fired,
            "host_anchor": bool(host_rx and host_rx.search(text)),
            "weak_anchor": weak_anchor(text, domain),
            "in_sponsor_read": _in_sponsor(start, segments),
            "text": text,
            "_phrases": _phrases(text),
        })
    return {"id": ref, "transcript": True, "candidates": found}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=None,
                    help="comma-separated <channel>:<video> refs, instead of stdin")
    ap.add_argument("--host-terms", default=None,
                    help="comma-separated facts distinctive to the host, from the "
                         "identity step. Never generic possessives.")
    ap.add_argument("--domain-terms", default=None,
                    help="comma-separated possessive nouns that are objects in "
                         "this channel's subject matter rather than facts about "
                         "the speaker's life, for example team,squad,roster on a "
                         "gaming or sport channel. A passage whose only "
                         "possessive is one of these stops counting as "
                         "self-disclosure. Off by default, because on a business "
                         "channel \"my team\" is a real life fact.")
    ap.add_argument("--max-per-video", type=int, default=30,
                    help="ceiling per video (default 30). A two-hour episode "
                         "yields about 30, so this protects against an outlier "
                         "rather than routinely discarding material.")
    ap.add_argument("--max-candidates", type=int, default=400)
    ap.add_argument("--unsignalled", choices=["keep", "drop"], default="keep",
                    help="'drop' returns only passages carrying at least one "
                         "host signal; the count set aside is always reported. "
                         "Default is keep: the signals are sparse, and the "
                         "judging step rejects misattributed material reliably "
                         "anyway. On a single-voice channel the signals barely "
                         "fire at all, so dropping here empties the pool.")
    a = ap.parse_args()

    if a.ids:
        corpus = {"selected": [{"id": r.strip()} for r in a.ids.split(",")
                               if r.strip()]}
    else:
        corpus = json.load(sys.stdin)
    videos = corpus.get("selected") or []
    if not videos:
        sys.exit("no videos in input")

    host_terms = [t.strip() for t in (a.host_terms or "").split(",") if t.strip()]
    host_rx = (re.compile("|".join(re.escape(t) for t in host_terms), re.I)
               if host_terms else None)
    domain = frozenset(w.strip().lower().replace("-", "")
                       for w in (a.domain_terms or "").split(",") if w.strip())
    segments = sponsor_segments([v["id"] for v in videos if v.get("id")])

    all_cands, no_transcript, per_video_dropped = [], [], 0
    for v in videos:
        res = scan_video(v, host_rx, segments.get(v["id"], []), domain)
        if not res["transcript"]:
            no_transcript.append(res["id"])
            continue
        all_cands.extend(res["candidates"])

    # Recurrence needs every passage in hand, so it runs after the per-video pass
    # and before any capping.
    add_recurrence(all_cands)
    for c in all_cands:
        c["host_signals"] = host_signal_count(c)
        del c["_phrases"]

    by_video: dict[str, list[dict]] = defaultdict(list)
    for c in all_cands:
        by_video[c["id"]].append(c)
    kept = []
    for ref, group in by_video.items():
        group.sort(key=_rank)
        per_video_dropped += max(0, len(group) - a.max_per_video)
        kept.extend(group[:a.max_per_video])

    signalled = [c for c in kept if c["host_signals"] > 0]
    unsignalled_count = len(kept) - len(signalled)
    pool = signalled if a.unsignalled == "drop" else kept

    pool.sort(key=_rank)
    dropped_by_cap = max(0, len(pool) - a.max_candidates)
    pool = pool[:a.max_candidates]

    scanned = len(videos) - len(no_transcript)
    print(json.dumps({
        "channel_id": corpus.get("channel_id"),
        "videos_in_corpus": len(videos),
        "videos_with_transcript": scanned,
        "videos_without_transcript": len(no_transcript),
        "transcript_coverage": round(scanned / len(videos), 2) if videos else None,
        "missing_transcripts": no_transcript,
        "passages_flagged": len(all_cands),
        "dropped_by_per_video_cap": per_video_dropped,
        "dropped_by_total_cap": dropped_by_cap,
        "candidates_returned": len(pool),
        "host_terms_used": host_terms,
        "domain_terms_used": sorted(domain),
        "signals": {
            "host_anchor": sum(1 for c in pool if c["host_anchor"]),
            "in_sponsor_read": sum(1 for c in pool if c["in_sponsor_read"]),
            "recurring_3plus": sum(1 for c in pool
                                   if c["recurrence_videos"] >= 3),
            "weak_anchor_only": sum(1 for c in pool if c["weak_anchor"]
                                    and not (c["host_anchor"]
                                             or c["in_sponsor_read"]
                                             or c["recurrence_videos"] >= 3)),
            "no_signal_at_all": unsignalled_count,
        },
        "filter_note": ("coarse pattern filter, not a verdict; every passage "
                        "still has to pass the three-part self-reference test "
                        "in references/evidence-rules.md"),
        "attribution_note": ("host_anchor, in_sponsor_read and recurrence are "
                             "strong signals. weak_anchor is a half-signal: "
                             "roughly half are whoever else is in the "
                             "transcript, so keep those and LABEL them "
                             "unconfirmed rather than dropping them. Where a "
                             "second voice shares the transcript, a passage with "
                             "no signal at all is not attributable from the "
                             "transcript alone. Where only one voice is present "
                             "there is nothing to separate and no signal is "
                             "required, so the three-part test decides."),
        "candidates": pool,
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
