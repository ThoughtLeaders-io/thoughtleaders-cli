#!/usr/bin/env python3
"""Views Guarantee calculator.

Usage:
    vg.py <channel_id_or_name>                     # single-answer mode
    vg.py <channel_id_or_name> --sweep             # recommendation + full table
    vg.py <channel_id_or_name> --rich-output       # adds per-video VG, cadence, campaign length
    vg.py <channel_id_or_name> --max-bundle-size 8 # raise the bundle ceiling (default 4, up to 10)
    vg.py <channel_id_or_name> --target max        # pick the largest bundle that clears 80%
"""

# ruff: noqa: T201
# This is a standalone CLI script; print is the intended output mechanism.

import argparse
import datetime
import json
import random
import subprocess
import sys
from dataclasses import dataclass
from typing import TypedDict

SEED = 42  # passed to a fresh random.Random in bootstrap_sweep so each call starts from the same RNG state
DEFAULT_MAX_BUNDLE_SIZE = 4
HARD_MAX_BUNDLE_SIZE = 10
N_SIMS = 10000
TARGET_LIKELIHOOD = 0.80
FLOOR_PCT = 0.75
MIN_SAMPLE = 5
THIN_SAMPLE = 10
MIN_VIDEO_AGE_DAYS = 30
# Upper cap on the cadence window (days). The actual span used is the smaller of this and
# the age of the oldest video in the already-fetched bootstrap sample — no extra ES query.
CADENCE_WINDOW_DAYS = 180
# Window staircase (upper bound, in days). Mirrors the PV calculator's range so the bootstrap
# samples from the same era of the channel that defined PV. Widen only when the narrower window
# has fewer than MIN_SAMPLE videos; never sample beyond the last step.
SAMPLE_WINDOW_STEPS: list[int] = [90, 120, 180, 240]
PRIMARY_WINDOW_MAX_DAYS: int = SAMPLE_WINDOW_STEPS[0]
# Relative VG difference between primary and full-range results that, by itself, qualifies as
# an inconsistency. Differences in chosen N or in the 80%-likelihood-reached flag also qualify.
INCONSISTENCY_VG_DIFF = 0.10


class _ChannelShowResult(TypedDict, total=False):
    name: str
    projected_views: int | None


class _V30Row(TypedDict):
    id: str
    v30: int | None


@dataclass(frozen=True)
class ChannelInfo:
    id: str
    name: str
    projected_views: int | None


@dataclass(frozen=True)
class BootstrapRow:
    N: int
    vg: int
    likelihood: float
    floor: int
    p20: int


def run(cmd: list[str], on_error: str | None = None) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        sys.exit(on_error or f"command failed: {' '.join(cmd)} (exit {r.returncode})")
    return r.stdout


def resolve_channel(arg: str) -> ChannelInfo:
    if arg.isdigit():
        out = run(["tl", "channels", "show", arg, "--json"])
        results: list[_ChannelShowResult] = json.loads(out)["results"]
        if not results:
            sys.exit(f"no channel found with id '{arg}'")
        result = results[0]
        return ChannelInfo(id=arg, name=result["name"], projected_views=result.get("projected_views"))

    out = run(
        ["tl", "channels", "find", arg],
        on_error=f"no channel found matching '{arg}' (or ambiguous — see stderr above)",
    )
    found: list[dict[str, object]] = json.loads(out)["results"]
    if not found:
        sys.exit(f"no channel found matching '{arg}'")
    return resolve_channel(str(found[0]["id"]))


