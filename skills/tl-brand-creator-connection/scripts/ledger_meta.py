#!/usr/bin/env python3
"""The ledger's meta header, and the reuse decision built on it.

One machine file per creator: ``<profiles>/<channel_id>-facts.jsonl``, whose
FIRST line is the meta record (``"schema": "tl-creator-meta/v2"``: what the
build was: when, over which videos, what it found) and whose every following
line is one fact. There is no ``<channel_id>-meta.json`` sidecar any more;
everything goes through ``scripts/store_io.py``.

Two subcommands:

    ledger_meta.py write --channel <id> [--profiles-dir tl-creator-profiles]
        [--from facts.verified.jsonl]
        [--channel-name "…"] [--format solo] [--format-evidence "…"]
        [--rounds N] [--lanes …] [--context <json>]

    With ``--from``, the verified working facts (``verify_quotes.py``'s
    output) become the ledger: every transcript fact must carry
    ``verify.match == "exact"``: anything else refuses the write with the
    offending fact ids and exit 2, the ``verify`` key is stripped, every
    other field is kept, and the file is written with the header first.
    Without ``--from`` the existing ledger's header is rewritten in place:
    the facts are untouched, the counts are recounted from the build's
    files, and descriptive fields not passed again (name, format, lanes,
    credits, channel context) are carried over from the old header.

    Counts come from the build's own files, the ledger (facts, counted
    through ``store_io``), the passage store (videos matched, corpus
    window), the windows files (passages), classified.jsonl (windows
    judged), gems.jsonl (gems) and the fetch summaries (videos with
    transcript, latest upload, rounds). Nothing is typed in by hand; a count
    that cannot be derived is 0 and says so in ``missing``.

    ledger_meta.py check --channel <id> [--profiles-dir tl-creator-profiles]
        [--rebuild] [--no-refresh] [--max-new-videos 5] [--max-age-days 60]

    Reads ``<channel_id>-facts.jsonl``. When it exists and carries a header
    this prints ONE announcement line (creator, build date, corpus window,
    fact count, uploads since) followed by a JSON decision: ``reuse`` (few
    new uploads and a young ledger), ``refresh`` (an additive round is worth
    it: more than --max-new-videos uploads since, or older than
    --max-age-days), or ``build`` (nothing usable, a headerless ledger, a
    legacy ledger + ``<id>-meta.json`` pair, or --rebuild). The uploads
    count is one cheap index count against ``meta.latest_video_date``.
    ``--no-refresh`` forces ``reuse``; ``--rebuild`` forces ``build``. A
    ledger built from transcripts only refreshes when ``--lanes
    transcripts+socials`` is asked for; the reverse reuses (more grounded
    facts, never fewer).

Stdout is the announcement line (check only) and one JSON object; exit 0,
except a refused ``write --from``, which exits 2.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import store_io  # sibling module  # noqa: E402
import tl_data  # noqa: E402
from channel_context import set_cached_with_evidence  # noqa: E402  sibling: the cache writer

SCHEMA = "tl-creator-meta/v2"
DEFAULT_MAX_NEW_VIDEOS = 5
DEFAULT_MAX_AGE_DAYS = 60
LANES = ("transcripts", "transcripts+socials")
# descriptive fields a refresh write keeps from the existing record unless
# the caller passes them again
CARRIED = ("channel_name", "format", "format_evidence", "credits_spent", "lanes", "context")


def _count_lines(path: pathlib.Path) -> int:
    if not path.exists():
        return 0
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _corpus_window(corpus_path: pathlib.Path) -> tuple[str | None, str | None, int]:
    """(earliest, latest) publication date among the stored videos, and how
    many videos the store holds."""
    if not corpus_path.exists():
        return None, None, 0
    lo = hi = None
    n = 0
    with gzip.open(corpus_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            n += 1
            d = (json.loads(line).get("publication_date") or "")[:10]
            if not d:
                continue
            lo = d if lo is None or d < lo else lo
            hi = d if hi is None or d > hi else hi
    return lo, hi, n


def _fetch_summaries(corpus_dir: pathlib.Path) -> list[dict]:
    out = []
    for p in sorted(glob.glob(str(corpus_dir / "fetch*.json"))):
        try:
            out.append(json.loads(pathlib.Path(p).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return out


def _clip(text, n: int) -> str | None:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return None
    return (text[: n - 1].rstrip() + "…") if len(text) > n else text


def load_context(path: str | None) -> dict | None:
    """The parts of channel_context.py's output the connections page shows:
    what the platform already says about the channel (its About text and the
    AI profile, which lead "Who they are" so the ledger only has to add what
    the videos prove), linked platforms and sibling-channel candidates."""
    if not path:
        return None
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {"about_text": _clip(data.get("about_text"), 700),
            "generated_profile": _clip(data.get("generated_profile"), 900),
            # The creator's own labelled sites, discovered in channel context.
            # Kept apart from the platform links because they are where the
            # identity lane starts, and because a reuse that drops them makes
            # the next run rediscover what this one already knew.
            "websites": [
                {k: str(v) for k, v in w.items() if k in ("label", "url")}
                for w in (data.get("websites") or []) if isinstance(w, dict)],
            "social_links": [str(x) for x in (data.get("social_links") or [])],
            # A time-boxed socials lane reads some linked platforms and not
            # others; carrying the split keeps the page's honesty strip from
            # reporting an unopened page as read.
            "social_links_read": [str(x) for x in (data.get("social_links_read") or [])],
            "social_links_unread": [str(x) for x in (data.get("social_links_unread") or [])],
            "second_channel_candidates": [
                {k: v for k, v in c.items() if k in ("name", "link", "id", "channel_id", "source")}
                for c in (data.get("second_channel_candidates") or []) if isinstance(c, dict)]}


def build_meta(channel: int, profiles_dir: pathlib.Path, corpus_dir: pathlib.Path, *,
               channel_name: str | None = None, fmt: str | None = None,
               format_evidence: str | None = None, rounds: int | None = None,
               credits_spent: float | None = None, lanes: str | None = None,
               context: dict | None = None, previous: dict | None = None,
               today: dt.date | None = None) -> dict:
    facts_path = profiles_dir / f"{channel}-facts.jsonl"
    if not facts_path.exists():
        raise SystemExit(f"no ledger at {facts_path}: run the build first")
    previous = previous or {}
    given = {"channel_name": channel_name, "format": fmt, "format_evidence": format_evidence,
             "credits_spent": credits_spent, "lanes": lanes, "context": context}
    carried = {k: (given[k] if given[k] is not None else previous.get(k)) for k in CARRIED}
    if carried["lanes"] is None:
        carried["lanes"] = LANES[0]
    missing: list[str] = []
    summaries = _fetch_summaries(corpus_dir)
    lo, hi, videos_matched = _corpus_window(corpus_dir / "corpus.jsonl.gz")
    if not videos_matched:
        missing.append("corpus.jsonl.gz")
    passages = sum(_count_lines(pathlib.Path(p))
                   for p in glob.glob(str(corpus_dir / "windows*.jsonl.gz")))
    if not passages:
        missing.append("windows.jsonl.gz")
    windows_judged = _count_lines(corpus_dir / "classified.jsonl")
    if not windows_judged:
        missing.append("classified.jsonl")
    gems = _count_lines(corpus_dir / "gems.jsonl")
    videos_with_transcript = 0
    latest_video_date: str | None = None
    for s in summaries:
        videos_with_transcript = max(videos_with_transcript,
                                     int(s.get("videos_with_transcript") or 0))
        d = (s.get("latest_video_date") or "")[:10]
        if d and (latest_video_date is None or d > latest_video_date):
            latest_video_date = d
    if not summaries:
        missing.append("fetch.json")
    if latest_video_date is None:
        latest_video_date = hi           # the newest video the passages came from
    meta = {
        "schema": SCHEMA,
        "channel_id": channel,
        "channel_name": carried["channel_name"],
        "generated_at": (today or dt.date.today()).isoformat(),
        "corpus_window": [lo, hi],
        "coverage": {
            "videos_with_transcript": videos_with_transcript,
            "videos_matched": videos_matched,
            "passages": passages,
            "windows_judged": windows_judged,
            "gems": gems,
            "facts": store_io.count_facts(facts_path),
        },
        "format": carried["format"],
        "format_evidence": carried["format_evidence"],
        "lanes": carried["lanes"],
        "latest_video_date": latest_video_date,
        "rounds": rounds if rounds is not None else max(1, len(summaries)),
        "facts_file": facts_path.name,
    }
    if carried["credits_spent"] is not None:
        meta["credits_spent"] = carried["credits_spent"]
    if carried["context"]:
        meta["context"] = carried["context"]
    if missing:
        meta["missing"] = missing
    return meta


def count_uploads_since(channel: int, since: str) -> int:
    """Uploads dated after ``since``: one count, no documents fetched."""
    body = {"size": 0, "track_total_hits": True,
            "query": {"bool": {"filter": [{"term": {"doc_type": "article"}},
                                          {"term": {"channel.id": channel}},
                                          {"range": {"publication_date": {"gt": since}}}]}}}
    data = tl_data._tl_json(["db", "es", "-", "--json"], input_text=json.dumps(body))
    return int((data or {}).get("total") or 0)


def announce(meta: dict, new_videos: int | None) -> str:
    name = meta.get("channel_name") or f"channel {meta.get('channel_id')}"
    lo, hi = (meta.get("corpus_window") or [None, None])[:2]
    window = f"{(lo or '?')[:7]} → {(hi or '?')[:10]}"
    facts = (meta.get("coverage") or {}).get("facts", 0)
    since = (f"{new_videos} videos uploaded since." if new_videos is not None
             else "uploads since: unknown (count failed).")
    return (f"Found a ledger for {name} built {meta.get('generated_at')} over {window}, "
            f"{facts} facts. {since}")


def lane_gap(meta: dict, requested: str | None) -> str | None:
    """Why the stored lanes do not cover the requested ones, or None. A
    ledger that also read socials covers a transcripts-only request; the
    reverse does not."""
    if not requested:
        return None
    have = str(meta.get("lanes") or LANES[0])
    if requested == "transcripts+socials" and have != "transcripts+socials":
        return f"socials lane requested; ledger is {have}"
    return None


def decide(meta: dict, new_videos: int | None, *, rebuild: bool, no_refresh: bool,
           max_new: int, max_age_days: int, lanes: str | None = None,
           today: dt.date | None = None) -> dict:
    today = today or dt.date.today()
    try:
        built = dt.date.fromisoformat(str(meta.get("generated_at"))[:10])
        age_days = (today - built).days
    except (TypeError, ValueError):
        age_days = None
    out = {"new_videos": new_videos, "age_days": age_days,
           "next_round": int(meta.get("rounds") or 1) + 1,
           "lanes": meta.get("lanes") or LANES[0]}
    gap = lane_gap(meta, lanes)
    if rebuild:
        out.update(decision="build", reason="--rebuild")
    elif no_refresh:
        out.update(decision="reuse", reason="--no-refresh")
    elif gap:
        out.update(decision="refresh", reason=gap)
    elif new_videos is None:
        out.update(decision="refresh", reason="upload count failed; refreshing to be safe")
    elif new_videos > max_new:
        out.update(decision="refresh", reason=f"{new_videos} new uploads > {max_new}")
    elif age_days is None or age_days > max_age_days:
        out.update(decision="refresh", reason=f"ledger is {age_days} days old > {max_age_days}")
    else:
        out.update(decision="reuse",
                   reason=f"{new_videos} new uploads ≤ {max_new} and {age_days} days ≤ {max_age_days}")
    return out


class Unverified(Exception):
    """Raised by ``verified_facts``: the ids that did not match exactly."""

    def __init__(self, ids: list[str]):
        super().__init__(", ".join(ids))
        self.ids = ids


def verified_facts(path: pathlib.Path) -> list[dict]:
    """The ledger facts inside ``verify_quotes.py``'s output: every transcript
    fact must have matched EXACTLY (a partial match is how a fabricated quote
    gets a real timestamp), and the ``verify`` bookkeeping does not belong in
    the ledger. Everything else on the fact, ``members`` included, survives."""
    _, facts = store_io.read_ledger(path)
    bad: list[str] = []
    out: list[dict] = []
    for i, fact in enumerate(facts, 1):
        provenance = fact.get("provenance") or ("transcript" if fact.get("video") else "n/a")
        verify = fact.get("verify") or {}
        if provenance == "transcript" and str(verify.get("match")) != "exact":
            bad.append(f"{fact.get('fact_id') or f'line {i}'}"
                       f" ({verify.get('match') or 'unverified'})")
        out.append({k: v for k, v in fact.items() if k != "verify"})
    if bad:
        raise Unverified(bad)
    return out


# --------------------------------------------------------------------------- #
# What a finished run caches on the channel record, beside the host name the
# cast sheet cached earlier: the format label when the cast sheets agree with
# it, the host's aliases once the host's name is settled, and the sibling
# channels the record points at. Each value has a `.evidence` key; a value
# already cached is never rewritten.
# --------------------------------------------------------------------------- #
FORMAT_AGREES = {"interview": {"interview", "collab"}, "multi_host": {"multi_host", "collab"},
                 "solo": {"solo", "staged"}, "faceless_scripted": {"faceless"}}
FORMAT_CACHE_VIDEOS_MIN = 10
ALIAS_VIDEOS_MIN = 2


def _cast_counts(cast: dict) -> tuple[dict[str, int], dict[str, int], dict[str, str]]:
    """``(videos per format, videos per lowercase host name, the spelling used most)``."""
    formats: dict[str, int] = {}
    hosts: dict[str, int] = {}
    spelling: dict[str, dict[str, int]] = {}
    for v in cast.values():
        if not isinstance(v, dict):
            continue
        fmt = str(v.get("format") or "")
        formats[fmt] = formats.get(fmt, 0) + 1
        for h in {str(h).strip() for h in v.get("hosts") or []}:
            if h and h.lower() != "host":
                hosts[h.lower()] = hosts.get(h.lower(), 0) + 1
                spelling.setdefault(h.lower(), {})[h] = spelling.get(h.lower(), {}).get(h, 0) + 1
    best = {k: max(c, key=c.get) for k, c in spelling.items()}
    return formats, hosts, best


def cache_run_attributes(channel: int, context: dict, *, fmt: str | None, evidence: str | None,
                         cast: dict | None, host_names: list[str], writer=None) -> dict:
    """Cache ``format_label``, ``host_aliases`` and ``sibling_channels`` on the
    channel record; returns the outcome per key (``set``, ``already set: …``
    or ``skipped: <why>``)."""
    writer = writer or set_cached_with_evidence
    out: dict[str, str] = {}
    formats, hosts, spelling = _cast_counts(cast or {})
    judged = sum(formats.values())

    # format label: the model's call, confirmed by the measured cast formats
    cached = context.get("cached_format_label")
    if cached:
        out["format_label"] = f"already set: {cached}"
    elif not fmt:
        out["format_label"] = "skipped: no format label"
    elif judged < FORMAT_CACHE_VIDEOS_MIN:
        out["format_label"] = f"skipped: cast sheets judged {judged} videos, fewer than {FORMAT_CACHE_VIDEOS_MIN}"
    else:
        top = max(formats, key=formats.get)
        if top in FORMAT_AGREES.get(fmt, set()):
            out["format_label"] = writer(channel, "format_label", fmt,
                                         f"{evidence or 'format call'}; cast sheets: {top} in "
                                         f"{formats[top]} of {judged} videos")
        else:
            out["format_label"] = f"skipped: cast sheets say {top} in {formats[top]} of {judged} videos, the run says {fmt}"

    # host aliases: only once the host's name is settled on the record
    host = context.get("cached_host_name")
    if context.get("cached_host_aliases"):
        out["host_aliases"] = f"already set: {', '.join(context['cached_host_aliases'])}"
    elif not host:
        out["host_aliases"] = "skipped: host name not cached"
    else:
        why: dict[str, list[str]] = {}
        for name in host_names:
            why.setdefault(name.strip(), []).append("given to the run")
        for low, n in hosts.items():
            if n >= ALIAS_VIDEOS_MIN:
                why.setdefault(spelling[low], []).append(f"cast sheets name the host in {n} videos")
        for r in context.get("name_candidates") or []:
            if int(r.get("said_outright_videos") or 0) >= ALIAS_VIDEOS_MIN:
                why.setdefault(str(r["name"]).capitalize(), []).append(
                    f"said outright in {r['said_outright_videos']} uploads")
        aliases = [a for a in why if a and a.lower() not in {host.lower(), host.split()[0].lower()}]
        if not aliases:
            out["host_aliases"] = "skipped: no alias with evidence"
        else:
            out["host_aliases"] = writer(channel, "host_aliases", aliases,
                                         "; ".join(f"{a}: {', '.join(why[a])}" for a in aliases))

    # sibling channels: the record's own pointers
    cached_sib = context.get("cached_sibling_channels") or []
    siblings = [{"link": c["link"], "source": c.get("source")}
                for c in context.get("second_channel_candidates") or []
                if isinstance(c, dict) and c.get("link") and c.get("source") != "cached"]
    if cached_sib:
        out["sibling_channels"] = f"already set: {len(cached_sib)} channels"
    elif not siblings:
        out["sibling_channels"] = "skipped: no sibling candidates"
    else:
        by_source: dict[str, int] = {}
        for c in siblings:
            by_source[str(c["source"])] = by_source.get(str(c["source"]), 0) + 1
        out["sibling_channels"] = writer(
            channel, "sibling_channels", siblings,
            f"{len(siblings)} candidates from the channel's own pointers: "
            + ", ".join(f"{k} ({n})" for k, n in sorted(by_source.items())))
    return out


def cmd_write(a: argparse.Namespace) -> int:
    profiles = pathlib.Path(a.profiles_dir)
    corpus_dir = profiles / ".corpus" / str(a.channel)
    path = profiles / f"{a.channel}-facts.jsonl"
    previous = store_io.read_ledger(path)[0] if path.exists() else None
    if a.from_facts:
        try:
            facts = verified_facts(pathlib.Path(a.from_facts))
        except Unverified as exc:
            print(f"refusing to write the ledger: {len(exc.ids)} transcript facts did not "
                  f"match their captions exactly, fix or drop them, then re-run "
                  f"verify_quotes.py: {exc}", file=sys.stderr)
            return 2
        profiles.mkdir(parents=True, exist_ok=True)
        store_io.write_ledger(path, None, facts)      # counted, then headed below
    else:
        facts = store_io.read_ledger(path)[1] if path.exists() else []
    meta = build_meta(a.channel, profiles, corpus_dir, channel_name=a.channel_name,
                      fmt=a.format, format_evidence=a.format_evidence, rounds=a.rounds,
                      lanes=a.lanes,
                      context=load_context(a.context), previous=previous)
    store_io.write_ledger(path, meta, facts)
    cache = None
    if a.context:
        try:
            full = json.loads(pathlib.Path(a.context).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            full = {}
        cast = None
        if a.cast and pathlib.Path(a.cast).exists():
            try:
                cast = json.loads(pathlib.Path(a.cast).read_text(encoding="utf-8"))
            except ValueError:
                cast = None
        cache = cache_run_attributes(a.channel, full, fmt=a.format, evidence=a.format_evidence,
                                     cast=cast, host_names=[x.strip() for x in (a.host_names or "").split(",")
                                                            if x.strip()])
    print(json.dumps({"ledger": str(path), **meta, "cache": cache}, ensure_ascii=False))
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    profiles = pathlib.Path(a.profiles_dir)
    facts_path = profiles / f"{a.channel}-facts.jsonl"
    sidecar = profiles / f"{a.channel}-meta.json"
    meta = store_io.read_ledger(facts_path)[0] if facts_path.exists() else None
    if meta is None:
        if not facts_path.exists():
            reason = "no ledger"
        elif sidecar.exists():
            reason = f"legacy ledger: {sidecar.name} sidecar, no meta header"
        else:
            reason = "incomplete ledger: no meta header"
        print(json.dumps({"decision": "build", "reason": reason,
                          "facts": str(facts_path), "meta": str(facts_path),
                          "next_round": 1}))
        return 0
    new_videos: int | None = None
    since = meta.get("latest_video_date")
    if since:
        try:
            new_videos = count_uploads_since(a.channel, since)
        except Exception as exc:  # reporting only: the decision falls back to refresh
            print(f"upload count failed: {exc}", file=sys.stderr)
    print(announce(meta, new_videos))
    out = decide(meta, new_videos, rebuild=a.rebuild, no_refresh=a.no_refresh,
                 max_new=a.max_new_videos, max_age_days=a.max_age_days, lanes=a.lanes)
    out.update(facts=str(facts_path), meta=str(facts_path),
               latest_video_date=since, generated_at=meta.get("generated_at"),
               fact_count=(meta.get("coverage") or {}).get("facts"))
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write",
                       help="write the ledger's meta header from the build's files")
    w.add_argument("--channel", type=int, required=True)
    w.add_argument("--profiles-dir", default="tl-creator-profiles")
    w.add_argument("--from", dest="from_facts", default=None,
                   help="verify_quotes.py output: its facts become the ledger "
                        "(exact matches only, verify stripped). Omit to rewrite "
                        "the header of the existing ledger in place.")
    w.add_argument("--channel-name", default=None)
    w.add_argument("--format", default=None,
                   help="solo | interview | multi_host | faceless_scripted")
    w.add_argument("--format-evidence", default=None)
    w.add_argument("--rounds", type=int, default=None,
                   help="extraction rounds run; default: number of fetch summaries")
    w.add_argument("--lanes", choices=LANES, default=None,
                   help="which creator-source lanes built the ledger; default: transcripts, "
                        "or the existing record's value on a refresh")
    w.add_argument("--context", default=None,
                   help="channel_context.py output JSON: linked platforms and sibling "
                        "channels are kept in the header for the connections page, and "
                        "the format label, host aliases and sibling channels are cached "
                        "on the channel record from it")
    w.add_argument("--cast", default=None,
                   help="cast.json from cast_sheet.py apply: the measured per-video formats "
                        "and host names that confirm the format label and the aliases")
    w.add_argument("--host-names", dest="host_names", default=None,
                   help="the host aliases the run used, comma-separated")
    w.set_defaults(fn=cmd_write)
    c = sub.add_parser("check", help="reuse decision for an existing ledger")
    c.add_argument("--channel", type=int, required=True)
    c.add_argument("--profiles-dir", default="tl-creator-profiles")
    c.add_argument("--rebuild", action="store_true", help="force a full build")
    c.add_argument("--no-refresh", action="store_true", help="reuse as is, whatever is new")
    c.add_argument("--max-new-videos", type=int, default=DEFAULT_MAX_NEW_VIDEOS)
    c.add_argument("--max-age-days", type=int, default=DEFAULT_MAX_AGE_DAYS)
    c.add_argument("--lanes", choices=LANES, default=None,
                   help="lanes this run wants; a ledger built without the socials lane "
                        "refreshes when transcripts+socials is asked for")
    c.set_defaults(fn=cmd_check)
    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
