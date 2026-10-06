#!/usr/bin/env python3
"""Assemble extractor output files into the classified record, the gem list
and the candidate facts, validating the contract mechanically.

Each extractor agent produces ``<returns>/batch-NNN.extract.json``:
    {"batch": "NNN", "windows": N,
     "gems":     [{"i", "start", "anchor", "life_domain", "speaker_guess",
                   "speaker_evidence", "entity_corrections", "notable", "claim",
                   "quote_span": {"first", "last"}, "confidence"}],
     "not_gems": [{"i", "speaker_guess", "reason"}]}

Checks per batch: every index 0..N-1 exactly once; ``start`` and ``anchor``
match the window they claim (``start`` is a hard check; the five-word anchor
is advisory because extractors normalise punctuation); enums valid; the quote
span resolves to a contiguous 4-45-word substring of the window text, which
is cut mechanically so every quote is verbatim by construction, then extended
to the end of its caption line when it stopped inside one (``corpus.jsonl.gz``
beside ``--out``); the claim must say only what the quote says (every name,
number and family word of the claim is in the quote, a family word as the
creator's own relative), or the gem is refused and reported under
``claims_refused_overreach``; a ``likely`` with no named reason in
``speaker_evidence`` is read as ``confirmed``; ``people`` keeps only names the
quote holds. The extractor
does not tier sensitivity: every gem gets a keyword ``sensitivity`` hint here
(``tier_hint.py``, ``sensitivity_source: "heuristic"``), which the merge pass
owns from then on; a tier an old-schema extractor did send is validated and
kept (``sensitivity_source: "extractor"``). Windows an
extractor skipped, or whose verdict failed a check, are **unjudged**: they
stay out of every output file (so a later ``--exclude`` round can still pick
them up) and are listed in ``respawn.json`` in case a caller wants to
re-judge exactly those; nothing is hand-patched.

Usage: assemble_extracts.py --batches <dir> --returns <dir> --out <dir>
                            [--append] [--min-coverage 0.95]
Exit 0 when the assembled share of the expected windows is at least
``--min-coverage`` (a few unjudged windows are accepted and reported as
``unjudged=N``); exit 3 below the threshold, or whenever a batch file has no
return file at all (an extractor that never ran, not a few bad verdicts).
A batch may have several return files (the original plus subset re-judges
named batch-NNN.extract.r2.json …); later files override the indexes they
carry. ``--append`` adds a later round's rows to the existing files, replacing
any earlier rows for the same windows, so re-assembling a round after a
re-judge never stacks a second copy of its gems.
Outputs in <out>: classified.jsonl, gems.jsonl (cluster_gems.py input),
candidates.jsonl (verify_quotes.py input), respawn.json, one FUNNEL line.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import pathlib
import re
import sys
import time
from collections import Counter

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tier_hint  # noqa: E402  sibling: the keyword sensitivity hint
from store_io import open_corpus  # noqa: E402  sibling: the corpus reader

DOMAINS = {"origin", "family", "pets", "home", "work", "money", "health", "habits",
           "tastes", "beliefs", "relationships", "other"}
# `shared` is a "we" line about the hosts' shared life on a multi-host channel
SPEAKERS = {"host", "guest", "cohost", "shared", "narration", "unclear"}
KEPT_SPEAKERS = ("host", "cohost", "shared", "unclear")     # whose gems reach the ledger
SENSITIVITY = {"none", "lifestyle", "clinical", "children", "location"}
WITHHELD = {"clinical", "children", "location"}   # excluded from connection angles by default
DEFAULT_MIN_COVERAGE = 0.95
# A `likely` verdict needs one of these reasons in `speaker_evidence`
# (extractor-rubric.md, `confidence`); any other `likely` reads as confirmed.
LIKELY_REASONS = ("staged", "premise", "contradict", "doubt", "unsure",
                  "ambiguous", "cannot place", "unclear")
# A family word in a claim must be in the quote as the creator's own relative;
# each group is one relative under its spoken names.
FAMILY_GROUPS = (
    ("mom", "mum", "mother", "mama", "momma", "mommy"),
    ("dad", "father", "papa", "daddy"),
    ("parent", "parents"),
    ("brother",), ("sister",),
    ("grandma", "grandmother", "nana", "granny", "gran"),
    ("grandpa", "grandfather", "granddad", "gramps"),
    ("wife",), ("husband",), ("girlfriend",), ("boyfriend",),
    ("fiance", "fiancé", "fiancee", "fiancée"), ("partner",), ("spouse",),
    ("cousin",), ("son",), ("daughter",), ("kids", "children"),
    ("aunt", "auntie"), ("uncle",), ("nephew",), ("niece",),
)
FAMILY_WORDS = {w: group[0] for group in FAMILY_GROUPS for w in group}
_OWN = re.compile(r"\b(?:my|our)\s+(\w+)(?:\s+(\w+))?(?:\s+(\w+))?(?:\s+(\w+))?")
_OWN_STOP = {"and", "or", "but", "with", "his", "her", "their", "your", "the", "a", "an"}
_OTHERS = re.compile(r"\b(?:his|her|their|your)\s+(\w+)(?:\s+(\w+))?(?:\s+(\w+))?")
_CAP = re.compile(r"\b[A-Z][a-zA-Z'’-]{2,}\b")
_NUM = re.compile(r"(\d+(?:[.,]\d+)*)(s\b)?")     # "30s" is a decade, not 30
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+")
# a number the captions spell out: "three kids", "in his thirties". Never
# "one", which is as often a pronoun ("no one", "one of my kids").
_NUM_WORDS = {w: str(n) for n, w in enumerate(
    "two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split(), start=2)}
_NUM_WORDS.update({w: str(n) for n, w in zip(range(30, 100, 10),
                  "thirty forty fifty sixty seventy eighty ninety".split())})
_NUM_WORDS.update({w[:-1] + "ies": n + "s" for w, n in list(_NUM_WORDS.items())
                   if w.endswith("ty")})
_NOT_NAMES = {"The", "She", "He", "They", "Her", "His", "Their", "YouTube", "Instagram",
              "TikTok", "Facebook", "Twitter", "Christmas", "Sunday", "Monday", "Tuesday",
              "Wednesday", "Thursday", "Friday", "Saturday", "January", "February",
              "March", "April", "June", "July", "August", "September", "October",
              "November", "December"}
_SENTENCE_END = re.compile(r"[.!?]")
# timed-text markup the caption parser sometimes leaves inside a line
_CAPTION_TAG = re.compile(r'</?\w+[^>]*>|\btext start="[^"]*"(?:\s+dur="[^"]*")?>?')


def _lc(text: str) -> str:
    return re.sub(r"[^\w\s]", "", (text or "").lower())


def bare_words(text: str) -> set[str]:
    """Lowercase words with a possessive "'s" and punctuation dropped."""
    return {_lc(re.sub(r"['’]s$", "", w)) for w in (text or "").split()} - {""}


def word_in(word: str, words: set[str]) -> bool:
    """A claim word is in the quote when the two are equal without a
    possessive "'s", or when one starts with the other and the shorter has at
    least 5 letters ("Czechoslovak" and "czechoslovakia"; "Eric" and "Erica"
    never)."""
    w = _lc(re.sub(r"['’]s$", "", word or ""))
    if not w:
        return True
    return any(w == q or (min(len(w), len(q)) >= 5 and (w.startswith(q) or q.startswith(w)))
               for q in words)


# a relative the claim gives to another relative ("his brother's wife", "a
# brother who has a wife") belongs to that relative, not to the creator
_RELATIVES_OF = re.compile(r"\b(\w+)(?:['’]s|\s+who\s+has(?:\s+an?)?)\s+(\w+)")


def is_english(window: dict | None) -> bool:
    """The window's captions are English (a blank language counts as English)."""
    return str((window or {}).get("language") or "en").lower().startswith("en")


