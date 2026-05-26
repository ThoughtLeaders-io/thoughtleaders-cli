# Scoring

Deliberately simple (per the approved plan). Three check groups, each scored
**independently 0–100**: start at 100, subtract the fixed per-flag penalty for
every triggered flag, floor at 0. **Final score = simple mean of the three
group sub-scores.** No weighting matrix, no bonuses, no per-group caps.

```
final = (A + B + C) / 3
```

## Verdict bands

| score | verdict | advice |
|---|---|---|
| ≥ 90 | CLEAN | Safe to book at standard rates |
| ≥ 70 | MINOR_FLAGS | Book but note caveats to the AM |
| ≥ 40 | MIXED | Manual review; consider rate reduction |
| < 40 | FRAUD_LIKELY | Do not book without senior sign-off + heavy discount |

## Hard overrides

If either trigger fires, the verdict is forced to **FRAUD_LIKELY** and the
score capped at 39 regardless of the mean:

1. **Group C — non-organic audience:** Haiku classifier organic share
   **< 30%** (`group_c.hard_fail`), or an effectively dead comment section
   (<8-viewer-comment early exit). Fake comments are the most direct proof of
   a fake audience.
2. **Group B — concealed/misrepresented performance** (`group_b.hard_fail`):
   ≥2 sold+published sponsored videos offline/unlisted (or one with ≥5k
   views); OR ≥3 high-view videos scrubbed AND ≥15% of all tracked views
   gone. Using deletion to hide paid delivery or strike-bait is bad faith,
   not housekeeping.

Neither fires for benign deletion (low-view, young, non-sponsored re-uploads
are excluded before scoring).

## Penalties (authoritative list)

Penalties live in each script's `PENALTIES` dict; this table mirrors them.
Severity drives report ordering/icons only, not math.

### Group A — `engagement_ratios.py`
| code | penalty | severity |
|---|---|---|
| A_like_rate_vs_peers | 30 | critical |
| A_comment_rate_vs_peers | 25 | critical |
| A_longform_shorts_gap | 25 | critical |
| A_views_to_subs | 15 | warning |
| A_organic_floor | 15 | warning |
| A_per_video_outliers | 10 | info |

### Group B — `anomaly_detector.py` + `video_integrity.py`
| code | penalty | severity |
|---|---|---|
| B_burst_without_engagement | 25 | critical |
| B_engagement_incoherence | 25 | critical |
| B_latelife_drip_frozen_likes | 20 | critical |
| B_guarantee_cliff | 15 | warning |
| B_slow_start_late_spike | 15 | warning |
| B_subs_flat_while_views_surge | 15 | warning |
| B_sponsored_video_concealed | 30 | critical |
| B_high_view_video_scrub | 25 crit (≥15% views gone) / 12 warn (≥3%) / 0 (<3%) | scaled by view-share |
| B_unlisted_with_traffic | 15 | warning |

### Group C — `comment_analyzer.py`
| code | penalty | severity |
|---|---|---|
| C_comment_scarcity | 35 | critical |
| C_llm_not_organic | 30 | critical |
| C_language_mismatch | 20 | critical |
| C_generic_templates | 18 | warning |
| C_bot_usernames | 15 | warning |
| C_near_duplicates | 15 | warning |
| C_length_uniform | 12 | warning |
| C_commenter_churn | 12 | warning |
| C_emoji_only | 10 | info |
| C_low_reply_ratio | 8 | info |
| C_sentiment_uniform | 8 | info |
| C_time_clustered | 8 | info |

`C_bot_usernames` is **conditional**: the auto-generated-handle share is always
recorded as a metric, but the −15 only applies in the LLM step when organic
share is also low (< 55%). YouTube's own default handles are letters+digits,
so on a healthy-organic channel a high share is noise — it fires only as
corroboration when the audience is independently suspect.

Penalties intentionally let two criticals in a group drive it near zero — a
channel with two independent strong fraud signals in one dimension should not
score "mixed". Tune here as cases accumulate; record the reasoning in
`case-studies.md`.

## Reference result

Origin fraud case (AI/coding channel): A=0, B=15, C=27 → **14.0 FRAUD_LIKELY**.
