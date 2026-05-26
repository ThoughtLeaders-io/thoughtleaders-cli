# Case studies

Ground-truth runs — the regression set and evidence base for threshold tuning.
Cases are **anonymized**: this skill ships in a public repo, so no channel
name, id, handle, brand, or deal reference appears here. Each case keeps only
the niche, rough size, metrics, and the lesson it taught.

## Case A — FRAUD_LIKELY (the origin case)

**Final 14.0/100** · A=0 · B=15 · C=27. AI/coding niche, mid-six-figure subs,
English, TPP + MSN.

- An ad we had already booked on this channel delivered 156k views / 32 likes
  — the same dead-engagement pattern we then built the skill to catch.
- **Group A:** like rate 0.027% (125× below peer median 3.4%), comment rate
  0.0027% (78× below), avg longform views 29% of subs, shorts like-rate 20×
  longform, all 16 longforms >5× the ~730-view organic floor.
- **Group B:** 7/10 longforms burst-without-engagement, 4/10 incoherent
  (r≈−0.12), 4/10 late-life drip with frozen likes, 4/10 slow-start/late-spike.
- **Group C:** 21 viewer comments across 2.17M scraped views (~2% of a
  conservative floor); Haiku organic share 33% (9 generic, 4 bot, 1 promo);
  off-language/emoji junk from random-string handles on English videos.
- Verdict matched the manual investigation exactly. The canonical positive
  regression case.

## Clean control — CLEAN

**A=100 · B=100 · C≈100** (pre-LLM; only the now-fixed reply-data false-flag
fired). Web-dev tutorials, ~1M subs.

- like rate 5.05%, comment rate 0.36%, views/subs 2.1% — all healthy. 411
  viewer comments across 221k scraped views, 100% language match, 2% generic.
- No A or B flags. Confirms the skill does not false-positive on a strong
  organic channel. Canonical negative regression case.

## Case B — FRAUD_LIKELY (AI comment farm)

**Final 39.0/100** (hard override) · A=60 · B=0 · C=70-rule-based →
C_llm_not_organic. Health/wellness niche (cat 21), ~100k subs, non-TPP, not MSN.

- **The canonical "LLM catches what rules miss" case.** Group C rule-based
  checks score 100: 768 viewer comments across 1.08M scraped views, 100%
  English, 0% generic-keyword, normal length distribution — every heuristic
  passes. The comments are a *sophisticated LLM-generated comment farm*:
  grammatically perfect, on-topic, uniform template texture ("I liked that
  you mentioned X because Y", "my [relative] always says…", manufactured
  "do you ever…?" engagement questions) from auto-style firstname-lastname
  handles.
- Only the Haiku classifier caught it: per-pass organic 5% / 15%, majority
  15% → < 30% hard override → FRAUD_LIKELY.
- Group B independently = 0 (bursts at 0.000% like-rate, frozen-like drips,
  r=−0.08 incoherence, clean ~50,000 plateau, 0 subs / 100k views). Group A:
  avg views = 105% of subs, like-rate kept artificially healthy (5.2%) to
  mask the dead comment ratio.
- Pure-metrics or pure-keyword tools would pass this channel. Demonstrates
  why comment scraping + LLM classification is non-negotiable.

## Calibration channel — MINOR_FLAGS (real channel, calibration anchor)

**Final 84.7/100** · A=75 · B=100 · C=79. Military/defense niche (cat 14),
~350k subs, TPP + MSN.

- Genuine opinionated human audience: vets recounting service, defense
  procurement debate, political snark, real foreign-language viewers. LLM
  organic 80%, stable across passes (78%/80%).
- Group B clean (100) — organic curves, **and** video integrity clean:
  1/50 offline (2%), 0 unlisted; the one offline video (713 views, pulled
  2d after publish, non-sponsored) correctly classified **benign** and
  excluded. The canonical proof that benign deletion is not penalized.
- Caveats (why not CLEAN): `A_comment_rate_vs_peers` (lurker-heavy defense
  audience, likely genuine) and a high auto-suffixed-handle share that the LLM
  independently scored 80% organic — so the bot-handle override correctly did
  NOT fire. Good example of supporting heuristics being overridden by
  authoritative evidence.

## Case C — prior manual sponsorship investigation (not yet re-run through the skill)

A sponsored video bought to a 500k-view guarantee. Curve: slow start →
discrete +150k spike → hard cliff at 581k → frozen. Only 2% of views from YT
impressions; 27 subs / 580k views. Expected skill behavior when run with
`adlink:<id>` drill-down: B_guarantee_cliff, B_slow_start_late_spike,
B_subs_flat_while_views_surge. **TODO:** run it through the skill and record.

## Tuning log

- Initial thresholds set from the origin fraud case (positive) + a clean
  web-dev control (negative) pair. `C_comment_scarcity` added after the first
  origin-case run scored Group C 92 — comment *volume vs views* was the missing
  signal; it's now the single highest comment penalty (35).
- `C_low_reply_ratio` made conditional on reply data actually being present
  (yt-dlp doesn't always surface reply counts) to stop it false-flagging clean
  channels.
- Added `video_integrity.py` (Group B add-on) — intent-aware deleted/unlisted
  detection via ES `offline_since` + `content_aspects:'unlisted'`,
  cross-referenced with sold+published adlinks. Deletion alone is not
  penalized; only concealment/misrepresentation (sponsored video hidden,
  high-view scrub, unlisted-with-traffic). New Group B hard override. Verified
  non-regressive on the calibration channel (benign 713-view/2-day removal
  excluded, stays 84.7).
- Added multi-pass classifier merge (`merge_passes`, majority vote, skeptical
  tie-break). Single-pass LLM organic share wobbled (the comment-farm case:
  5% vs 15% across runs); 2-pass majority stabilizes the reported number. The
  verdict was already robust via the wide 30% margin — this only fixes
  run-to-run number jitter. SKILL.md instructs two classifier passes;
  `--finalize` accepts multiple LLM files.
- `B_high_view_video_scrub` escalation made view-share-based (not raw count):
  large channels always shed a few old high-view videos, so <3% of tracked
  views gone is no longer penalized. `C_bot_usernames` made conditional on a
  low LLM organic share, since YouTube's own default handles match the
  auto-handle pattern — it now corroborates rather than fires standalone.