def claim_numbers(text: str) -> list[tuple[str, str]]:
    """``(as written, comparison key)`` per number: thousands commas dropped
    ("1,000" is "1000"), a decade keeps its "s" ("30s")."""
    out = []
    for m in _NUM.finditer(text or ""):
        n = m.group(1)
        key = n.replace(",", "") if _THOUSANDS.fullmatch(n) else n
        out.append((n, key + ("s" if m.group(2) else "")))
    return out


def number_keys(text: str, spelled: bool = False) -> set[str]:
    """The comparison keys of every number in ``text`` ("30s" also counts as
    30); with ``spelled``, also the ones written as English words."""
    found = set()
    for _, key in claim_numbers(text):
        found |= {key, key.rstrip("s")}
    if spelled:
        found |= {_NUM_WORDS[w] for w in _lc(text).split() if w in _NUM_WORDS}
    return found


def claim_overreach(claim: str, quote: str, corrections: dict | None = None,
                    english: bool = True) -> list[str]:
    """Words of the claim the quote does not carry: a name, a number, or a
    family word the quote does not have as the creator's own relative
    ("my brother"). A name the extractor corrected from a caption misspelling
    (`entity_corrections`, as_heard -> corrected) counts when the as-heard
    words are in the quote. The claim is always English, so a quote in another
    language is checked for names and numbers only. Empty means the claim says
    only what the quote says."""
    q = _lc(quote)
    q_words = set(q.split())
    q_bare = bare_words(quote)
    own = set()
    for m in _OWN.finditer(q):          # "my older brother", never past "and his"
        for g in m.groups():
            if not g or g in _OWN_STOP:
                break
            own.add(g)
    heard = {_lc(str(v)): _lc(str(k)).split() for k, v in (corrections or {}).items()}
    bad: list[str] = []
    for tok in _CAP.findall(" ".join((claim or "").split()[1:])):   # a capitalised first word is grammar
        if tok in _NOT_NAMES or word_in(tok, q_bare):
            continue
        if any(_lc(tok) in c and all(w in q_words for w in words) for c, words in heard.items()):
            continue
        bad.append(tok)
    in_quote = number_keys(quote, spelled=english)
    for num, key in claim_numbers(claim):
        if key not in in_quote:
            bad.append(num)
    if not english:
        return bad
    # a family word in the claim must be in the quote, and when the quote
    # gives it another owner ("his brother", "their mom") and never the
    # creator's own ("my brother"), the relative is someone else's
    def groups(words) -> set[str]:
        return {FAMILY_WORDS[w] for w in words if w in FAMILY_WORDS} | {
            FAMILY_WORDS[w.rstrip("s")] for w in words if w.rstrip("s") in FAMILY_WORDS}
    own_groups = groups(own)
    other_groups = groups({g for m in _OTHERS.finditer(q) for g in m.groups() if g})
    quote_groups = groups(q_words)
    lowered = (claim or "").lower()
    theirs = {_lc(m.group(2)) for m in _RELATIVES_OF.finditer(lowered)
              if _lc(m.group(1)) in FAMILY_WORDS or _lc(m.group(1)).rstrip("s") in FAMILY_WORDS}
    for k, raw in enumerate((claim or "").split()):
        if k and raw[:1].isupper():
            continue                     # a capitalised family word is part of a name
        word = _lc(raw)
        group = FAMILY_WORDS.get(word) or FAMILY_WORDS.get(word.rstrip("s"))
        if not group:
            continue
        if group not in quote_groups:
            bad.append(word)
        elif word not in theirs and group in other_groups and group not in own_groups:
            bad.append(word)
    return bad


