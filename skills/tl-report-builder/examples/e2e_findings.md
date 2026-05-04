# End-to-end test findings

First end-to-end run of the redesigned skill against live `tl db pg` data. Three queries from `golden_queries.md` (G01 happy path, G07 routing trap, G11 substring-noise regression). The runs surfaced one real bug in the Phase 2 spec (fixed in the same commit) plus two behavioral observations worth noting for future calibration.

---

## G01 — happy path (type 3, gaming channels)

**`USER_QUERY`**: `"Build me a report of gaming channels with 100K+ subscribers in English"`

### Phase 1 — routing
- Heuristic: "gaming channels" + "subscribers" + no deal-stage jargon
- Output: `report_type: 3` ✓

### Phase 2 — schema + validation

**`topic_matcher`**: fetched 10 live topics from `thoughtleaders_topics`. Topic 98 (PC Games) has `keywords[0] = "gaming"` — verbatim head-term match.
- Verdict: `{ strong_matches: [98], weak_matches: [], no_match: false }` ✓
- Other tools (T2–T5) skipped per their criteria.

**FilterSet composed**:
```json
{
  "filterset": {
    "keywords": ["gaming", "esports", "gameplay"],
    "keyword_operator": "OR",
    "reach_from": 100000,
    "languages": ["en"],
    "channel_formats": [4],
    "sort": "-reach"
  },
  "_routing_metadata": { "matched_topic_ids": [98], "intent_signal": null }
}
```

**Validation**:
- **`db_count`**: 6,092 → classification `normal` (51–10000 bucket) ✓
- **`db_sample`** (top 10 by reach):

| Reach | Channel | Verdict |
|---:|---|---|
| 481,000,000 | MrBeast | borderline (entertainment, but related to MrBeast Gaming) |
| 61,900,000 | Dude Perfect | ⚠️ noise (sports trick shots, not gaming) |
| 56,100,000 | MrBeast Gaming | ✓ |
| 51,300,000 | Techno Gamerz | ✓ |
| 45,600,000 | Total Gaming | ✓ |
| 43,000,000 | XXXTENTACION | ⚠️ noise (rap artist, deceased) |
| 42,000,000 | LankyBox | ✓ |
| 35,000,000 | SSSniperWolf | ✓ |
| 26,000,000 | VanossGaming | ✓ |
| 25,400,000 | MiawAug | ✓ |

**`sample_judge`** (predicted): `uncertain` — 7/10 plausible matches, 2 noise (XXXTENTACION clearly off-target; Dude Perfect debatable).

