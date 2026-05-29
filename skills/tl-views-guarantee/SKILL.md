---
name: tl-views-guarantee
description: Calculate the optimal views guarantee (VG) for a multi-video sponsorship buy with a YouTube creator. Given a channel ID or name, returns "video bundle size / views guarantee / likelihood to hit" based on bootstrap simulation of the channel's recent video performance (view counts measured at video age ~30 days). Use when someone asks "what VG should I push for with [creator]", "how many videos should I buy from [creator]", "calculate VG for [channel]", "what's a safe guarantee for [channel]", or anything involving setting views guarantees in a sponsorship deal. Triggers on "VG", "views guarantee", "views minimum", and any request to size a multi-video buy.
---

# Views Guarantee (VG) Calculator

Runs a single script and returns one answer.

## Usage

User says:
- "What VG should I push for with Sydney Watson?"
- "Calculate VG for channel 20107"
- "How many videos should I buy from Stephen Gardner?"

**Default path — this is what you do almost every time.** Run the script with just the channel ID or name, no flags (`<SKILL_DIR>` is this skill's directory):

```bash
python3 <SKILL_DIR>/scripts/vg.py <channel_id_or_name>
```

Print the script's four-line output back to the user verbatim — don't reformat it into a table, add commentary, or pull in extra metrics. Then, in one short line, offer to go deeper (e.g. "Want the full bundle-size sweep, a larger buy, or the per-video / cadence breakdown?"). Keep the first answer minimal; only reach for the flags below when the user actually asks for more. Don't volunteer them by running them speculatively.

### Optional flags — only when the user explicitly asks for more

Add these **one at a time, matched to what the user requested** — never stack them by default:

- `--sweep`: the user wants to see every bundle size, not just the recommendation. Prints the recommendation followed by the full table.
- `--max-bundle-size N`: the user is considering a larger / long-term buy (5+ videos). Raises the ceiling from the default `4` up to `10`.
- `--target max`: the user (or the brand) prefers the biggest bundle that still clears the threshold rather than the smallest. Pair with a raised `--max-bundle-size` to actually pick a larger buy. (`--target min` is the default and need not be passed.)
- `--rich-output`: the user wants the extra economics — `Per-video VG`, `Upload cadence` (longform uploads per month), and `Campaign length` (≈ bundle size ÷ cadence). In sweep mode it also adds `Campaign length` and `VG/video` table columns plus `Projected views` / `Sample size` / `Sample window` context lines.
- `--full-range`: only when the script itself printed an **INCONSISTENT RESULTS** banner suggesting it — forces the sample to the full 30–240d window instead of the staircase.

## What the script does

1. Resolves channel ID from name if needed (via `tl channels find <name>`)
2. Pulls `projected_views` from the channel record
3. Picks a sample window matching the range used for the channel's projected views: primary is **videos published 30–90 days ago**; if fewer than 5 videos survive, widens to **30–120**, then **30–180**, then **30–240**. Never samples beyond 240 days (the outer bound of that range).
4. Looks up each video's view count at age 28–32 days
5. Bootstrap-simulates 10k buys for each video bundle size from 1 up to `--max-bundle-size` (default 4, configurable up to 10)
6. For each bundle size: `VG = max(0.75 × bundle_size × projected_views, p20 of bootstrap totals)`
7. With `--target min` (default), picks the smallest bundle size whose likelihood ≥ 80%. With `--target max`, picks the largest such bundle, capped at `--max-bundle-size`.
8. If no bundle size hits 80%, falls back to the closest match: highest likelihood for `--target min`, largest bundle for `--target max`. The result is reported with its actual (sub-80%) likelihood as a negotiation signal.
9. If the sample came from anything other than the primary 30–90d window, prints a **FALLBACK WINDOW** banner — the bootstrap reflects older performance than the projected-views baseline, so treat the result as less current.
10. If the primary sample is **thin** (fewer than 10 videos) and the staircase didn't already use the widest window, the script silently re-runs the bootstrap against the full 30–240d sample and compares. If the two results disagree on the chosen bundle size, on whether they reach the 80% likelihood threshold, or by ≥10% on VG, it prints an **INCONSISTENT RESULTS** banner suggesting you re-run with `--full-range` to inspect the wider view.

## Output format

**This is the default and the only output you produce unless the user asks for more.** Four lines — relay them as-is:

```
Channel: Sydney Watson (20107)
Video bundle size: 2
Views guarantee: 536,422
Likelihood to hit: 80%
```

<details>
<summary>What the optional flags add (only render these when the user asked for them)</summary>

`--sweep` — recommendation block first, then the full table with the chosen row marked `←`:

```
Channel: Sydney Watson (20107)
Video bundle size: 2
Views guarantee: 536,422
Likelihood to hit: 80%

Bundle size            VG  Likelihood
          1       257,989        71%
          2       536,422        80%  ←
          3       841,851        80%
          4     1,166,196        80%
```

`--sweep --rich-output --max-bundle-size 10 --target max` — adds the per-bundle rich detail (`Per-video VG`, `Upload cadence`, `Campaign length`), the `Projected views` / `Sample size` / `Sample window` context lines under `Likelihood to hit`, and two extra table columns (`Campaign length` after `Bundle size`, `VG/video` between `VG` and `Likelihood`):

```
Channel: Sydney Watson (20107)
Video bundle size: 10
Views guarantee: 3,109,269
Likelihood to hit: 80%
Projected views: 343,986
Sample size: 14 videos
Sample window: 30-90d
Per-video VG: 310,926
Upload cadence: 6.2/month
Campaign length: ~1.6 months

Bundle size  Campaign length            VG    VG/video  Likelihood
          1      ~0.2 months       257,989     257,989        71%
          2      ~0.3 months       536,422     268,211        80%
          ...
         10      ~1.6 months     3,109,269     310,926        80%  ←
```

</details>

## Edge cases

- **<5 historical samples**: skill exits with `insufficient data — only <count> videos with 30-day view data (need 5+)`.
- **5-9 samples**: prints `⚠️  THIN SAMPLE: only <count> videos — bootstrap variance is high, treat result as approximate.` underneath the result.
- **No projected_views on the channel record**: usually means the channel hasn't published enough content to establish a baseline (not a data staleness issue). Statistical VG isn't available — fall back on your own judgement.
- **Volatile/underperforming creators**: the skill reports the floor VG with whatever likelihood the data supports (could be 60–70%). A lower likelihood isn't a failure — treat it as a negotiation signal. A missed guarantee typically just means the creator owes a make-good video, so a guarantee you're comfortable accepting at lower confidence can still be the right call.

## Methodology notes

- Floor: `0.75 × bundle_size × projected_views` (the 75% rule, aggregate)
- Skew adjustment: `max(floor, p20 of bootstrap)` — the bootstrap p20 will exceed the floor only when the channel has tight distribution and the floor would over-shoot, which is rare. In practice the floor binds.
- Bootstrap = resampling with replacement from actual historical 30-day view counts. No distribution assumptions.
- Sample window mirrors the same range over which the channel's projected views are computed, so the bootstrap reflects the same era of the channel that defined projected views. Staircase: 30–90 → 30–120 → 30–180 → 30–240. Always keep the bootstrap window inside the projected-views window — sampling beyond it mixes current projected views against a stale empirical distribution and produces misleading "channel under-delivers" results on recently-spiking channels.
- Per-video "30-day view count" = the average of all view-count snapshots recorded for that video between ages 28 and 32 days inclusive, cast to integer. Averaging across the 5-day window smooths single-snapshot jitter; alternative aggregations (min ≈ age-28 snapshot, max ≈ age-32 snapshot) would lock to one end of the window.
- Likelihood threshold for picking the bundle size = 80%.
- Default max bundle size = 4; raise via `--max-bundle-size` up to a hard ceiling of 10. 5+ video buys imply long-term campaigns — pair the raised ceiling with `--target max` to actually pick a larger bundle.
- Bundle-size sweep starts at 1 — single-video buys allowed when data supports it.
- Upload cadence (`--rich-output`) is derived from the videos already fetched for the bootstrap — no extra query. If the fetched set spans more than 180 days, only the most recent 180 days are used; if it spans less (high-cadence channel), the actual span is used. Cadence = `(videos − 1) ÷ months` so the rate doesn't leak into the blank intervals before the earliest and after the most recent video. Campaign length = `bundle size ÷ cadence`.