def _quote_end(cues: list, quote: str, start: float | None):
    """Where the quote ends in the normalised cue stream, nearest ``start``:
    ``(hay, end, last cue, cue_end)``, or None when it is not found.
    Cues are ``[start, text]`` from the corpus."""
    needle = " ".join(_lc(quote or "").split())
    if not needle or not cues:
        return None
    # the normalised cue stream, with the cue that owns every character
    hay_parts: list[str] = []
    owner: list[int] = []
    cue_end: dict[int, int] = {}
    for i, (_, text) in enumerate(cues):
        n = " ".join(_lc(str(text)).split())
        if not n:
            continue
        if hay_parts:
            hay_parts.append(" ")
            owner.append(i)
        hay_parts.append(n)
        owner.extend([i] * len(n))
        cue_end[i] = len(owner)
    hay = "".join(hay_parts)
    hits = []
    pos = hay.find(needle)
    while pos >= 0:
        # whole words only: "my mom" is not a match inside "my moms camera"
        before_ok = pos == 0 or hay[pos - 1] == " "
        after_ok = pos + len(needle) == len(hay) or hay[pos + len(needle)] == " "
        if before_ok and after_ok:
            hits.append(pos)
        pos = hay.find(needle, pos + 1)
    if not hits:
        return None
    pos = min(hits, key=lambda p: abs(float(cues[owner[p]][0]) - float(start or 0)))
    end = pos + len(needle)
    return hay, end, owner[end - 1], cue_end


