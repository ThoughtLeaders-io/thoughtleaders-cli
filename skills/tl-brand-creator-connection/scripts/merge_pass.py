#!/usr/bin/env python3
"""The merge pass as a compact decision contract: the agent judges, this script
materialises the ledger.

The old merge pass asked one agent to compose the whole ledger, ~220 full fact
records, ~118 KB in a single write, of which roughly three quarters was
verbatim copying of fields the clustered file already held, and that copying
dominated the run's wall clock. Everything mechanical in that output is
derivable here:
fact ids, urls, recurrence over distinct videos, the confidence default, the
sensitivity boolean, the `selected` pick. What is left for a model is the
judgment a script cannot make, attribution, folds, narrowing an over-reaching
claim, supersession, and that fits in a few kilobytes of decisions.

Two subcommands:

``prepare``
    Numbers the clusters ``c001…`` in file order and writes one compact line
    per cluster the agent must judge (no window text, no member list), plus, on a refresh, a compact view of the existing ledger to fold into or
    supersede. The deterministic half of ``references/evidence-rules.md`` runs
    here: guest windows never reach the agent, and neither do unclear
    windows on a shared-voice format (a second host's ``cohost`` line and a
    ``shared`` "we" line are judged like the host's). On a refresh the previous round's
    ``merge-state.json`` decides which clusters are genuinely new; the rest
    carry their judgment forward untouched.

``expand``
    Validates the returned decisions like ``assemble_extracts.py`` validates
    extractor returns, every judged cluster placed exactly once, targets that
    exist, enums, fold chains that terminate, no number in a narrowed claim
    that is not in the evidence, and exits 3 with the offending ids so the
    orchestrator re-asks for exactly those as a patch decisions file, never
    hand-patches. Then it builds the facts, rewrites ``merge-state.json`` so
    the next round can inherit, and prints the FUNNEL line.

Usage:
    merge_pass.py prepare --clustered <corpus>/gems-clustered.jsonl
        --format <solo|interview|multi_host|faceless_scripted>
        [--existing <profiles>/<id>-facts.jsonl]
        [--state <corpus>/merge-state.json] [--shards N | auto]
        [--channel <id>] --out <corpus>

    ``--shards`` defaults to clusters / 40 (floor 1, ceiling 6), so the
    cluster -> prepare chain runs as one command. With ``--channel``,
    ``authenticate.py`` runs on the written shard files: staged-premise
    claims and contradicting clusters get one channel-scoped query each and
    carry the evidence (``probe``, ``conflicts_with``, ``staged``) into the
    shard's input; ``probe.json`` is left for ``expand``.

    merge_pass.py expand --clustered <corpus>/gems-clustered.jsonl
        --decisions <file> [--decisions <patch> …]
        [--existing <profiles>/<id>-facts.jsonl]
        [--state <corpus>/merge-state.json]
        --format <label> --channel <id> --out <corpus>/facts.jsonl
        [--fallback-original]

The decisions file (what the agent returns) is ONE object:

    {"decisions": {
        "c013": {"action": "fold", "target": "f007"},
        "c014": {"action": "drop", "reason": "claim asserts more than the quote"},
        "c015": {"action": "keep", "tier": "lifestyle", "claim": "narrowed claim",
                 "confidence": "unconfirmed", "supersedes": "f003",
                 "gloss": "English translation of a non-English quote"}},
     "selected": ["c015", "f001"],
     "facts": [{"ref": "s1", "provenance": "social", "claim": "runs a pottery studio",
                "domain": "work", "sensitivity": "none",
                "source_url": "https://instagram.com/…", "seen_date": "2025-03-02",
                "corroborates": "c012"}]}

The optional top-level ``facts`` list is the identity lane's way into the
ledger: social/web facts carry ``source_url`` and ``seen_date`` instead of a
quote, a video and a start, are numbered after the clusters, and publish at
``unconfirmed`` unless ``corroborates`` names a kept cluster or an existing
fact, cross-lane corroboration is the top tier in ``evidence-rules.md``, so
it lifts BOTH facts to ``confirmed``. An optional ``ref`` is what ``selected``
can name them by.

Every field of a ``keep`` other than ``action`` is optional. ``target`` and
``supersedes`` may name a kept cluster (``c*``) or, on a refresh, an existing
fact (``f*``); a fold target must share the domain. Later ``--decisions``
files override earlier ones per cluster id, which is how the exit-3 re-ask
lands as a small patch.

Exit 0 on success, 3 on a contract violation (with the offending ids on
stdout), 2 on a usage error.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import tier_hint  # noqa: E402
import assemble_extracts as _ax  # noqa: E402  sibling: the claim-to-quote check
from store_io import read_ledger, write_ledger  # noqa: E402
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data  # noqa: E402  the shared CLI wrapper

DOMAINS = {"origin", "family", "pets", "home", "work", "money", "health",
           "habits", "tastes", "beliefs", "relationships", "other"}
# The socials lane writes its own `facts` records rather than judging clusters,
# so it reaches for domain words the enum does not carry ("hobbies", "gear").
# Measured on a live run: 5 of 9 identity facts used a near-miss label and the
# whole expand failed, costing a hand-written patch. These are the near-misses
# with exactly one sensible target; anything else still fails loudly with the
# allowed list. The aliasing is reported, never silent.
DOMAIN_ALIASES = {
    "hobbies": "habits", "hobby": "habits", "interests": "habits",
    "routine": "habits", "routines": "habits",
    # An ambiguous label lands in the enum's own catch-all rather than a
    # guessed specific domain: "other" is honest, a wrong "work" is not.
    "identity": "other", "personal": "other", "misc": "other",
    "gear": "other", "stuff": "other",
    "career": "work", "job": "work", "business": "work",
    "location": "home", "residence": "home",
    "fitness": "health", "wellness": "health",
    "food": "tastes", "preferences": "tastes",
    "partner": "relationships", "marriage": "relationships",
    "childhood": "origin", "background": "origin", "history": "origin",
    "finances": "money",
}
SENSITIVITY = {"none", "lifestyle", "clinical", "children", "location"}
WITHHELD = {"clinical", "children", "location"}
CONFIDENCE = {"confirmed", "unconfirmed"}
# Sensitivity near-misses. An alias may only ever move a value to a MORE
# protective tier: raising "medical" to `clinical` withholds a fact that would
# otherwise have been usable, which is the safe direction to be wrong in.
# Nothing aliases INTO "none", because that would strip protection from a fact
# the lane was trying to flag.
SENSITIVITY_ALIASES = {
    "medical": "clinical", "health": "clinical", "diagnosis": "clinical",
    "condition": "clinical", "illness": "clinical",
    "kids": "children", "child": "children", "kid": "children",
    "address": "location", "geo": "location", "where": "location",
    "personal": "lifestyle", "private": "lifestyle",
}
# Confidence near-misses. The extractor stage upstream grades a passage
# `confirmed` / `likely` / `unconfirmed`, and the merge agent carries its
# vocabulary downstream into a field that holds only two of those words. Every
# alias here resolves DOWNWARD to `unconfirmed`: a near-miss must never promote
# a fact to `confirmed`, because cross-lane corroboration is the only thing
# that earns the top tier (`evidence-rules.md`).
CONFIDENCE_ALIASES = {
    "likely": "unconfirmed", "probable": "unconfirmed",
    "possible": "unconfirmed", "unclear": "unconfirmed",
    "uncertain": "unconfirmed", "unverified": "unconfirmed",
    "partial": "unconfirmed", "weak": "unconfirmed",
}
ACTIONS = {"keep", "fold", "drop"}
# The identity lane. `evidence-rules.md`: lanes never masquerade as each other,
# so a social/web fact names its source and seen-date and carries no quote,
# video or start, those belong to the transcript lane alone.
IDENTITY_PROVENANCE = {"social", "web", "bio"}
IDENTITY_REQUIRED = ("claim", "domain", "sensitivity", "source_url", "seen_date")
IDENTITY_BANNED = ("quote", "video", "start", "url")
# The bio lane. The creator's own written self-description is the most
# explicit thing they ever say about themselves and the least verified: they
# write untrue and out-of-date things in an About box, and nobody edits it.
# So a bio fact is an identity-lane record with two extra rules of its own:
# only a TRANSCRIPT fact may corroborate it (a second written bio agreeing
# with the first is one source, not two), and a bio fact nothing corroborates
# never reaches a claim or a pitch, it renders in its own labelled block, or,
# at a withheld tier, is dropped from the ledger entirely.
BIO = "bio"
FORMATS = {"solo", "interview", "multi_host", "faceless_scripted"}

# Formats where one voice holds the transcript, so an unattributed window is
# the host's (capped at unconfirmed) rather than unattributable.
SINGLE_VOICE = {"solo", "faceless_scripted"}

# A window's own hint outranks the channel label for that cluster: a solo
# channel's one interview upload is still an interview, and a prank,
# challenge or stunt upload has other people speaking in it.
_HINT_NON_SOLO = re.compile(r"interview|collab|reaction|staged", re.I)

# Facts the connections page leads with. The agent proposes, the script owns
# the final count: never a contract violation. The ledger keeps every
# verified fact whatever this says, and the page's "who they are" run reads
# fine at 40; a lower cap was a page-length guess that left real gems off the
# page.
SELECTED_TARGET = 40
# A fact is recent when the newest upload saying it is inside this many
# months of the run date; recent facts rank ahead of older ones.
RECENT_MONTHS = 24
# A claim found only inside an upload's opening hook, and in no other video,
# is `unconfirmed`: hooks are written to pull viewers in.
HOOK_SECONDS = 60
RUN_DATE: str = ""        # set by expand; the ledger's date for the recency test
# Shards for the merge pass when `prepare` is not told: clusters / 40, floor
# 1, ceiling 6, so around 90 clusters become two agents rather than one slow
# one (the merge shard is otherwise the longest single agent in a run).
SHARD_DIVISOR = 40
SHARD_MAX = 6

_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


def funnel(**fields) -> None:
    print("FUNNEL " + " ".join(f"{k}={v}" for k, v in fields.items()),
          file=sys.stderr)


def read_jsonl(path: pathlib.Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{path}:{n}: not JSON ({exc})") from exc
    return out


def write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, default=str,
                                separators=(",", ":")) + "\n")


# --------------------------------------------------------------------------- #
# cluster accessors, one place that knows the clustered line's shape
# --------------------------------------------------------------------------- #
def cid(index: int) -> str:
    return f"c{index + 1:03d}"


def member_key(member: dict) -> str:
    """The identity a refresh inherits by.

    Never the fact's own (video, start): ``verify_quotes.py`` rewrites a
    fact's start to the located timestamp, so only the cluster member's own
    offset survives a round.
    """
    return f"{member.get('video_id')}:{member.get('start')}"


def members_of(line: dict) -> list[dict]:
    members = line.get("members")
    if isinstance(members, list) and members:
        return [m for m in members if isinstance(m, dict)]
    w = line.get("window") or {}
    return [{"video_id": w.get("video_id"), "start": w.get("start"),
             "published": w.get("published")}]


def member_keys(line: dict) -> list[str]:
    return [member_key(m) for m in members_of(line)]


def distinct_videos(line: dict) -> list[str]:
    seen: list[str] = []
    for m in members_of(line):
        vid = m.get("video_id")
        if vid and vid not in seen:
            seen.append(vid)
    return seen


def _member_flag(line: dict, field: str, mode: str) -> bool:
    """``all``/``any`` over a boolean the members carry.

    ``cluster_gems.py`` writes ``in_sponsor_read`` and ``host_anchor`` onto
    every member ref. A clustered file written before that change has them
    only on the representative window: a singleton then answers from the
    window, and a multi-member cluster answers conservatively (an unknown
    member is not an ad read, and is not an anchor).
    """
    members = members_of(line)
    known = [bool(m.get(field)) for m in members if field in m]
    if not known:
        window = line.get("window") or {}
        if field in window and len(members) <= 1:
            return bool(window.get(field))
        return bool(window.get(field)) if mode == "any" else False
    if len(known) != len(members) and mode == "all":
        return False
    return all(known) if mode == "all" else any(known)


def ad_read_only(line: dict) -> bool:
    return _member_flag(line, "in_sponsor_read", "all")


def anchored(line: dict) -> bool:
    return _member_flag(line, "host_anchor", "any")


def cluster_claim(line: dict) -> str:
    v = line.get("verdict") or {}
    return str(v.get("claim") or v.get("notable") or "").strip()


def effective_format(line: dict, fmt: str) -> str:
    """The channel format, unless this cluster's own window says otherwise."""
    hint = str((line.get("window") or {}).get("format_hint") or "")
    if hint and _HINT_NON_SOLO.search(hint):
        return "interview"
    return fmt


