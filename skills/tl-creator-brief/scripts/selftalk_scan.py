#!/usr/bin/env python3
"""Generous local recall pass over a fetched corpus: rank windows, reject nothing.

Reads the local ``corpus.jsonl.gz`` written by ``fetch_corpus.py`` — never the
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
    selftalk_scan.py --corpus tl-creator-profiles/.corpus/<id>/corpus.jsonl.gz \\
        --host-terms "<surname>,<company>,<former role>"
    # after new entities surface ("my dog Luna"), re-scan locally — free:
    selftalk_scan.py --corpus ... --host-terms ... --entity-terms "Luna"

Output: ``windows.jsonl.gz`` (every kept window, ranked) and ``batches/*.json``
(rank-ordered ~50-window batches, capped at ``--max-windows`` for the model
layer, ready to fan out to classifier agents) next to the corpus, plus one
JSON summary on stdout. Raw transcript text stays in the files; only counts
and paths reach the orchestrator.
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import pathlib
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data
from channel_context import TITLE_SECOND_VOICE  # sibling script
from fetch_corpus import open_corpus, open_corpus_write  # sibling script

WINDOW_CHARS = 260
BATCH_SIZE = 50
MAX_MODEL_WINDOWS = 500    # ceiling on windows batched for the model layer
SPONSOR_PAD = 75      # an ad read runs past the seconds the detector flags
IDS_CHUNK = 1000
ES_CONCURRENCY = 4    # parallel id-chunk fetches for the sponsor-span lookup
MAX_WORKERS = 8       # ceiling on scan processes; env var overrides
WORKERS_ENV = "CREATOR_BRIEF_SCAN_WORKERS"
MIN_CHUNK_VIDEOS = 100    # coarse tasks: per-window IPC would cost more than
#                           the parallelism buys back
MIN_CHUNK_ENV = "CREATOR_BRIEF_SCAN_MIN_CHUNK"   # lower it to exercise the pool
#                                                  on a small corpus

# Every lexicon pattern below is all-lower-case and is matched against the
# window's lower-cased text, never the raw text — the same lower-casing the
# tokenizer already does, done once per window and shared. Case-insensitive
# matching over mixed-case text costs about twice as much for exactly the same
# answers, so the fold happens once instead of inside every scan.
TOKEN_RE = re.compile(r"[\w']+")

FIRST_PERSON = re.compile(r"\b(i|i'm|im|i've|i'd|i'll|my|me|myself|mine|we|our)\b")

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
        r"i('ve| have) always|i never went|allergic|diagnosed|obsessed with)\b")),
    ("own_life", re.compile(
        r"\bmy (dad|mum|mom|father|mother|parents|wife|husband|partner|"
        r"girlfriend|boyfriend|kid|kids|son|daughter|child|children|brother|"
        r"sister|family|dog|cat|pet|house|home|flat|hometown|school|"
        r"university|college|degree|company|business|agency|startup|team|"
        r"job|career|routine|morning|diet|training|therapist|doctor|"
        r"podcast|studio|office|book|friend|best friend|nursery|garden|"
        r"hobby|hobbies|collection|setup|gym|workout|"
        r"favou?rite (food|meal|snack|dish|game|band|movie|show|team)|"
        r"comfort food|go-?to (order|meal|snack)|guitar|piano)\b")),
    ("self_characterisation", re.compile(
        r"\b(i consider myself|i see myself|i'?m the kind of|i'?m the type of|"
        r"i'?ve always been|i'?m not really a|i tend to|my favou?rite|"
        r"i'?m terrible at|i can'?t stand|i genuinely (love|hate)|"
        r"i'?m a big fan of|personally i|for me personally)\b")),
]

# First-person talk about running a show or a business: often the host,
# frequently whoever else shares the transcript. A half-signal for ranking.
WEAK_ANCHOR = re.compile(
    r"\b(my|our) (podcast|show|channel|company|business|agency|startup|fund|"
    r"team|book|brand|investors|co-?founder|business partner)\b")

# Stage directions and opinion framing: rank DOWN, never drop. "as I said, my
# dad ran a bakery" must survive; the model sorts it out.
STAGE = re.compile(
    r"\b(i'?ll show you|let me show|i'?m going to (show|explain|walk)|"
    r"in this video|in today'?s video|before we (start|begin|get into)|"
    r"let'?s (get|jump|dive)|stay tuned|coming up)\b")

# The only hard drop, and only when the window's first-person content IS the
# boilerplate: both patterns are masked out and the remainder re-tested, so
# "I live in London, and remember to subscribe" survives.
BOILERPLATE = re.compile(
    r"\b(subscribe|smash th(e|at) like|link (in|below)|link in the "
    r"description|notification bell|comment below|patreon|join the channel)\b")
BOILER_FP = re.compile(
    r"\b(my|our) (channel|patreon|newsletter|merch|videos?|links?|discord|"
    r"instagram|twitter)\b")

# Cheap prefilters. Semantically pure "does ANY of the group fire?" unions of
# the patterns above: the vast majority of windows fire none of them, so one
# combined scan replaces five. When a union hits, the individual patterns are
# re-run to get the exact per-feature answer — the features themselves are
# unchanged.
ANY_DISCLOSURE = re.compile(
    "|".join(f"(?:{rx.pattern})" for _, rx in DISCLOSURE))
ANY_MISC = re.compile(
    "|".join(f"(?:{rx.pattern})"
             for rx in (WEAK_ANCHOR, STAGE, BOILERPLATE)))

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
    """Match multi-word terms against a token stream, token-bounded.

    Every comparison is memoised per (term word, corpus token): the corpus
    vocabulary is finite, so each distinct pair pays for the edit-distance /
    soundex work exactly once, however many windows repeat it. Single-word
    terms take a set-algebra fast path — after warm-up their answer is three
    C-level set operations, no per-token Python loop and no n-gram slide.
    """

    def __init__(self, terms: list[str]):
        self.terms = []
        for t in terms:
            words = [w for w in re.findall(r"[\w']+", t.lower()) if w]
            if words:
                self.terms.append((t, words))
        # single-word memo: word -> (tokens already judged, strong, phonetic)
        self._seen: dict[str, set[str]] = {}
        self._strong: dict[str, set[str]] = {}
        self._phonetic: dict[str, set[str]] = {}
        # multi-word memos: word -> {token: strength}
        self._strict: dict[str, dict[str, int]] = {}
        self._loose: dict[str, dict[str, int]] = {}
        for _, words in self.terms:
            for w in words:
                self._seen.setdefault(w, set())
                self._strong.setdefault(w, set())
                self._phonetic.setdefault(w, set())
                self._strict.setdefault(w, {})
                self._loose.setdefault(w, {})

    def _strict_hit(self, word: str, token: str) -> int:
        cache = self._strict[word]
        got = cache.get(token, -1)
        if got < 0:
            got = cache[token] = _tokens_match(word, token)
        return got

    def _loose_hit(self, word: str, token: str) -> int:
        cache = self._loose[word]
        got = cache.get(token, -1)
        if got < 0:
            got = cache[token] = _tokens_match_loose(word, token)
        return got

    def _single(self, word: str, token_set: set[str]) -> int:
        seen = self._seen[word]
        fresh = token_set - seen
        if fresh:
            strong, phonetic = self._strong[word], self._phonetic[word]
            for token in fresh:
                got = _tokens_match(word, token)
                if got == STRONG:
                    strong.add(token)
                elif got:
                    phonetic.add(token)
            seen |= fresh
        if not token_set.isdisjoint(self._strong[word]):
            return STRONG
        if not token_set.isdisjoint(self._phonetic[word]):
            return PHONETIC
        return 0

    def hits(self, tokens: list[str],
             token_set: set[str] | None = None) -> list[tuple[str, str]]:
        """[(term, "strong" | "phonetic")], best strength per term.

        ``token_set`` is an optional caller-supplied ``set(tokens)``; passing
        the set the caller already built avoids rebuilding it per matcher.
        """
        if not self.terms:
            return []
        if token_set is None:
            token_set = set(tokens)
        found = []
        for original, words in self.terms:
            n = len(words)
            if n == 1:
                best = self._single(words[0], token_set)
            else:
                best = 0
                for i in range(len(tokens) - n + 1):
                    strengths = [self._strict_hit(w, tokens[i + k])
                                 for k, w in enumerate(words)]
                    if all(strengths):
                        best = max(best, min(strengths))
                    elif strengths.count(0) == 1:
                        # multi-word rescue: one mangled word among strong ones
                        k = strengths.index(0)
                        if (all(s == STRONG for j, s in enumerate(strengths)
                                if j != k)
                                and self._loose_hit(words[k], tokens[i + k])):
                            best = max(best, PHONETIC)
                    if best == STRONG:
                        break
            if best:
                found.append((original,
                              "strong" if best == STRONG else "phonetic"))
        return found


def _window_tokens(text: str) -> list[str]:
    # \w is Unicode-aware: accented names and non-Latin scripts tokenize
    # instead of being silently stripped.
    return TOKEN_RE.findall(text.lower())


# --------------------------------------------------------------------------- #
# corpus + sponsor spans
# --------------------------------------------------------------------------- #
def load_corpus(path: pathlib.Path) -> list[dict]:
    videos = []
    with open_corpus(path) as f:
        for line in f:
            line = line.strip()
            if line:
                videos.append(json.loads(line))
    if not videos:
        sys.exit(f"empty corpus at {path}")
    return videos


def _sponsor_chunk(chunk: list[str]) -> dict[str, list[tuple[float, float]]]:
    """One id-chunk's spans. Any query failure propagates to the caller."""
    rows = tl_data.db_es({
        "size": len(chunk),
        "query": {"ids": {"values": chunk}},
        "_source": ["id", "brand_mentions"],
    })
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
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
    return out