def extend_to_cue_end(cues: list, quote: str, start: float | None) -> str:
    """A quote that stops inside a caption line is extended to that line's
    end (or to the first sentence end inside it), so the words that change
    its meaning cannot be cut away."""
    found = _quote_end(cues, quote, start)
    if found is None:
        return quote
    hay, end, last, cue_end = found
    if end >= cue_end[last]:
        return quote                                 # the quote ends with the line
    if _SENTENCE_END.search((quote or "").split()[-1][-1:]):
        return quote                                 # the quote ends with its sentence
    raw_words = str(cues[last][1]).split()
    norm_words = " ".join(_lc(str(cues[last][1])).split()).split()
    if len(raw_words) != len(norm_words):
        return quote                                 # a token with no letters; leave it
    cue_start = cue_end[last] - len(" ".join(norm_words))
    consumed = len(hay[cue_start:end].split())
    out: list[str] = []
    for w in raw_words[consumed:]:
        if "<" in w:
            break                                    # a caption tag the parser left behind
        out.append(w)
        if _SENTENCE_END.search(w):
            break
    return quote + " " + " ".join(out) if out else quote


def next_line(cues: list, quote: str, start: float | None) -> str | None:
    """The caption line after a quote that ends where its line ends, with no
    sentence end: the sentence may go on there. The judge reads it and
    narrows or drops a claim it changes; the quote itself is not touched."""
    found = _quote_end(cues, quote, start)
    if found is None or not quote.split():
        return None
    _, end, last, cue_end = found
    if end < cue_end[last] or _SENTENCE_END.search(quote.split()[-1][-1:]):
        return None
    for _, text in cues[last + 1:]:
        following = " ".join(_CAPTION_TAG.sub(" ", str(text)).split())
        if following:
            return following
    return None


def load_cues(out: pathlib.Path) -> dict[str, list]:
    """``corpus.jsonl.gz`` beside the outputs, when the fetch wrote one."""
    path = out / "corpus.jsonl.gz"
    if not path.exists():
        return {}
    cues: dict[str, list] = {}
    with open_corpus(path) as fh:
        for line in fh:
            if line.strip():
                v = json.loads(line)
                cues[str(v.get("id"))] = v.get("cues") or []
    return cues


def people_in_quote(people, quote: str) -> list[dict]:
    """The extractor's `people`, kept only where the name is in the quote."""
    q = bare_words(quote)
    out: list[dict] = []
    for p in people or []:
        if not isinstance(p, dict):
            continue
        name = str(p.get("name") or "").strip()
        if name and all(_lc(re.sub(r"['’]s$", "", w)) in q for w in name.split()):
            rel = str(p.get("relation") or "").strip().lower() or None
            out.append({"name": name, "relation": rel})
    return out


def is_bio_window(window: dict) -> bool:
    """A window from the bio lane, which this assembly must never touch.

    Everything assembled here is stamped ``provenance: "transcript"`` and given
    ``video``/``start`` from its window, so a bio window (no video, a character
    offset where a timestamp belongs) would be minted as a quote at
    ``watch?v=None&t=0s``. ``bio_lane.py facts`` mints identity-lane records for
    those instead. Both marks are checked because ``extractor_prompt.py`` strips
    them from what the model sees, so an extractor's return cannot forge them."""
    return (window.get("retrieval") == "bio"
            or window.get("bio_source") is not None
            or window.get("format_hint") == "bio"
            or not window.get("video_id"))


def first5(t: str) -> str:
    return " ".join(t.split()[:5])


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _key(token: str) -> str:
    """A word's matching key: case-folded, punctuation stripped, letters of any
    script kept (windows come in any language)."""
    return "".join(ch for ch in token.casefold() if ch.isalnum())


def _words(s: str) -> list[str]:
    """Words with case and punctuation stripped, the matching key. Extractors
    add a full stop or a comma the captions never had; the cut itself always
    comes from the window text, so the quote stays verbatim by construction."""
    return [w for w in (_key(t) for t in s.split()) if w]