def get_v30_sample(channel_id: str, force_full_range: bool = False) -> tuple[list[int], int, list[int]]:
    """Return (sample, window_max_days, fetched_ages).

    - `sample`: 30-day view counts for the videos inside the chosen staircase window.
    - `window_max_days`: upper-bound age (days) of the window actually used.
    - `fetched_ages`: ages (days) of every video pulled from ES before the staircase narrowed
      anything. Reused by the cadence calculator to avoid a second ES query.

    Walks the SAMPLE_WINDOW_STEPS staircase: takes everything in 30..steps[i]; widens to the next
    step only when the current window has fewer than MIN_SAMPLE videos. When force_full_range=True,
    skips the staircase and samples directly from 30..SAMPLE_WINDOW_STEPS[-1]. Caller is
    responsible for enforcing MIN_SAMPLE on the returned sample.
    """
    today = datetime.datetime.now(tz=datetime.UTC).date()
    widest_max: int = SAMPLE_WINDOW_STEPS[-1]
    # Bound publication_date precisely: at least MIN_VIDEO_AGE_DAYS old (so 30-day view data
    # exists) and no older than the widest window step. ES returns the 40 most-recent longform
    # videos in that range, freshest first.
    oldest_ok = (today - datetime.timedelta(days=widest_max)).isoformat()
    newest_ok = (today - datetime.timedelta(days=MIN_VIDEO_AGE_DAYS)).isoformat()
    es_body = {
        "size": 40,
        "_source": ["id", "publication_date"],
        "query": {
            "bool": {
                "filter": [
                    {"term": {"channel.id": str(channel_id)}},
                    {"term": {"content_type": "longform"}},
                    {
                        "range": {
                            "publication_date": {
                                "gte": oldest_ok,
                                "lte": newest_ok,
                                "format": "yyyy-MM-dd",
                            }
                        }
                    },
                ]
            }
        },
        "sort": [{"publication_date": {"order": "desc"}}],
    }
    out = run(["tl", "db", "es", json.dumps(es_body), "--json"])
    upload_rows: list[dict[str, str]] = json.loads(out)["results"]

    # The ES range constrains age to [MIN_VIDEO_AGE_DAYS, widest_max]; the staircase below narrows
    # it further. Bare YouTube ID (split off the compound `<channel>:<youtube>` form) is what the
    # Firebolt query keys on. Sort freshest-first for deterministic ordering independent of ES.
    aged_with_age: list[tuple[str, int]] = [
        (row["id"].split(":", 1)[1], (today - datetime.date.fromisoformat(row["publication_date"])).days) for row in upload_rows
    ]
    aged_with_age.sort(key=lambda pair: pair[1])
    fetched_ages: list[int] = [age for _, age in aged_with_age]

    if not aged_with_age:
        return [], PRIMARY_WINDOW_MAX_DAYS, fetched_ages

    chosen_max: int = widest_max
    chosen_ids: list[str] = []
    if force_full_range:
        chosen_ids = [uid for uid, age in aged_with_age if age <= widest_max]
        chosen_max = widest_max
    else:
        for window_max in SAMPLE_WINDOW_STEPS:
            ids_in_window = [uid for uid, age in aged_with_age if age <= window_max]
            if len(ids_in_window) >= MIN_SAMPLE:
                chosen_max = window_max
                chosen_ids = ids_in_window
                break
        else:
            chosen_ids = [uid for uid, age in aged_with_age if age <= chosen_max]

    if not chosen_ids:
        return [], chosen_max, fetched_ages
    quoted = ",".join(f"'{v}'" for v in chosen_ids)
    q = (
        f"SELECT id, CAST(AVG(view_count) FILTER (WHERE age >= 28 AND age <= 32) AS BIGINT) AS v30 "
        f"FROM article_metrics WHERE channel_id = {channel_id} "
        f"AND id IN ({quoted}) GROUP BY id"
    )
    out = run(["tl", "db", "fb", q, "--json"])
    v30_rows: list[_V30Row] = json.loads(out)["results"]
    # Build sample in the deterministic publication-date order from `chosen_ids`. The Firebolt query
    # has no ORDER BY, so v30_rows can come back in different orders across runs — picking by index
    # into a shuffled list would make the seeded RNG hit different elements each invocation.
    v30_by_id: dict[str, int | None] = {r["id"]: r["v30"] for r in v30_rows}
    sample: list[int] = [v for uid in chosen_ids if (v := v30_by_id.get(uid)) is not None]
    return sample, chosen_max, fetched_ages


