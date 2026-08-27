#!/usr/bin/env python3
"""Generous local recall pass over a fetched corpus: rank windows, reject nothing.

Reads the local ``corpus.jsonl`` written by ``fetch_corpus.py`` — never the
index — windows every transcript into ~260-char passages (keeping cue start
seconds, so every future quote is born with its ``&t=`` link), and keeps any
window carrying a first-person marker or a fuzzy entity hit.

This layer exists solely to cut model-token spend, so it is tuned for recall,
never precision. **Nothing with first-person content is hard-rejected.** The
old disclosure/exclusion lexicons are demoted to *ranking features*: they
order which windows the model reads first, they reject nothing. The only hard
drop is provable boilerplate ("subscribe", "link in the description") carrying
no other first-person content. The models decide what is a gem; this script
only decides what they read first.

Fuzzy entity matching is **token-bounded**: a term is compared against whole
transcript tokens (and token n-grams for multi-word terms), never substrings,
so a surname "Lee" can never match "sleep". Within a token, exact match,
capped edit distance, a shared long prefix, or an equal phonetic key all
count — that is what survives caption mangling ("Maddox" for Matiks,
"social channel" for Social Chain).

Deterministic attribution features are attached to every window as *model
inputs, not verdicts*: ad-read overlap from sponsored ``brand_mentions``
spans (near-proof of host voice, and simultaneously banned as a gem source —
see references/evidence-rules.md), cross-video recurrence of rare phrases,
and fuzzy host-anchor hits.

Usage:
    selftalk_scan.py --corpus tl-creator-profiles/.corpus/<id>/corpus.jsonl \\
        --host-terms "<surname>,<company>,<former role>"
    # after new entities surface ("my dog Luna"), re-scan locally — free:
    selftalk_scan.py --corpus ... --host-terms ... --entity-terms "Luna"

Output: ``windows.jsonl`` (every kept window, ranked) and ``batches/*.json``
(rank-ordered ~50-window batches ready to fan out to classifier agents) next
to the corpus, plus one JSON summary on stdout. Raw transcript text stays in
the files; only counts and paths reach the orchestrator.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data
from channel_context import TITLE_SECOND_VOICE  # sibling script

WINDOW_CHARS = 260
BATCH_SIZE = 50
SPONSOR_PAD = 75      # an ad read runs past the seconds the detector flags
IDS_CHUNK = 1000

FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'd|i'll|my|me|myself|mine|we|our)\b",
                          re.I)

# Ranking features only. None of these gates anything.
DISCLOSURE = [
    ("life_verb", re.compile(
        r"\b(founded|co-?founded|started (my|a|the)|built (my|a)|launched|"
        r"grew up|was raised|raised in|taught myself|self-?taught|studied|"
        r"majored|dropped out|graduated|got fired|was fired|quit|left school|"
        r"moved to|used to (be|work|play|live|do)|worked (at|as|for)|"
        r"trained as|my first job|when i was (a|\d)|i was born|"
        r"as a kid|growing up|my childhood|back home( in)?|"
        r"i collect|i('m| am) (really |super |big )?into|my go-?to|"
        r"i('ve| have) always|i never went|allergic|diagnosed|obsessed with)\b",
        re.I)),
    ("own_life", re.compile(
        r"\bmy (dad|mum|mom|father|mother|parents|wife|husband|partner|"
        r"girlfriend|boyfriend|kid|kids|son|daughter|child|children|brother|"
        r"sister|family|dog|cat|pet|house|home|flat|hometown|school|"
        r"university|college|degree|company|business|agency|startup|team|"
        r"job|career|routine|morning|diet|training|therapist|doctor|"
        r"podcast|studio|office|book|friend|best friend|nursery|garden|"
        r"hobby|hobbies|collection|setup|gym|workout|"
        r"favou?rite (food|meal|snack|dish|game|band|movie|show|team)|"
        r"comfort food|go-?to (order|meal|snack)|guitar|piano)\b",
        re.I)),
    ("self_characterisation", re.compile(
        r"\b(i consider myself|i see myself|i'?m the kind of|i'?m the type of|"
        r"i'?ve always been|i'?m not really a|i tend to|my favou?rite|"
        r"i'?m terrible at|i can'?t stand|i genuinely (love|hate)|"
        r"i'?m a big fan of|personally i|for me personally)\b", re.I)),
]

# First-person talk about running a show or a business: often the host,
# frequently whoever else shares the transcript. A half-signal for ranking.
WEAK_ANCHOR = re.compile(
    r"\b(my|our) (podcast|show|channel|company|business|agency|startup|fund|"
    r"team|book|brand|investors|co-?founder|business partner)\b", re.I)

# Stage directions and opinion framing: rank DOWN, never drop. "as I said, my
# dad ran a bakery" must survive; the model sorts it out.
STAGE = re.compile(
    r"\b(i'?ll show you|let me show|i'?m going to (show|explain|walk)|"
    r"in this video|in today'?s video|before we (start|begin|get into)|"
    r"let'?s (get|jump|dive)|stay tuned|coming up)\b", re.I)

# The only hard drop, and only when the window's first-person content IS the
# boilerplate: both patterns are masked out and the remainder re-tested, so
# "I live in London, and remember to subscribe" survives.
BOILERPLATE = re.compile(
    r"\b(subscribe|smash th(e|at) like|link (in|below)|link in the "
    r"description|notification bell|comment below|patreon|join the channel)\b",
    re.I)
BOILER_FP = re.compile(
    r"\b(my|our) (channel|patreon|newsletter|merch|videos?|links?|discord|"
    r"instagram|twitter)\b", re.I)

_STOP = set("""a an the and or but if of to in on at by for with from as is are
was were be been being it its this that these those i me my myself we our you
your he she they them his her their there here what which who when where how
why not no so than then too very can will just don't should now do does did
doing have has had having would could about up down out over under again know
think like really thing things get got going gone one two three also because
said say says see saw want way lot much many more most bit kind sort actually
maybe probably always never often sometimes yeah okay right well even still
back come came make made take took give gave put good bad great big small new
old first last time year years day days people person life feel felt look
talk tell told mean need guess quite pretty""".split())

RARE_SHARE = 0.30     # a phrase is distinctive only if one word is this rare


# --------------------------------------------------------------------------- #
# token-bounded fuzzy matching
# --------------------------------------------------------------------------- #
def _soundex(word: str) -> str:
    """Full-length soundex code, deliberately untruncated: the classic 4-char
    cut makes "watson" equal "watching", which is exactly the kind of false
    anchor this matcher must not produce."""
    codes = {"b": "1", "f": "1", "p": "1", "v": "1",
             "c": "2", "g": "2", "j": "2", "k": "2", "q": "2", "s": "2",
             "x": "2", "z": "2", "d": "3", "t": "3", "l": "4",
             "m": "5", "n": "5", "r": "6"}
    word = word.lower()
    out, prev = word[0], codes.get(word[0], "")
    for ch in word[1:]:
        code = codes.get(ch, "")
        if code and code != prev:
            out += code
        if ch not in "hw":
            prev = code
    return out


def _edit_distance(a: str, b: str, cap: int) -> int:
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ca != cb)))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def _common_prefix(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


STRONG, PHONETIC = 2, 1


def _tokens_match(term: str, token: str) -> int:
    """Whole-token comparison only — 'lee' can never match 'sleep'.

    Returns STRONG (exact / tight edit distance / long shared prefix),
    PHONETIC (equal full soundex code only — plausible caption mangling like
    "mates" for "Matiks", kept for recall but ranked low), or 0.
    """
    if term == token:
        return STRONG
    if len(term) < 4 or len(token) < 4:
        return 0            # short tokens: exact or nothing
    if term[0] != token[0]:
        return 0            # caption mangling rarely changes the first letter
    cap = 1 if len(term) < 8 else 2
    if _edit_distance(term, token, cap) <= cap:
        return STRONG
    if min(len(term), len(token)) >= 5 and _common_prefix(term, token) >= 4:
        return STRONG
    # equal full phonetic code ("maddox"/"matiks", "matx"/"matiks")
    if _soundex(term) == _soundex(token):
        return PHONETIC
    return 0


def _tokens_match_loose(term: str, token: str) -> int:
    """Rescue tier, used ONLY inside multi-word terms where every other word
    already matched strictly ("chain"/"channel" after "social" hit exactly).
    Alone it would drown a single-word term in near-misses."""
    got = _tokens_match(term, token)
    if got:
        return got
    if len(term) < 5 or len(token) < 5 or term[0] != token[0]:
        return 0
    if _common_prefix(term, token) >= 3 and _edit_distance(term, token, 3) <= 3:
        return PHONETIC
    return 0


class FuzzyMatcher:
    """Match multi-word terms against a token stream, token-bounded."""

    def __init__(self, terms: list[str]):
        self.terms = []
        for t in terms:
            words = [w for w in re.findall(r"[a-z0-9']+", t.lower()) if w]
            if words:
                self.terms.append((t, words))

    def hits(self, tokens: list[str]) -> list[tuple[str, str]]:
        """[(term, "strong" | "phonetic")], best strength per term."""
        found = []
        for original, words in self.terms:
            n = len(words)
            best = 0
            for i in range(len(tokens) - n + 1):
                strengths = [_tokens_match(w, tokens[i + k])
                             for k, w in enumerate(words)]
                if all(strengths):
                    best = max(best, min(strengths))
                elif n >= 2 and strengths.count(0) == 1:
                    # multi-word rescue: one mangled word among strong matches
                    k = strengths.index(0)
                    if (all(s == STRONG for j, s in enumerate(strengths)
                            if j != k)
                            and _tokens_match_loose(words[k], tokens[i + k])):
                        best = max(best, PHONETIC)
                if best == STRONG:
                    break
            if best:
                found.append((original,
                              "strong" if best == STRONG else "phonetic"))
        return found


def _window_tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


# --------------------------------------------------------------------------- #
# corpus + sponsor spans
# --------------------------------------------------------------------------- #
def load_corpus(path: pathlib.Path) -> list[dict]:
    videos = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                videos.append(json.loads(line))
    if not videos:
        sys.exit(f"empty corpus at {path}")
    return videos


def sponsor_segments(refs: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Spoken sponsored segments per video, batched over the whole corpus.

    Every mention is re-checked individually: only ``type == "sponsored"`` AND
    ``field == "transcript"`` counts, so an organic or description mention in
    the same video never poisons the span list. A query failure raises — it is
    never a silent empty span list.
    """
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for i in range(0, len(refs), IDS_CHUNK):
        chunk = refs[i:i + IDS_CHUNK]
        rows = tl_data.db_es({
            "size": len(chunk),
            "query": {"ids": {"values": chunk}},
            "_source": ["id", "brand_mentions"],
        })
        for row in rows:
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
                # (0, 0) is a detection with no located position; padded, it
                # would wrongly claim the opening of the video as an ad read.
                if start <= 0 and end <= 0:
                    continue
                out[str(row.get("id"))].append((float(start), float(end)))
    return dict(out)