def _find_words(hay: list[str], needle: list[str], start: int = 0) -> int:
    n = len(needle)
    for k in range(start, len(hay) - n + 1):
        if hay[k:k + n] == needle:
            return k
    return -1


def extract_span(text: str, span: dict | None) -> str | None:
    first = (span or {}).get("first", "").strip()
    last = (span or {}).get("last", "").strip()
    if not first or not last:
        return None
    tokens = [(m.start(), m.end(), _key(m.group())) for m in re.finditer(r"\S+", text)]
    tokens = [t for t in tokens if t[2]]
    keys = [t[2] for t in tokens]
    f_words, l_words = _words(first), _words(last)
    if not f_words or not l_words:
        return None
    a = _find_words(keys, f_words)
    if a < 0:
        return None
    b = _find_words(keys, l_words, a)
    if b < 0:
        return None
    q = text[tokens[a][0]:tokens[b + len(l_words) - 1][1]]
    return q if 4 <= len(q.split()) <= 45 else None


def merge_return_files(efs: list[pathlib.Path], problems: list) -> tuple[dict, dict, set]:
    """Later files override the indexes they carry; within ONE file an index
    must appear exactly once, a duplicate is ambiguous and invalidates it."""
    merged_g: dict[int, dict] = {}
    merged_ng: dict[int, dict] = {}
    bad_idx: set[int] = set()
    for ef in efs:
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", ef.read_text(encoding="utf-8").strip())
        try:
            data = json.loads(raw)
        except Exception as e:
            problems.append(f"{ef.name} unparseable: {str(e)[:60]}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{ef.name} envelope is not an object")
            continue
        g_list = data.get("gems")
        ng_list = data.get("not_gems")
        if not isinstance(g_list, list) or not isinstance(ng_list, list):
            problems.append(f"{ef.name} gems/not_gems missing or not lists")
            continue
        counts: dict[int, int] = {}
        for x in list(g_list) + list(ng_list):
            if isinstance(x, dict) and isinstance(x.get("i"), int):
                counts[x["i"]] = counts.get(x["i"], 0) + 1
        dups = {i for i, c in counts.items() if c > 1}
        # This file is a later verdict for every index it carries. A valid
        # retry clears an earlier duplicate; a duplicate in the retry removes
        # and invalidates an earlier valid verdict.
        for i in counts:
            bad_idx.discard(i)
        for i in dups:
            merged_g.pop(i, None)
            merged_ng.pop(i, None)
        bad_idx.update(dups)
        for x in g_list:
            if isinstance(x, dict) and isinstance(x.get("i"), int) and x["i"] not in dups:
                merged_ng.pop(x["i"], None)
                merged_g[x["i"]] = x
        for x in ng_list:
            if isinstance(x, dict) and isinstance(x.get("i"), int) and x["i"] not in dups:
                merged_g.pop(x["i"], None)
                merged_ng[x["i"]] = x
    return merged_g, merged_ng, bad_idx