def bootstrap_sweep(sample: list[int], projected_views: int, max_bundle_size: int) -> list[BootstrapRow]:
    rng = random.Random(SEED)
    rows: list[BootstrapRow] = []
    for N in range(1, max_bundle_size + 1):
        totals: list[int] = [sum(rng.choices(sample, k=N)) for _ in range(N_SIMS)]
        totals.sort()
        p20: int = totals[int(N_SIMS * 0.20)]
        floor: int = int(FLOOR_PCT * N * projected_views)
        vg: int = max(floor, p20)
        likelihood: float = sum(1 for t in totals if t >= vg) / N_SIMS
        rows.append(BootstrapRow(N=N, vg=vg, likelihood=likelihood, floor=floor, p20=p20))
    return rows


def pick_bundle(rows: list[BootstrapRow], target: str) -> tuple[BootstrapRow, bool]:
    """Pick the recommended bundle.

    With qualifying rows (likelihood ≥ TARGET_LIKELIHOOD): smallest N (target=min) or largest N
    (target=max). With nothing qualifying: pick the row whose meaning best matches the target —
    max likelihood (with smaller N as tiebreaker) for target=min, max N for target=max.
    """
    qualifying = [r for r in rows if r.likelihood >= TARGET_LIKELIHOOD]
    if qualifying:
        return (qualifying[0] if target == "min" else qualifying[-1]), False
    if target == "min":
        return max(rows, key=lambda r: (r.likelihood, -r.N)), True
    return rows[-1], True


def cadence_per_month(fetched_ages: list[int]) -> float | None:
    """Longform upload cadence (videos / month) derived from already-fetched ages.

    Uses videos up to CADENCE_WINDOW_DAYS old; if the fetched set spans further the older tail
    is dropped. The N−1 in the formula accounts for the fact that N timestamps describe N−1
    intervals over span_days — without it the rate would over-count by attributing fractional
    videos to the blank gaps before the earliest and after the most recent video in the window.
    """
    in_window = [a for a in fetched_ages if a <= CADENCE_WINDOW_DAYS]
    if len(in_window) < 2:
        return None
    span_days = max(in_window) - min(in_window)
    if span_days <= 0:
        return None
    return (len(in_window) - 1) / (span_days / 30)