def compact(line: dict, index: int) -> dict:
    """One line of ``merge-input.jsonl``: everything the judgment needs and
    nothing else, no window text, no member list."""
    w = line.get("window") or {}
    v = line.get("verdict") or {}
    return {
        "c": cid(index),
        "domain": v.get("life_domain"),
        "speaker": v.get("speaker_guess"),
        "speaker_evidence": v.get("speaker_evidence"),
        "people": v.get("people") or [],
        "last_seen": newest_evidence(line, None),
        "tier": v.get("sensitivity"),
        "conf": v.get("confidence"),
        "claim": cluster_claim(line),
        "quote": v.get("quote"),
        # the caption line after a quote cut at a line break
        "next_line": v.get("next_line"),
        "title": w.get("title"),
        "published": w.get("published"),
        "videos": len(distinct_videos(line)),
        "occ": line.get("occurrences") or len(members_of(line)),
        "ad_read": ad_read_only(line),
        "anchor": anchored(line),
        "format_hint": w.get("format_hint"),
        # a staged premise (prank, challenge, skit title): the words are the
        # host's, the fact may be the bit; `authenticate.py` checks and the
        # shard decides with its `probe`
        "staged": str(w.get("format_hint") or "") == "staged",
        "lang": w.get("language"),
        "notable": v.get("notable"),
    }


def newest_evidence(line: dict, probe_entry: dict | None) -> str | None:
    """The newest date any evidence gives a cluster's claim: its members'
    upload dates, and the newest upload `authenticate.py` found saying the
    same thing anywhere in the catalogue."""
    dates = [str(m.get("published") or "")[:10] for m in members_of(line)]
    w = line.get("window") or {}
    dates.append(str(w.get("published") or "")[:10])
    if probe_entry:
        dates.append(str(((probe_entry.get("probe") or {}).get("newest")) or "")[:10])
    dates = [d for d in dates if d]
    return max(dates) if dates else None


def load_probe(path: pathlib.Path | None) -> dict[str, dict]:
    """`probe.json` from `authenticate.py`, keyed by cluster id; {} when the
    probe did not run (a refresh with nothing staged, or an older corpus)."""
    if not path or not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    results = data.get("results") if isinstance(data, dict) else None
    return {k: v for k, v in (results or {}).items() if isinstance(v, dict)}


def staged_only(line: dict, probe_entry: dict | None) -> bool:
    """A claim from a staged window that the probe could not find in any
    non-staged upload (or that no probe reached). It is kept, never dropped,
    but it does not confirm and does not reach a brand-facing page."""
    w = line.get("window") or {}
    if str(w.get("format_hint") or "") != "staged":
        return False
    p = (probe_entry or {}).get("probe") or {}
    return int(p.get("non_staged_videos") or 0) == 0


# --------------------------------------------------------------------------- #
# the deterministic pre-judgment (evidence-rules + the refresh state)
# --------------------------------------------------------------------------- #
def auto_drop_reason(line: dict, fmt: str) -> str | None:
    """The drops ``evidence-rules.md`` makes without a model.

    ``guest`` is another person's line on any format and never enters.
    ``cohost`` (the second named host) and ``shared`` (a "we" line about the
    hosts' shared life) are judged like the host's. ``unclear`` is an honest
    answer on a shared-voice format and drops there; on a single-voice format
    it (and ``narration``) publishes as the host, capped at ``unconfirmed``.
    """
    speaker = str((line.get("verdict") or {}).get("speaker_guess") or "")
    fmt = effective_format(line, fmt)
    if speaker == "guest":
        return "speaker guest"
    if speaker == "unclear" and fmt not in SINGLE_VOICE:
        return f"speaker unclear on {fmt} format"
    return None