def return_file_key(path: pathlib.Path) -> tuple[int, str]:
    """Base extraction first, then retries in numeric rather than lexical order."""
    m = re.search(r"\.r(\d+)\.json$", path.name)
    return (int(m.group(1)) if m else 0, path.name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", required=True)
    ap.add_argument("--returns", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--append", action="store_true", help="add this round's rows to existing "
                    "classified/gems/candidates files instead of replacing them")
    ap.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE,
                    help="assembled/expected share below which the exit code is 3 "
                         f"(default {DEFAULT_MIN_COVERAGE}; 1.0 = every window or nothing)")
    a = ap.parse_args()
    if not 0.0 <= a.min_coverage <= 1.0:
        print("--min-coverage must be between 0 and 1", file=sys.stderr)
        return 2
    t0 = time.monotonic()
    out = pathlib.Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows, gems, cands, respawn, report = [], [], [], {}, {}
    missing_batches: list[str] = []
    dropped_by_speaker: Counter = Counter()
    cues_by_video = load_cues(out)
    overreach: list[dict] = []          # claims refused: they say what the quote does not
    extended = 0                        # quotes extended to the end of their caption line
    promoted = 0                        # `likely` with no named reason, read as confirmed
    for bf in sorted(glob.glob(os.path.join(a.batches, "batch-*.json"))):
        n = os.path.basename(bf)[6:9]
        wins = json.load(open(bf, encoding="utf-8"))
        bio = [i for i, w in enumerate(wins) if isinstance(w, dict) and is_bio_window(w)]
        if bio:
            print(f"{bf}: windows {bio[:5]}{'…' if len(bio) > 5 else ''} are bio-lane windows "
                  "(or carry no video_id). The transcript assembly stamps every row "
                  "provenance=transcript with a video and a start, so a bio window would "
                  "publish as a quote at a timestamp that does not exist. Run "
                  "`bio_lane.py facts` on that batch's returns instead.", file=sys.stderr)
            return 2
        efs = sorted(pathlib.Path(a.returns).glob(f"batch-{n}.extract*.json"),
                     key=return_file_key)
        r = {"expected": len(wins), "file": bool(efs), "gems": 0, "problems": []}
        if not efs:
            respawn[n] = list(range(len(wins)))
            r["problems"].append("missing file")
            missing_batches.append(n)
            report[n] = r
            continue
        merged_g, merged_ng, bad_idx = merge_return_files(efs, r["problems"])
        if not merged_g and not merged_ng:
            respawn[n] = list(range(len(wins)))
            report[n] = r
            continue
        G = list(merged_g.values())
        NG = list(merged_ng.values())
        seen = [x.get("i") for x in G] + [x.get("i") for x in NG]
        for i in range(len(wins)):
            if seen.count(i) != 1:
                bad_idx.add(i)
        for x in NG:
            i = x.get("i")
            if i is None or i in bad_idx or not (0 <= i < len(wins)):
                continue
            if x.get("speaker_guess") not in SPEAKERS:
                bad_idx.add(i)
                continue
            rows.append({"window": wins[i], "verdict": {"i": i, "self_disclosure": False,
                         "speaker_guess": x.get("speaker_guess"), "notable": x.get("reason")}, "error": None})
        for v in G:
            i = v.get("i")
            if i is None or i in bad_idx or not (0 <= i < len(wins)):
                continue
            w = wins[i]
            problems = []
            if v.get("start") != w["start"]:
                problems.append("start")            # hard: the verdict is not about this window
            anchor_ok = norm(v.get("anchor")) == norm(first5(w["text"]))
            if v.get("speaker_guess") not in SPEAKERS:
                problems.append("speaker")
            if v.get("life_domain") not in DOMAINS:
                problems.append("domain")
            if v.get("sensitivity") is not None and v.get("sensitivity") not in SENSITIVITY:
                problems.append("sensitivity")     # present but not a tier: stale schema
            q = extract_span(w["text"], v.get("quote_span"))
            if q is None:
                problems.append("span")
            if problems:
                bad_idx.add(i)
                r["problems"].append((i, problems))
                continue
            if not anchor_ok:
                r["anchor_soft_mismatch"] = r.get("anchor_soft_mismatch", 0) + 1
            v = dict(v)
            v["self_disclosure"] = True
            # the quote may not stop inside a caption line: the words after
            # the cut can change its meaning
            q2 = extend_to_cue_end(cues_by_video.get(str(w.get("id")), []), q, w.get("start"))
            if q2 != q:
                extended += 1
                q = q2
            v["quote"] = q
            nl = next_line(cues_by_video.get(str(w.get("id")), []), q, w.get("start"))
            if nl:
                v["next_line"] = nl
            # the claim says only what the quote says (names, numbers, the
            # creator's own relatives); a claim that says more is refused
            over = claim_overreach(str(v.get("claim") or ""), q, v.get("entity_corrections"),
                                   english=is_english(w))
            if over:
                overreach.append({"batch": n, "i": i, "claim": v.get("claim"), "not_in_quote": over})
                rows.append({"window": w, "verdict": {"i": i, "self_disclosure": False,
                             "speaker_guess": v.get("speaker_guess"),
                             "notable": "claim says more than the quote: " + ", ".join(over)},
                             "error": None})
                continue
            # `likely` carries only with a named reason; otherwise it is the
            # extractor hedging on a plain first-person line
            if v.get("confidence") == "likely" and not any(
                    k in str(v.get("speaker_evidence") or "").lower() for k in LIKELY_REASONS):
                v["confidence"] = "confirmed"
                promoted += 1
            v["people"] = people_in_quote(v.get("people"), q)
            if v.get("sensitivity") is None:
                v["sensitivity"] = tier_hint.tier_for(v.get("claim"), v.get("notable"), q)
                v["sensitivity_source"] = "heuristic"
            else:
                v["sensitivity_source"] = "extractor"
            v["sensitive"] = v["sensitivity"] in WITHHELD
            rows.append({"window": w, "verdict": v, "error": None})
            # a cohost on a multi-host channel is one of the creators and a
            # shared line is both of them; the merge keeps them apart by
            # `speaker`. Guests and narration stay out.
            if v["speaker_guess"] not in KEPT_SPEAKERS:
                dropped_by_speaker[v["speaker_guess"]] += 1
            if v["speaker_guess"] in KEPT_SPEAKERS:
                r["gems"] += 1
                gems.append({"window": w, "verdict": v, "error": None})
                cands.append({"fact_id": f"b{n}-{i:03d}", "claim": v.get("claim"), "domain": v["life_domain"],
                              "provenance": "transcript", "quote": q, "video": w["id"], "start": w["start"],
                              "published": w.get("published"), "confidence": v.get("confidence"),
                              "sensitivity": v["sensitivity"], "sensitive": v["sensitive"],
                              "sensitivity_source": v["sensitivity_source"],
                              "speaker_guess": v["speaker_guess"], "notable": v.get("notable"),
                              "speaker_evidence": v.get("speaker_evidence"),
                              "people": v["people"],
                              "entity_corrections": v.get("entity_corrections") or {}})
        if bad_idx:
            respawn[n] = sorted(bad_idx)
        report[n] = r
    # --append is idempotent: a round that is re-assembled after a re-judge
    # replaces its own earlier rows (same window id + start) instead of
    # stacking a second copy under them
    this_round = {(x["window"].get("id"), x["window"].get("start")) for x in rows}

    def _keep(line: str) -> bool:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            return True
        w = obj.get("window")
        key = ((w.get("id"), w.get("start")) if isinstance(w, dict)
               else (obj.get("video"), obj.get("start")))      # candidates.jsonl rows
        return key not in this_round

    for name, items in (("classified.jsonl", rows), ("gems.jsonl", gems), ("candidates.jsonl", cands)):
        kept = ""
        if a.append and (out / name).exists():
            with open(out / name, encoding="utf-8") as fh:
                kept = "".join(ln for ln in fh if ln.strip() and _keep(ln))
        with open(out / name, "w", encoding="utf-8") as fh:
            fh.write(kept + "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items))
    (out / "respawn.json").write_text(json.dumps(respawn, indent=1), encoding="utf-8")
    expected = sum(r["expected"] for r in report.values())
    unjudged = sum(len(v) for v in respawn.values())
    raw_coverage = len(rows) / expected if expected else 1.0
    coverage = round(raw_coverage, 3)
    # A whole batch without a return file is an extractor that never ran,
    # never a coverage question; a few unjudged windows above the threshold
    # are accepted and reported, and stay reachable through respawn.json or
    # a later --exclude round. The threshold is compared unrounded.
    rc = 3 if (missing_batches or raw_coverage < a.min_coverage) else 0
    elapsed = round(time.monotonic() - t0, 1)
    print(json.dumps({"batches": len(report), "windows_expected": expected, "windows_assembled": len(rows),
                      "gems": len(gems), "unjudged_windows": unjudged, "coverage": coverage,
                      "gems_dropped_by_speaker": dict(dropped_by_speaker),
                      "claims_refused_overreach": overreach,
                      "quotes_extended_to_line_end": extended,
                      "likely_read_as_confirmed": promoted,
                      "min_coverage": a.min_coverage, "missing_batches": missing_batches,
                      "respawn": respawn,
                      "problems": {k: r["problems"] for k, r in report.items() if r["problems"]},
                      "anchor_soft_mismatches": sum(r.get("anchor_soft_mismatch", 0) for r in report.values()),
                      "out": str(out), "elapsed_s": elapsed, "exit": rc}, indent=1))
    print(f"FUNNEL stage=assemble windows_expected={expected} windows_assembled={len(rows)} "
          f"gems={len(gems)} unjudged={unjudged} coverage={coverage} overreach={len(overreach)} "
          f"extended={extended} promoted={promoted} elapsed_s={elapsed}", file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
