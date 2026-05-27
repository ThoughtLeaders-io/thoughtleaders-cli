#!/usr/bin/env python3
"""Composite scoring — deliberately simple (per approved plan).

Three check groups (A engagement, B view-curves, C comments), each an
independent 0-100 sub-score. Final = simple mean. No weighting matrix, no
bonuses. One override: if Group C flags a hard fail (<30% organic from the
Haiku pass, or an effectively dead comment section), the verdict is forced
to "do not book" regardless of the mean.
"""
from __future__ import annotations

BANDS = [
    (90, "CLEAN", "Safe to book at standard rates."),
    (70, "MINOR_FLAGS", "Book but note caveats to the AM."),
    (40, "MIXED", "Manual review required; consider rate reduction."),
    (0, "FRAUD_LIKELY", "Do not book without senior sign-off + heavy discount."),
]


def band(score: float) -> tuple[str, str]:
    for threshold, label, advice in BANDS:
        if score >= threshold:
            return label, advice
    return "FRAUD_LIKELY", BANDS[-1][2]


def composite(group_a: dict, group_b: dict, group_c: dict) -> dict:
    a, b, c = group_a["subscore"], group_b["subscore"], group_c["subscore"]
    mean = round((a + b + c) / 3, 1)

    c_fail = bool(group_c.get("hard_fail"))
    b_fail = bool(group_b.get("hard_fail"))
    hard_fail = c_fail or b_fail
    if hard_fail:
        final = min(mean, 39.0)
        if c_fail and b_fail:
            reason = (
                "Non-organic audience (comments) and concealed/scrubbed video "
                "history (hard override)"
            )
        elif c_fail:
            reason = "Comment analysis shows a non-organic audience (hard override)"
        else:
            reason = (
                "Deleted/unlisted videos indicate concealed or misrepresented "
                "performance (hard override)"
            )
        label, advice = "FRAUD_LIKELY", (
            f"{reason} — do not book without senior sign-off."
        )
    else:
        final = mean
        label, advice = band(mean)

    all_flags = (
        group_a["flags"] + group_b["flags"] + group_c["flags"]
    )
    crit = [f for f in all_flags if f["severity"] == "critical"]
    return {
        "final_score": final,
        "verdict": label,
        "advice": advice,
        "hard_override_applied": hard_fail,
        "group_scores": {"A_engagement": a, "B_view_curves": b, "C_comments": c},
        "n_flags": len(all_flags),
        "n_critical": len(crit),
        "critical_flags": [f["code"] for f in crit],
    }


if __name__ == "__main__":
    import json
    import sys

    d = json.load(open(sys.argv[1]))
    print(json.dumps(composite(d["group_a"], d["group_b"], d["group_c"]), indent=2))
