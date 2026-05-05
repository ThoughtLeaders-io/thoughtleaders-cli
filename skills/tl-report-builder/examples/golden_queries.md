# Golden Queries — hand-curated NL inputs

A small, hand-curated test set the skill must handle correctly. Used during prompt iteration and as the seed corpus for shadow-mode comparison against the production system.

**Source**: distilled from `#ai-report-builder` Slack history + common patterns AMs use today.

**Format per query**:
- `ID` — stable identifier
- `Query` — exact NL phrasing
- `Expected report type` — CONTENT (1) | BRANDS (2) | CHANNELS (3) | SPONSORSHIPS (8)
- `Expected topic match(es)` — IDs from `thoughtleaders_topics` (snapshot 96–105) or `none`
- `Expected keywords` (rough) — what the keyword set should look like
- `Notes` — what makes this query interesting; what an early version is likely to get wrong

---

## 1. Straightforward channels query
- **ID**: G01
- **Query**: `"Build me a report of gaming channels with 100K+ subscribers in English"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 98 (PC Games) — strong
- **Expected keywords**: gaming, esports, gameplay, twitch streamer
- **Notes**: Baseline. Should match Topic 98 immediately; subscriber threshold + language are simple FilterSet fields.

## 2. Brand-driven query
- **ID**: G02
- **Query**: `"Show me brands sponsoring AI tutorial channels in the last 6 months"`
- **Expected report type**: BRANDS (2)
- **Expected topic match(es)**: 96 (Artificial Intelligence) — strong
- **Expected keywords**: AI tutorial, machine learning tutorial, ChatGPT tutorial
- **Notes**: BRANDS report driven by a topic + recency. The matcher should catch "AI" as Topic 96. Recency window → date filter (`days_ago: 180`).

## 3. Multi-topic ambiguity
- **ID**: G03
- **Query**: `"AI cooking shows for product placements"`
- **Expected report type**: CHANNELS (3) or CONTENT (1) (depending on AM intent)
- **Expected topic match(es)**: 96 (AI) **and** 99 (Cooking) — both strong
- **Expected keywords**: AI cooking, smart kitchen, generative AI recipes
- **Notes**: Multi-topic disambiguation case. Skill should surface both matches with an option to AND/OR them. Don't silently pick one. "Product placements" is an outreach-intent signal; Phase 3 should pick outreach-flavored columns (`Sponsorship Score`, `Sponsorships Sold`, `Outreach Email`).

## 4. Sponsorship pipeline query
- **ID**: G04
- **Query**: `"Pull me Q1 2026 sold sponsorships for personal investing channels"`
- **Expected report type**: SPONSORSHIPS (8)
- **Expected topic match(es)**: n/a (`topic_matcher` is skipped for type 8)
- **Expected keywords**: n/a (type 8 doesn't use content-keyword matching)
- **Notes**: Type 8 routes through the sponsorship FilterSet — `start_date: "2026-01-01"`, `end_date: "2026-03-31"`, `filters_json.publish_status: [3]` (Sold). The personal-investing context surfaces as a follow-up clarification, not a topic-keyword filter.

## 5. Content with brand exclusion
- **ID**: G05
- **Query**: `"Wellness videos but exclude anything sponsored by Nike or Adidas"`
- **Expected report type**: CONTENT (1)
- **Expected topic match(es)**: 100 (Wellness) — strong
- **Expected keywords**: wellness, fitness, mindfulness, health
- **Notes**: Tests `cross_references` use. Phase 2 invokes `name_resolver` for "Nike" / "Adidas" → brand IDs, then emits `cross_references: [{ type: "exclude_proposed_to_brand", brand_names: ["Nike", "Adidas"] }]`.

## 6. Vague / under-specified
- **ID**: G06
- **Query**: `"Build me a report"`
- **Expected report type**: ask
- **Expected topic match(es)**: n/a
- **Expected keywords**: n/a
- **Notes**: Negative test. Phase 1 must follow up with a clarifying question rather than hallucinate a default report type.

## 7. Sponsorship synonym (deal-stage jargon)
- **ID**: G07
- **Query**: `"Show me partnerships from last quarter for beauty creators"`
- **Expected report type**: SPONSORSHIPS (8)
- **Expected topic match(es)**: n/a (skipped for type 8)
- **Expected keywords**: n/a
- **Notes**: Tests the deal-stage-jargon mapping in `report_glossary.md` — "partnership" must route to type 8 like "sponsorship" / "deal". The "beauty creators" context is a clarifying-question opportunity (channel filter) rather than a topic match. Date scope: `days_ago: 90` if the user says "last quarter" without dates.

## 8. AND vs OR keyword operator
- **ID**: G08
- **Query**: `"Channels covering both cooking AND wellness topics"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 99 (Cooking) + 100 (Wellness) — both strong
- **Expected keywords**: cooking + wellness, healthy recipes
- **Notes**: User explicitly said "both" / "AND" — Phase 2 must emit `keyword_operator: "AND"`. Default is OR; this query checks the override path. Doubles as a multi-topic test like G03.