def fmt_campaign_length(N: int, cadence: float | None) -> str:
    if not cadence:
        return "n/a"
    return f"~{N / cadence:.1f} months"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("channel")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument(
        "--full-range",
        action="store_true",
        help="Force the sample to come from the full 30-240d window, skipping the staircase.",
    )
    ap.add_argument(
        "--max-bundle-size",
        type=int,
        default=DEFAULT_MAX_BUNDLE_SIZE,
        help=(f"Largest bundle size to consider (default {DEFAULT_MAX_BUNDLE_SIZE}, up to {HARD_MAX_BUNDLE_SIZE})."),
    )
    ap.add_argument(
        "--target",
        choices=["min", "max"],
        default="min",
        help=(
            "Optimization target: smallest bundle that clears 80%% (min, default) or largest that "
            "clears 80%% (max). With --target max and adequate data the answer almost always "
            "equals --max-bundle-size."
        ),
    )
    ap.add_argument(
        "--rich-output",
        action="store_true",
        help="Include per-video VG, upload cadence, and campaign length in both modes.",
    )
    args = ap.parse_args()
    channel_arg: str = args.channel
    use_sweep: bool = args.sweep
    use_full_range: bool = args.full_range
    max_bundle_size: int = args.max_bundle_size
    target: str = args.target
    rich_output: bool = args.rich_output

    if not 1 <= max_bundle_size <= HARD_MAX_BUNDLE_SIZE:
        sys.exit(f"--max-bundle-size must be between 1 and {HARD_MAX_BUNDLE_SIZE} (got {max_bundle_size})")

    channel = resolve_channel(channel_arg)
    if channel.projected_views is None:
        sys.exit(
            f"channel {channel.name} ({channel.id}) has no projected_views — usually means "
            f"the channel hasn't published enough content to establish a baseline. Statistical "
            f"VG not available; fall back on your own judgement."
        )
    pv: int = channel.projected_views

    sample, window_max, fetched_ages = get_v30_sample(channel.id, force_full_range=use_full_range)
    if len(sample) < MIN_SAMPLE:
        sys.exit(f"insufficient data — only {len(sample)} videos with 30-day view data (need {MIN_SAMPLE}+)")

    rows = bootstrap_sweep(sample, pv, max_bundle_size)
    chosen, fallback = pick_bundle(rows, target)

    widest_max: int = SAMPLE_WINDOW_STEPS[-1]
    inconsistency_banner: str = ""
    # Only worth comparing against the full range when the primary sample is thin AND the
    # staircase actually narrowed (otherwise the full-range answer is the primary answer).
    if not use_full_range and window_max != widest_max and len(sample) < THIN_SAMPLE:
        full_sample, _, _ = get_v30_sample(channel.id, force_full_range=True)
        if len(full_sample) >= MIN_SAMPLE:
            full_rows = bootstrap_sweep(full_sample, pv, max_bundle_size)
            full_chosen, full_fallback = pick_bundle(full_rows, target)
            vg_diff: float = abs(chosen.vg - full_chosen.vg) / chosen.vg
            if chosen.N != full_chosen.N or fallback != full_fallback or vg_diff >= INCONSISTENCY_VG_DIFF:
                inconsistency_banner = (
                    f"⚠️  INCONSISTENT RESULTS: primary 30-{window_max}d sample disagrees with "
                    f"the full 30-{widest_max}d sample. Re-run with --full-range to compare."
                )

    thin_sample_banner: str = (
        f"⚠️  THIN SAMPLE: only {len(sample)} videos — bootstrap variance is high, treat result as approximate." if len(sample) < THIN_SAMPLE else ""
    )
    window_banner: str = (
        f"⚠️  FALLBACK WINDOW: primary 30-{PRIMARY_WINDOW_MAX_DAYS}d window had fewer than "
        f"{MIN_SAMPLE} videos. Sample drawn from 30-{window_max}d. "
        f"VG reflects older performance - treat as less current."
        if window_max != PRIMARY_WINDOW_MAX_DAYS and not use_full_range
        else ""
    )

    cadence: float | None = cadence_per_month(fetched_ages) if rich_output else None
    fb_note: str = "  ⚠️  no bundle size hit 80% — reporting closest match" if fallback else ""

    # Recommendation block (both modes; capitalized labels)
    print(f"Channel: {channel.name} ({channel.id})")
    print(f"Video bundle size: {chosen.N}")
    print(f"Views guarantee: {chosen.vg:,.0f}")
    print(f"Likelihood to hit: {chosen.likelihood:.0%}{fb_note}")

    # Sweep+rich context lines slot between the headline numbers and the per-bundle rich lines.
    if use_sweep and rich_output:
        print(f"Projected views: {pv:,}")
        print(f"Sample size: {len(sample)} videos")
        print(f"Sample window: 30-{window_max}d")

    # Per-bundle rich lines (both modes when --rich-output is set).
    if rich_output:
        print(f"Per-video VG: {chosen.vg // chosen.N:,}")
        cad_str = f"{cadence:.1f}/month" if cadence else "n/a"
        print(f"Upload cadence: {cad_str}")
        print(f"Campaign length: {fmt_campaign_length(chosen.N, cadence)}")

    if use_sweep:
        print()
        if rich_output:
            print(f"{'Bundle size':>11}  {'Campaign length':>15}  {'VG':>12}  {'VG/video':>10}  {'Likelihood':>10}")
            for r in rows:
                marker = "  ←" if r.N == chosen.N else ""
                cl = fmt_campaign_length(r.N, cadence)
                print(f"{r.N:>11}  {cl:>15}  {r.vg:>12,.0f}  {r.vg // r.N:>10,}  {r.likelihood:>9.0%}{marker}")
        else:
            print(f"{'Bundle size':>11}  {'VG':>12}  {'Likelihood':>10}")
            for r in rows:
                marker = "  ←" if r.N == chosen.N else ""
                print(f"{r.N:>11}  {r.vg:>12,.0f}  {r.likelihood:>9.0%}{marker}")
        print()

    if thin_sample_banner:
        print(thin_sample_banner)
    if window_banner:
        print(window_banner)
    if inconsistency_banner:
        print(inconsistency_banner)


if __name__ == "__main__":
    main()
