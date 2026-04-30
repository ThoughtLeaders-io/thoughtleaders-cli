# Golden Queries — hand-curated NL inputs for the v2 skill

**Purpose**: a small, hand-curated test set the v2 skill must handle correctly. Used for prompt iteration in M2/M3 and as Creator inputs in the M8 refinement pipeline.

**Source**: distilled from `#ai-report-builder` Slack history + common patterns AMs use today. Expand to ~50 once M2 lands and we have a working matcher to test against.

**Note**: expected verdicts may be refined as the matcher rehearsal surfaces more conservative behavior. See [`topic_matcher_rehearsal.md`](topic_matcher_rehearsal.md) for the first-run results.

**Format per query**:
- `ID` — stable identifier
- `Query` — exact NL phrasing
- `Expected report type` — CONTENT (1) | BRANDS (2) | CHANNELS (3) | SPONSORSHIPS (8)
- `Expected topic match(es)` — IDs from `thoughtleaders_topics` (96–105 today) or `none`
- `Expected keywords` (rough) — what the keyword set should look like
- `Notes` — what makes this query interesting; what an early version is likely to get wrong

---

## 1. Straightforward channels query
- **ID**: G01
- **Query**: `"Build me a report of gaming channels with 100K+ subscribers in English"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 98 (PC Games) — strong
- **Expected keywords**: gaming, esports, gameplay, twitch streamer
- **Notes**: Baseline. Should match Topic 98 immediately; subscriber threshold + language are simple filterset fields.

## 2. Brand-driven query
- **ID**: G02
- **Query**: `"Show me brands sponsoring AI tutorial channels in the last 6 months"`
- **Expected report type**: BRANDS (2)
- **Expected topic match(es)**: 96 (Artificial Intelligence) — strong
- **Expected keywords**: AI tutorial, machine learning tutorial, ChatGPT tutorial
- **Notes**: BRANDS report driven by a topic + recency. The matcher should catch "AI" as Topic 96. Recency window → date filter.

## 3. Multi-topic ambiguity
- **ID**: G03
- **Query**: `"AI cooking shows for product placements"`
- **Expected report type**: CHANNELS (3) or CONTENT (1) (depending on AM intent)
- **Expected topic match(es)**: 96 (AI) **and** 99 (Cooking) — both strong
- **Expected keywords**: AI cooking, smart kitchen, generative AI recipes
- **Notes**: **Multi-topic disambiguation case** (open Q2 in architecture doc). Skill should surface both matches with an option to AND/OR them. Don't silently pick one.

## 4. Sponsorship pipeline query
- **ID**: G04
- **Query**: `"Pull me Q1 2026 sold sponsorships for personal investing channels"`
- **Expected report type**: SPONSORSHIPS (8)
- **Expected topic match(es)**: 97 (Personal Investing) — strong
- **Expected keywords**: investing, stock market, personal finance
- **Notes**: SPONSORSHIPS reports skip keyword research per v1's flow (sponsorships query Postgres directly, not ES). v2 should detect type 8 and route to a SQL-only path (no keyword research → straight to Phase 3 with `publish_status=3` + date range).

## 5. Content with brand exclusion
- **ID**: G05
- **Query**: `"Wellness videos but exclude anything sponsored by Nike or Adidas"`
- **Expected report type**: CONTENT (1)
- **Expected topic match(es)**: 100 (Wellness) — strong
- **Expected keywords**: wellness, fitness, mindfulness, health
- **Notes**: Tests `exclude_brands` cross-reference. v2 must resolve "Nike" / "Adidas" to brand IDs upfront (Surprise #6 in v1-vs-v2 doc — v1 silently drops unresolved cross-refs).

## 6. Vague / under-specified
- **ID**: G06
- **Query**: `"Build me a report"`
- **Expected report type**: ask
- **Expected topic match(es)**: n/a
- **Expected keywords**: n/a
- **Notes**: **Negative test.** Skill must ask for specifics rather than hallucinate a default. The v1 system prompt has guidance for this; v2 should preserve it.

## 7. Sponsorship synonym (v1 weakness)
- **ID**: G07
- **Query**: `"Show me partnerships from last quarter for beauty creators"`
- **Expected report type**: SPONSORSHIPS (8)
- **Expected topic match(es)**: 104 (Beauty) — strong
- **Expected keywords**: beauty, makeup, skincare
- **Notes**: **Tests Surprise #1 from v1 audit.** v1's `_SPONSORSHIP_KEYWORDS = {pipeline, deal, deals, adlink, adlinks}` does NOT contain "partnership" — v1 misclassifies this as type 3 (CHANNELS). v2 must broaden the sponsorship intent set.

## 8. AND vs OR keyword operator
- **ID**: G08
- **Query**: `"Channels covering both cooking AND wellness topics"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 99 (Cooking) + 100 (Wellness) — both strong
- **Expected keywords**: cooking + wellness, healthy recipes (combined)
- **Notes**: **Tests Surprise #2.** v1 silently defaults `keyword_operator` to OR; user explicitly said "AND" / "both". v2 must infer AND from conjunctions. This also doubles as a multi-topic test like G03.

## 9. Off-taxonomy query (no topic match)
- **ID**: G09
- **Query**: `"Find me crypto / Web3 channels"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: none (verdict: weak/none for all 10 seeded topics — "Personal Investing" overlap is partial at best)
- **Expected keywords**: crypto, bitcoin, ethereum, web3, defi
- **Notes**: **Tests "no topic match" path.** Matcher returns no strong verdicts → Filter Builder falls back to keyword-only path. Should *not* force a weak topic match (Topic 97 / Personal Investing); should generate keywords directly. v2's matcher must distinguish "weak match" from "force-fit."

## 10. Cross-reference with date scope
- **ID**: G10
- **Query**: `"Tech channels we haven't pitched in the last 12 months"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 101 (Computing) — strong (topic keywords `"tech career"`, `"tech interview prep"` literally contain `"tech"`); 96 (AI) — weak (tech-adjacent, but no AI-specific keyword in the query)
- **Expected keywords**: tech, computing, programming, software (Computing-leaning)
- **Notes**: **Multi-step source query case** (cross-ref with date filter). v1 has `multi_step_query` semantics in `system_prompt.txt` (lines 29–54) for this. v2 must invoke that pattern — extract channel IDs from a sponsorship-history sub-query with `days_ago: 365`, then exclude them from the main filterset. *Expected verdicts refined 2026-04-29 after the first matcher rehearsal — original prediction was "both strong"; the conservative rule of "weak when no explicit keyword match" is correct.*

---

## Hand-rating rubric (for M2 exit signal)

For each golden query, the skill's Phase 1 + Phase 2a output is **defensible** if:
1. Report type matches expected (or is "ask" for G06)
2. Topic matcher returns the expected verdicts (`strong` for the listed IDs, `weak`/`none` for others)
3. Reasoning string explains *why* — at least one quoted phrase from the query

**Target for M2 exit**: 8 out of 10 defensible verdicts on first run, no critical misclassifications (i.e., G07's "partnership" must route to type 8, not 3).

## What to add later (when expanding to ~50)
- More multi-topic combinations (Topic × Topic, Topic × keyword)
- Date-range edge cases ("last week", "Q4 2025", "since the new year")
- Demographic filters ("Gen Z creators", "channels with majority female audience")
- Channel-format filters (Shorts, podcasts, livestreams)
- Boolean combinations ("either gaming or beauty, not both")
- Lookalike requests ("channels similar to MrBeast")
- Edit-mode triggers ("update my Q1 gaming report to also include esports")
