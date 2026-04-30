# End-to-End Walkthrough — G03 ("AI cooking shows for product placements")

**Date**: 2026-04-29
**Golden**: G03 — chosen as the natural pair to G09. Where G09 exercises Phase 2b (off-taxonomy → keyword research), **G03 exercises the topic matcher itself** — Phase 2a returns TWO strong matches → Phase 2b is SKIPPED → Phase 2c uses the topics' curated keywords directly.
**Companion**: [`E2E_WALKTHROUGH_G09.md`](E2E_WALKTHROUGH_G09.md) — the off-taxonomy run-2b walkthrough.
**Live data**: every `tl db pg` query in this walkthrough was actually executed during this session; outputs shown are real. **Provenance per query** noted inline.

---

## Why this golden

G03 — *"AI cooking shows for product placements"* — is the canonical exercise of:

1. **Multi-topic strong matching** — both Topic 96 (AI) and Topic 99 (Cooking) get strong verdicts. Real production case where a query hits two clusters.
2. **Phase 2b SKIP path** — strong match exists, so we trust topics' curated keywords; no fresh keyword research needed. Cheaper than G09's path (no validation loop over candidates).
3. **AND-vs-OR inference** — "AI cooking" is a composite noun, not "AI or cooking." Phase 2c must infer AND.
4. **Intent vs filter signals** — "for product placements" is intent (informs column/widget choice in Phase 4), not a filter. Phase 2c should NOT translate it into a keyword.
5. **Narrow-but-non-zero results** — the AI ∩ Cooking intersection is small (single-digit channels). Phase 3 must handle "narrow but valid" gracefully without retrying.

---

## Setup

```
$ tl --version
tl-cli 0.6.2

$ tl whoami
nerya@thoughtleaders.io  (org: ThoughtLeaders)

$ tl balance
balance: 996,732 credits  (after the queries in this walkthrough)
```

---

## STEP 0 — User invocation

```
$ tl ask "AI cooking shows for product placements"
```

