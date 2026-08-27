#!/usr/bin/env python3
"""Cut transcripts down to candidate self-reference lines, cheaply.

The expensive way to find where a creator talks about themselves is to have a
model read every transcript. On a channel with hundreds of two-hour uploads that
is the entire cost of the skill, and worse, the raw text then sits in a
conversation and is paid for again on every following turn.

So this does the mechanical half in plain Python, for nothing: fetch the
transcripts, and keep only the windows that look like self-disclosure. It throws
away the great majority of the text. What survives goes to a model for the
judgement half, the three-part test in ``references/evidence-rules.md``, which is
the part that actually needs judgement.

**This filter is a coarse net, deliberately.** It over-collects and it will miss
things. Its job is to make the judgement step affordable, not to be right. Three
lists decide a window:

* a first-person marker must be present
* a self-disclosure cue must be present: a life verb ("founded", "grew up",
  "taught myself"), a possessive about their own life ("my dad", "my agency"),
  or a self-characterisation ("I consider myself", "my favourite")
* and no exclusion may fire: stage directions ("I'll show you in a second") and
  opinions about the world ("I think you should buy gold") are both first person
  and neither is worth anything. They are the two failure modes the rule exists
  to stop.

**Attribution is the hard part on an interview channel**, and captions carry no
speaker labels. The guest talks about themselves constantly, so most self-talk on
the channel belongs to the wrong person, and a model reading a 260-character
window cannot tell whose "I" it is either. Two mechanical signals are attached to
every candidate so the judgement step is not guessing:

``host_anchor``: the window matches a distinctive fact about the host, passed in
with ``--host-terms`` from the cheap identity step. If the host is known to have
founded a marketing agency and the guest is a neuroscientist, a line about
founding a marketing agency is attributable. This is what the identity step is
really for: it is the attribution key, not just background colour.

A positional signal was tried here and removed. The theory was that an interview
host speaks alone in the opening minutes, so early windows would be the host's.
Tested on a large interview channel it did the opposite: the show cold-opens on a
clip of the GUEST, so "early" reliably tagged guest speech. A heuristic that
points the wrong way is worse than none.

On an interview channel, a candidate without ``host_anchor`` is not attributable
from the transcript alone, and the judgement step keeps it only if the speaker
names themselves or is named in the surrounding text. That is a real loss of
recall and it is the correct trade: a quote attributed to the wrong human being
is worse than a missing quote.

Every candidate comes back with its video and its offset already attached,
reusing ``quote_timestamp.fetch_cues``, so nothing needs timestamping later.

Usage:
    build_corpus.py --channel 138573 | selftalk_scan.py
    build_corpus.py --channel 138573 | selftalk_scan.py \
        --host-terms "bartlett,social chain,marketing agency,my podcast"
    selftalk_scan.py --ids 138573:abc123,138573:def456

Output (stdout): one JSON object. Candidates are capped; the cap is reported.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

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
EXCLUDE = re.compile(
    # stage directions: exist only because the video exists
    r"\b(i'?ll show you|let me show|i want to (talk|show|tell you about)|"
    r"i'?m going to (show|talk|explain|walk)|as i (said|mentioned)|"
    r"i'?ll come back|i'?ll explain|coming up|in this video|in today'?s video|"
    r"before we (start|begin|get into)|make sure you|don'?t forget to|"
    r"let'?s (get|jump|dive|talk|look)|we'?ll (look|see|talk|cover)|"
    r"stay tuned|link (in|below)|subscribe|"
    # opinions about the world, not facts about the speaker
    r"i think you should|i believe you should|you should probably|if i were you|"
    r"in my opinion|i would argue|i'?d argue|my point is|my argument)\b", re.I)

WINDOW_CHARS = 260


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


def judge(text: str) -> list[str] | None:
    """Return which disclosure cues fired, or None if the window is rejected."""
    if not FIRST_PERSON.search(text):
        return None
    if EXCLUDE.search(text):
        return None
    fired = [name for name, rx in DISCLOSURE if rx.search(text)]
    return fired or None


def _host_rx(terms: list[str]):
    if not terms:
        return None
    parts = [re.escape(t.strip()) for t in terms if t.strip()]
    return re.compile("|".join(parts), re.I) if parts else None


def _signal_rank(c: dict) -> tuple:
    """Best-attributed, most-disclosing candidates first, so the caps keep those."""
    return (
        0 if c["host_anchor"] else 1,
        -len(c["cues_fired"]),
        c["start"],
    )


def scan_video(video: dict, max_per_video: int, host_rx) -> dict:
    ref = video["id"]
    try:
        cues = fetch_cues(ref)
    except SystemExit:
        # fetch_cues exits on a missing document; that is a coverage gap, not a
        # run-ending error.
        return {"id": ref, "transcript": False, "candidates": []}
    if not cues:
        return {"id": ref, "transcript": False, "candidates": []}

    found = []
    for start, text in windows(cues):
        fired = judge(text)
        if not fired:
            continue
        found.append({
            "id": ref,
            "host_anchor": bool(host_rx and host_rx.search(text)),
            "video_id": video.get("video_id") or str(ref).split(":")[-1],
            "title": video.get("title"),
            "published": video.get("published"),
            "start": start,
            "url": f"https://www.youtube.com/watch?v="
                   f"{video.get('video_id') or str(ref).split(':')[-1]}&t={start}s",
            "cues_fired": fired,
            "text": text,
        })
    found.sort(key=_signal_rank)
    dropped = max(0, len(found) - max_per_video)
    return {"id": ref, "transcript": True,
            "candidates": found[:max_per_video], "dropped_in_video": dropped}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", default=None,
                    help="comma-separated <channel>:<video> refs, instead of stdin")
    ap.add_argument("--max-per-video", type=int, default=8)
    ap.add_argument("--max-candidates", type=int, default=300)
    ap.add_argument("--host-terms", default=None,
                    help="comma-separated distinctive facts about the host, from "
                         "the identity step; used to attribute a line to the host "
                         "rather than a guest")
    a = ap.parse_args()

    if a.ids:
        corpus = {"selected": [{"id": r.strip()} for r in a.ids.split(",")
                               if r.strip()]}
    else:
        corpus = json.load(sys.stdin)
    videos = corpus.get("selected") or []
    if not videos:
        sys.exit("no videos in input")
    host_terms = [t for t in (a.host_terms or "").split(",") if t.strip()]
    host_rx = _host_rx(host_terms)

    candidates, no_transcript, dropped_in_videos = [], [], 0
    for v in videos:
        res = scan_video(v, a.max_per_video, host_rx)
        if not res["transcript"]:
            no_transcript.append(res["id"])
            continue
        dropped_in_videos += res.get("dropped_in_video", 0)
        candidates.extend(res["candidates"])

    candidates.sort(key=_signal_rank)
    dropped_by_cap = max(0, len(candidates) - a.max_candidates)
    candidates = candidates[:a.max_candidates]

    scanned = len(videos) - len(no_transcript)
    print(json.dumps({
        "channel_id": corpus.get("channel_id"),
        "videos_in_corpus": len(videos),
        "videos_with_transcript": scanned,
        "videos_without_transcript": len(no_transcript),
        "transcript_coverage": (round(scanned / len(videos), 2)
                                if videos else None),
        "missing_transcripts": no_transcript,
        "candidates_returned": len(candidates),
        "host_terms_used": host_terms,
        "with_host_anchor": sum(1 for c in candidates if c["host_anchor"]),
        "dropped_by_per_video_cap": dropped_in_videos,
        "dropped_by_total_cap": dropped_by_cap,
        "filter_note": ("coarse pattern filter, not a verdict; every candidate "
                        "still has to pass the three-part self-reference test "
                        "in references/evidence-rules.md"),
        "attribution_note": ("on an interview channel, a candidate without "
                             "host_anchor is not attributable to the host from "
                             "the transcript alone; keep it only if the speaker "
                             "names themselves or is named nearby, else drop it. "
                             "On a solo channel there is no attribution risk and "
                             "host_anchor is not required."),
        "candidates": candidates,
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