def sponsor_segments(refs: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Spoken sponsored segments per video, batched over the whole corpus.

    Every mention is re-checked individually: only ``type == "sponsored"`` AND
    ``field == "transcript"`` counts, so an organic or description mention in
    the same video never poisons the span list. A query failure raises — it is
    never a silent empty span list.

    Id chunks are fetched concurrently, but merged strictly in chunk order and
    a video's ids never straddle two chunks, so the resulting span lists are
    the same lists in the same order as a serial fetch.
    """
    chunks = [refs[i:i + IDS_CHUNK] for i in range(0, len(refs), IDS_CHUNK)]
    if not chunks:
        return {}
    out: dict[str, list[tuple[float, float]]] = defaultdict(list)
    with ThreadPoolExecutor(max_workers=min(ES_CONCURRENCY,
                                            len(chunks))) as pool:
        for part in pool.map(_sponsor_chunk, chunks):
            for ref, spans in part.items():
                out[ref].extend(spans)
    return dict(out)


def _fetch_segments(refs: list[str], holder: dict) -> None:
    """Thread body: stash the spans, or the failure, for the parent to see.

    The parent re-raises whatever landed here, so an index failure is still
    loud — it never degrades into a silently empty span list.
    """
    try:
        holder["segments"] = sponsor_segments(refs)
    except BaseException as exc:              # noqa: BLE001 — re-raised below
        holder["error"] = exc


def apply_sponsor_reads(
        kept: list[dict],
        segments: dict[str, list[tuple[float, float]]]) -> None:
    """Fill in the per-window ``in_sponsor_read`` flag once spans have landed.

    Windows are built with the flag already present (and False), so writing it
    here overwrites in place and leaves the key order untouched.
    """
    if not segments:
        return
    for c in kept:
        segs = segments.get(c["id"])
        if not segs:
            continue
        start = c["start"]
        c["in_sponsor_read"] = any(s - SPONSOR_PAD <= start <= e + SPONSOR_PAD
                                   for s, e in segs)


def windows(cues: list) -> list[tuple[int, str]]:
    """Group cues into ~WINDOW_CHARS passages, keyed to the opening offset."""
    out, buf, start = [], [], None
    held = 0          # running sum(len(x) + 1 for x in buf), kept incremental
    for cue in cues:
        offset, text = cue[0], (cue[1] or "").strip()
        if not text:
            continue
        if start is None:
            start = int(offset)
        buf.append(text)
        held += len(text) + 1
        if held >= WINDOW_CHARS:
            out.append((start, " ".join(buf)))
            # one cue of overlap, so a sentence split at a boundary survives
            buf, start = [text], int(offset)
            held = len(text) + 1
    if buf and start is not None:
        out.append((start, " ".join(buf)))
    return out


# --------------------------------------------------------------------------- #
# recurrence (attribution feature: guests change between uploads, the host
# does not — but recurrence alone must never confirm on a multi-host channel;
# that rule lives with the model, in references/evidence-rules.md)
# --------------------------------------------------------------------------- #
def _filter_content(tokens: list[str]) -> list[str]:
    """Content words, filtered out of a window's existing token list.

    The tokenizer and this filter read the same lower-cased text through the
    same regex, so a window's content words are just its tokens minus the
    stop, short and numeric ones — there is never a second pass over the text.
    """
    return [w for w in tokens
            if len(w) > 2 and w not in _STOP and not w.isdigit()]


def _phrase_list(words: list[str], n: int = 4) -> list[str]:
    return [" ".join(words[i:i + n]) for i in range(len(words) - n + 1)]


def add_recurrence(cands: list[dict]) -> None:
    """Attach cross-video phrase recurrence, from each window's cached tokens.

    Candidates arrive carrying ``_content`` (their content words, derived from
    the tokens the scan already produced); this consumes and removes it. The
    n-gram keys stay the same joined strings the phrase set has always used
    and ``recurring_phrase`` is emitted verbatim; between phrases recurring in
    equally many videos, the lexicographically smallest one wins — a fixed
    rule, because set iteration order is hash-seed dependent.

    This runs in the parent, over the merged candidate list, precisely because
    it is the one cross-video step: a worker only ever sees its own slice.
    """
    # Both tallies are per VIDEO, so words and phrases are folded into one bag
    # per video first and counted once each — a phrase repeated across fifty
    # windows of the same upload is one video either way, and this way it costs
    # one increment instead of fifty.
    video_words: dict[str, set[str]] = {}
    video_phrases: dict[str, set[str]] = {}
    phrase_sets: list[set[str]] = []
    for c in cands:
        words = c.pop("_content")
        ref = c["id"]
        bag = video_words.get(ref)
        if bag is None:
            bag = video_words[ref] = set()
        bag.update(words)
        unique = set()
        for ph in _phrase_list(words):
            unique.add(ph)
        phrase_sets.append(unique)
        bag = video_phrases.get(ref)
        if bag is None:
            bag = video_phrases[ref] = set()
        bag |= unique

    ceiling = max(1, int(len(video_words) * RARE_SHARE))
    word_videos: dict[str, int] = defaultdict(int)
    for bag in video_words.values():
        for w in bag:
            word_videos[w] += 1
    rare = {w for w, seen in word_videos.items() if seen <= ceiling}

    phrase_videos: dict[str, int] = defaultdict(int)
    for bag in video_phrases.values():
        for ph in bag:
            phrase_videos[ph] += 1
    # A phrase has to clear BOTH bars — seen in more than one video, and
    # carrying a rare word — and the one-video majority fails the first bar,
    # so the distinctiveness test only ever runs on the survivors. The
    # surviving table is the only one the per-window loop consults.
    recurring = {ph: seen for ph, seen in phrase_videos.items()
                 if seen > 1 and not rare.isdisjoint(ph.split())}
    recurring_keys = set(recurring)

    for c, unique in zip(cands, phrase_sets):
        best, best_ph = 1, None
        if not unique.isdisjoint(recurring_keys):
            for ph in unique:
                seen = recurring.get(ph)
                if seen is None:
                    continue
                # Ties are broken lexicographically, NOT by whichever phrase
                # the set happened to yield first: set iteration order depends
                # on the hash seed, so the old "first one wins" made
                # recurring_phrase differ between runs of the same corpus.
                if seen > best or (seen == best and best_ph is not None
                                   and ph < best_ph):
                    best, best_ph = seen, ph
        c["recurrence_videos"] = best
        c["recurring_phrase"] = best_ph


# --------------------------------------------------------------------------- #
# the scan itself — pure per-video work, so it parallelises across processes
# --------------------------------------------------------------------------- #
def scan_videos(videos: list[dict], host_m: "FuzzyMatcher",
                entity_m: "FuzzyMatcher", lexicon_mode: str) -> tuple:
    """Window + feature one slice of the corpus.

    Depends on nothing but its arguments, so the same slice always yields the
    same windows in the same order whether it ran here or in a worker.
    ``in_sponsor_read`` is left False and filled in by
    ``apply_sponsor_reads`` once the sponsor-span fetch has landed.

    Returns ``(kept, dropped_boilerplate, dropped_no_signal, windows_seen)``.
    """
    kept: list[dict] = []
    dropped_boiler = dropped_no_signal = total_windows = 0
    for v in videos:
        ref = str(v["id"])
        vid = ref.split(":")[-1]
        # Per-VIDEO format hint: one channel mixes formats, and a reaction or
        # collab upload on a solo channel must not inherit the solo rule.
        title_hint = next((fmt for fmt, rx in TITLE_SECOND_VOICE.items()
                           if v.get("title") and rx.search(v["title"])), None)
        # The recall lexicons are English. A non-English video gets NO
        # lexical gating — every window goes to the (multilingual) model
        # layer, because Spanish pro-drop or Japanese subject omission means
        # an English-shaped pronoun regex finds nothing to anchor on. An
        # absent language (older corpus) keeps the English path.
        lang = str(v.get("transcript_language") or "").lower()
        lexical = (lexicon_mode == "on"
                   or (lexicon_mode == "auto"
                       and (not lang or lang.startswith("en"))))
        title = v.get("title")
        published = str(v.get("publication_date") or "")[:10]
        for start, text in windows(v["cues"]):
            total_windows += 1
            # One lower-casing and one tokenisation per window, shared by the
            # lexicons, both matchers, and the recurrence features.
            low = text.lower()
            tokens = TOKEN_RE.findall(low)
            token_set = set(tokens)
            first_person = bool(FIRST_PERSON.search(low))
            host_hits = host_m.hits(tokens, token_set)
            ent_hits = entity_m.hits(tokens, token_set)
            if lexical and not first_person and not host_hits and not ent_hits:
                dropped_no_signal += 1
                continue
            if ANY_DISCLOSURE.search(low):
                cues_fired = [name for name, rx in DISCLOSURE
                              if rx.search(low)]
            else:
                cues_fired = []
            if ANY_MISC.search(low):
                boiler = bool(BOILERPLATE.search(low))
                weak = bool(WEAK_ANCHOR.search(low))
                stage = bool(STAGE.search(low))
            else:
                boiler = weak = stage = False
            if lexical and boiler and not host_hits and not ent_hits:
                masked = BOILER_FP.sub(" ", BOILERPLATE.sub(" ", low))
                if not FIRST_PERSON.search(masked):
                    dropped_boiler += 1
                    continue
            kept.append({
                "id": ref,
                "video_id": vid,
                "title": title,
                "language": lang or None,
                "format_hint": title_hint,
                "published": published,
                "start": start,
                # No stored url: it is exactly f(video_id, start), and a big
                # channel would carry half a million copies of a string every
                # consumer can build. Whoever SHOWS a window builds the link
                # then — and a verified quote builds it from the timestamp
                # verification located, which is not always this one.
                "text": text,
                "cues_fired": cues_fired,
                # host_anchor (the attribution signal) requires a STRONG hit;
                # phonetic-only anchors stay visible in host_anchor_terms
                "host_anchor": any(st == "strong" for _, st in host_hits),
                "host_anchor_terms": host_hits,
                "entity_hits": ent_hits,
                "weak_anchor": weak,
                "stage_direction": stage,
                "boilerplate": boiler,
                "in_sponsor_read": False,
                "_content": _filter_content(tokens),
            })
    return kept, dropped_boiler, dropped_no_signal, total_windows


_WORKER: dict = {}


def _worker_init(host_terms: list[str], entity_terms: list[str],
                 lexicon_mode: str) -> None:
    _WORKER["host_m"] = FuzzyMatcher(host_terms)
    _WORKER["entity_m"] = FuzzyMatcher(entity_terms)
    _WORKER["lexicon"] = lexicon_mode


def _scan_task(videos: list[dict]) -> tuple:
    return scan_videos(videos, _WORKER["host_m"], _WORKER["entity_m"],
                       _WORKER["lexicon"])


def _env_int(name: str) -> int:
    """A positive integer from the environment, or 0 when unset/unusable."""
    raw = (os.environ.get(name) or "").strip()
    if raw:
        try:
            asked = int(raw)
        except ValueError:
            return 0
        if asked > 0:
            return asked
    return 0


def worker_count() -> int:
    """Scan processes to use. ``CREATOR_BRIEF_SCAN_WORKERS=1`` forces serial."""
    return _env_int(WORKERS_ENV) or min(MAX_WORKERS, os.cpu_count() or 1)


def min_chunk_videos() -> int:
    """Videos per scan task floor. ``CREATOR_BRIEF_SCAN_MIN_CHUNK`` overrides
    it, the same way ``CREATOR_BRIEF_SCAN_WORKERS`` overrides the worker
    count, so a small corpus can still be run through the pool."""
    return _env_int(MIN_CHUNK_ENV) or MIN_CHUNK_VIDEOS


def _video_chunks(videos: list[dict], workers: int) -> list[list[dict]]:
    """Coarse tasks: a few per worker, never fewer than MIN_CHUNK_VIDEOS
    videos each, so pickling the results stays a small share of the work."""
    per = max(min_chunk_videos(), -(-len(videos) // (workers * 4)))
    return [videos[i:i + per] for i in range(0, len(videos), per)]


def scan_corpus(videos: list[dict], host_terms: list[str],
                entity_terms: list[str], lexicon_mode: str) -> tuple:
    """Scan every video, in parallel when it is worth it.

    Chunks are merged in submission order and each chunk is scanned exactly as
    the serial path would scan it, so the parallel result is identical to the
    serial one, window for window. If the pool cannot start, this falls back
    to the serial path rather than failing the run.

    Returns the four scan counters plus the number of chunks the pool actually
    ran — 0 whenever the scan stayed serial, so the run summary (and the test
    that compares the two paths) can tell which path produced the windows.
    """
    workers = worker_count()
    chunks = _video_chunks(videos, workers) if workers > 1 else []
    if len(chunks) > 1:
        try:
            ctx = multiprocessing.get_context("spawn")
            with ctx.Pool(min(workers, len(chunks)), initializer=_worker_init,
                          initargs=(host_terms, entity_terms,
                                    lexicon_mode)) as pool:
                parts = pool.map(_scan_task, chunks, chunksize=1)
        except (OSError, ValueError, ImportError,
                multiprocessing.ProcessError) as exc:
            print(f"scan: worker pool unavailable ({exc}); running serially",
                  file=sys.stderr)
        else:
            kept: list[dict] = []
            boiler = no_signal = total = 0
            for part_kept, part_boiler, part_no_signal, part_total in parts:
                kept.extend(part_kept)
                boiler += part_boiler
                no_signal += part_no_signal
                total += part_total
            return kept, boiler, no_signal, total, len(chunks)
    return scan_videos(videos, FuzzyMatcher(host_terms),
                       FuzzyMatcher(entity_terms), lexicon_mode) + (0,)


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


def is_lexical(window: dict, lexicon_mode: str) -> bool:
    """Did the English recall lexicons rank (and gate) this window?"""
    lang = window.get("language") or ""
    return (lexicon_mode == "on"
            or (lexicon_mode == "auto"
                and (not lang or lang.startswith("en"))))


def select_batched(kept: list[dict], max_windows: int,
                   lexicon_mode: str) -> list[dict]:
    """The model-layer budget, applied to a rank-sorted ``kept`` list.

    ``windows.jsonl.gz`` keeps the full recall record (free, local, re-scannable),
    but only up to ``max_windows`` go out to the classifier. Lexicon-ranked
    windows compete on score; the unranked pool — windows the English lexicons
    never scored (non-English under auto, everything under ``--lexicon off``),
    which sort in chronological order — is sampled at an even stride so the
    batched set still spans the channel's whole history instead of one end of
    it.

    The split is by lexical status, NOT by score sign: an English window
    scoring 0 was ranked (low) and must never displace top-scored windows via
    the stride. Splitting on the sign is the regression this function exists
    to hold — it let a flood of zero-score windows crowd the real gems out of
    the batches.
    """
    if not 0 < max_windows < len(kept):
        return kept
    ranked = [c for c in kept if is_lexical(c, lexicon_mode)]
    unranked = [c for c in kept if not is_lexical(c, lexicon_mode)]
    q_ranked = min(len(ranked), round(max_windows * len(ranked) / len(kept)))
    q_unranked = min(len(unranked), max_windows - q_ranked)
    q_ranked = min(len(ranked), max_windows - q_unranked)
    take_unranked = unranked
    if len(unranked) > q_unranked:
        # Stride over publication order, not list order — the kept sort is
        # (-rank_score, id, start) and video ids are arbitrary, so only a
        # date-ordered pool actually spans the channel's history.
        pool = sorted(unranked, key=lambda c: (c["published"], c["id"],
                                               c["start"]))
        step = len(pool) / max(q_unranked, 1)
        take_unranked = [pool[int(i * step)] for i in range(q_unranked)]
    return ranked[:q_ranked] + take_unranked


def funnel(**fields) -> None:
    """One machine-parseable stage line for the run report (stderr)."""
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def main() -> None:
    started = time.monotonic()
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", required=True,
                    help="path to corpus.jsonl.gz from fetch_corpus.py "
                         "(a plain .jsonl corpus is read too)")
    ap.add_argument("--host-terms", default="",
                    help="comma-separated facts distinctive to the host: "
                         "surname, companies, funds, a named former role. "
                         "Matched fuzzily, token-bounded.")
    ap.add_argument("--entity-terms", default="",
                    help="comma-separated entities already surfaced (family "
                         "names, pet names, brands) for the free local "
                         "re-scan; matched the same fuzzy way")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    ap.add_argument("--max-windows", type=int, default=MAX_MODEL_WINDOWS,
                    help="ceiling on windows written to batch files for the "
                         "model layer (0 = uncapped). windows.jsonl.gz always "
                         "keeps everything; past the cap, ranked windows "
                         "keep their top scores and unranked (non-English) "
                         "windows are sampled evenly across the channel's "
                         "history rather than truncated at one end")
    ap.add_argument("--lexicon", choices=["auto", "on", "off"], default="auto",
                    help="auto (default): apply the English recall lexicons "
                         "only to English-language videos and keep every "
                         "window of other languages for the model layer; "
                         "on/off force one path for the whole corpus")
    a = ap.parse_args()

    corpus_path = pathlib.Path(a.corpus)
    out_dir = corpus_path.parent
    videos = load_corpus(corpus_path)

    host_terms = [t.strip() for t in a.host_terms.split(",") if t.strip()]
    entity_terms = [t.strip() for t in a.entity_terms.split(",") if t.strip()]
    with_transcript = [v for v in videos if v.get("cues")]

    # The sponsor-span lookup is network-bound and the scan is CPU-bound, so
    # the fetch runs alongside the scan and is joined before any window is
    # finalised. A failure in there is re-raised here — never swallowed.
    seg_holder: dict = {}
    seg_thread = threading.Thread(
        target=_fetch_segments,
        args=([str(v["id"]) for v in with_transcript], seg_holder),
        daemon=True)
    seg_thread.start()

    lang_counts: dict[str, int] = defaultdict(int)
    for v in with_transcript:
        lang_counts[str(v.get("transcript_language") or "unknown").lower()] += 1

    (kept, dropped_boiler, dropped_no_signal, total_windows,
     parallel_chunks) = scan_corpus(with_transcript, host_terms, entity_terms,
                                    a.lexicon)

    seg_thread.join()
    if "error" in seg_holder:
        raise seg_holder["error"]
    apply_sponsor_reads(kept, seg_holder.get("segments") or {})

    add_recurrence(kept)
    for c in kept:
        c["rank_score"] = rank_score(c)
    kept.sort(key=lambda c: (-c["rank_score"], c["id"], c["start"]))

    windows_file = out_dir / "windows.jsonl.gz"
    with open_corpus_write(windows_file) as f:
        for c in kept:
            f.write(json.dumps(c, default=str) + "\n")

    # Model-layer budget — see select_batched() for the rule and the
    # score-sign regression it guards.
    batched = select_batched(kept, a.max_windows, a.lexicon)

    batch_dir = out_dir / "batches"
    batch_dir.mkdir(exist_ok=True)
    for old in batch_dir.glob("batch-*.json"):
        old.unlink()
    batch_paths = []
    for i in range(0, len(batched), a.batch_size):
        p = batch_dir / f"batch-{i // a.batch_size:03d}.json"
        p.write_text(json.dumps(batched[i:i + a.batch_size], default=str),
                     encoding="utf-8")
        batch_paths.append(str(p))

    elapsed = round(time.monotonic() - started, 1)
    print(json.dumps({
        "corpus": str(corpus_path),
        "elapsed_s": elapsed,
        "videos": len(videos),
        "videos_with_transcript": len(with_transcript),
        "transcript_coverage": round(len(with_transcript) / len(videos), 2),
        "windows_total": total_windows,
        "windows_kept": len(kept),
        "kept_share": round(len(kept) / max(total_windows, 1), 2),
        "windows_batched": len(batched),
        "windows_over_cap": len(kept) - len(batched),
        "max_windows": a.max_windows,
        "dropped_boilerplate_only": dropped_boiler,
        "dropped_no_first_person_no_entity": dropped_no_signal,
        "lexicon_mode": a.lexicon,
        "languages": dict(sorted(lang_counts.items(),
                                 key=lambda kv: -kv[1])),
        "non_english_windows_kept": sum(
            1 for c in kept
            if c["language"] and not c["language"].startswith("en")),
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
        "windows_file": str(windows_file),
        "batches": batch_paths,
        # how the scan ran, not what it found: 0 means the serial path
        "parallel_chunks": parallel_chunks,
        "note": ("ranked recall pass, not a verdict; batches are rank-ordered "
                 "so early stopping loses the least-promising windows. The "
                 "features are model inputs, never gates. Batches are already "
                 "capped at max_windows (ranked windows keep top scores, "
                 "unranked non-English windows are stride-sampled across the "
                 "channel's history); windows_over_cap says what stayed "
                 "local, in windows.jsonl.gz, uninspected."),
    }, indent=1, default=str))
    funnel(stage="scan", windows_total=total_windows, windows_kept=len(kept),
           windows_capped=len(batched),
           windows_over_cap=len(kept) - len(batched),
           batches=len(batch_paths), elapsed_s=elapsed)


if __name__ == "__main__":
    main()
