#!/usr/bin/env python3
"""Authenticate the claims a merge shard should not have to guess about.

Two kinds of candidate leave the extractor looking exactly like a fact and
are not one, or not yet one:

* **A claim stated inside a staged premise.** A prank, challenge or skit
  upload (``format_hint: staged`` on the window) can put "my husband" or
  "we just moved" in the host's own mouth as the bit. The words are hers; the
  fact may not be.
* **Two clusters that contradict each other in a durable domain.** "We live
  in the mountains of Fictionia" (2020-01) and "we live in coastal Exampleland"
  (2020-04) cannot both be current. Latest-wins between those two videos is
  not the whole answer when the window sample never reached a later upload
  that says Fictionia again.

The merge shard should not settle either on the strength of two lines of
compact input. The rule: **do not drop, demote or supersede a fact because
the pipeline is unsure; go and check.**

So this script checks. For each flagged cluster it runs ONE channel-scoped
Elasticsearch query and keeps only the uploads that say the same thing:

* a specific phrase (a partner or family word: ``"my fiance"``,
  ``"my sister"``) counts on its own;
* otherwise the claim's three rarest words on this channel (rarity from the
  corpus windows) are searched, and an upload counts only where at least two
  of them sit within ``NEAR_SECONDS`` of each other in its captions
  (``"cousin"`` near ``"jack"``, ``"terrified"`` near ``"flying"``);
* the cluster's own uploads never count as confirming themselves;
* an upload is staged when its title, its cast sheet or its windows say so.

What the whole catalogue says lands on the merge-input line as ``probe``::

    {"videos": 4, "newest": "2024-06-02", "oldest": "2020-01-10",
     "staged_videos": 1, "non_staged_videos": 3, "staged_share": 0.25,
     "own_videos": 1, "own_non_staged_videos": 0, "recurring_videos": 5,
     "sample": [{"video_id": "...", "title": "...", "published": "...",
                 "start": 412, "line": "the matched caption lines"}],
     "query": "fictionia ~ live (2 of 2 within 30 s)"}

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
  being uncertain. Not ``staged_only`` when the cluster's own uploads include
  a non-staged one, or when the claim recurs in four or more uploads (own
  plus found): a line repeated across separate videos is the person's, not a
  one-off bit;
* nothing found either side of a conflict: keep both, ``unconfirmed``;
* newest dated evidence wins a conflict, and the identity lane's
  ``seen_date`` is evidence too when its source is the creator's own profile.

Budget: one query per flagged cluster, ``--max-queries`` (default 30) per
run, ``size`` 50, foreground, no deepening. This module is import-only: it
runs inside ``merge_pass.py prepare`` when ``--channel`` is given, which
calls ``run()`` on the shard files it just wrote.

The merge-input files are rewritten in place with ``probe`` /
``conflicts_with`` / ``staged`` added; ``probe.json`` (one object keyed by
cluster id) is what ``expand`` reads for its dated-evidence check. A failed
query is never raised: it is recorded on the line as ``probe: {"error": ...}``
and the shard is told to treat it as "nothing found".
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tl_data  # noqa: E402
from channel_context import TITLE_HINTS  # noqa: E402

# Words that make a relationships/family claim a status, not an anecdote.
PARTNER_NOUNS = {"husband", "wife", "boyfriend", "girlfriend", "fiance", "fiancé",
                 "fiancee", "fiancée", "partner", "spouse", "ex", "married",
                 "engaged", "divorced", "single", "dating", "pregnant", "baby"}
HOME_VERBS = re.compile(r"\b(live[sd]? in|living in|moved? to|moving to|based in|"
                        r"grew up in|from)\b", re.I)
# Cue phrases worth searching on their own; the shortest ones (i, my) are not.
MIN_CUE_WORDS = 2
STOP_ENTITIES = {"I", "My", "The", "A", "An", "In", "On", "At", "We", "She", "He",
                 "They", "It", "Youtube", "YouTube", "Instagram", "TikTok", "Chef",
                 "YouTuber", "Youtuber", "YouTubers", "Youtubers", "Mafia", "Host", "Creator"}
MAX_SAMPLE = 5
QUERY_SIZE = 50
APOSTROPHE_TOKEN = " 39 "
# Two claim words count as the same statement only this close in the captions.
NEAR_SECONDS = 30
# How many of the quote's most telling words a probe searches.
KEY_WORDS = 4
# Beside a name, a word used in more than this share of the channel's
# uploads ("brother", "girl") says nothing about the claim.
NAME_PARTNER_MAX_SHARE = 0.15
CORPUS_SIZE_KEY = "\x00uploads"
# A phrase holding one of these is specific enough to count on its own.
SPECIFIC_NOUNS = {"husband", "wife", "boyfriend", "girlfriend", "fiance", "fiancé",
                  "fiancee", "fiancée", "spouse", "sister", "brother", "mom", "mum",
                  "mother", "dad", "father", "son", "daughter", "kids", "grandma",
                  "grandpa", "cousin", "aunt", "uncle", "dog", "cat"}
# Words that never make a claim specific.
STOPWORDS = set("""a an the and or but if so to of in on at by for with from as is are was were be been
being am do does did done have has had having i me my mine we us our you your he him his she her they
them their it its this that these those there here what which who whom when where why how all any both
each few more most other some such no nor not only own same than too very can will just should now
about into over after before again then once also really like just know get got gets getting go goes
going gonna went come came make made want wanted think said say says see saw look right good thing
things time times people guys video videos channel youtube today one two every always never ever much
many still even back first last new well yeah okay oh uh um lot lots way day days year years
home house place stuff used ago plan big second kid kids eat guy guys man bro dude friend friends
called calls named saying says talks close single call calling live lives living lived room rooms
actually basically literally genuinely honestly seriously totally freaking anyway anyways since whatever
gonna wanna kinda sorta maybe probably definitely funny crazy insane cool nice great awesome bad
little big huge tiny someone something anything everything nothing somebody anybody everybody
put take took give gave keep kept let lets tell told ask asked try tried need needed feel felt
thank thanks please sorry hey hi hello bye listen look looking watch watching wait start started
work working job finally exact exactly inside outside tonight morning night afternoon week weeks
today yesterday tomorrow minute minutes hour hours second seconds""".split())


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
    """Every staged window (a claim said inside a premise is checked against
    the non-staged uploads whatever its domain), or a line already marked as
    conflicting (set by ``find_conflicts`` before this runs)."""
    return bool(line.get("conflicts_with")) or is_staged(line)


def find_conflicts(lines: list[dict]) -> int:
    """Mark pairs that cannot both be current: two ``home`` claims naming
    different places, or two relationship claims with different partner
    nouns where the committed one is older (a step back). A girlfriend who
    later becomes a fiancee is the relationship moving on, not a conflict.
    Same-claim pairs (same place, same noun) are folds, not conflicts, and
    are left to the shard."""
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
                # girlfriend then fiancee is the same relationship moving on,
                # not two relationships: only a step back is a conflict
                newer_committed = (str(a.get("published") or "") >= str(b.get("published") or "")
                                   if na in committed else
                                   str(b.get("published") or "") >= str(a.get("published") or ""))
                if newer_committed:
                    continue
                link(a, b)
    return marked


def _stem(word: str) -> str:
    """A light stem so "boxing", "boxes" and "box" meet and "loves" meets
    "love"; never a dictionary."""
    w = word.lower().strip("'’")
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("ing"):
        w = w[:-3]
        return w[:-1] if len(w) > 3 and w[-1] == w[-2] else w
    if len(w) > 3 and w.endswith("ed"):
        return w[:-2] if w[-3] != "e" else w[:-1]
    if len(w) > 3 and w.endswith("es") and w[-3] in "sxz":
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'’]*", (text or "").lower())


def specific_phrase(phrase: str | None) -> bool:
    """A partner or family phrase ("my fiance", "my sister") names one thing
    already; a general one ("i hate", "best friend", "every time") does not."""
    return bool(phrase) and any(w in SPECIFIC_NOUNS for w in _words(phrase))


def doc_freq(corpus: pathlib.Path | None) -> dict[str, int]:
    """How many of the channel's corpus uploads use each stem: the rarer a
    claim word, the more it says about this claim. {} without a corpus."""
    out: dict[str, int] = {}
    if not corpus or not corpus.exists():
        return out
    import gzip
    try:
        with gzip.open(corpus, "rt", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                rec = json.loads(raw)
                text = " ".join(str(c[1]) for c in (rec.get("cues") or []) if len(c) > 1)
                out[CORPUS_SIZE_KEY] = out.get(CORPUS_SIZE_KEY, 0) + 1
                for st in {_stem(w) for w in _words(text)}:
                    out[st] = out.get(st, 0) + 1
    except (OSError, ValueError):
        return {}
    return out


def claim_names(line: dict) -> list[str]:
    """Names the claim gives a person or place that the quote also says
    ("Jack", "Hope"), never the claim's capitalised first word ("Has",
    "His", "Loves") and never a platform name."""
    claim = str(line.get("claim") or "")
    first = (_words(claim) or [""])[0]
    quote = set(_words(str(line.get("quote") or "")))
    return [e for e in entities(claim) if e != first and e in quote and e not in STOPWORDS]


def quote_terms(line: dict, freq: dict[str, int], skip: set[str] | None = None,
                k: int = KEY_WORDS) -> list[str]:
    """The quote's ``k`` most telling words (never a common word, never a
    name in ``skip``), rarest on this channel first, in the quote's spelling."""
    skip = {_stem(w) for w in (skip or set())}
    picked: dict[str, str] = {}
    for w in _words(str(line.get("quote") or "")):
        if w in STOPWORDS or len(w) < 3 or not w.isalpha():
            continue
        st = _stem(w)
        if st in skip or st in picked or st in STOPWORDS:
            continue
        picked[st] = w
    ranked = sorted(picked.items(), key=lambda kv: (freq.get(kv[0], 0) if freq else 0, -len(kv[1])))
    return [surface for _st, surface in ranked[:k]]


