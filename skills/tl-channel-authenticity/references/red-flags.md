# Red-flag catalogue

Every signal the skill checks, why it matters, and the threshold. Codes match
the `flags[].code` in the JSON output. Real cases are referenced by anonymized
label only.

## Group A — engagement & peer ratios (`engagement_ratios.py`)

| code | trigger | why |
|---|---|---|
| `A_like_rate_vs_peers` | longform like:view < 0.4× peer-cohort median | Paid/bot views don't like. Origin case: 0.027% vs 3.4% peer median (125×). |
| `A_comment_rate_vs_peers` | longform comment:view < 0.4× peer median | Same logic for comments. Origin case: 78× below. |
| `A_views_to_subs` | avg longform views > 20% of subs | Healthy 1–15%. Origin case 28%. Implies non-subscriber/external traffic. |
| `A_longform_shorts_gap` | shorts like-rate ≥ 5× longform like-rate (shorts ≥0.3%) | Organic shorts + dead longforms ⇒ longforms are the promoted units. The smoking gun on the origin case (20×). |
| `A_organic_floor` | ≥ half of longforms exceed 5× the median-short view count | Non-viral shorts ≈ true audience size. Origin case median short = 688 views vs 180k longform. |
| `A_per_video_outliers` | ≥⅓ of longforms >1.5σ below the channel's own like:view mean | One real audience produces consistent ratios; promoted videos don't. |

Peer baseline: niche-matched (`tl channels similar`, fallback PG cohort:
same content_category+language, active, reach ±50%, published <60d), median
of each peer's last-10-longform like/comment rates. Cached 30 days.

## Group B — view-curve time-series (`anomaly_detector.py`)

| code | trigger | why |
|---|---|---|
| `B_burst_without_engagement` | a Δ-segment with Δviews/day > 3× rolling mean, >5k views, and segment like-rate < ½ lifetime | Real virality brings likes; injected views don't. |
| `B_engagement_incoherence` | Pearson r(Δviews, Δlikes+Δcomments) < 0.2 over the curve | Organic videos: views and engagement move together (r>0.6). Fraud: decoupled. |
| `B_guarantee_cliff` | plateau within 5% of a round number (50k/100k/250k/500k/1M…) by age ≤60 then flat | A bought-view case: bought to a 500k guarantee, cliffed at 581k. |
| `B_slow_start_late_spike` | views@2 < 25th-pctile-ish (< 0.15× final) AND views@10/views@2 > 8 | Paid traffic switched on days after publish — classic bought-view signature. |
| `B_latelife_drip_frozen_likes` | age ≥20 segment with >3k new views but ≤1 new like | Post-publish ad campaigns drip views with zero engagement. Seen on every video of the origin case. |
| `B_subs_flat_while_views_surge` | < 30 new subs per 100k channel views over snapshot window | A bought-view case: 27 subs / 580k views. Viewers don't convert ⇒ not real interest. |

Interpolation (`view_curves.py`) is self-contained (linear + log bracket
interpolation, per-segment deltas) — no external dependency.

### Group B add-on — video integrity (`video_integrity.py`)

Deletion/unlisting is **not** a signal by itself — channels legitimately
re-upload and clean house. The signal is deletion used to **conceal or
misrepresent performance**. Source: ES `offline_since` (exists ⇒ video gone)
and `content_aspects` containing `'unlisted'`. Intent is inferred from
view count, age-at-removal, and whether the video was a paid sponsorship.

| code | trigger | why |
|---|---|---|
| `B_sponsored_video_concealed` | a SOLD+PUBLISHED adlink's video is now offline/unlisted | Brand paid, ad went live, delivery then hidden. Bad-faith + finance/delivery alarm. Hard-fail if ≥2, or one with ≥5k views. |
| `B_high_view_video_scrub` | offline video(s) above the channel's high-view bar (max of 50k or 25% of median) | You don't delete a 2M-view video by accident. Penalty scales by the **share of tracked views** gone, not raw count (big channels always shed a few old high-view videos): ≥15% → −25 critical; ≥3% → −12 warning; <3% → recorded, not penalized. Hard-fail only if ≥3 videos AND ≥15% of views vanished. |
| `B_unlisted_with_traffic` | unlisted video still carrying ≥20k views | Hidden from channel page/subscribers while accruing views — running content the organic audience never sees. |

Benign (recorded in metrics, **not** penalized): removed ≤7d after publish,
<5k views, non-sponsored (re-upload/mistake — e.g. a 713-view video pulled
2 days after publish).

## Group C — comment content (`comment_analyzer.py` + Haiku subagent)

| code | trigger | why |
|---|---|---|
| `C_comment_scarcity` | viewer comments < 15% of a 1-per-2,000-views floor (scraped ≥50k views) | The single loudest signal. Origin case: ~21 comments across ~1.8M scraped views. Measured on freshly-scraped comments so it can't be a stale count. |
| `C_language_mismatch` | <60% of comments in channel language (en channels) | Off-language comment farms — e.g. off-language/emoji junk flooding an English channel. |
| `C_generic_templates` | >40% generic ("nice video", lone emoji…) | Padding. Library in `comment-patterns.md`. |
| `C_length_uniform` | ≥70% ≤5 words AND median <8 words | Bots cluster short; real audiences have a long tail. |
| `C_emoji_only` | >25% emoji-only / no real text | Filler. |
| `C_bot_usernames` | >30% handles match `^@?[a-z]+[-_]?\d{4,}$` **AND** LLM organic share < 55% | YouTube's own default handles match this pattern too, so it's only a tell when the audience is independently suspect — fires as corroboration in the LLM step, never on format alone. |
| `C_near_duplicates` | largest token-Jaccard>0.7 cluster >10% | Templated posting. |
| `C_low_reply_ratio` | <5% of top comments have any reply | Real audiences converse. |
| `C_no_creator_engagement` | creator hearts 0 comments | Creator ignores a section they know is fake. |
| `C_commenter_churn` | <2% commenters appear on >1 video | No recurring fanbase; throwaway accounts. |
| `C_time_clustered` | >50% of comments in first hour on a weeks-old video | Burst posting. |
| `C_llm_not_organic` | Haiku classifier <50% organic | Catches subtle patterns rules miss. <30% ⇒ hard override → FRAUD_LIKELY. |

## Contributing new signals

Found a robust new tell? Add a row here, add a penalty + severity to the
relevant `PENALTIES` dict in the script, and document the penalty in
`scoring.md`. Keep thresholds evidence-based, but **reference cases by
anonymized label only — never a channel name, id, or handle** (this skill
ships in a public repo).