## 9. Off-taxonomy query (no topic match)
- **ID**: G09
- **Query**: `"Find me crypto / Web3 channels"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: none — `topic_matcher` returns weak/none for all topics ("Personal Investing" overlap is partial at best — `keywords[]` covers stocks/portfolio/budgeting, NOT crypto/Web3)
- **Expected keywords**: crypto, bitcoin, ethereum, web3, defi
- **Notes**: Tests the no-topic-match path. `topic_matcher` returns no strong verdicts → Phase 2 invokes `keyword_research`. Should *not* force a weak topic match into the FilterSet's `topics` field.

## 10. Cross-reference with date scope
- **ID**: G10
- **Query**: `"Tech channels we haven't pitched in the last 12 months"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 101 (Computing) — strong (topic keywords `"tech career"`, `"tech interview prep"` literally contain `"tech"`); 96 (AI) — weak (tech-adjacent, but no AI-specific keyword in the query)
- **Expected keywords**: tech, computing, programming, software
- **Notes**: Tests the `database_query` tool's `multi_step_query` path. The "haven't pitched in 12 months" condition needs an arbitrary date filter that the named `cross_references` catalog can't express directly — `multi_step_query` source query: `report_type: 8`, `filterset: { days_ago: 365 }`, `filters_json: { publish_status: "0,2,6,7,8" }`, `extract: "channel_ids"`, `apply_as: "exclude_channels"`.

---

## Off-taxonomy expansion goldens

These exercise paths the off-taxonomy keyword research takes that G09 alone doesn't cover.

## 11. Anti-overlap with weak topic match
- **ID**: G11
- **Query**: `"channels about IRS tax debt forgiveness programs"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: 97 (Personal Investing) — **weak** (tax-adjacent finance vertical, but `keywords[]` covers stocks/portfolio/budgeting, NOT tax debt resolution); rest none
- **Expected `keyword_research` behavior**: runs (no strong matches); produces tax-debt-resolution candidates AND avoids overlap with Topic 97's stocks/ETFs/portfolio territory
- **Notes**: Tests `keyword_research`'s anti-overlap rule. Validation will show TL data is sparse on this niche (most candidates near-zero) — Phase 4 will likely surface a "narrow result" takeaway. That's a real-data feature, not a bug. **This is the canonical `sample_judge` regression test**: substring noise (`IRS` matching inside "first") can produce inflated counts of obviously-wrong channels (Cocomelon, music labels, etc.); `sample_judge` must catch this and route to a Mode-B follow-up rather than emit silently.

## 12. Obscure niche, all-none
- **ID**: G12
- **Query**: `"channels about competitive speedcubing"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: none (no topic covers Rubik's cube solving or twisty-puzzle hobby)
- **Expected `keyword_research` behavior**: runs; emits hobby-specific terms (`speedcubing`, `cubing`, `Rubik`, `twisty puzzles`) — has to discipline itself to not over-propose adjacencies (e.g. "puzzle games", which would drift into PC Games territory)
- **Notes**: Tests the LLM's ability to stay narrow on a small niche.

## 13. Off-taxonomy with explicit AND
- **ID**: G13
- **Query**: `"channels about both 3D printing and miniature painting"`
- **Expected report type**: CHANNELS (3)
- **Expected topic match(es)**: none (no topic covers either)
- **Expected `keyword_research` behavior**: runs; `recommended_operator: "AND"` because user said "both X and Y"; emits keyword candidates for each side independently
- **Notes**: Combines AND-inference with off-taxonomy. AND intersection in TL data is narrow but non-zero. Distinguishes from G09's OR-default path.

---

## What "defensible" looks like

For each golden, Phase 1 + Phase 2 output is **defensible** if:
1. Report type matches expected (or is "ask" for G06).
2. `topic_matcher` returns the expected verdicts (`strong` for the listed IDs, `weak`/`none` for others).
3. Reasoning string explains *why* — at least one quoted phrase from the query.
4. For type-8 goldens (G04, G07): no topic_matcher invocation, no `keywords` emitted.
5. For off-taxonomy goldens (G09, G11–G13): `keyword_research` is invoked; its candidates have non-zero `db_count` after validation; the resulting FilterSet's `keywords` array is tight (3–6 entries, no obvious adjacencies).

---

## What to add later (when expanding to ~50)

- More multi-topic combinations (Topic × Topic, Topic × keyword)
- Date-range edge cases ("last week", "Q4 2025", "since the new year")
- Demographic filters ("Gen Z creators", "channels with majority female audience")
- Channel-format filters (Shorts, podcasts, livestreams)
- Boolean combinations ("either gaming or beauty, not both")
- Lookalike requests ("channels similar to MrBeast") — exercises `similar_channels`
- Type-8 owner-filter cases ("Q1 deals owned by [sales rep name]") — exercises `owner_sales_name` in `filters_json`
- Edit-mode triggers ("update my Q1 gaming report to also include esports")
- More off-taxonomy goldens — currently 4 (G09, G11–G13); aim for ~10