def load_state(path: pathlib.Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    members = data.get("members") if isinstance(data, dict) else None
    if not isinstance(members, dict):
        return {}
    return {k: v for k, v in members.items() if isinstance(v, dict)}


def plan(clusters: list[dict], fmt: str, state: dict[str, dict],
         existing_ids: set[str]) -> list[dict]:
    """One record per cluster saying who judges it.

    ``judge``: sent to the agent (new, or re-judged because its members now
    span several existing facts, or because one of them was dropped last
    round). ``additive``: every known member belongs to ONE existing fact and
    none was dropped, so the judgment carries and only recurrence changes.
    ``auto_dropped``: a deterministic evidence-rules drop. ``carry_dropped``: every member was dropped last round and nothing new joined.
    """
    out: list[dict] = []
    for i, line in enumerate(clusters):
        rec: dict = {"c": cid(i), "index": i, "known": [], "fact_id": None,
                     "reason": None}
        reason = auto_drop_reason(line, fmt)
        if reason:
            rec["status"] = "auto_dropped"
            rec["reason"] = reason
            out.append(rec)
            continue
        keys = member_keys(line)
        known_facts: list[str] = []
        dropped = 0
        unknown = 0
        for key in keys:
            entry = state.get(key)
            if not entry:
                unknown += 1
                continue
            fid = entry.get("fact") or entry.get("folded")
            if fid and fid in existing_ids:
                if fid not in known_facts:
                    known_facts.append(fid)
            elif "dropped" in entry:
                dropped += 1
            else:
                unknown += 1
        rec["known"] = known_facts
        rec["dropped_members"] = dropped
        if len(known_facts) == 1 and not dropped:
            rec["status"] = "additive"
            rec["fact_id"] = known_facts[0]
        elif known_facts:
            # Either the members now span several facts, or one of them was
            # dropped last round and the rest were kept. Both are a changed
            # picture, and carrying the old judgment forward would silently
            # resurrect a dropped window or merge two facts, the agent
            # decides, with the ids it is deciding between.
            rec["status"] = "judge"
            rec["rejudge"] = True
        elif dropped and not unknown:
            rec["status"] = "carry_dropped"
            rec["reason"] = "every member was dropped in an earlier round"
        else:
            rec["status"] = "judge"
        out.append(rec)
    return out


# --------------------------------------------------------------------------- #
# prepare
# --------------------------------------------------------------------------- #
def shard_rows(rows: list[dict], shards: int) -> list[list[dict]]:
    """Pack whole life domains into ``shards`` files.

    Folds only happen inside a domain, so a domain split across two agents
    would make a fold impossible to express. Biggest domain into the emptiest
    shard, deterministically.
    """
    by_domain: dict[str, list[dict]] = {}
    for row in rows:
        by_domain.setdefault(str(row.get("domain") or ""), []).append(row)
    buckets: list[list[dict]] = [[] for _ in range(shards)]
    order = sorted(by_domain.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    for _, group in order:
        target = min(range(shards), key=lambda i: (len(buckets[i]), i))
        buckets[target].extend(group)
    for bucket in buckets:
        bucket.sort(key=lambda r: r["c"])
    return buckets


def existing_line(fact: dict, rejudge: bool) -> dict:
    return {"f": fact.get("fact_id"), "domain": fact.get("domain"),
            "tier": fact.get("sensitivity"), "claim": fact.get("claim"),
            "recurrence": fact.get("recurrence"),
            "rejudge": bool(rejudge)}


def cmd_prepare(a: argparse.Namespace) -> int:
    t0 = time.monotonic()
    clusters = read_jsonl(pathlib.Path(a.clustered))
    out_dir = pathlib.Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    existing_facts: list[dict] = []
    if a.existing:
        _, existing_facts = read_ledger(a.existing)
    existing_ids = {str(f.get("fact_id")) for f in existing_facts}

    state_path = pathlib.Path(a.state) if a.state else out_dir / "merge-state.json"
    state = load_state(state_path if a.existing or a.state else None)

    records = plan(clusters, a.format, state, existing_ids)
    rows: list[dict] = []
    for rec in records:
        if rec["status"] != "judge":
            continue
        row = compact(clusters[rec["index"]], rec["index"])
        if rec["known"]:
            row["known"] = rec["known"]
        if rec.get("dropped_members"):
            row["dropped_members"] = rec["dropped_members"]
        rows.append(row)

    # --shards auto (the default): the count follows the clusters, so the
    # cluster -> prepare chain runs as one command, with no need to break the
    # chain by hand to read the cluster count first.
    shards = a.shards if a.shards and a.shards > 0 else max(
        1, min(SHARD_MAX, -(-len(rows) // SHARD_DIVISOR)))
    files: list[str] = []
    shard_sizes: list[int] = []
    if shards > 1:
        for n, bucket in enumerate(shard_rows(rows, shards), 1):
            path = out_dir / f"merge-input-{n}.jsonl"
            write_jsonl(path, bucket)
            files.append(str(path))
            shard_sizes.append(len(bucket))
    else:
        path = out_dir / "merge-input.jsonl"
        write_jsonl(path, rows)
        files.append(str(path))
        shard_sizes.append(len(rows))

    # Authenticate before the shard reads: staged-premise claims and
    # contradicting clusters get one channel-scoped query each, and the
    # evidence lands on the merge-input line. The shard decides with it.
    probe_summary: dict | None = None
    if a.channel is not None:
        import authenticate  # sibling; imported here so prepare without --channel needs no tl CLI
        probe_summary = authenticate.run(
            a.channel, [pathlib.Path(f) for f in files], pathlib.Path(a.clustered),
            a.max_queries)
        probe_path = out_dir / "probe.json"
        probe_path.write_text(json.dumps(probe_summary, ensure_ascii=False, indent=1),
                              encoding="utf-8")
        probe_summary = {k: v for k, v in probe_summary.items() if k != "results"}
        probe_summary["probe_file"] = str(probe_path)

    if existing_facts:
        rejudge_ids = {f for rec in records if rec["status"] == "judge"
                       for f in rec["known"]}
        path = out_dir / "merge-existing.jsonl"
        write_jsonl(path, [existing_line(f, str(f.get("fact_id")) in rejudge_ids)
                           for f in existing_facts])
        files.append(str(path))

    counts = {"clusters": len(clusters),
              "judged": sum(1 for r in records if r["status"] == "judge"),
              "rejudge": sum(1 for r in records if r.get("rejudge")),
              "additive": sum(1 for r in records if r["status"] == "additive"),
              "auto_dropped": sum(1 for r in records if r["status"] == "auto_dropped"),
              "carry_dropped": sum(1 for r in records if r["status"] == "carry_dropped"),
              "existing_facts": len(existing_facts)}
    elapsed = round(time.monotonic() - t0, 1)
    print(json.dumps({**counts, "files": files, "shards": shards,
                      "shard_sizes": shard_sizes, "format": a.format,
                      "probe": probe_summary,
                      "elapsed_s": elapsed,
                      "note": ("one line per cluster the agent must judge; "
                               "auto-dropped and additive clusters never "
                               "reach it")}, indent=1))
    funnel(stage="merge-prepare", elapsed_s=elapsed, shards=shards, **counts)
    return 0


# --------------------------------------------------------------------------- #
# expand
# --------------------------------------------------------------------------- #
def load_decisions(paths: list[str]) -> tuple[dict[str, dict], list[str],
                                              list[dict], list[str]]:
    """Merge the decision files. Later files override earlier ones per id,
    which is what makes the exit-3 re-ask a small patch instead of a rewrite.

    ``selected`` is a **union** across files, in first-seen order, because a
    sharded merge returns one file per shard and each shard can only nominate
    from the domains it saw: replacing would let the last shard read silently
    decide the whole page. ``expand`` still owns the final count.

    The identity-lane ``facts`` list is a **union** by ``ref`` for exactly
    the same reason: a sharded merge gives each shard its own slice of the
    lane, so replacing would keep only the last file read and silently drop
    the rest, along with every ``corroborates`` call the earlier shards made.
    Later files win per ``ref`` when they are a PATCH of the file that set it
    (they re-decide at least one of its clusters, or carry no decisions at
    all); a later SHARD that reuses the ref (its decisions are disjoint, so it
    is judging other clusters and numbered its own slice from ``s1`` again)
    has its ref namespaced ``s<shard>-<ref>`` and appended, and its own
    ``selected`` picks follow the rename. Without the rename, lane facts are
    lost to that collision with no violation raised, since every file's
    ``facts`` is non-empty. A record with no ``ref`` cannot be keyed,
    so it is appended. An empty or omitted ``facts`` leaves the union standing,
    which is what a shard whose domains hold no lane record returns. A file
    that changes nothing at all is still a violation: a patch that no-ops is
    the failure mode that costs a stage a manual diagnosis."""
    decisions: dict[str, dict] = {}
    selected: list[str] = []
    identity: list[dict] = []
    problems: list[str] = []
    ref_slot: dict[str, int] = {}
    ref_keys: dict[str, set[str]] = {}     # ref -> decision keys of the file that set it
    for n, p in enumerate(paths, 1):
        path = pathlib.Path(p)
        m = re.search(r"(?:^|-)s(\d+)\b", path.stem)
        shard = f"s{m.group(1)}" if m else f"f{n}"
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "",
                     path.read_text(encoding="utf-8").strip())
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            problems.append(f"{path.name}: not JSON ({exc})")
            continue
        if not isinstance(data, dict):
            problems.append(f"{path.name}: envelope is not an object")
            continue
        got = data.get("decisions")
        if not isinstance(got, dict):
            problems.append(f"{path.name}: no `decisions` object")
            continue
        touched = False
        own_keys: set[str] = set()
        for key, value in got.items():
            if not isinstance(value, dict):
                problems.append(f"{path.name}: decision for {key} is not an object")
                continue
            decisions[str(key)] = value
            own_keys.add(str(key))
            touched = True
        renamed: dict[str, str] = {}
        if "facts" in data:
            if not isinstance(data["facts"], list):
                problems.append(f"{path.name}: `facts` is not a list")
            else:
                recs = [x for x in data["facts"] if isinstance(x, dict)]
                if len(recs) != len(data["facts"]):
                    problems.append(f"{path.name}: a `facts` entry is not an object")
                for rec in recs:
                    ref = str(rec.get("ref") or "").strip()
                    if not ref:
                        identity.append(rec)
                        continue
                    if (ref in ref_slot and own_keys
                            and not (own_keys & ref_keys.get(ref, set()))):
                        # another shard's numbering, not a patch of this record
                        new_ref = f"{shard}-{ref}"
                        renamed[ref] = new_ref
                        rec = dict(rec, ref=new_ref)
                        ref = new_ref
                    if ref in ref_slot:
                        identity[ref_slot[ref]] = rec
                    else:
                        ref_slot[ref] = len(identity)
                        identity.append(rec)
                    ref_keys[ref] = ref_keys.get(ref, set()) | own_keys
                if recs:
                    touched = True
        if isinstance(data.get("selected"), list):
            for x in data["selected"]:
                pick = renamed.get(str(x), str(x))
                if pick not in selected:
                    selected.append(pick)
            touched = True
        if not touched:
            problems.append(
                f"{path.name}: carries no decisions, no `selected` and no "
                "`facts`, so it changes nothing; a patch file must say what "
                "it is patching")
    return decisions, selected, identity, problems


def _alias_field(rec: dict, field: str, allowed: set[str],
                 aliases: dict[str, str], label: str) -> str | None:
    """Rewrite one near-miss enum value in place. Returns a
    ``label.field: was -> now`` note, or None when there was nothing to do."""
    got = rec.get(field)
    if not isinstance(got, str) or got in allowed:
        return None
    now = aliases.get(got.strip().lower())
    if not now:
        return None
    rec[field] = now
    return f"{label}.{field}: {got} -> {now}"


def alias_enums(decisions: dict[str, dict], identity: list[dict]) -> list[str]:
    """Rewrite near-miss enum values to the enum, in place, before ``validate``
    sees them. Returns one ``ref.field: was -> now`` note per rewrite so the
    caller can report them: a correction nobody sees is how a lane keeps
    getting it wrong. A value with no single sensible target is left alone for
    ``validate`` to reject with the allowed list.

    Two stages reach for words the enums do not carry, and prose in the prompt
    has not stopped either. The socials lane writes its own ``facts`` records
    rather than judging clusters, so it invents domain labels ("hobbies",
    "gear", "history"). The merge agent carries the extractor's confidence
    vocabulary downstream ("likely"), which otherwise costs a re-ask. Both
    are near-misses with exactly one sensible target, so they are
    normalised here rather than argued with in the prompt."""
    notes: list[str] = []
    # Only `confidence` is aliased on the decision path, and deliberately not
    # `tier`: the merge agent judges against a rubric that states the five
    # tiers, and its tier vocabulary has never drifted, so a wrong tier there
    # should still fail loudly. The confidence field is different, it is the
    # extractor's own vocabulary arriving one stage late.
    for key, dec in sorted(decisions.items()):
        if not isinstance(dec, dict):
            continue
        note = _alias_field(dec, "confidence", CONFIDENCE,
                            CONFIDENCE_ALIASES, key)
        if note:
            notes.append(note)
    for i, rec in enumerate(identity):
        if not isinstance(rec, dict):
            continue
        label = rec.get("ref") or f"facts[{i}]"
        for field, allowed, aliases in (
                ("domain", DOMAINS, DOMAIN_ALIASES),
                ("sensitivity", SENSITIVITY, SENSITIVITY_ALIASES),
                ("confidence", CONFIDENCE, CONFIDENCE_ALIASES)):
            note = _alias_field(rec, field, allowed, aliases, label)
            if note:
                notes.append(note)
    return notes


def numbers_in(text: str) -> list[str]:
    return _NUMBER.findall(text or "")


def resolve_fold(start: str, folds: dict[str, str]) -> tuple[str | None, bool]:
    """Follow a fold chain to its terminal. Returns (terminal, cycle)."""
    seen = {start}
    node = start
    while node in folds:
        node = folds[node]
        if node in seen:
            return None, True
        seen.add(node)
    return node, False


def validate(records: list[dict], clusters: list[dict], decisions: dict[str, dict],
             existing: dict[str, dict], identity: list[dict],
             fallback: bool) -> tuple[dict, dict, list[dict]]:
    """The contract check. Returns (violations, folds, fallbacks)."""
    violations: dict[str, list[str]] = {}
    existing_ids = set(existing)

    def bad(key: str, why: str) -> None:
        violations.setdefault(key, []).append(why)

    judged = {r["c"]: r for r in records if r["status"] == "judge"}
    by_cid = {cid(r["index"]): clusters[r["index"]] for r in records}

    for key in decisions:
        if key not in judged:
            bad(key, "unknown id: not a cluster this round asked about")

    for key in judged:
        if key not in decisions:
            bad(key, "missing decision")

    kept: dict[str, dict] = {}
    folds: dict[str, str] = {}
    for key, dec in decisions.items():
        if key not in judged:
            continue
        action = dec.get("action")
        if action not in ACTIONS:
            bad(key, f"action must be one of {sorted(ACTIONS)}, got {action!r}")
            continue
        if action == "keep":
            kept[key] = dec
        elif action == "fold":
            target = str(dec.get("target") or "")
            if not target:
                bad(key, "fold without a target")
            else:
                folds[key] = target

    for key, dec in kept.items():
        tier = dec.get("tier")
        if tier is not None and tier not in SENSITIVITY:
            bad(key, f"tier must be one of {sorted(SENSITIVITY)}, got {tier!r}")
        conf = dec.get("confidence")
        if conf is not None and conf not in CONFIDENCE:
            bad(key, f"confidence must be one of {sorted(CONFIDENCE)}, got {conf!r}")
        if dec.get("ended") not in (None, True, False):
            bad(key, f"ended takes only true or false, got {dec.get('ended')!r}")

    # fold targets: a c* target must be a kept cluster, an f* target must exist
    # in the ledger we are refreshing. A fold MAY cross a life domain. The
    # extractor files each passage independently, so one fact routinely arrives
    # as two candidates in two domains ("his real name is X" under `other`,
    # "real name is X" under `origin`); refusing the fold there left the only
    # options as a duplicate in the ledger or a deleted copy. The merged fact
    # takes the TARGET's domain, because `fact_from_cluster` builds every record
    # from the terminal cluster. Crossings are reported rather than silent, so a
    # run can still see when the extractor's filing disagreed with itself.
    for key, target in folds.items():
        if target.startswith("f"):
            if target not in existing_ids:
                bad(key, f"fold target {target} is not in --existing")
            continue
        if target not in kept:
            bad(key, f"fold target {target} is not a kept cluster")

    for key in folds:
        _, cycle = resolve_fold(key, {k: v for k, v in folds.items()
                                      if not v.startswith("f")})
        if cycle:
            bad(key, "fold chain is a cycle")

    for key, dec in kept.items():
        sup = dec.get("supersedes")
        if sup is None:
            continue
        if not isinstance(sup, str):
            # A list here is the agent saying one fact replaces several. The
            # old message blamed the target for not existing, which sent the
            # diagnosis the wrong way for a whole re-ask.
            bad(key, f"supersedes takes a single cluster or fact id, not a "
                     f"{type(sup).__name__}: supersede the closest fact and "
                     "handle any others as their own decisions")
            continue
        if sup.startswith("f"):
            if sup not in existing_ids:
                bad(key, f"supersedes target {sup} is not in --existing")
        elif sup not in kept:
            bad(key, f"supersedes target {sup} is not a kept cluster")

    # A narrowed claim may only narrow: non-empty, every number and name in it
    # from the quote or the cluster's own claim, and every family word in the
    # quote as the creator's own relative (the assembler's check). A cheap
    # tripwire, not a proof, but it is the one that catches an invented figure.
    fallbacks: list[dict] = []
    for key, dec in kept.items():
        if "claim" not in dec:
            continue
        claim = str(dec.get("claim") or "").strip()
        line = by_cid[key]
        # Token comparison, never substring: "has 3 dogs" must not pass on a
        # quote that says "13 dogs".
        quote = str((line.get("verdict") or {}).get("quote") or "")
        evidence = set(numbers_in(quote)) | set(numbers_in(cluster_claim(line)))
        # names: the quote's words, the cluster claim's, and any name the
        # extractor corrected from a caption misspelling, matched by _ax.word_in
        corrected = " ".join(str(v) for v in
                             ((line.get("verdict") or {}).get("entity_corrections") or {}).values())
        names = _ax.bare_words(quote) | _ax.bare_words(cluster_claim(line)) | _ax.bare_words(corrected)
        why = None
        if not claim:
            why = "narrowed claim is empty"
        else:
            new = [n for n in numbers_in(claim) if n not in evidence]
            # the claim's first word is grammar ("Owns two dogs"), never a name
            new += [n for n in _name_tokens(" ".join(claim.split()[1:]))
                    if not _ax.word_in(n, names)]
            new += [w for w in _ax.claim_overreach(claim, quote,
                                                   english=_ax.is_english(line.get("window")))
                    if w in _ax.FAMILY_WORDS or w.rstrip("s") in _ax.FAMILY_WORDS]
            if new:
                why = ("narrowed claim introduces names, numbers or relatives absent "
                       f"from the quote and the cluster claim: {', '.join(new)}")
        if why is None:
            continue
        if fallback:
            fallbacks.append({"c": key, "reason": why})
        else:
            bad(key, why)

    # The identity lane. A social/web fact names its source instead of quoting
    # a transcript, so it is checked on entirely different fields, and it may
    # never carry the transcript lane's, because lanes never masquerade.
    refs: set[str] = set()
    for i, rec in enumerate(identity):
        label = str(rec.get("ref") or f"facts[{i}]")
        if label in refs:
            bad(label, "duplicate ref")
        refs.add(label)
        if rec.get("provenance") not in IDENTITY_PROVENANCE:
            bad(label, "provenance must be one of "
                       f"{sorted(IDENTITY_PROVENANCE)}, got "
                       f"{rec.get('provenance')!r}")
        for field in IDENTITY_REQUIRED:
            if not str(rec.get(field) or "").strip():
                bad(label, f"{field} is required on an identity-lane fact")
        for field in IDENTITY_BANNED:
            if rec.get(field) is not None:
                bad(label, f"an identity-lane fact carries no {field}")
        if rec.get("domain") is not None and rec.get("domain") not in DOMAINS:
            bad(label, f"domain must be one of {sorted(DOMAINS)}, "
                       f"got {rec.get('domain')!r}")
        if rec.get("sensitivity") is not None and rec.get("sensitivity") not in SENSITIVITY:
            bad(label, f"sensitivity must be one of {sorted(SENSITIVITY)}, "
                       f"got {rec.get('sensitivity')!r}")
        conf = rec.get("confidence")
        if conf is not None and conf not in CONFIDENCE:
            bad(label, f"confidence must be one of {sorted(CONFIDENCE)}, got {conf!r}")
        corr = rec.get("corroborates")
        if corr is None:
            continue
        corr = str(corr)
        if corr.startswith("f"):
            if corr not in existing_ids:
                bad(label, f"corroborates target {corr} is not in --existing")
            elif (rec.get("provenance") == BIO
                  and (existing.get(corr) or {}).get("provenance") != "transcript"):
                # A written bio confirmed by another written bio is one source
                # twice, not corroboration. Only the videos can verify the
                # About box.
                bad(label, f"a bio fact may only corroborate a transcript fact; {corr} is "
                           f"{(existing.get(corr) or {}).get('provenance')!r}")
        elif corr not in kept:
            bad(label, f"corroborates target {corr} is not a kept cluster")

    return violations, folds, fallbacks


def default_confidence(line: dict, fmt: str) -> str:
    """The extractor's own call carries on every format: on a shared-voice
    upload the rubric lets it say ``confirmed`` only on a named sign of the
    creator's voice (``evidence-rules.md``, Attribution), and the judge sees
    that sign in ``speaker_evidence`` and can lower it."""
    extractor = str((line.get("verdict") or {}).get("confidence") or "")
    return "confirmed" if extractor == "confirmed" else "unconfirmed"


def capped_confidence(line: dict, fmt: str, override: str | None) -> str:
    """Agent override beats the default; the evidence-rules cap beats both:
    an unattributed (unclear/narration) window is ``unconfirmed`` whatever
    the override says."""
    value = override if override in CONFIDENCE else default_confidence(line, fmt)
    speaker = str((line.get("verdict") or {}).get("speaker_guess") or "")
    if speaker in ("unclear", "narration"):
        return "unconfirmed"
    return value


def hook_only(line: dict, videos: list[str]) -> bool:
    """A staged upload (its title marks a prank, challenge or stunt), every
    member in the first ``HOOK_SECONDS``, and no other video says it. An
    ordinary upload's opening is the creator introducing themselves."""
    members = members_of(line)
    staged = str((line.get("window") or {}).get("format_hint") or "") == "staged"
    if not staged or not members or len(videos) > 1:
        return False
    return all(float(m.get("start") or 0) < HOOK_SECONDS for m in members)


_AGO = re.compile(r"\b(?:about |around |almost |over |nearly |like )?(\d{1,2}|a|an|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)\s+(?:and a half |or so )?(years?|months?)\s+ago\b", re.I)
_WORD_NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
             "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
             "fifteen": 15, "twenty": 20}
_CHANNEL_START = re.compile(r"\b(start|started|launch|launched|began|begin|create|created|made)\b.{0,40}\b(channel|youtube|videos)\b|\b(channel|youtube)\b.{0,30}\b(started|launched|began)\b", re.I)


def dated_claim(claim: str, published: str | None, first_upload: str | None) -> tuple[str, str | None]:
    """"X years ago" becomes a year from the upload date ("about 2020, said
    in 2025"). A claim about the channel's own start is checked against the
    channel's first upload; when they disagree by a year or more, the first
    upload's year is used and the creator's words are kept beside it.
    Returns the claim and a note (None when nothing changed)."""
    year_said = str(published or "")[:4]
    if not year_said.isdigit():
        return claim, None
    try:
        said = dt.date.fromisoformat(str(published)[:10])
    except ValueError:
        said = dt.date(int(year_said), 7, 1)
    m = _AGO.search(claim or "")
    if not m:
        return claim, None
    n = int(m.group(1)) if m.group(1).isdigit() else _WORD_NUM.get(m.group(1).lower(), 0)
    unit = m.group(2).lower()
    months = n * 12 if unit.startswith("year") else n
    year = (said.year * 12 + said.month - 1 - months) // 12
    first = str(first_upload or "")[:4]
    if _CHANNEL_START.search(claim) and first.isdigit() and abs(int(first) - year) >= 1:
        text = f"in {first} (the channel's first upload; said \"{m.group(0)}\" in {year_said})"
        note = f"channel start: creator said {m.group(0)} in {year_said}, first upload {first}"
    else:
        text = f"in about {year} (said in {year_said})"
        note = f"{m.group(0)} -> {year}"
    return claim[:m.start()] + text + claim[m.end():], note


def fact_from_cluster(line: dict, fact_id: str, dec: dict, fmt: str, channel: str,
                      videos: list[str], keys: list[str],
                      use_original_claim: bool,
                      probe_entry: dict | None = None,
                      first_upload: str | None = None) -> dict:
    v = line.get("verdict") or {}
    w = line.get("window") or {}
    claim = cluster_claim(line)
    if not use_original_claim and str(dec.get("claim") or "").strip():
        claim = str(dec["claim"]).strip()
    tier = dec.get("tier") if dec.get("tier") in SENSITIVITY else v.get("sensitivity")
    tier = tier if tier in SENSITIVITY else "none"
    vid = w.get("video_id")
    start = w.get("start")
    staged = str(w.get("format_hint") or "") == "staged"
    only_staged = staged_only(line, probe_entry)
    confidence = capped_confidence(line, fmt, dec.get("confidence"))
    if only_staged:
        # said inside a set-up and found nowhere else: kept, never dropped,
        # never confirmed, never on a brand-facing page
        confidence = "unconfirmed"
    hook = hook_only(line, videos)
    if hook:
        confidence = "unconfirmed"
    claim, date_note = dated_claim(claim, w.get("published"), first_upload)
    fact = {
        "fact_id": fact_id,
        "claim": claim,
        "domain": v.get("life_domain"),
        "provenance": "transcript",
        "quote": v.get("quote"),
        "video": f"{channel}:{vid}",
        "start": start,
        "url": f"https://www.youtube.com/watch?v={vid}&t={start}s",
        "published": w.get("published"),
        "last_seen": newest_evidence(line, probe_entry),
        "recurrence": len(videos),
        "confidence": confidence,
        "sensitivity": tier,
        "sensitive": tier in WITHHELD,
        "speaker": v.get("speaker_guess") if v.get("speaker_guess") in ("cohost", "shared") else "host",
        "people": v.get("people") or [],
        "superseded_by": None,
        "selected": False,
        "members": keys,
    }
    if dec.get("ended") is True:
        fact["ended"] = True
    if hook:
        fact["hook_only"] = True
    if date_note:
        fact["dated"] = date_note
    if staged:
        fact["staged"] = True
        fact["staged_only"] = only_staged
        p = (probe_entry or {}).get("probe") or {}
        if p.get("videos") is not None:
            fact["probe"] = {"videos": p.get("videos"),
                             "non_staged_videos": p.get("non_staged_videos"),
                             "newest": p.get("newest")}
    if str(dec.get("gloss") or "").strip():
        fact["gloss"] = str(dec["gloss"]).strip()
    return fact


def fail(violations: dict[str, list[str]]) -> int:
    """Exit 3 with the offending ids, so the orchestrator re-asks the agent
    for exactly those and never hand-patches the ledger."""
    print(json.dumps({"error": "decision contract violated",
                      "violations": {k: v for k, v in sorted(violations.items())},
                      "hint": ("re-ask the agent for exactly these ids and "
                               "pass the answer as another --decisions file; "
                               "a second failure runs expand "
                               "--fallback-original")}, indent=1))
    return 3


def identity_fact(rec: dict, fact_id: str) -> dict:
    """A social/web fact: its source and seen-date stand where the transcript
    lane's quote, video and start would be. Alone it is never `confirmed`: only cross-lane corroboration lifts it, and that is applied once both
    sides of the pair exist."""
    tier = rec.get("sensitivity") if rec.get("sensitivity") in SENSITIVITY else "none"
    fact = {
        "fact_id": fact_id,
        "claim": str(rec.get("claim") or "").strip(),
        "domain": rec.get("domain"),
        "provenance": rec.get("provenance"),
        "source_url": str(rec.get("source_url") or "").strip(),
        "seen_date": str(rec.get("seen_date") or "").strip(),
        "recurrence": 1,
        "confidence": "unconfirmed",
        "sensitivity": tier,
        "sensitive": tier in WITHHELD,
        "superseded_by": None,
        "selected": False,
        "members": [],
    }
    if str(rec.get("gloss") or "").strip():
        fact["gloss"] = str(rec["gloss"]).strip()
    # A written-source excerpt is not a quote: it has a URL and a seen-date
    # where a quote has a video and a timestamp, and it is cut from the stored
    # bio text mechanically by `bio_lane.py`, never authored by a model. The
    # ban on `quote`/`video`/`start`/`url` stands.
    if str(rec.get("source_excerpt") or "").strip():
        fact["source_excerpt"] = str(rec["source_excerpt"]).strip()
    if str(rec.get("sensitivity_source") or "").strip():
        fact["sensitivity_source"] = str(rec["sensitivity_source"]).strip()
    return fact


def bio_key(text) -> str:
    """The comparison form of a bio claim or excerpt: lower-cased, punctuation
    and whitespace collapsed, so a re-read About line matches its earlier self."""
    return " ".join(re.sub(r"[^\w\s]", " ", str(text or "").lower()).split())


def bio_gate(facts: list[dict]) -> tuple[list[dict], list[dict]]:
    """``(kept, dropped)``: what an uncorroborated bio fact is allowed to be.

    Run over EVERY bio fact in the final ledger, including records carried
    from ``--existing`` on a refresh, which never pass through the corroboration
    pass again, and only after tier inheritance, so a bio fact that just
    inherited a withheld tier from a transcript fact naming the same person is
    judged at the tier it ended up with.

    Corroborated (a transcript fact says the same thing): a normal confirmed
    fact. Uncorroborated and sensitive: dropped from the ledger, because "he
    says in his own bio that he has ADHD" is exactly the sentence this pipeline
    exists not to hand a brand. Uncorroborated otherwise: kept, never selected,
    never in a pitch, and rendered only under "In their own words
    (unverified)"."""
    kept: list[dict] = []
    dropped: list[dict] = []
    for fact in facts:
        if fact.get("provenance") != BIO:
            kept.append(fact)
            continue
        corroborated = (fact.get("confidence") == "confirmed"
                        and bool(fact.get("corroborated_by")))
        fact["unverified_bio"] = not corroborated
        if corroborated:
            kept.append(fact)
            continue
        fact["confidence"] = "unconfirmed"
        fact["selected"] = False
        if fact.get("sensitivity") in WITHHELD:
            dropped.append(fact)
            continue
        kept.append(fact)
    return kept, dropped


def corroboration_holds(target: dict | None) -> bool:
    """Whether a fact can still corroborate a bio claim: a transcript fact,
    not said only inside a staged premise, and not retired. The renderer's
    ``bio_corroborated`` asks the same question again at the other end."""
    return (target is not None
            and target.get("provenance") == "transcript"
            and not target.get("staged_only")
            and not target.get("retired_reason"))


def moment_key(fact: dict) -> tuple | None:
    """The passage a transcript fact quotes: video plus timestamp. None for a
    fact with no located moment (a bio or social record)."""
    vid, start = fact.get("video"), fact.get("start")
    if not vid or start is None:
        return None
    return (str(vid), int(float(start)))


def selectable(fact: dict) -> bool:
    """Whether a fact may carry ``selected``, which is what reaches a
    brand-facing page's "who they are" section.

    ``children`` and ``location`` never do. ``clinical`` does only where the
    creator made it public themselves: for a transcript fact that is 3+
    distinct videos, per ``references/evidence-rules.md``, since one passing
    mention never qualifies. A social or web record is public by the act of
    having been posted, and its recurrence is always 1 because the record
    carries no videos at all, so recurrence cannot be the test there.

    ``build_html.py --check`` refuses a selected fact at a withheld tier at
    the other end of the pipeline. That check is the backstop; this is the
    end that owns the rule, so nothing is left to be caught at render time.
    Nothing opts itself in: the fill-to-target loop reads this too."""
    if fact.get("retired_reason") or fact.get("ended"):
        return False
    tier = fact.get("sensitivity")
    if tier in ("children", "location"):
        return False
    if fact.get("staged_only"):
        return False
    if fact.get("provenance") == BIO and fact.get("confidence") != "confirmed":
        return False
    if tier == "clinical" and fact.get("provenance") == "transcript":
        return int(fact.get("recurrence") or 0) >= 3
    if tier_hint.names_child(fact.get("claim"), fact.get("quote")):
        return False
    if tier_hint.names_money(fact.get("claim"), fact.get("quote")):
        return False
    return True


def unselectable_reason(fact: dict) -> str:
    if fact.get("retired_reason"):
        return f"retired: {fact['retired_reason']}"
    if fact.get("ended"):
        return "ended: the evidence shows it is over"
    tier = fact.get("sensitivity")
    if tier in ("children", "location"):
        return f"withheld tier {tier}"
    if fact.get("staged_only"):
        return "said only inside staged premises; no non-staged upload confirms it"
    if fact.get("provenance") == BIO and fact.get("confidence") != "confirmed":
        return "written in their own bio; no upload corroborates it"
    if tier == "clinical":
        return "clinical below three videos"
    if tier_hint.names_child(fact.get("claim"), fact.get("quote")):
        return "names a child"
    if tier_hint.names_money(fact.get("claim"), fact.get("quote")):
        return "names a sum of money"
    return "not eligible"


def _name_tokens(text: str) -> set[str]:
    return {t.lower() for t in re.findall(r"\b[A-Z][a-zA-Z'’-]{2,}\b", text or "")
            if t not in ("The", "She", "He", "They", "Her", "His", "Their", "YouTube",
                         "Instagram", "TikTok", "Currently", "Real", "Has", "Is",
                         "Was", "Married", "Grew", "Launched", "Worked", "Operates")}


def is_recent(fact: dict, today: str | None = None) -> bool:
    """``last_seen`` inside the last ``RECENT_MONTHS`` of the run date. A
    fact with no date (a social or bio record) is not recent. A fact from a
    ledger saved before ``last_seen`` existed falls back to ``published``,
    which is never later."""
    seen = str(fact.get("last_seen") or fact.get("published") or "")[:10]
    today = (today or RUN_DATE or dt.date.today().isoformat())[:10]
    if not seen or not today:
        return False
    y, m = int(today[:4]), int(today[5:7])
    m -= RECENT_MONTHS
    while m <= 0:
        m += 12
        y -= 1
    return seen >= f"{y:04d}-{m:02d}-{today[8:10]}"


def rank_key(fact: dict) -> tuple:
    """Strongest first: confirmed before unconfirmed, recent before older,
    then recurrence, then the fact id so the pick never depends on dict order."""
    return (0 if fact.get("confidence") == "confirmed" else 1,
            0 if is_recent(fact) else 1,
            -int(fact.get("recurrence") or 0),
            str(fact.get("fact_id")))


# early uploads (at most this many) followed by a gap of more than a year are
# hobby videos from before the channel began, not its start
EARLY_UPLOADS_MAX = 5
START_GAP_DAYS = 365


def channel_start(dates: list[str]) -> str | None:
    """The first upload of the channel as it runs today: the oldest upload,
    unless at most ``EARLY_UPLOADS_MAX`` earlier uploads sit before a gap of
    more than ``START_GAP_DAYS``; then the first upload after that gap."""
    days = sorted(dt.date.fromisoformat(d[:10]) for d in dates if d and d[:10].count("-") == 2)
    if not days:
        return None
    start = 0
    for i in range(min(EARLY_UPLOADS_MAX, len(days) - 1)):
        if (days[i + 1] - days[i]).days > START_GAP_DAYS:
            start = i + 1
    return days[start].isoformat()


def first_upload_date(channel: str | None) -> str | None:
    """The channel's start (``channel_start``), one platform query, only when a
    claim speaks of the channel's own start. None when it cannot be fetched."""
    if not channel or not str(channel).isdigit():
        return None
    try:
        rows = tl_data.db_es({
            "size": EARLY_UPLOADS_MAX + 1, "_source": ["publication_date"],
            "query": {"bool": {"filter": [{"term": {"doc_type": "article"}},
                                          {"term": {"channel.id": int(channel)}}]}},
            "sort": [{"publication_date": "asc"}]})
        return channel_start([str((r or {}).get("publication_date") or "") for r in rows])
    except Exception:          # noqa: BLE001  reported in the summary, never raised
        return None


def people_list(facts: list[dict]) -> dict:
    """One row per exact spelling across the active ledger: the relation
    words seen, the facts, the videos and the last mention. ``two_names``
    lists a two-word name whose halves each appear as a single name elsewhere:
    two people a caption list ran together."""
    rows: dict[str, dict] = {}
    for f in facts:
        if f.get("superseded_by") or f.get("retired_reason"):
            continue
        for p in f.get("people") or []:
            name = str(p.get("name") or "").strip()
            if not name:
                continue
            row = rows.setdefault(name, {"relations": [], "facts": [], "videos": set(),
                                         "last_mention": None})
            rel = p.get("relation")
            if rel and rel not in row["relations"]:
                row["relations"].append(rel)
            row["facts"].append(str(f.get("fact_id")))
            if f.get("video"):
                row["videos"].add(str(f["video"]))
            seen = str(f.get("last_seen") or f.get("published") or "")[:10]
            if seen and (row["last_mention"] is None or seen > row["last_mention"]):
                row["last_mention"] = seen
    singles = {n.lower() for n in rows if len(n.split()) == 1}
    two_names = [n for n in rows if len(n.split()) == 2
                 and all(w.lower() in singles for w in n.split())]
    out = {n: {"relations": r["relations"], "facts": r["facts"],
               "videos": len(r["videos"]), "last_mention": r["last_mention"]}
           for n, r in sorted(rows.items())}
    return {"people": out, "two_names": two_names}


def cmd_expand(a: argparse.Namespace) -> int:
    t0 = time.monotonic()
    global RUN_DATE
    RUN_DATE = dt.date.today().isoformat()
    clusters = read_jsonl(pathlib.Path(a.clustered))
    out_path = pathlib.Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    existing_facts: list[dict] = []
    if a.existing:
        _, existing_facts = read_ledger(a.existing)
    existing_by_id = {str(f.get("fact_id")): dict(f) for f in existing_facts}
    existing_ids = set(existing_by_id)

    state_path = pathlib.Path(a.state) if a.state else out_path.parent / "merge-state.json"
    prior_state = load_state(state_path if (a.existing or a.state) else None)
    probe_path = out_path.parent / "probe.json"
    probes = load_probe(probe_path)

    records = plan(clusters, a.format, prior_state, existing_ids)
    by_c = {r["c"]: r for r in records}

    decisions, agent_selected, identity, problems = load_decisions(a.decisions)
    enum_aliases = alias_enums(decisions, identity)
    violations, folds, fallbacks = validate(records, clusters, decisions,
                                            existing_by_id, identity,
                                            a.fallback_original)
    if problems:
        violations.setdefault("_files", []).extend(problems)
    if violations:
        return fail(violations)

    fallback_ids = {f["c"] for f in fallbacks}
    kept = [r["c"] for r in records
            if r["status"] == "judge" and decisions[r["c"]].get("action") == "keep"]
    kept_set = set(kept)

    # Every folded cluster resolves to the terminal it lands on: a c* chain
    # ends at a kept cluster, an f* target ends at an existing fact.
    terminal: dict[str, str] = {}
    for key in folds:
        node, seen = key, {key}
        while node in folds:
            node = folds[node]
            if node.startswith("f") or node in seen:
                break
            seen.add(node)
        terminal[key] = node

    # fact ids: fresh builds number in cluster order; a refresh continues
    # after the ledger's highest id so an existing fact never changes id.
    next_num = 0
    for fid in existing_ids:
        m = re.fullmatch(r"f(\d+)", fid)
        if m:
            next_num = max(next_num, int(m.group(1)))

    assigned: dict[str, str] = {}          # cluster id -> fact id
    for key in kept:
        rec = by_c[key]
        if rec["status"] == "judge" and rec["known"]:
            # a re-judged cluster keeps the first fact id it inherited
            reuse = rec["known"][0]
            if reuse not in assigned.values():
                assigned[key] = reuse
                continue
        next_num += 1
        assigned[key] = f"f{next_num:03d}"

    additive = [r for r in records if r["status"] == "additive"]
    for rec in additive:
        assigned[rec["c"]] = rec["fact_id"]

    # A drop can re-judge evidence that previously owned an active fact. That
    # old fact must not fall through to the blanket carry-forward below.
    # Preserve it as retired history unless another surviving cluster still
    # owns the same fact id this round.
    reused_ids = set(assigned.values())
    reused_ids.update(t for t in terminal.values() if str(t).startswith("f"))
    retired_by_drop: dict[str, str] = {}
    for key, dec in decisions.items():
        if dec.get("action") != "drop":
            continue
        reason = str(dec.get("reason") or "evidence rejected by the merge pass")
        for old in by_c[key].get("known") or []:
            if old not in reused_ids:
                retired_by_drop[old] = reason

    # identity-lane facts are numbered after the clusters
    identity_ids: list[str] = []
    identity_by_ref: dict[str, str] = {}
    for i, rec in enumerate(identity):
        next_num += 1
        fact_id = f"f{next_num:03d}"
        identity_ids.append(fact_id)
        identity_by_ref[str(rec.get("ref") or f"facts[{i}]")] = fact_id

    # Supersession is checked again once ids are resolved: a re-judged cluster
    # that reuses f003 may not also claim to supersede f003, and two facts may
    # not supersede each other.
    sup_edges: dict[str, str] = {}
    owner = {fact_id: key for key, fact_id in assigned.items()}
    post: dict[str, list[str]] = {}
    for key in kept:
        raw = decisions[key].get("supersedes")
        if raw is None:
            continue
        target = assigned.get(str(raw), str(raw))
        if target == assigned[key]:
            post.setdefault(key, []).append(
                f"supersedes resolves to the fact itself ({target})")
            continue
        sup_edges[assigned[key]] = target
        # Latest wins, on evidence, not on the two lines the shard happened to
        # see. If the superseded cluster's newest evidence (its own uploads,
        # or what authenticate.py found saying the same thing) is newer than
        # the superseder's, the decision points the wrong way. Refused as a
        # re-ask with the dates, never edited here: the shard decides.
        if not str(raw).startswith("f") and str(raw) in by_c:
            newer = newest_evidence(clusters[by_c[str(raw)]["index"]], probes.get(str(raw)))
            older = newest_evidence(clusters[by_c[key]["index"]], probes.get(key))
            if newer and older and newer > older:
                post.setdefault(key, []).append(
                    f"supersedes {raw}, but {raw}'s evidence is dated {newer} and "
                    f"{key}'s {older}: the newer fact stands. Reverse the "
                    f"supersession, or keep both with neither superseding")
    # The identity lane is dated evidence too: a lane record seen this year
    # that corroborates a cluster another cluster just superseded says the
    # superseded fact is the current one (a home claim must not be superseded
    # by a same-year rival while the creator's own bio still says the former).
    for rec in identity:
        corr = rec.get("corroborates")
        if corr is None:
            continue
        corr = str(corr)
        seen = str(rec.get("seen_date") or "")[:10]
        for key in kept:
            if str(decisions[key].get("supersedes")) != corr:
                continue
            older = newest_evidence(clusters[by_c[key]["index"]], probes.get(key))
            if seen and older and seen > older:
                post.setdefault(key, []).append(
                    f"supersedes {corr}, but identity fact {rec.get('ref') or '?'} "
                    f"(seen {seen}) corroborates {corr} and is newer than {key}'s "
                    f"evidence ({older}): {corr} is the current fact. Reverse the "
                    f"supersession or drop the corroboration, with a reason")
    for src in sup_edges:
        node, seen = src, {src}
        while node in sup_edges:
            node = sup_edges[node]
            if node in seen:
                post.setdefault(owner.get(src, src), []).append(
                    "supersedes chain is a cycle")
                break
            seen.add(node)
    if post:
        return fail(post)

    # members that land on each fact: the cluster's own, everything folded in,
    # and (on a refresh) whatever the existing fact already carried.
    keys_by_fact: dict[str, list[str]] = {}
    videos_by_fact: dict[str, list[str]] = {}
    newest_by_fact: dict[str, str] = {}

    def add_evidence(fact_id: str, line: dict) -> None:
        keys = keys_by_fact.setdefault(fact_id, [])
        vids = videos_by_fact.setdefault(fact_id, [])
        seen = newest_evidence(line, None)
        if seen and seen > newest_by_fact.get(fact_id, ""):
            newest_by_fact[fact_id] = seen
        for m in members_of(line):
            key = member_key(m)
            if key not in keys:
                keys.append(key)
            vid = m.get("video_id")
            if vid and vid not in vids:
                vids.append(vid)

    def seed_from_existing(fact_id: str, into: str | None = None) -> None:
        prior = existing_by_id.get(fact_id) or {}
        target = into or fact_id
        keys = keys_by_fact.setdefault(target, [])
        vids = videos_by_fact.setdefault(target, [])
        for key in prior.get("members") or []:
            if key not in keys:
                keys.append(key)
            vid = str(key).rsplit(":", 1)[0]
            if vid and vid not in vids:
                vids.append(vid)
        vid = str(prior.get("video") or "").split(":")[-1]
        if vid and vid not in vids:
            vids.append(vid)
        seen = str(prior.get("last_seen") or prior.get("published") or "")[:10]
        if seen > newest_by_fact.get(target, ""):
            newest_by_fact[target] = seen

    for key, fact_id in assigned.items():
        if fact_id in existing_ids:
            seed_from_existing(fact_id)
        add_evidence(fact_id, clusters[by_c[key]["index"]])

    folded_into: dict[str, list[str]] = {}
    # Folds that merged two domains. Legal, and reported so the extractor's
    # disagreement with itself stays visible in the expand summary.
    crossed_domains: list[str] = []
    for key, target in terminal.items():
        fact_id = assigned.get(target) if not target.startswith("f") else target
        if not fact_id:
            continue
        if fact_id in existing_ids and fact_id not in keys_by_fact:
            seed_from_existing(fact_id)
        add_evidence(fact_id, clusters[by_c[key]["index"]])
        folded_into.setdefault(fact_id, []).append(key)
        src = (clusters[by_c[key]["index"]].get("verdict") or {}).get("life_domain")
        if target.startswith("f"):
            dst = (existing_by_id.get(target) or {}).get("domain")
        else:
            dst = (clusters[by_c[target]["index"]].get("verdict")
                   or {}).get("life_domain")
        if src and dst and src != dst:
            crossed_domains.append(f"{key} ({src}) -> {target} ({dst})")

    # A re-judged cluster inherited several fact ids and kept one of them.
    # The others must not stay active: their evidence pools into the fact that
    # was kept and they are marked superseded by it, history stays, a stale
    # duplicate does not. A fact the decisions already fold into or supersede
    # explicitly is left to that decision, and one that another cluster owns
    # this round is not ours to retire.
    explicit = {str(t) for t in terminal.values() if str(t).startswith("f")}
    explicit |= {str(decisions[k].get("supersedes")) for k in kept
                 if decisions[k].get("supersedes") is not None}
    owned = set(assigned.values())
    reconciled: dict[str, str] = {}
    for key in kept:
        rec = by_c[key]
        for old in rec.get("known") or []:
            if old == assigned[key] or old in explicit or old in owned:
                continue
            if old in reconciled:
                continue
            seed_from_existing(old, into=assigned[key])
            reconciled[old] = assigned[key]

    # ---- build the facts -------------------------------------------------- #
    # the channel's first upload is fetched once, only when a kept claim
    # speaks of the channel's own start in "years ago" terms
    def used_claim(k: str) -> str:
        narrowed = "" if k in fallback_ids else decisions[k].get("claim")
        return str(narrowed or cluster_claim(clusters[by_c[k]["index"]]) or "")

    first_upload = None
    if any(_CHANNEL_START.search(used_claim(k)) and _AGO.search(used_claim(k)) for k in kept):
        first_upload = first_upload_date(a.channel)
    facts: list[dict] = []
    fact_index: dict[str, dict] = {}
    for key in kept:
        fact_id = assigned[key]
        line = clusters[by_c[key]["index"]]
        fact = fact_from_cluster(line, fact_id, decisions[key], a.format,
                                 a.channel, videos_by_fact.get(fact_id, []),
                                 keys_by_fact.get(fact_id, []),
                                 key in fallback_ids, probes.get(key), first_upload)
        # a fold or an inherited fact can carry newer evidence than the
        # representative cluster
        fact["last_seen"] = max(str(fact.get("last_seen") or ""),
                                newest_by_fact.get(fact_id, "")) or None
        facts.append(fact)
        fact_index[fact_id] = fact

    for rec in additive:
        fact_id = rec["fact_id"]
        if fact_id in fact_index:
            # an existing fact whose members now sit in several re-clustered
            # clusters is one fact, not one per cluster: its evidence was
            # already pooled above
            continue
        prior = dict(existing_by_id.get(fact_id) or {})
        prior["recurrence"] = len(videos_by_fact.get(fact_id, []))
        prior["members"] = keys_by_fact.get(fact_id, [])
        prior["last_seen"] = max(str(prior.get("last_seen") or ""),
                                 newest_by_fact.get(fact_id, "")) or None
        facts.append(prior)
        fact_index[fact_id] = prior

    for fact_id, prior in existing_by_id.items():
        if fact_id in fact_index:
            continue
        carried = dict(prior)
        if fact_id in retired_by_drop:
            carried["retired_reason"] = retired_by_drop[fact_id]
            carried["selected"] = False
        if fact_id in keys_by_fact:      # something folded into it this round
            seed_from_existing(fact_id)
            carried["members"] = keys_by_fact[fact_id]
            carried["recurrence"] = len(videos_by_fact[fact_id])
        facts.append(carried)
        fact_index[fact_id] = carried

    for rec, fact_id in zip(identity, identity_ids):
        fact = identity_fact(rec, fact_id)
        facts.append(fact)
        fact_index[fact_id] = fact

    # cross-lane corroboration is the top tier in `evidence-rules.md`: a
    # transcript fact and an identity-lane fact that name the same thing lift
    # each other to `confirmed`.
    corroborated: list[list[str]] = []
    bio_uncorroborated: list[list[str]] = []
    for rec, fact_id in zip(identity, identity_ids):
        raw = rec.get("corroborates")
        if raw is None:
            continue
        target = assigned.get(str(raw), str(raw))
        if target not in fact_index:
            continue
        if (fact_index[fact_id].get("provenance") == BIO
                and not corroboration_holds(fact_index[target])):
            # Only an upload can verify an About box, not one that said it
            # inside a staged premise (the confidence cap the transcript lane
            # already applied), and not one whose evidence was rejected.
            bio_uncorroborated.append([fact_id, target])
            continue
        fact_index[fact_id]["confidence"] = "confirmed"
        fact_index[target]["confidence"] = "confirmed"
        # The link is kept on the fact, not just in this run's summary: the
        # renderer re-derives whether a bio fact is really corroborated (the
        # quote may fail verification downstream) instead of trusting
        # `confidence`.
        if fact_index[fact_id].get("provenance") == BIO:
            fact_index[fact_id]["corroborated_by"] = target
        corroborated.append([fact_id, target])

    # A lane record naming the same person as a withheld-tier transcript fact
    # inherits that tier: a minor relative can be `children` on the transcript
    # facts and `none` on the bio-page record that names them, and the two
    # records are one person.
    tier_rank = {"none": 0, "lifestyle": 1, "clinical": 2, "children": 3, "location": 3}
    withheld_names: dict[str, str] = {}
    for f in facts:
        if f.get("provenance") == "transcript" and f.get("sensitivity") in WITHHELD:
            for tok in _name_tokens(str(f.get("claim") or "")):
                withheld_names.setdefault(tok, str(f["sensitivity"]))
    tier_inherited: list[list[str]] = []
    for rec, fact_id in zip(identity, identity_ids):
        fact = fact_index[fact_id]
        candidates: list[str] = []
        raw = rec.get("corroborates")
        if raw is not None:
            target = assigned.get(str(raw), str(raw))
            if target in fact_index and fact_index[target].get("sensitivity") in WITHHELD:
                candidates.append(str(fact_index[target]["sensitivity"]))
        for tok in _name_tokens(str(fact.get("claim") or "")):
            if tok in withheld_names:
                candidates.append(withheld_names[tok])
        if not candidates:
            continue
        new_tier = max(candidates, key=lambda t: tier_rank.get(t, 0))
        if tier_rank.get(new_tier, 0) > tier_rank.get(str(fact.get("sensitivity")), 0):
            tier_inherited.append([fact_id, str(fact.get("sensitivity")), new_tier])
            fact["sensitivity"] = new_tier
            fact["sensitive"] = new_tier in WITHHELD

    # A bio fact confirmed on an earlier run is only as good as the upload that
    # confirmed it. When that transcript fact is retired or gone, the bio fact
    # goes back to being the creator's own unverified words: the gate below
    # then keeps it off the page, or drops it at a sensitive tier.
    bio_corroboration_lost: list[list[str]] = []
    for f in facts:
        link = str(f.get("corroborated_by") or "")
        if f.get("provenance") != BIO or not link:
            continue
        if corroboration_holds(fact_index.get(link)):
            continue
        f.pop("corroborated_by", None)
        f["confidence"] = "unconfirmed"
        bio_corroboration_lost.append([str(f.get("fact_id")), link])

    # An unconfirmed bio claim carried from an earlier ledger lives only as
    # long as the About text still says it. The carried record never passes the
    # corroboration loop again, so without this it would render under "In their
    # own words (unverified)" on every refresh forever, years after the creator
    # deleted the line. Expiry runs only when this run's bio lane produced
    # records: with none, an empty About box and a skipped lane look the same,
    # and a skipped lane must not empty the ledger.
    bio_expired: list[str] = []
    current_bio = [rec for rec in identity if rec.get("provenance") == BIO]
    if current_bio:
        still_said = {bio_key(rec.get("claim")) for rec in current_bio}
        still_said |= {bio_key(rec.get("source_excerpt")) for rec in current_bio}
        still_said.discard("")
        for fact_id in list(existing_by_id):
            fact = fact_index.get(fact_id)
            if not fact or fact.get("provenance") != BIO:
                continue
            if fact.get("confidence") == "confirmed" and fact.get("corroborated_by"):
                continue
            if (bio_key(fact.get("claim")) in still_said
                    or bio_key(fact.get("source_excerpt")) in still_said):
                continue
            facts.remove(fact)
            fact_index.pop(fact_id, None)
            bio_expired.append(fact_id)

    # What an uncorroborated bio fact may be, applied here, after tier
    # inheritance, and over every bio fact in the ledger including the ones
    # carried from `--existing`, which never pass the corroboration loop again.
    facts, bio_dropped = bio_gate(facts)
    for f in bio_dropped:
        fact_index.pop(str(f.get("fact_id")), None)

    # a re-judged cluster's other inherited facts stay as history
    for old, new in reconciled.items():
        if old in fact_index:
            fact_index[old]["superseded_by"] = new

    # supersession: the newer fact marks the older, which stays as history.
    for key in kept:
        sup = decisions[key].get("supersedes")
        if sup is None:
            continue
        sup = str(sup)
        target = assigned.get(sup, sup)
        if target in fact_index:
            fact_index[target]["superseded_by"] = assigned[key]

    facts.sort(key=lambda f: str(f.get("fact_id")))

    # two first names a caption list ran together are two people: the fact
    # keeps both names apart and drops to `unconfirmed`, off every page
    people = people_list(facts)
    for f in facts:
        for p in list(f.get("people") or []):
            if str(p.get("name")) in people["two_names"]:
                f["people"] = [q for q in f["people"] if q is not p] + [
                    {"name": w, "relation": p.get("relation")} for w in str(p["name"]).split()]
                f["confidence"] = "unconfirmed"
                f["two_names"] = str(p["name"])
    people_path = out_path.parent / "people.json"
    people_path.write_text(json.dumps(people, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---- selected: the agent proposes, the script owns the count ---------- #
    # Quality first: the agent's picks are ranked before they are taken, an
    # `unconfirmed` pick is refused with its reason, and nothing unconfirmed
    # is ever filled in: a thin ledger shows fewer facts, never guesses.
    active = [f for f in facts
              if not f.get("superseded_by") and not f.get("retired_reason")]
    eligible = {str(f["fact_id"]) for f in active if selectable(f)}
    picked: list[str] = []
    ignored: dict[str, str] = {}
    # one moment, one pick: the same passage split into two facts in two
    # domains ("used to live with my parents": family, home) is one thing the
    # creator said, and the page must not say it twice
    moments: set[tuple] = set()

    def take(fact: dict) -> None:
        picked.append(str(fact["fact_id"]))
        mk = moment_key(fact)
        if mk is not None:
            moments.add(mk)

    def fresh(fact: dict) -> bool:
        mk = moment_key(fact)
        return mk is None or mk not in moments

    # the agent names c* ids, f* ids, and an identity fact's own `ref`
    pick_map = {**assigned, **identity_by_ref}
    proposed: list[dict] = []
    for raw in agent_selected:
        fact_id = pick_map.get(raw, raw)
        if fact_id not in fact_index:
            ignored[raw] = "unknown id"
        elif fact_index[fact_id].get("superseded_by"):
            ignored[raw] = f"superseded by {fact_index[fact_id]['superseded_by']}"
        elif fact_id not in eligible:
            ignored[raw] = unselectable_reason(fact_index[fact_id])
        elif fact_id not in [str(p["fact_id"]) for p in proposed]:
            proposed.append(fact_index[fact_id])
    for fact in sorted(proposed, key=rank_key):
        fact_id = str(fact["fact_id"])
        if fact.get("confidence") != "confirmed":
            ignored[fact_id] = "unconfirmed: never on the page"
            continue
        if len(picked) >= SELECTED_TARGET:
            ignored[fact_id] = f"over the {SELECTED_TARGET}-fact target"
            continue
        if not fresh(fact):
            ignored[fact_id] = "same moment as a fact already picked"
            continue
        take(fact)
    # fill: confirmed facts seen in two or more videos first, then confirmed
    # by rank (recent before older); never an unconfirmed fact
    for fact in sorted(active, key=rank_key):
        if len(picked) >= SELECTED_TARGET:
            break
        fact_id = str(fact["fact_id"])
        if (fact_id in eligible and fact_id not in picked and fresh(fact)
                and fact.get("confidence") == "confirmed"
                and int(fact.get("recurrence") or 0) >= 2):
            take(fact)
    for fact in sorted(active, key=rank_key):
        if len(picked) >= SELECTED_TARGET:
            break
        fact_id = str(fact["fact_id"])
        if (fact_id in eligible and fact_id not in picked and fresh(fact)
                and fact.get("confidence") == "confirmed"):
            take(fact)
    chosen = set(picked)
    ignored = {k: v for k, v in ignored.items()
               if pick_map.get(k, k) not in chosen}
    for fact in facts:
        fact["selected"] = str(fact.get("fact_id")) in chosen

    write_ledger(out_path, None, facts)

    # ---- state: what the next round inherits by --------------------------- #
    members_state: dict[str, dict] = dict(prior_state)
    for key, fact_id in assigned.items():
        for mkey in member_keys(clusters[by_c[key]["index"]]):
            members_state[mkey] = {"fact": fact_id}
    for key, target in terminal.items():
        fact_id = assigned.get(target) if not target.startswith("f") else target
        if not fact_id:
            continue
        for mkey in member_keys(clusters[by_c[key]["index"]]):
            members_state[mkey] = {"folded": fact_id}
    for rec in records:
        if rec["status"] in ("auto_dropped", "carry_dropped"):
            for mkey in member_keys(clusters[rec["index"]]):
                members_state.setdefault(mkey, {"dropped": rec["reason"]})
    for key, dec in decisions.items():
        if dec.get("action") != "drop":
            continue
        reason = str(dec.get("reason") or "dropped by the merge pass")
        for mkey in member_keys(clusters[by_c[key]["index"]]):
            members_state[mkey] = {"dropped": reason}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(
        {"schema": "tl-creator-merge-state/v1", "channel": a.channel,
         "format": a.format, "facts": len(facts),
         "members": members_state}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    dropped = sum(1 for k, d in decisions.items() if d.get("action") == "drop")
    auto_dropped = sum(1 for r in records
                       if r["status"] in ("auto_dropped", "carry_dropped"))
    elapsed = round(time.monotonic() - t0, 1)
    summary = {
        "clusters": len(clusters),
        "judged": sum(1 for r in records if r["status"] == "judge"),
        "auto_dropped": auto_dropped,
        "additive": len(additive),
        "facts": len(facts),
        "new_facts": len(kept_set),
        "folded": len(terminal),
        "folded_across_domains": sorted(crossed_domains),
        "dropped": dropped,
        "selected": len(chosen),
        "identity_facts": len(identity_ids),
        "bio_facts": sum(1 for f in facts if f.get("provenance") == BIO),
        "bio_confirmed": sum(1 for f in facts
                             if f.get("provenance") == BIO and not f.get("unverified_bio")),
        "bio_unverified": sum(1 for f in facts if f.get("unverified_bio")),
        "bio_dropped": [[str(f.get("fact_id")), str(f.get("sensitivity"))]
                        for f in bio_dropped],
        "bio_expired": bio_expired,
        "bio_corroboration_refused": bio_uncorroborated,
        "bio_corroboration_lost": bio_corroboration_lost,
        "enum_aliases": enum_aliases,
        "corroborated": corroborated,
        "reconciled": reconciled,
        "superseded": sum(1 for f in facts if f.get("superseded_by")),
        "claim_fallbacks": fallbacks,
        "selected_ignored": ignored,
        "staged_facts": sum(1 for f in facts if f.get("staged")),
        "staged_only": [str(f["fact_id"]) for f in facts if f.get("staged_only")],
        "ended": [str(f["fact_id"]) for f in facts if f.get("ended")],
        "hook_only": [str(f["fact_id"]) for f in facts if f.get("hook_only")],
        "dated_claims": {str(f["fact_id"]): f["dated"] for f in facts if f.get("dated")},
        "first_upload": first_upload,
        "two_names": people["two_names"],
        "people_file": str(people_path),
        "recent_months": RECENT_MONTHS,
        "run_date": RUN_DATE,
        "tier_inherited": tier_inherited,
        "probe_file": str(probe_path) if probes else None,
        "facts_file": str(out_path),
        "state_file": str(state_path),
        "elapsed_s": elapsed,
    }
    print(json.dumps(summary, indent=1))
    funnel(stage="merge", clusters=len(clusters), judged=summary["judged"],
           auto_dropped=auto_dropped, additive=len(additive),
           facts=len(facts), folded=len(terminal),
           folded_across_domains=len(crossed_domains), dropped=dropped,
           selected=len(chosen), identity_facts=len(identity_ids),
           staged_only=len(summary["staged_only"]),
           tier_inherited=len(tier_inherited),
           enum_aliases=len(enum_aliases), elapsed_s=elapsed)
    if enum_aliases:
        print("near-miss enum values aliased: "
              + "; ".join(enum_aliases), file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("prepare", help="write the compact judgment input")
    p.add_argument("--clustered", required=True)
    p.add_argument("--format", required=True, choices=sorted(FORMATS))
    p.add_argument("--existing", default=None, help="the ledger being refreshed")
    p.add_argument("--state", default=None,
                   help="merge-state.json from the previous round "
                        "(default: <out>/merge-state.json)")
    p.add_argument("--shards", type=int, default=None,
                   help="split the input across N agents, whole domains only; "
                        f"default: clusters / {SHARD_DIVISOR}, floor 1, ceiling {SHARD_MAX}")
    p.add_argument("--channel", type=int, default=None,
                   help="channel id; when given, authenticate.py probes staged-premise "
                        "and contradicting clusters and writes probe.json")
    p.add_argument("--max-queries", type=int, default=60,
                   help="probe budget, one ES query per staged or conflicting cluster")
    p.add_argument("--out", required=True, help="directory for merge-input*.jsonl")
    p.set_defaults(fn=cmd_prepare)

    e = sub.add_parser("expand", help="validate decisions and build the facts")
    e.add_argument("--clustered", required=True)
    e.add_argument("--decisions", action="append", required=True,
                   help="repeatable; later files override earlier ones per id")
    e.add_argument("--existing", default=None)
    e.add_argument("--state", default=None,
                   help="default: merge-state.json beside --out")
    e.add_argument("--format", required=True, choices=sorted(FORMATS))
    e.add_argument("--channel", required=True, help="channel id, for `video`")
    e.add_argument("--out", required=True, help="facts.jsonl to write")
    e.add_argument("--fallback-original", action="store_true",
                   help="use the cluster's own claim for claims that fail the "
                        "tripwire instead of exiting 3")
    e.set_defaults(fn=cmd_expand)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