def probe_plan(line: dict, cluster: dict | None, freq: dict[str, int]) -> tuple[str | None, str | None, list[str], int]:
    """``(phrase, name, terms, need)``. A partner or family phrase on a claim
    that names nobody counts alone. A claim that names someone needs the
    name and one of ``terms`` within ``NEAR_SECONDS``. Any other claim needs
    ``need`` of its quote's ``terms`` within ``NEAR_SECONDS`` of each other:
    most of what the creator said, said again."""
    cue = cue_phrase(line, cluster)
    names = claim_names(line)
    if specific_phrase(cue) and not names:
        return cue, None, [], 0
    terms = quote_terms(line, freq, skip=set(names))
    if names:
        n = freq.get(CORPUS_SIZE_KEY, 0)
        if n:
            telling = [w for w in terms if freq.get(_stem(w), 0) / n <= NAME_PARTNER_MAX_SHARE]
            terms = telling or terms
        return None, names[0], terms, 1
    need = max(2, -(-len(terms) * 3 // 5))  # at least 2, else 60% rounded up
    return None, None, terms, need


def es_body(channel: int, phrase: str | None, name: str | None, terms: list[str], need: int) -> dict:
    """The specific phrase alone, or the name plus one term, or ``need`` of
    the terms, with highlighted caption fragments so nearness can be checked."""
    if phrase:
        must = [{"bool": {"should": [
            {"match_phrase": {"transcript": {"query": v}}} for v in _phrase_variants(phrase)
        ], "minimum_should_match": 1}}]
    else:
        # each term as said and as its stem ("forklifts", "forklift"): the
        # index does not stem, the captions vary
        must = [{"bool": {"should": [
            {"bool": {"should": [{"match": {"transcript": {"query": v}}}
                                 for v in dict.fromkeys((w, _stem(w)))],
                      "minimum_should_match": 1}} for w in terms
        ], "minimum_should_match": need}}]
        if name:
            must.insert(0, {"match": {"transcript": {"query": name}}})
    return {
        "size": QUERY_SIZE,
        "_source": ["id", "title", "publication_date", "transcript_language"],
        "query": {"bool": {"filter": [
            {"term": {"doc_type": "article"}},
            {"term": {"channel.id": channel}},
            {"exists": {"field": "transcript"}},
        ], "must": must}},
        "sort": [{"publication_date": "desc"}, {"id": "asc"}],
        # fragments centred on the name when there is one, so a name said
        # once is not crowded out by a common word said twenty times
        "highlight": {"fields": {"transcript": {
            "fragment_size": 600, "number_of_fragments": 10, "order": "score",
            **({"highlight_query": {"match": {"transcript": {"query": name}}}} if name else {})}}},
    }


def _has_name(text: str, name: str, cased: bool) -> bool:
    """The name as a name: where the captions carry capitals, "Hope" and
    never the verb "hope"; in older all-lowercase captions, the word."""
    if cased:
        return re.search(rf"\b{re.escape(name[:1].upper() + name[1:])}\b", text) is not None
    return name in _words(text)


def near_hit(fragments: list[str], phrase: str | None, name: str | None,
             terms: list[str], need: int) -> tuple[int, str] | None:
    """(start second, caption text) of the first place this upload says the
    claim again: the phrase, or the name with one term, or ``need`` terms,
    all within ``NEAR_SECONDS``. None when the words only share a video."""
    import fetch_cues  # sibling; one home for the timed-text fragment parser
    stems = {_stem(w) for w in terms}
    for frag in fragments or []:
        _text, _hits, _start, _raw, pieces = fetch_cues.clean(frag)
        if not pieces:
            continue
        if phrase:
            joined = " ".join(p[1].lower() for p in pieces)
            if phrase.lower() in joined or phrase.lower().replace("'", "") in joined.replace("'", ""):
                return int(pieces[0][0]), " ".join(p[1] for p in pieces)[:240]
            continue
        cased = any(ch.isupper() for p in pieces for ch in p[1])
        found = [(float(st), {_stem(w) for w in _words(tx)} & stems) for st, tx in pieces]
        anchors = ([float(st) for st, tx in pieces if _has_name(tx, name, cased)] if name
                   else [t for t, hit in found if hit])
        for t0 in anchors:
            near: set[str] = set()
            for t, hit in found:
                if abs(t - t0) <= NEAR_SECONDS:
                    near |= hit
            if len(near) >= need:
                lines = [p[1] for p in pieces if abs(float(p[0]) - t0) <= NEAR_SECONDS]
                return int(t0), " ".join(lines)[:240]
    return None


def probe(channel: int, line: dict, cluster: dict | None,
          freq: dict[str, int] | None = None, staged_videos: set[str] | None = None,
          own_videos: set[str] | None = None) -> dict:
    phrase, name, terms, need = probe_plan(line, cluster, freq or {})
    if not phrase and (len(terms) < need or (not name and len(terms) < 2)):
        return {"skipped": "no specific phrase and too few telling words in the quote",
                "videos": 0}
    label = (f"\"{phrase}\"" if phrase
             else (f"{name} + one of {', '.join(terms)}" if name
                   else f"{need} of {', '.join(terms)}") + f" within {NEAR_SECONDS} s")
    try:
        rows = tl_data.cli_rows(["db", "es", "-", "--json", "--highlight"],
                                input_text=json.dumps(es_body(channel, phrase, name, terms, need)))
    except Exception as exc:  # recorded, never raised: the shard treats it as nothing found
        return {"query": label, "error": str(exc)[:300]}
    staged_videos = staged_videos or set()
    own_videos = own_videos or set()
    seen: dict[str, dict] = {}
    for r in rows:
        vid = str(r.get("id") or "").split(":", 1)[-1]
        if not vid or vid in seen or vid in own_videos:
            continue
        hit = near_hit((r.get("highlight") or {}).get("transcript") or [], phrase, name, terms, need)
        if hit is None:
            continue
        title = str(r.get("title") or "")
        title_staged = (bool(TITLE_HINTS["staged"].search(title))
                        and not any(TITLE_HINTS[k].search(title) for k in ("reaction", "interview_or_collab")))
        seen[vid] = {"video_id": vid, "title": title,
                     "published": str(r.get("publication_date") or "")[:10],
                     "staged": title_staged or vid in staged_videos,
                     "start": hit[0], "line": hit[1]}
    vids = list(seen.values())
    dates = sorted(v["published"] for v in vids if v["published"])
    staged_n = sum(1 for v in vids if v["staged"])
    own_non_staged = sum(1 for v in own_videos if v not in staged_videos)
    return {
        "query": label,
        "videos": len(vids),
        "newest": dates[-1] if dates else None,
        "oldest": dates[0] if dates else None,
        "staged_videos": staged_n,
        "non_staged_videos": len(vids) - staged_n,
        "staged_share": round(staged_n / len(vids), 2) if vids else None,
        "own_videos": len(own_videos),
        "own_non_staged_videos": own_non_staged,
        "recurring_videos": len(vids) + len(own_videos),
        "sample": [{k: v[k] for k in ("video_id", "title", "published", "staged", "start", "line")}
                   for v in vids[:MAX_SAMPLE]],
    }


def staged_video_ids(corpus_dir: pathlib.Path | None) -> set[str]:
    """Uploads the run already knows are staged: a window's ``format_hint``
    or the cast sheet's ``format``, not the title alone."""
    out: set[str] = set()
    if not corpus_dir:
        return out
    import gzip
    win = corpus_dir / "windows.jsonl.gz"
    if win.exists():
        try:
            with gzip.open(win, "rt", encoding="utf-8") as fh:
                for raw in fh:
                    raw = raw.strip()
                    if raw:
                        w = json.loads(raw)
                        if str(w.get("format_hint") or "") == "staged" and w.get("video_id"):
                            out.add(str(w["video_id"]))
        except (OSError, ValueError):
            pass
    cast = corpus_dir / "cast.json"
    if cast.exists():
        try:
            for vid, sheet in json.loads(cast.read_text(encoding="utf-8")).items():
                if isinstance(sheet, dict) and str(sheet.get("format") or "") == "staged":
                    out.add(str(vid))
        except (OSError, ValueError):
            pass
    return out


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
    corpus_dir = clustered.parent if clustered else None
    freq = doc_freq(corpus_dir / "corpus.jsonl.gz") if corpus_dir else {}
    staged_ids = staged_video_ids(corpus_dir)
    conflicts = find_conflicts(lines)
    queried = 0
    results: dict[str, dict] = {}
    for line in lines:
        if not wants_probe(line):
            continue
        if queried >= max_queries:
            line["probe"] = {"skipped": f"query budget of {max_queries} reached"}
            continue
        cluster = clusters_by_c.get(str(line.get("c")))
        own = {str(m.get("video_id")) for m in ((cluster or {}).get("members") or [])
               if isinstance(m, dict) and m.get("video_id")}
        own.add(str(((cluster or {}).get("window") or {}).get("video_id") or ""))
        own.discard("")
        line["probe"] = probe(channel, line, cluster, freq, staged_ids, own)
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