def windows(cues: list) -> list[tuple[int, str]]:
    """Group cues into ~WINDOW_CHARS passages, keyed to the opening offset."""
    out, buf, start = [], [], None
    for cue in cues:
        offset, text = cue[0], (cue[1] or "").strip()
        if not text:
            continue
        if start is None:
            start = int(offset)
        buf.append(text)
        if sum(len(x) + 1 for x in buf) >= WINDOW_CHARS:
            out.append((start, " ".join(buf)))
            # one cue of overlap, so a sentence split at a boundary survives
            buf, start = [text], int(offset)
    if buf and start is not None:
        out.append((start, " ".join(buf)))
    return out


# --------------------------------------------------------------------------- #
# recurrence (attribution feature: guests change between uploads, the host
# does not — but recurrence alone must never confirm on a multi-host channel;
# that rule lives with the model, in references/evidence-rules.md)
# --------------------------------------------------------------------------- #
def _content_words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z']+", text.lower())
            if w not in _STOP and len(w) > 2]


def _phrases(text: str, n: int = 4) -> set[str]:
    words = _content_words(text)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def add_recurrence(cands: list[dict]) -> None:
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
        del c["_phrases"]


# --------------------------------------------------------------------------- #
# ranking — features order the read, they reject nothing
# --------------------------------------------------------------------------- #
def rank_score(c: dict) -> int:
    s = 2 * len(c["cues_fired"])
    if any(st == "strong" for _, st in c["entity_hits"]):
        s += 3
    elif c["entity_hits"]:
        s += 1              # phonetic-only: plausible mangling, ranked low
    if c["host_anchor"]:
        s += 2
    elif c["host_anchor_terms"]:
        s += 1
    if c["weak_anchor"]:
        s += 1
    if c["recurrence_videos"] >= 3:
        s += 1
    if c["stage_direction"]:
        s -= 2
    if c["boilerplate"]:
        s -= 3
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True,
                    help="path to corpus.jsonl from fetch_corpus.py")
    ap.add_argument("--host-terms", default="",
                    help="comma-separated facts distinctive to the host: "
                         "surname, companies, funds, a named former role. "
                         "Matched fuzzily, token-bounded.")
    ap.add_argument("--entity-terms", default="",
                    help="comma-separated entities already surfaced (family "
                         "names, pet names, brands) for the free local "
                         "re-scan; matched the same fuzzy way")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    a = ap.parse_args()

    corpus_path = pathlib.Path(a.corpus)
    out_dir = corpus_path.parent
    videos = load_corpus(corpus_path)

    host_terms = [t.strip() for t in a.host_terms.split(",") if t.strip()]
    entity_terms = [t.strip() for t in a.entity_terms.split(",") if t.strip()]
    host_m = FuzzyMatcher(host_terms)
    entity_m = FuzzyMatcher(entity_terms)

    with_transcript = [v for v in videos if v.get("cues")]
    segments = sponsor_segments([str(v["id"]) for v in with_transcript])

    kept, dropped_boiler, dropped_no_signal, total_windows = [], 0, 0, 0
    for v in with_transcript:
        ref = str(v["id"])
        vid = ref.split(":")[-1]
        segs = segments.get(ref, [])
        # Per-VIDEO format hint: one channel mixes formats, and a reaction or
        # collab upload on a solo channel must not inherit the solo rule.
        title_hint = next((fmt for fmt, rx in TITLE_SECOND_VOICE.items()
                           if v.get("title") and rx.search(v["title"])), None)
        for start, text in windows(v["cues"]):
            total_windows += 1
            tokens = _window_tokens(text)
            first_person = bool(FIRST_PERSON.search(text))
            host_hits = host_m.hits(tokens)
            ent_hits = entity_m.hits(tokens)
            if not first_person and not host_hits and not ent_hits:
                dropped_no_signal += 1
                continue
            cues_fired = [name for name, rx in DISCLOSURE if rx.search(text)]
            boiler = bool(BOILERPLATE.search(text))
            if boiler and not host_hits and not ent_hits:
                masked = BOILER_FP.sub(" ", BOILERPLATE.sub(" ", text))
                if not FIRST_PERSON.search(masked):
                    dropped_boiler += 1
                    continue
            kept.append({
                "id": ref,
                "video_id": vid,
                "title": v.get("title"),
                "format_hint": title_hint,
                "published": str(v.get("publication_date") or "")[:10],
                "start": start,
                "url": f"https://www.youtube.com/watch?v={vid}&t={start}s",
                "text": text,
                "cues_fired": cues_fired,
                # host_anchor (the attribution signal) requires a STRONG hit;
                # phonetic-only anchors stay visible in host_anchor_terms
                "host_anchor": any(st == "strong" for _, st in host_hits),
                "host_anchor_terms": host_hits,
                "entity_hits": ent_hits,
                "weak_anchor": bool(WEAK_ANCHOR.search(text)),
                "stage_direction": bool(STAGE.search(text)),
                "boilerplate": boiler,
                "in_sponsor_read": any(s - SPONSOR_PAD <= start <= e + SPONSOR_PAD
                                       for s, e in segs),
                "_phrases": _phrases(text),
            })

    add_recurrence(kept)
    for c in kept:
        c["rank_score"] = rank_score(c)
    kept.sort(key=lambda c: (-c["rank_score"], c["id"], c["start"]))

    with open(out_dir / "windows.jsonl", "w", encoding="utf-8") as f:
        for c in kept:
            f.write(json.dumps(c, default=str) + "\n")

    batch_dir = out_dir / "batches"
    batch_dir.mkdir(exist_ok=True)
    for old in batch_dir.glob("batch-*.json"):
        old.unlink()
    batch_paths = []
    for i in range(0, len(kept), a.batch_size):
        p = batch_dir / f"batch-{i // a.batch_size:03d}.json"
        p.write_text(json.dumps(kept[i:i + a.batch_size], default=str),
                     encoding="utf-8")
        batch_paths.append(str(p))

    print(json.dumps({
        "corpus": str(corpus_path),
        "videos": len(videos),
        "videos_with_transcript": len(with_transcript),
        "transcript_coverage": round(len(with_transcript) / len(videos), 2),
        "windows_total": total_windows,
        "windows_kept": len(kept),
        "kept_share": round(len(kept) / max(total_windows, 1), 2),
        "dropped_boilerplate_only": dropped_boiler,
        "dropped_no_first_person_no_entity": dropped_no_signal,
        "host_terms": host_terms,
        "entity_terms": entity_terms,
        "features": {
            "disclosure_cue": sum(1 for c in kept if c["cues_fired"]),
            "host_anchor": sum(1 for c in kept if c["host_anchor"]),
            "entity_hit": sum(1 for c in kept if c["entity_hits"]),
            "in_sponsor_read": sum(1 for c in kept if c["in_sponsor_read"]),
            "recurring_3plus": sum(1 for c in kept
                                   if c["recurrence_videos"] >= 3),
        },
        "windows_file": str(out_dir / "windows.jsonl"),
        "batches": batch_paths,
        "note": ("ranked recall pass, not a verdict; batches are rank-ordered "
                 "so early stopping loses the least-promising windows. The "
                 "features are model inputs, never gates."),
    }, indent=1, default=str))


if __name__ == "__main__":
    main()
