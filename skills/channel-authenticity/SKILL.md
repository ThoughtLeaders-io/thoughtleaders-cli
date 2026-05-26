---
name: channel-authenticity
description: >
  Detect non-organic views / fake engagement / bot comments on a YouTube
  channel before booking (or after delivering) a sponsorship. Use when asked
  to vet a channel, check if views/comments are real, investigate suspicious
  engagement, audit a sponsorship delivery, or whenever someone shares a
  YouTube channel/handle/URL and asks "is this real / safe to buy an ad on".
  Triggers: "fake views", "bot comments", "non-organic", "is this channel
  legit", "vet this channel", "engagement looks off", "audit this sponsorship".
---

# Channel Authenticity

Takes a channel (handle / URL / `channel.id` / channel name) — or
`adlink:<id>` for a sponsorship drill-down — and returns a 0–100 authenticity
score plus ranked red-flag findings. Built and calibrated from real
bought-view and comment-farm investigations.

## Hard rules

- **One mode. Every run does everything.** No flags, no opt-in tiers. Groups
  A, B, and C all run, every time.
- **Comment scraping (Group C) is mandatory and never skipped.** Metrics and
  view-curves can be hand-waved ("the algorithm", "we ran ads"); reading what
  the audience actually says is the only direct proof. A run without it is
  invalid.
- **Data access is CLI-only.** Everything goes through `tl_cli.py` → the
  `tl` CLI (`tl db pg/fb/es`, `tl channels similar`). No database credentials
  are ever used. If the CLI isn't authenticated the skill fails fast with a
  clear message.

## Setup check

```bash
cd .claude/skills/channel-authenticity/scripts
python3 tl_cli.py preflight        # must print "OK"
```
If this errors with `cli_unavailable`, tell the user to run `tl auth login`
(or set `TL_API_KEY`). Comment scraping additionally needs `yt-dlp`
(`pip install yt-dlp`) — it uses the android InnerTube client so **no cookies
or API key are required**.

## How to run (two phases — a Haiku subagent sits in the middle)

**Phase 1 — collect.** From the `scripts/` dir:
```bash
python3 analyze_channel.py "<handle|url|id|name|adlink:ID>"
```
This runs Groups A + B + C(rule-based), scrapes ≥10 latest longforms
(+ highest-view + most-recently-sponsored), and prints a JSON envelope with
`state_path`, `llm_batch_path`, and `llm_batch_size`.

If the ref matches **multiple channels** (common for names with localized
dupes), Phase 1 exits (code 4) with `{"error":"ambiguous_channel",
"candidates":[{id,name,subscribers}…]}` instead of guessing. Show the
candidates to the user — they're ordered by subscriber count, highest first
(the most likely intended) — let them pick, then re-run Phase 1 with that
numeric id.

**Phase 2 — classify comments with the subagent (run it TWICE).** Read the
file at `llm_batch_path` (a JSON array of `{i, text, author}`). Invoke the
`youtube-comment-classifier` agent via the **Agent tool**
(`subagent_type: youtube-comment-classifier`) **two separate times** on the
same batch. Prepend one context line: `channel niche: cat
<content_category>, language <language>` (values are in the envelope). Each
call returns a strict JSON array
`[{"i":N,"label":"organic|generic-template|bot-like|promotional|spam"}]`.
Save each reply verbatim to its own file, e.g. `/tmp/ca_llm1.json` and
`/tmp/ca_llm2.json`. Two passes are majority-voted in finalize so the
reported organic share is stable run-to-run (single-pass LLM labeling
wobbles ±10pts; the verdict is robust either way but the number shouldn't
move). Sophisticated AI-comment farms read as clean English with normal
volume — only the classifier catches them, so the double pass matters.

If the batch is empty (channel had almost no comments), skip the subagent and
pass an empty array `[]` — near-zero comments is itself the loudest signal
and Group C already penalizes it.

**Phase 3 — finalize** (pass both classifier files):
```bash
python3 analyze_channel.py --finalize <state_path> /tmp/ca_llm1.json /tmp/ca_llm2.json
```
This applies the LLM verdict, computes the composite score, writes the final
JSON + markdown report to `/tmp`, and prints the report. Present that report
to the user (it's already formatted — peer comparison, group scores, ranked
flags, verdict).

## Scoring (see references/scoring.md)

Three groups, each scored 0–100 independently (start at 100, subtract fixed
per-flag penalties). **Final = simple mean of the three.** Two hard
overrides force `FRAUD_LIKELY` (score capped at 39) regardless of the mean:
(1) Group C — non-organic audience (<30% organic from the Haiku pass, or a
dead comment section); (2) Group B — concealed/misrepresented performance
(≥2 sold+published sponsored videos deleted/unlisted, or one with ≥5k views;
or ≥3 high-view videos scrubbed with ≥15% of tracked views gone).

Bands: ≥90 CLEAN · ≥70 MINOR_FLAGS · ≥40 MIXED · <40 FRAUD_LIKELY.

## What each group checks

- **Group A — engagement & peer ratios** (`engagement_ratios.py`,
  `peer_cohort.py`): like:view & comment:view vs a niche-matched peer
  baseline, avg-views/subs, longform-vs-shorts engagement gap, organic floor
  from shorts, per-video outliers.
- **Group B — view-curve time-series + video integrity** (`view_curves.py`,
  `anomaly_detector.py`, `video_integrity.py`): burst-without-engagement,
  Δviews↔Δengagement incoherence, guarantee-cliff at round numbers,
  slow-start/late-spike, late-life view drip with frozen likes,
  subs-flat-while-views-surge, plus **intent-aware deleted/unlisted video
  detection** (ES `offline_since` + `content_aspects:'unlisted'` × sold
  adlinks; benign re-uploads excluded — deletion only counts when used to
  conceal/misrepresent performance).
- **Group C — comment content** (`comment_scraper.py`,
  `comment_analyzer.py` + Haiku subagent): comment scarcity vs views,
  length uniformity, language mismatch, generic templates, emoji-only,
  bot-handle patterns, near-duplicates, reply ratio, creator engagement,
  cross-video commenter churn, time clustering, LLM organic share.

Full catalogue + thresholds: `references/red-flags.md`.
Exact `tl` queries each check issues: `references/tl-cli-recipes.md`.

## After a run

Offer to log the verdict (channel, score, top flags, date) to a "Channel
Vetting Log" sheet via the `gws` skill if the user wants an audit trail.
If you discover a new robust signal, add it to `references/red-flags.md` and
a penalty to `references/scoring.md` (self-improvement).