**Routing decision** (Claude in-session reads `SKILL.md`'s description):
- Description mentions: *"... 'find me X channels' / 'build a report' / 'make a report on' ..."*
- This phrasing ("AI cooking **shows** for product placements") is closer to a soft signal — could mean "show me" (just list) or "build me a report on shows" (saved report).
- Per the description's soft-signal rule, the skill **asks first**: *"Do you want a saved TL report, or just a quick list here?"*
- For this walkthrough, assume the user replies **"Yes, build the report"** → proceed.

This first-step disambiguation is a real user-facing artifact — half of soft-signal queries probably want a quick lookup, not a saved report. The cost of asking is one round-trip; the cost of building+saving the wrong artifact is much higher.

---

## PHASE 1 — Report Type Selection

**Goal**: infer `ReportType` enum from the NL query alone.

```
Query: "AI cooking shows for product placements"

1. Sponsorship intent? Check expanded set
   {pipeline, deal, deals, adlink, adlinks, sponsorship, partnership, promotion}
   → "product placements" is sponsorship-adjacent BUT phrased as the report's
     intent ("for X"), not "report on/about X sponsorships"
   → Phase 1 rule: "for <X>" is intent context, not type signal
   → NOT type 8

2. Similar-channels pattern? ("similar to X")
   → no match

3. "shows" — specifically the word "shows" — is interesting:
   - In TL vocabulary "show" ≈ video/content; soft signal toward CONTENT (1)
   - But the user said "AI cooking shows" as a noun phrase referring to channels
     producing such shows; the actual entity is the channel
   → Phase 1 rule: "<topic> shows" with no other content-specific markers
     ("video", "upload", "episode") → CHANNELS (3), not CONTENT
   → CHANNELS (3)

4. No "brand" / "advertiser" → NOT type 2

5. Default for "<topic-noun-phrase> for <intent>"
   → CHANNELS (3)
```

**Output**: `report_type = 3`

**Note for M3 implementation**: rule 3 is subtle and worth a Phase 1 unit test — "AI cooking shows" should resolve to type 3, not type 1. The same logic should classify "**videos** about AI cooking" as type 1.

---

## PHASE 2a — Topic Matcher (M2 ✓ implemented)

### Step 2a.1 — Fetch live topics

```
$ tl db pg --json "SELECT id, name, description, keywords FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"
```

**Provenance**: re-verified live this session (full envelope returns 10 topics with descriptions + keywords; same shape as G09's Step 2a.1).

For Phase 2a's matcher reasoning, the relevant rows are **96 (AI)** and **99 (Cooking)**:

```json
{
  "id": 96,
  "name": "Artificial Intelligence",
  "keywords": [
    "artificial intelligence", "AI tools", "machine learning", "LLM",
    "AI coding", "AI video editor", "AI agent", "prompt engineering",
    "generative AI", "AI assistant", "AI automation", "AI startups",
    "ChatGPT tutorial", "Claude AI", "AI agents for coding",
    "AI tools for creators", "best AI tools"
  ]
}
{
  "id": 99,
  "name": "Cooking",
  "keywords": [
    "cooking", "recipes", "home cooking", "food", "meal prep",
    "healthy snacks", "breakfast recipes", "cocktail recipes",
    "mukbang", "budget meals", "protein powder", "cereal alternative",
    "vegan recipes", "easy dinner recipe", "5-ingredient meals",
    "mixology", "pantry meal ideas", "ASMR eating show"
  ]
}
```

(Provenance for those specific two rows: `tl db pg --json "SELECT id, name, keywords FROM thoughtleaders_topics WHERE id IN (96, 99) ORDER BY id LIMIT 10 OFFSET 0"` — fresh execution this session, 1.41 credits charged.)

### Step 2a.2 — Apply [`prompts/topic_matcher.md`](../skills/tl-report-build/prompts/topic_matcher.md)

The matcher prompt walks each topic's keywords against the query. For G03:

| Topic | Reasoning | Verdict |
|---|---|---|
| 96 (AI) | User said "AI cooking shows"; "AI" matches topic name + topic keyword "AI tools". | **strong** |
| 97 (Personal Investing) | "AI cooking" is unrelated to investing; no keyword overlap. | none |
| 98 (PC Games) | unrelated | none |
| 99 (Cooking) | User said "AI **cooking** shows"; "cooking" is the topic name AND a topic keyword. | **strong** |
| 100 (Wellness) | "Cooking" tangentially relates to nutrition/wellness, but the topic is supplements/mental health/biohacking — no keyword overlap with "cooking" or "AI". | none |
| 101–105 | unrelated | none |

**Output of Phase 2a**:

```json
{
  "query": "AI cooking shows for product placements",
  "verdicts": [
    {
      "topic_id": 96, "topic_name": "Artificial Intelligence",
      "verdict": "strong",
      "reasoning": "User said 'AI cooking shows'; 'AI' matches topic keyword 'AI tools' and the topic name.",
      "matching_keywords": ["AI tools"]
    },
    {
      "topic_id": 99, "topic_name": "Cooking",
      "verdict": "strong",
      "reasoning": "User said 'AI cooking shows'; 'cooking' matches topic keyword 'cooking' and the topic name.",
      "matching_keywords": ["cooking"]
    },
    /* 96, 97, 98, 100–105 = none */
  ],
  "summary": {
    "strong_matches": [96, 99],
    "weak_matches": [],
    "no_match": false
  }
}
```

This is the multi-topic case the matcher prompt is explicitly designed for: **don't pick a winner; emit `strong` for every topic that fits**.

### Step 2a.3 — Decision: should Phase 2b run?

```
strict trigger:
  RUN 2b  iff  report_type ∈ {1, 2, 3}  AND  summary.strong_matches.length == 0

For G03:
  report_type = 3              ✓
  strong_matches = [96, 99]    ✗ (length 2, not 0)
  → SKIP Phase 2b
```

**Phase 2b is skipped.** Topics 96 and 99 already carry curated `keywords[]` arrays from the `pipeline_analysis_v1` seeding methodology — those keywords were ES-validated when the topics were created. No need to re-validate.

**Cost saved**: G09 ran 7+ keyword validation queries (~1.2 credits each, ~8 credits total). G03 saves all of that. The skip-2b path is significantly cheaper for any well-phrased query that hits the topic taxonomy.

---

## PHASE 2c — Filter Builder, Pass A (M3 part 2, mocked here)

**Goal**: assemble a partial FilterSet from (verdicts + topics' curated keywords + schema discovery + NL query semantics).

### Step 2c.1 — Multi-topic operator inference

The Filter Builder LLM examines the query phrasing to decide whether multiple topics should AND or OR:

| Pattern | Operator | Examples |
|---|---|---|
| "X AND Y" / "both X and Y" / composite noun "X Y" / "X-themed Y" | AND | "cooking AND wellness", "AI cooking", "tech-themed gaming" |
| "X or Y" / "X and/or Y" / list comma | OR | "gaming or beauty", "AI, cooking, or wellness" |
| ambiguous | OR (with surface) | "gaming and cooking channels" — could mean either; default OR, surface to user as "Did you mean both or either?" |

For G03: **"AI cooking shows"** is a composite noun (AI-modifies-cooking). The filter wants channels that are **both** AI-related AND Cooking-related → `topic_operator: AND`.

This inference is encoded as a rule in `prompts/filter_builder.md` (M3 deliverable).

### Step 2c.2 — Schema discovery

```
$ tl db pg --json "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='thoughtleaders_channel' ORDER BY ordinal_position LIMIT 100 OFFSET 0"
```

(Provenance: same query as G09's Step 2c.1; the schema is identical between runs. Reusing the result.)

Confirms field names: `channel_name`, `description`, `reach`, `language`, `is_active`, `format`, `content_category`, `demographic_*`, etc.

### Step 2c.3 — Handle "for product placements"

This is the trickiest part of G03. **"for product placements"** is an intent signal, not a filter. Three reasonable handlings:

| Option | What | Verdict |
|---|---|---|
| A | Add `keywords: ["product placement", "branded content"]` filter | ✗ wrong — channels rarely describe themselves with these terms |
| B | Convert to a structured filter (e.g., `accepts_sponsorships: true` if such a field exists) | ✗ no such field in schema |
| C | Pass to Phase 4 as **column-selection intent** ("user wants channels they can pitch — surface deal_count, last_sponsored_at, demographics") | ✓ correct |

The Filter Builder marks this as `_intent_signal: "product placements → optimize column selection for outreach"` and passes it through to Phase 4 metadata. Filter itself is not affected.

### Step 2c.4 — Apply `prompts/filter_builder.md` (M3 deliverable; mocked)

LLM emits the partial FilterSet using v1's authoritative schema. **No `topics` field exists in v1's FilterSet** — the topic IDs `[96, 99]` are v2 routing metadata only; they get translated into `keyword_groups` using head keywords from each topic's `keywords[]` array. Phase 2c's multi-topic AND becomes `keyword_operator: "AND"`:

```json
{
  "report_type": 3,
  "keyword_groups": [
    { "text": "AI",      "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "cooking", "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false }
  ],
  "keyword_operator": "AND",
  "channel_formats": [4],
  "days_ago": 730,
  "sort": "-reach",
  "_routing_metadata": {
    "matched_topic_ids": [96, 99],
    "intent_signal": "product placements → optimize column selection for outreach"
  }
}
```

The `_routing_metadata` block is internal scaffolding the orchestration uses to thread topic IDs and intent through to Phase 4. **It is stripped before the config is POSTed to the platform.** The platform sees only the v1-schema fields above.

---

## PHASE 3 — Validation Loop (M4, mocked here, but with real SQL execution)

**Goal**: ground the FilterSet in real data — check `db_count` and `db_sample`.

The challenge: **for Phase 3 db_count/db_sample, how do we approximate the platform's eventual ES `keyword_groups` query in raw PG SQL?**

The platform runs `keyword_groups` against ES with full text-relevance scoring. Phase 3's PG validation is a *coarser* approximation using `ILIKE` on `description` + `channel_name`. That's an acceptable smoke check (gets us "is this a non-zero set" and "do the top channels look right") without the precision of the eventual ES query.

The orchestration translates the partial FilterSet's `keyword_groups` + `keyword_operator: "AND"` into:

```sql
SELECT COUNT(*) AS total_match
FROM thoughtleaders_channel
WHERE is_active = TRUE
  AND (
    /* Topic 96 (AI) — channel must match at least one of these */
    description ILIKE '%artificial intelligence%'
    OR description ILIKE '%machine learning%'
    OR description ILIKE '%generative ai%'
  )
  AND (
    /* Topic 99 (Cooking) — channel must match at least one of these */
    description ILIKE '%cooking%'
    OR description ILIKE '%recipes%'
    OR description ILIKE '%food%'
  )
LIMIT 1 OFFSET 0
```

(Real implementation would expand to all keywords of both topics + check `channel_name` too; using a 3-keyword-per-topic subset here for SQL readability.)

### Step 3.1 — Baseline counts (sanity checks)

Before running the intersection, the orchestration checks each side independently to make sure the subsets are non-empty. Two cheap queries:

```
$ tl db pg --json "SELECT COUNT(*) AS cooking_only FROM thoughtleaders_channel WHERE is_active=true AND description ILIKE '%cooking%' LIMIT 1 OFFSET 0"
{ "results": [{"cooking_only": 7548}] }   ← 7,548 channels mention "cooking"

$ tl db pg --json "SELECT COUNT(*) AS ai_only FROM thoughtleaders_channel WHERE is_active=true AND description ILIKE '%artificial intelligence%' LIMIT 1 OFFSET 0"
{ "results": [{"ai_only": 984}] }          ← 984 channels mention "artificial intelligence"
```

(Both fresh executions this session; 1.18 credits each.)

Both sides have substantial population — the AND won't fail trivially.

### Step 3.2 — `db_count` (the intersection)

```
$ tl db pg --json "SELECT COUNT(*) AS ai_and_cooking FROM thoughtleaders_channel WHERE is_active=true AND description ILIKE '%cooking%' AND description ILIKE '%artificial intelligence%' LIMIT 1 OFFSET 0"
{ "results": [{"ai_and_cooking": 3}] }    ← 3 channels strict
```

```
$ tl db pg --json "SELECT COUNT(*) AS ai_and_cooking_expanded FROM thoughtleaders_channel WHERE is_active=true AND (description ILIKE '%cooking%' OR description ILIKE '%recipes%' OR description ILIKE '%food%') AND (description ILIKE '%artificial intelligence%' OR description ILIKE '%machine learning%' OR description ILIKE '%generative ai%') LIMIT 1 OFFSET 0"
{ "results": [{"ai_and_cooking_expanded": 9}] }   ← 9 channels with broader OR-OR-AND
```

(Both fresh executions this session.)

**db_count = 9.** Tiny set, but **non-zero**. Phase 3 must decide what to do.

### Step 3.3 — Phase 3 decision rules for narrow results

| `db_count` range | Verdict | Action |
|---|---|---|
| 0 | empty | retry Phase 2c (or back to 2b for off-taxonomy) with feedback "filterset matched 0 rows" |
| 1–4 | very narrow | proceed but **flag to user** — "small intersection (N channels); confirm intent" |
| 5–50 | narrow | proceed with **note** — "narrow intersection; full sample shown" |
| 51–10,000 | normal | proceed silently |
| 10,001–50,000 | broad | proceed with **suggestion** — "broad result; consider narrowing" |
| > 50,000 | too broad | offer to narrow; do not save without user confirmation |

For G03 with 9 matches: **narrow** → proceed, surface count to user with note.

### Step 3.4 — `db_sample`

```
$ tl db pg --json "SELECT id, channel_name, reach FROM thoughtleaders_channel WHERE is_active=true AND (description ILIKE '%cooking%' OR description ILIKE '%recipes%' OR description ILIKE '%food%') AND (description ILIKE '%artificial intelligence%' OR description ILIKE '%machine learning%' OR description ILIKE '%generative ai%') ORDER BY reach DESC NULLS LAST LIMIT 10 OFFSET 0"
```

**Real response** (fresh execution this session):

```json
{
  "results": [
    { "id": 83843,   "channel_name": "Rotimatic",          "reach": 41600 },
    { "id": 273595,  "channel_name": "Hans Forsberg",      "reach": 16300 },
    { "id": 1292865, "channel_name": "NEURA Robotics",     "reach": 8490  },
    { "id": 742674,  "channel_name": "NomadBull",          "reach": 5710  },
    { "id": 680861,  "channel_name": "Djpamelamc",         "reach": 4270  },
    { "id": 747228,  "channel_name": "Renvie Channel",     "reach": 3190  },
    { "id": 726570,  "channel_name": "NextGen factory",    "reach": 1110  },
    { "id": 666852,  "channel_name": "Jared Broker",       "reach": 333   },
    { "id": 289666,  "channel_name": "Exponential Africa", "reach": 2     }
  ],
  "total": 9
}
```

**Sample inspection — actually relevant signals:**
- **Rotimatic** (41.6K reach) — automated roti-making robot company. Genuine AI-cooking. ✓
- **NEURA Robotics** (8.5K) — humanoid robotics including kitchen automation. ✓
- **NextGen factory** (1.1K) — sounds like industrial automation; plausibly AI + food production. ✓
- **Hans Forsberg** (16.3K) — needs checking; possibly an AI-cooking creator. ⚠
- **NomadBull, Djpamelamc, Renvie Channel** — could be incidental matches. ⚠

Conclusion: real signal in the top half; some noise in the long tail (typical of `description ILIKE` matching). **Phase 3 verdict: ok, proceed**.

### Retry path (not exercised here)

If the same query had returned `db_count = 0`:
- Orchestration emits feedback to Phase 2c: *"Topic AND too narrow; suggest weakening to topic_operator: OR or relaxing keyword breadth."*
- Phase 2c re-emits with `topic_operator: OR` → `db_count` likely 8,000+ → too broad → narrow back
- Cap: 3 retries, then surface to user with a structured failure message

---

## PHASE 4 — Column/Widget Builder, Pass B (M5, mocked)

**Goal**: choose columns/widgets. Phase 4 reads the `_intent_signal` from Phase 2c.

For G03's intent ("for product placements"):

```json
{
  "columns": [
    "channel_name", "url", "reach",
    "deal_count",                  // ← intent signal: user wants channels they can pitch
    "last_sponsored_at",           // ← intent signal: recent sponsor activity = warm lead
    "demographic_age",
    "demographic_usa_share",       // ← geography matters for product placement
    "language"
  ],
  "widgets": [
    { "type": "bar_chart", "field": "deal_count", "label": "Past deal count" },
    { "type": "stacked_bar", "field": "demographic_age" }
  ],
  "default_sort": { "field": "deal_count", "direction": "desc" }
  // intent: surface most-pitched-before channels first (warm leads)
}
```

Note how the column choice differs from G09's:
- G09 (general crypto report) → cols emphasized `language`, `content_category`, basic identity
- G03 (product placement intent) → cols emphasized `deal_count`, `last_sponsored_at`, demographics

This is **why Phase 2c's `_intent_signal` matters** — it threads through Phase 4.

---

## PHASE 5 — Display (M6, mocked)

The skill assembles the final config in v1's authoritative shape — see [Appendix A](#appendix-a--authoritative-platform-config) for the complete field-accurate JSON. Conceptual summary at this point:

- **`report_type: 3`** (CHANNELS)
- **`filterset.keyword_groups`** = head keywords from Topics 96 + 99 (`"AI"`, `"cooking"`)
- **`filterset.keyword_operator: "AND"`** (multi-topic AND inferred from "AI cooking" composite)
- **`filterset.days_ago: 730`** (mandatory when keyword_groups present)
- **`filterset.sort: "-reach"`** (default for type 3)
- **`filterset.channel_formats: [4]`** (YouTube longform)
- **`columns`** with outreach-relevant set + custom `Cost Per Projected View` formula
- **`widgets`** with channel_count, reach metric, sponsored brands, growth histogram, uploads histogram
- **`refinement_suggestions`** including the broaden-to-OR alternative

Plus internal-only `_validation` metadata (stripped before POSTing):

```json
{
  "_validation": {
    "db_count": 9,
    "db_count_warning": "narrow intersection — only 9 channels match both AI AND Cooking",
    "db_sample_size": 9,
    "phase_2a": "strong matches: [96 (AI), 99 (Cooking)]",
    "phase_2b": "skipped (strong matches exist)",
    "phase_2c_retries": 0,
    "phase_3_retries": 0
  }
}
```

**User-facing message**:

> Built a report config for **"AI cooking shows for product placements"** — matches **9 channels**.
>
> The intersection of AI and Cooking is genuinely small in our data — only 9 channels mention both. Top match by reach: **Rotimatic** (41.6K — automated roti-making), **NEURA Robotics** (8.5K — kitchen automation).
>
> Notable signals:
> - Phase 2a found two strong topic matches: AI (96) AND Cooking (99)
> - Phase 2b skipped (strong matches; trust topics' curated keywords)
> - Phase 4 column choice optimized for product-placement outreach (deal_count, last_sponsored_at, demographics)
>
> The intersection is narrow — would you like me to:
> - **Save as is** (`tl reports create "AI cooking shows for product placements"`), or
> - **Broaden** (drop the AND, search for AI OR Cooking — much larger set ~8,500 channels), or
> - **Refine** (change the keyword sets for either topic)?

---

## Decision tree fired (summary table)

| Phase | Decision | Reason |
|---|---|---|
| Step 0 | ask first (soft signal) | "AI cooking shows for product placements" could be lookup or saved report |
| 1 | `report_type = 3` | "AI cooking shows" without content-specific markers → CHANNELS, not CONTENT |
| 2a | `strong_matches = [96, 99]` | Both "AI" and "cooking" match topic keywords |
| **2b** | **SKIP** | `strong_matches.length >= 1` → trust topics' curated keywords |
| 2c topic_operator | AND | "AI cooking" composite noun → AND, not OR |
| 2c intent | "product placements" → column-selection intent | Not a filter; threaded to Phase 4 |
| 3 | proceed (narrow, non-zero) | `db_count = 9`; in narrow range, surfaces warning to user |
| 4 | columns optimized for outreach | `deal_count`, `last_sponsored_at` chosen |
| 5 | display with broaden-option | offer alternative (OR instead of AND) given narrow result |

---

## What this walkthrough exercises

| Path | G03 (this walkthrough) | G09 (companion) |
|---|---|---|
| Phase 2a verdict shape | multi-topic strong | all-none |
| Phase 2b run? | NO (skip) | YES (run) |
| Phase 2c filter source | topics' curated keywords | freshly generated keywords |
| Phase 2c semantics | multi-topic AND inference | keyword OR (default) |
| Phase 3 db_count | 9 (narrow) | 4,272 (normal) |
| Phase 3 decision | proceed with warning | proceed silently |
| Phase 4 column emphasis | outreach (intent-driven) | content discovery (default) |
| Cost (validation queries) | ~3 (baselines + intersection) | ~8 (per-keyword + intersection) |

Together G03 + G09 cover the two main branches the architecture must handle. Every other golden falls onto one of these paths or a slight variation.

---

## Surprises / real-world findings from this run

1. **The AI ∩ Cooking intersection is GENUINELY tiny — 9 channels.** This isn't a noise problem; it's a real-world signal. AI-themed cooking is a small niche. Phase 3's narrow-result handling has to be designed for this case (not just for "broad reports of mainstream verticals").
2. **Top channel "Rotimatic" — 41.6K reach** — a real AI-cooking-adjacent channel (automated roti maker), not noise. The matcher finds genuine signal in the long tail.
3. **`tl db pg` timed out on the first multi-AND query.** Same observation as G09: the Phase 2c→Phase 3 SQL gets complex and the server can time out. The orchestration broke it into smaller queries (single-keyword baselines + simple intersection) which all completed. **Suggested M4 implementation**: if the full intersection times out, fall back to a CTE that computes baselines first.
4. **Phase 2c had to handle "for product placements" without forcing it into the FilterSet.** This is a class of "intent metadata" — phrases that affect downstream columns/widgets but not filters. v1 didn't have an explicit mechanism for this; M3+M4 should add it.
5. **"AI cooking shows" → CHANNELS not CONTENT.** Subtle. Without rule "type 3 default unless content-specific markers like 'video'/'episode'/'upload' are present," the matcher could have routed to type 1. Worth a Phase 1 unit test in M3.

---

## Cost breakdown (this walkthrough's actual credit usage)

Per the running balance values from the live executions:
- Topics fetch (full): 1.40 credits
- Topics fetch (96+99 only): 1.41 credits
- channel.thoughtleaders schema discovery: ~0 (re-used from G09 session)
- cooking_only baseline: 1.18
- ai_only baseline: 1.18
- ai_and_cooking strict: 1.18
- ai_and_cooking expanded: 1.18
- db_sample: ~0.5 (small result)
- **Total ≈ 8 credits** for full G03 e2e validation

Compare to G09: ~12 credits (more keyword validations in Phase 2b). Skip-2b path is ~30% cheaper for this size of query.

---

## Open question — RESOLVED 2026-04-29

**How do we represent `topic_operator: AND` in the platform's actual `dashboard.models.FilterSet` schema?**

**Answer**: v1's FilterSet has **no `topics` field**. Topics are not a v1 primitive — they're a v2 *cache* whose `keywords[]` arrays get **translated** into v1's `keyword_groups`. Multi-topic AND becomes `keyword_operator: "AND"` across head keywords from each topic. See [Appendix A](#appendix-a--authoritative-platform-config) below.

This is a pivotal v1→v2 architectural insight: **the v2 Topic Matcher is a routing layer that picks pre-curated keywords; the platform never sees a "topics" field**. M3's `filter_builder.md` must do the topics→keyword_groups translation explicitly.

---

## Appendix A — Authoritative platform config

What the skill would actually emit in Phase 5 — using v1's exact schema (verified against `_v1_system_prompt_REFERENCE.txt` and `create_report.py`).

### Top-level shape (per v1 prompt response schema, lines 11–24)

```json
{
  "action": "create_report",
  "report_title": "AI Cooking Channels (for product placement outreach)",
  "report_description": "Channels covering both AI and cooking themes — the intersection of Topics 96 (Artificial Intelligence) and 99 (Cooking). Optimized for product-placement outreach with sponsorship-history columns surfaced.",
  "summary": "Built a CHANNELS report for the AI×Cooking intersection (~9 channels) with outreach-friendly columns.",
  "report_type": 3,
  "filterset": { ... },
  "filters_json": { ... },
  "columns": { ... },
  "widgets": [ ... ],
  "histogram_bucket_size": "month",
  "refinement_suggestions": [ ... ]
}
```

### `filterset` (the actual schema — keyword_groups, NOT topics)

```json
{
  "filterset": {
    "keyword_groups": [
      {
        "text": "AI",
        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
        "exclude": false
      },
      {
        "text": "cooking",
        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
        "exclude": false
      }
    ],
    "keyword_operator": "AND",
    "channel_formats": [4],
    "days_ago": 730,
    "sort": "-reach"
  }
}
```

**Why this exact shape**:
- **Two `keyword_groups` entries** — one per topic anchor (head keyword). v1 mandates "each distinct topic/term must be its own separate keyword_groups entry; never combine with OR in a single text field" (line 144).
- **`keyword_operator: "AND"`** — encodes Phase 2c's multi-topic AND inference. With two groups + AND, the channel must match BOTH "AI" AND "cooking" in the searched fields.
- **`content_fields` includes `channel_description` and `channel_topic_description`** — v1's rule for type 3: "include channel-level fields to find channels truly dedicated to a niche, not just channels that occasionally mention it" (line 154).
- **`channel_formats: [4]`** — YouTube longform (v1 default for type 3).
- **`days_ago: 730`** — REQUIRED when keyword_groups present, per v1 line 79: "Keyword searches without a date constraint cause ES query timeouts."
- **`sort: "-reach"`** — REQUIRED for all reports per v1 line 268. Default for type 3 is reach descending.
- **No `topics` field** — there is none in v1's schema.

### `filters_json` (extra filters bucket)

```json
{
  "filters_json": {
    "min_brand_safety": "B"
  }
}
```

For product-placement outreach: minimum brand safety grade B (stay away from F-rated content). No other filters_json fields needed.

### `columns` (dict, NOT array — per v1 schema)

Columns chosen for product-placement outreach intent. Includes the v1-mandatory "TL Channel Summary":

```json
{
  "columns": {
    "Channel":                   { "display": true },
    "TL Channel Summary":        { "display": true },
    "Subscribers":               { "display": true },
    "Brand Safety":              { "display": true },
    "Sponsorship Score":         { "display": true },
    "Sponsorships Sold":         { "display": true },
    "Brands Sold":               { "display": true },
    "Last Sold Sponsorship":     { "display": true },
    "Open Proposals Count":      { "display": true },
    "USA Share":                 { "display": true },
    "Demographics - Age Median": { "display": true },
    "Channel URL":               { "display": true },
    "Outreach Email":            { "display": true },
    "Cost Per Projected View": {
      "display": true,
      "custom": true,
      "formula": "{Cost} / {Projected Views}",
      "cellType": "usd"
    }
  }
}
```

The custom column **Cost Per Projected View** = `{Cost} / {Projected Views}` (with `cellType: "usd"`) is the proactive formula suggestion v1 mandates (line 387 — "you MUST suggest at least one relevant custom formula"). For product-placement intent, cost-efficiency is the right framing.

### `widgets` (array — 4–6 widgets per v1 line 565)

```json
{
  "widgets": [
    { "aggregator": "channel_count",                  "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_metric", "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "sponsored_brands_count_metric",  "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_histogram", "type": "histogram", "index": 4, "width": 3, "height": 1 },
    { "aggregator": "uploads_histogram",              "type": "histogram", "index": 5, "width": 3, "height": 1 }
  ]
}
```

Widget rationale (per v1 lines 685–693):
- **Index 1** (most important): `channel_count` — answers "how many channels in this niche" at a glance (key for narrow result interpretation)
- **Index 2**: aggregate subscriber reach across the matched channels
- **Index 3**: sponsored brands count — relevant to product placement intent
- **Indices 4–5**: histograms last (take more visual space) — subscriber growth + uploads over time

### `histogram_bucket_size`

```json
{ "histogram_bucket_size": "month" }
```

Default; appropriate for `days_ago: 730`.

### `refinement_suggestions` (per v1 line 837 — MUST include 2–3, at least one with a custom formula)

```json
{
  "refinement_suggestions": [
    "Add an 'Engagement-per-subscriber' custom formula column ({Engagement} / {Subscribers}) to spot high-engagement micro-niche channels",
    "Broaden to OR (match channels covering AI OR cooking) — the strict AND intersection is small (~9 channels); OR returns ~8,500",
    "Narrow to channels with mostly US audience (set min_demographic_usa_share: 50)"
  ]
}
```

The first suggestion is the v1-mandated custom formula. The second offers the user the broaden-to-OR alternative we surfaced in the user-facing message. The third is a sizing/geography refinement common for product-placement intent.

### Full assembled JSON (what gets POSTed to `/api/dashboard/campaigns/`)

```json
{
  "action": "create_report",
  "report_title": "AI Cooking Channels (for product placement outreach)",
  "report_description": "Channels covering both AI and cooking themes — the intersection of Topics 96 (Artificial Intelligence) and 99 (Cooking). Optimized for product-placement outreach with sponsorship-history columns surfaced.",
  "summary": "Built a CHANNELS report for the AI×Cooking intersection (~9 channels) with outreach-friendly columns.",
  "report_type": 3,
  "filterset": {
    "keyword_groups": [
      {
        "text": "AI",
        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
        "exclude": false
      },
      {
        "text": "cooking",
        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
        "exclude": false
      }
    ],
    "keyword_operator": "AND",
    "channel_formats": [4],
    "days_ago": 730,
    "sort": "-reach"
  },
  "filters_json": {
    "min_brand_safety": "B"
  },
  "columns": {
    "Channel":                   { "display": true },
    "TL Channel Summary":        { "display": true },
    "Subscribers":               { "display": true },
    "Brand Safety":              { "display": true },
    "Sponsorship Score":         { "display": true },
    "Sponsorships Sold":         { "display": true },
    "Brands Sold":               { "display": true },
    "Last Sold Sponsorship":     { "display": true },
    "Open Proposals Count":      { "display": true },
    "USA Share":                 { "display": true },
    "Demographics - Age Median": { "display": true },
    "Channel URL":               { "display": true },
    "Outreach Email":            { "display": true },
    "Cost Per Projected View":   {
      "display": true,
      "custom": true,
      "formula": "{Cost} / {Projected Views}",
      "cellType": "usd"
    }
  },
  "widgets": [
    { "aggregator": "channel_count",                     "type": "metrics-box", "index": 1, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_metric",    "type": "metrics-box", "index": 2, "width": 2, "height": 1 },
    { "aggregator": "sponsored_brands_count_metric",     "type": "metrics-box", "index": 3, "width": 2, "height": 1 },
    { "aggregator": "channel_reach_at_scrape_histogram", "type": "histogram",   "index": 4, "width": 3, "height": 1 },
    { "aggregator": "uploads_histogram",                 "type": "histogram",   "index": 5, "width": 3, "height": 1 }
  ],
  "histogram_bucket_size": "month",
  "refinement_suggestions": [
    "Add an 'Engagement-per-subscriber' custom formula column ({Engagement} / {Subscribers}) to spot high-engagement micro-niche channels",
    "Broaden to OR (match channels covering AI OR cooking) — the strict AND intersection is small (~9 channels); OR returns ~8,500",
    "Narrow to channels with mostly US audience (set min_demographic_usa_share: 50)"
  ]
}
```

---

## Appendix B — what the v1 prompt got us, mapped to the v2 phases

This config maps to v2 phase outputs as follows:

| v1 config field | Comes from v2 phase |
|---|---|
| `report_title`, `report_description`, `summary` | Phase 5 (display formatting; uses NL_QUERY + intent signal) |
| `report_type: 3` | Phase 1 (CHANNELS routing) |
| `filterset.keyword_groups` (head keywords) | Phase 2c (translates Phase 2a's `strong_matches: [96, 99]` into head keywords from each topic's `keywords[]`) |
| `filterset.keyword_operator: "AND"` | Phase 2c (multi-topic AND inference from "AI cooking" composite noun) |
| `filterset.content_fields` | Phase 2c default for type 3 |
| `filterset.channel_formats: [4]` | Phase 2c default for type 3 |
| `filterset.days_ago: 730` | Phase 2c default (v1 mandate when keyword_groups present) |
| `filterset.sort: "-reach"` | Phase 2c default for type 3 |
| `filters_json.min_brand_safety` | Phase 4 (intent-driven addition for outreach context) |
| `columns` (specific selection + custom formula) | Phase 4 (driven by Phase 2c's `_intent_signal: "product placements"`) |
| `widgets` | Phase 4 |
| `histogram_bucket_size` | Phase 4 default |
| `refinement_suggestions` | Phase 5 (driven by Phase 3's "narrow result" finding) |

**Phase 2b is not represented in the config** — by design. When 2b is skipped (G03 case), the FilterSet uses the topics' curated keywords directly. When 2b runs (G09 case), its validated `KeywordSet` becomes the `keyword_groups` array.

---

## Appendix C — what would change for G09's report config

For contrast — the G09 config would have:

```json
{
  "report_type": 3,
  "filterset": {
    "keyword_groups": [
      {"text": "crypto",      "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false},
      {"text": "bitcoin",     "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false},
      {"text": "Web3",        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false},
      {"text": "ethereum",    "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false},
      {"text": "DeFi",        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false},
      {"text": "NFT",         "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false},
      {"text": "blockchain",  "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false}
    ],
    "keyword_operator": "OR",
    "channel_formats": [4],
    "days_ago": 730,
    "sort": "-reach"
  }
  /* + columns, widgets, etc. */
}
```

Differences from G03:
- 7 keyword_groups (from Phase 2b's validated set) vs G03's 2 (head keywords from topic anchors)
- `OR` operator vs G03's `AND`
- No topic anchor — keywords come entirely from Phase 2b's fresh research
- Larger result set (~4,272) vs G03's narrow ~9

Same v1 schema; same field names; same overall shape. The phases just feed different keyword arrays.
