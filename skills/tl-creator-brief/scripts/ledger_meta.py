#!/usr/bin/env python3
"""The per-creator meta record, and the reuse decision built on it.

Two subcommands:

    ledger_meta.py write --channel <id> [--profiles-dir tl-creator-profiles]
        [--corpus-dir <profiles>/.corpus/<id>] [--channel-name "…"]
        [--format solo] [--format-evidence "…"] [--rounds N]
        [--credits-spent N]

    Writes ``<profiles>/<channel_id>-meta.json`` from the files a build leaves
    behind (on a refresh, descriptive fields not passed again — name, format,
    lanes, credits, channel context — are carried over from the record): the
    verified ledger (facts), the passage store (videos matched, corpus window), the windows files (passages), classified.jsonl (windows
    judged), gems.jsonl (gems) and the fetch summaries (videos with
    transcript, latest upload, rounds). Nothing is typed in by hand; a count
    that cannot be derived is 0 and says so in ``missing``.

    ledger_meta.py check --channel <id> [--profiles-dir tl-creator-profiles]
        [--rebuild] [--no-refresh] [--max-new-videos 5] [--max-age-days 60]

    Looks for ``<channel_id>-facts.jsonl`` + ``<channel_id>-meta.json``. When
    both exist it prints ONE announcement line (creator, build date, corpus
    window, fact count, uploads since) followed by a JSON decision:
    ``reuse`` (few new uploads and a young ledger), ``refresh`` (an additive
    round is worth it: more than --max-new-videos uploads since, or older than
    --max-age-days), or ``build`` (nothing usable, or --rebuild). The uploads
    count is one cheap index count against ``meta.latest_video_date``.
    ``--no-refresh`` forces ``reuse``; ``--rebuild`` forces ``build``. A
    ledger built from transcripts only refreshes when ``--lanes
    transcripts+socials`` is asked for; the reverse reuses (more grounded
    facts, never fewer).

Stdout is the announcement line (check only) and one JSON object; exit 0.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import gzip
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "_shared"))
import tl_data  # noqa: E402

SCHEMA = "tl-creator-meta/v1"
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


def load_context(path: str | None) -> dict | None:
    """The parts of channel_context.py's output the ledger view still shows:
    linked platforms and sibling-channel candidates."""
    if not path:
        return None
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return {"social_links": [str(x) for x in (data.get("social_links") or [])],
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
            "facts": _count_lines(facts_path),
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
    """Uploads dated after ``since`` — one count, no documents fetched."""
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


def cmd_write(a: argparse.Namespace) -> int:
    profiles = pathlib.Path(a.profiles_dir)
    corpus_dir = (pathlib.Path(a.corpus_dir) if a.corpus_dir
                  else profiles / ".corpus" / str(a.channel))
    path = profiles / f"{a.channel}-meta.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    meta = build_meta(a.channel, profiles, corpus_dir, channel_name=a.channel_name,
                      fmt=a.format, format_evidence=a.format_evidence, rounds=a.rounds,
                      credits_spent=a.credits_spent, lanes=a.lanes,
                      context=load_context(a.context), previous=previous)
    path.write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"meta": str(path), **meta}, ensure_ascii=False))
    return 0


def cmd_check(a: argparse.Namespace) -> int:
    profiles = pathlib.Path(a.profiles_dir)
    facts_path = profiles / f"{a.channel}-facts.jsonl"
    meta_path = profiles / f"{a.channel}-meta.json"
    if not facts_path.exists() or not meta_path.exists():
        have = [p.name for p in (facts_path, meta_path) if p.exists()]
        print(json.dumps({"decision": "build", "reason": "no ledger" if not have
                          else f"incomplete ledger: only {', '.join(have)}",
                          "facts": str(facts_path), "meta": str(meta_path), "next_round": 1}))
        return 0
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
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
    out.update(facts=str(facts_path), meta=str(meta_path),
               latest_video_date=since, generated_at=meta.get("generated_at"),
               fact_count=(meta.get("coverage") or {}).get("facts"))
    print(json.dumps(out, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("write", help="write <channel_id>-meta.json from the build's files")
    w.add_argument("--channel", type=int, required=True)
    w.add_argument("--profiles-dir", default="tl-creator-profiles")
    w.add_argument("--corpus-dir", default=None,
                   help="default: <profiles-dir>/.corpus/<channel>")
    w.add_argument("--channel-name", default=None)
    w.add_argument("--format", default=None,
                   help="solo | interview | multi_host | faceless_scripted")
    w.add_argument("--format-evidence", default=None)
    w.add_argument("--rounds", type=int, default=None,
                   help="extraction rounds run; default: number of fetch summaries")
    w.add_argument("--credits-spent", type=float, default=None)
    w.add_argument("--lanes", choices=LANES, default=None,
                   help="which creator-source lanes built the ledger; default: transcripts, "
                        "or the existing record's value on a refresh")
    w.add_argument("--context", default=None,
                   help="channel_context.py output JSON: linked platforms and sibling "
                        "channels are kept in the record for the ledger view")
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
