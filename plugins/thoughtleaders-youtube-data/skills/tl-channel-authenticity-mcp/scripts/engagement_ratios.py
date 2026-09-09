#!/usr/bin/env python3
"""Group A — cheap aggregate engagement signals.

Returns {"subscore": 0-100, "flags": [...], "metrics": {...}} where each flag
is {code, severity, detail, penalty}. Penalties are defined in
references/scoring.md and applied here; the group subscore starts at 100 and
each triggered flag subtracts its penalty (floored at 0).
"""
from __future__ import annotations

import statistics

import _io_utf8  # noqa: F401  (side effect: forces UTF-8 stdout/stderr on Windows)
import peer_cohort

# code -> (penalty, severity)
PENALTIES = {
    "A_like_rate_vs_peers": (30, "critical"),
    "A_comment_rate_vs_peers": (25, "critical"),
    "A_views_to_subs": (15, "warning"),
    "A_longform_shorts_gap": (25, "critical"),
    "A_organic_floor": (15, "warning"),
    "A_per_video_outliers": (10, "info"),
}


def _agg(videos: list[dict]) -> tuple[int, int, int, int]:
    v = sum(x["views"] for x in videos)
    li = sum(x["likes"] for x in videos)
    c = sum(x["comments"] for x in videos)
    return v, li, c, len(videos)


def analyze(channel: dict, longform: list[dict], shorts: list[dict]) -> dict:
    flags: list[dict] = []
    metrics: dict = {}

    base = peer_cohort.get_baseline(channel)
    metrics["peer_baseline"] = base

    lf_v, lf_l, lf_c, lf_n = _agg(longform)
    sh_v, sh_l, sh_c, sh_n = _agg(shorts)

    lf_like_rate = lf_l / lf_v if lf_v else 0.0
    lf_cmt_rate = lf_c / lf_v if lf_v else 0.0
    sh_like_rate = sh_l / sh_v if sh_v else 0.0
    metrics.update(
        longform_like_rate=lf_like_rate,
        longform_comment_rate=lf_cmt_rate,
        shorts_like_rate=sh_like_rate,
        longform_videos=lf_n,
        shorts_videos=sh_n,
        avg_longform_views=(lf_v / lf_n) if lf_n else 0,
    )

    # 1. like:view vs peers
    if lf_v and lf_like_rate < 0.4 * base["like_rate_median"]:
        flags.append(
            _flag(
                "A_like_rate_vs_peers",
                f"Longform like rate {lf_like_rate*100:.3f}% is "
                f"{base['like_rate_median']/max(lf_like_rate,1e-9):.0f}x below peer "
                f"median ({base['like_rate_median']*100:.2f}%).",
            )
        )

    # 2. comment:view vs peers
    if lf_v and lf_cmt_rate < 0.4 * base["comment_rate_median"]:
        flags.append(
            _flag(
                "A_comment_rate_vs_peers",
                f"Longform comment rate {lf_cmt_rate*100:.4f}% is "
                f"{base['comment_rate_median']/max(lf_cmt_rate,1e-9):.0f}x below peer "
                f"median ({base['comment_rate_median']*100:.3f}%).",
            )
        )

    # 3. avg views / subscribers
    subs = channel.get("subscribers") or 0
    if subs and lf_n:
        ratio = (lf_v / lf_n) / subs
        metrics["views_to_subs_ratio"] = ratio
        if ratio > 0.20:
            flags.append(
                _flag(
                    "A_views_to_subs",
                    f"Avg longform views are {ratio*100:.0f}% of subscriber count "
                    f"({subs:,}); healthy channels run 1-15%. Sustained >20% "
                    f"implies a non-subscriber (external/paid) traffic source.",
                )
            )

    # 4. longform/shorts engagement gap
    if sh_v and lf_v and sh_like_rate > 0 and lf_like_rate > 0:
        gap = sh_like_rate / lf_like_rate
        metrics["shorts_over_longform_like_gap"] = gap
        if gap >= 5 and sh_like_rate >= 0.003:
            flags.append(
                _flag(
                    "A_longform_shorts_gap",
                    f"Shorts like rate ({sh_like_rate*100:.3f}%) is {gap:.0f}x the "
                    f"longform rate ({lf_like_rate*100:.3f}%). Organic shorts + "
                    f"dead longforms = longforms are being promoted/inflated.",
                )
            )

    # 5. organic floor from non-viral shorts
    if shorts:
        sviews = sorted(x["views"] for x in shorts)
        floor = statistics.median(sviews)
        metrics["organic_floor_shorts_median_views"] = floor
        if floor > 0 and lf_n:
            inflated = [x for x in longform if x["views"] > 5 * floor]
            metrics["longforms_above_5x_floor"] = len(inflated)
            if len(inflated) >= max(3, lf_n // 2):
                flags.append(
                    _flag(
                        "A_organic_floor",
                        f"{len(inflated)}/{lf_n} longforms exceed 5x the organic "
                        f"floor (median short = {floor:,.0f} views). The honest "
                        f"audience looks ~{floor:,.0f}, far below longform views.",
                    )
                )

    # 6. per-video like:view outliers (z-score)
    rates = [(x["likes"] / x["views"]) for x in longform if x["views"] > 1000]
    if len(rates) >= 5:
        mu = statistics.mean(rates)
        sd = statistics.pstdev(rates) or 1e-9
        outliers = [r for r in rates if (r - mu) / sd < -1.5]
        metrics["per_video_low_outliers"] = len(outliers)
        if len(outliers) >= max(2, len(rates) // 3):
            flags.append(
                _flag(
                    "A_per_video_outliers",
                    f"{len(outliers)}/{len(rates)} longforms sit >1.5σ below the "
                    f"channel's own like:view mean — inconsistent with one organic "
                    f"audience.",
                )
            )

    subscore = 100
    for f in flags:
        subscore -= f["penalty"]
    return {"subscore": max(subscore, 0), "flags": flags, "metrics": metrics}


def _flag(code: str, detail: str) -> dict:
    pen, sev = PENALTIES[code]
    return {"code": code, "severity": sev, "detail": detail, "penalty": pen}


if __name__ == "__main__":
    import json
    import sys

    import resolve_channel

    d = resolve_channel.resolve(sys.argv[1])
    print(json.dumps(analyze(d["channel"], d["longform"], d["shorts"]), indent=2, default=str))