**Phase 2 decision**: with `uncertain` → `decision: "alternatives"` favoring "Refine" per Step 2.V4. Phase 3 + Phase 4 do not fire; user gets a Mode-B prompt suggesting either accepting the result or refining (e.g., excluding music/entertainment vectors, or using a tighter keyword set from Topic 98's longer list: `"PC gaming"`, `"video games"`, `"gameplay"`, `"gaming PC build"`, etc.).

**Verdict**: Architecture sound. Skill correctly surfaces ambiguity rather than silently shipping the noise.

---

## G07 — partnership routing trap (type 8)

**`USER_QUERY`**: `"Show me partnerships from last quarter for beauty creators"`

### Phase 1 — routing (no DB needed)

Walk:
- "partnerships" — deal-stage jargon per `report_glossary.md` → strong type-8 signal
- "creators" — does NOT override (per the inlined Phase 1 G07 rule)
- "last quarter" → date scope `days_ago: 90`
- "beauty creators" — channel-filter clarification opportunity, NOT a topic match for type 8

**Output**: `report_type: 8` ✓

This is the v1 silent-ship trap (`_SPONSORSHIP_KEYWORDS` did not contain "partnership"). The redesigned skill catches it via the explicit deal-stage jargon mapping in `report_glossary.md`.

### Phase 2 — Tool routing per type 8

- T1 (`topic_matcher`): SKIPPED per type-8 rule ✓
- T2 (`keyword_research`): SKIPPED per type-8 rule ✓
- T3, T4, T5: contextual

Phase 1 surfaces a clarifying question per the inlined example: *"Which beauty creators specifically — by name (then I'll resolve via name_resolver and filter `channels`), or filter by content_categories: ['beauty']?"*

**Verdict**: ✓ Routes correctly. v1 weakness caught.

---

## G11 — substring-noise regression (type 3, IRS)

**`USER_QUERY`**: `"channels about IRS tax debt forgiveness programs"`

### Phase 1 — routing
- "channels" + no deal-stage jargon → `report_type: 3` ✓

### Phase 2 — schema + validation

**`topic_matcher`**: Topic 97 (Personal Investing) — keywords cover stocks/portfolio/budgeting, not tax-debt resolution. Verdict: `weak`. All other topics: `none`. Summary: `no_match: true` (zero strong, only weak).

**`keyword_research`**: invoked because no strong topic match. Output (predicted):
```json
{
  "keywords": ["IRS", "tax debt", "tax debt forgiveness", "tax debt relief", "tax resolution"],
  "validation_concerns": ["'IRS' is a 3-character keyword — risks substring noise (matches 'first', 'irish', etc.)"]
}
```

**FilterSet composed** with `validation_concerns` propagated.

**Validation**:
- **`db_count`** (description-only after channel_name ILIKE timeout): **16,910** → classification `broad` (10001–50000 bucket).
- **`db_sample`** (top 10 by reach):

| Reach | Channel |
|---:|---|
| 201,000,000 | Cocomelon - Nursery Rhymes |
| 44,600,000 | BRIGHT SIDE |
| 43,600,000 | Bruno Mars |
| 38,600,000 | RABBITWARREN - Baby Nin Nin vs ONIBALL |
| 38,100,000 | That Little Puff |
| 35,400,000 | Taarak Mehta Ka Ooltah Chashmah |
| 33,900,000 | The Tonight Show Starring Jimmy Fallon |
| 30,100,000 | Raffy Tulfo in Action |
| 29,900,000 | Chris Brown |
| 27,200,000 | Disney Jr. |

**Zero of these are about IRS tax debt.** Music artists, children's content, general entertainment, sitcoms. Substring noise from `IRS` matching inside `first`, `irish`, etc. — exactly as the inlined SKILL.md G11 example predicts.

**`sample_judge` verdict**: `looks_wrong`. Reasoning: "All 10 samples are music artists, children's content, or general entertainment — none are about IRS tax debt or financial services. Confirms the substring-noise warning from `keyword_research`."

**Phase 2 decision**: `decision: "alternatives"` with Mode-B prompt:
- Save anyway (inspect the long tail manually)
- Refine (drop `IRS` as standalone keyword; keep longer phrases `tax debt`, `tax debt forgiveness`, `tax debt relief` — less noise)
- Cancel (TL data may not have meaningful coverage for this niche)

Phase 3 + Phase 4 do NOT fire. ✓

**Verdict**: Architectural promise upheld. The validation gate catches the substring-noise silent ship and surfaces it to the user instead of emitting a 16,910-channel report full of Cocomelon and Bruno Mars.

---

## Bugs and findings

### 🔴 Bug 1 — Phase 2 Step 2.V1 SQL template times out without CTE

**Surfaced by**: G01.

**Issue**: The original spec's flat predicate (`WHERE description ILIKE '%...%' OR ... AND reach >= ... AND ...`) timed out on the full channels table. Postgres scans `description` before the indexed `reach`/`language`/`format` columns can prune. The keyword ILIKE alone — even single-keyword, no AND — times out without a pre-filter.

**Fix**: Updated SKILL.md Step 2.V1 to mandate the CTE pattern: `WITH filtered AS (...) SELECT ... FROM filtered WHERE <keyword predicate>`. Same commit as this findings file.

**Severity**: HIGH — without the fix, every keyword-bearing intelligence-report validation times out.

### 🟡 Finding 2 — channel_name ILIKE half is best-effort even with CTE

**Surfaced by**: G11 (no reach filter, so the CTE's `filtered` set is ~700k rows).

**Issue**: When the FilterSet has no reach floor, the CTE-filtered set is still very large. The `channel_name ILIKE` half of the keyword predicate times out even after the CTE. The Step 2.V2 retry rule already says to drop `channel_name ILIKE` on timeout — that path was triggered for G11 and produced the description-only count of 16,910.

**Mitigation**: Mentioned inline in Step 2.V1 — when the FilterSet has no indexed-column floor, drop `channel_name ILIKE` proactively rather than waiting for the timeout retry.

**Severity**: MEDIUM — already handled by the retry rule; this is a fast-path improvement.

### 🟢 Finding 3 — topic_matcher head-keyword expansion pulls noise

**Surfaced by**: G01 (XXXTENTACION, Dude Perfect false positives).

**Issue**: Expanding Topic 98 to just `["gaming", "esports", "gameplay"]` (head terms) catches non-gaming channels whose descriptions happen to mention the words. Topic 98's curated `keywords[]` has 18 entries including more specific terms (`"PC gaming"`, `"video games"`, `"gaming PC build"`, `"gaming commentary"`, etc.) — using a tier-based subset (head + sub_segment) would tighten the result.

**Fix**: Not yet — calibration finding. Two options:
1. Update `topic_matcher` to surface more of `keywords[]` for downstream expansion.
2. Update Phase 2's keyword expansion to favor sub_segment / long_tail terms over head terms when both are present.

**Severity**: LOW — current behavior produces a usable report once the user refines; it's a precision-vs-recall trade-off, not a correctness bug.

### 🟢 Finding 4 — sample_judge `uncertain` path is a real outcome

**Surfaced by**: G01.

**Issue**: 7-of-10 plausible + 2-3 noise is a common shape — not clean enough to confidently `matches_intent`, not bad enough to be `looks_wrong`. The skill's Step 2.V4 says `uncertain → alternatives favoring "Refine"`, which is correct. Worth noting that `uncertain` is the modal outcome for hi-cardinality keyword queries.

**Severity**: NONE — informational. The architecture handles it correctly; just expect this path to fire often.

### 🔴 Finding 5 — Validation engine routing: ES for intelligence, PG for sponsorships

**Surfaced by**: G02 + G03 (both repeatedly timed out on PG keyword scans).

**Issue**: The original SKILL.md spec used `tl db pg` as the universal validation engine. That's wrong for intelligence reports (types 1/2/3). PG has no trigram or full-text index on `description` / `channel_name`, so multi-keyword OR predicates time out even with the CTE workaround at moderate reach floors. The G01 / G02 / G03 e2e runs spent more time fighting timeouts than running validations.

The production data plane is split:
- **Intelligence (1/2/3)** → Elasticsearch (`tl db es`). Phrase-matching, scoring, no substring noise.
- **Sponsorship (8)** → Postgres (`tl db pg`). Relations + status + dates; no text search.

The PG smoke-check is fine as a narrow fallback (when ES is unavailable AND the FilterSet pre-filters tightly) but is not the production validation path.

**Fix applied**: SKILL.md Step 2.V1 + V2 + Data Sources table updated to:
- Route intelligence-report validation through `tl db es` with a `bool.filter` + `multi_match phrase` body shape.
- Keep `tl db pg` for type 8 and as the smoke-check fallback for intelligence.
- Note that ES phrase matching architecturally avoids the G11/G03 substring-noise class — `multi_match type: "phrase"` respects word boundaries.

**Implications for prior e2e tests** (G01 / G02 / G03):
- The PG timeouts those runs surfaced are **expected** for the wrong-tool-for-the-job case; they don't invalidate the architectural findings (substring noise, multi-topic intersection limits, data sparsity).
- Re-running G01–G03 against `tl db es` would produce different and likely cleaner results — the substring noise from `AI` matching `Tamil` etc. would not occur with ES phrase matching.
- The CTE workaround (Bug 1) is still correct and still applicable when PG IS used (type 8 or explicit smoke-check fallback).

**Severity**: HIGH — the validation engine choice was architecturally wrong for the most common report types (1/2/3). Fix landed in the same commit as this finding.

---

## Net e2e verdict

✅ **Architecture sound at the orchestration level.** All test queries route correctly through Phases 1–2. The validation gate catches silent-ship risks (G11, G03) and surfaces ambiguity (G01, G02) instead of emitting bad configs. The deal-stage jargon mapping catches the v1 weakness (G07).

✅ **Bug 1 fixed** — CTE pattern documented for the PG smoke-check path.

✅ **Bug 5 fixed** — validation engine now routes ES (intelligence) vs PG (sponsorships) per report type.

⏳ **Findings 3 + 4** are calibration items, not bugs — flagged for future tuning when shadow-mode begins.

⏳ **Phases 3 + 4** were not exercised in this run because Phase 2 terminated each query (G01 → uncertain, G02 → uncertain, G03 → looks_wrong, G07 → type 8 with clarifying question, G11 → looks_wrong). A clean happy-path run end-to-end through Phase 4 needs a query that produces a clean `matches_intent` verdict.

⏳ **Re-run of intelligence-report e2e tests against ES is recommended** once Step 2.V1's ES query body shape is rehearsed against the live `tl db es` endpoint — the PG-based runs above are valuable for surfacing substring/sparsity / multi-topic-intersection findings, but they don't represent the production validation path.
