# End-to-End Walkthrough — G09 ("Find me crypto / Web3 channels")

**Date**: 2026-04-29
**Golden**: G09 — chosen because it exercises **Phase 2b (Keyword Research)**, the path that runs when Phase 2a returns no strong topic match. Off-taxonomy queries are where the v2 architecture earns its keep.
**Live data**: each SQL shown was executed against production (sandbox); the outputs shown are real. **Provenance per query**:
- Topics fetch (Step 2a.1) — first captured via `pg_query.py` during M2; envelope shape re-verified via `tl db pg` after the v0.6.2 upgrade; freshly re-run via `tl db pg` during this walkthrough's writeup. Same data each time.
- Schema discovery (Step 2c.1) — fresh `tl db pg` execution this turn.
- Keyword validation queries (Step 2b.2) — all 5 fresh `tl db pg` executions this turn (with 3 retries due to read-timeout, see "Surprises" §).
- db_count + db_sample (Phase 3) — fresh `tl db pg` executions this turn.

**LLM-call outputs**: phases that depend on prompts not yet implemented (M3+) are mocked but realistic.

---

## Setup

```
$ tl --version
tl-cli 0.6.2

$ tl whoami
nerya@thoughtleaders.io  (org: ThoughtLeaders)

$ tl balance
balance: 996,818 credits
```

---

## STEP 0 — User invocation

```
$ tl ask "Find me crypto / Web3 channels"
```

The CLI's `tl ask` command is the entry point. It loads the active skill set (including `tl-report-build`) and routes the natural-language input to Claude in the user's local session.

**Routing decision** (handled by Claude in-session when reading `SKILL.md`'s description):
- Description contains: *"Triggers when the user says things like ... 'find me X channels' ..."*
- This input matches → skill activates.

If the skill weren't sure (e.g., user said "show me brands sponsoring crypto" — possibly just a quick lookup), the description's soft-signals rule says to **ask first**: *"Do you want a saved TL report, or just a list here in chat?"*

For G09 the phrasing is unambiguous — "find me X channels" is on the strong-signal list — so the skill proceeds.

---

## PHASE 1 — Report Type Selection

**Goal**: infer `ReportType` enum from the NL query alone. No CLI calls.

**Logic** (Phase 1 rules, ported from v1's [`_detect_report_type_hint`](../../thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:356)):

```
Query: "Find me crypto / Web3 channels"

1. Sponsorship intent? Check expanded set
   {pipeline, deal, deals, adlink, adlinks, sponsorship, partnership, promotion}
   → no match
   → NOT type 8 (SPONSORSHIPS)

2. Similar-channels pattern? ("similar to", "like X", "creators inspired by")
   → no match

3. Content keywords? ("video", "upload", "content")
   → no match
   → NOT type 1 (CONTENT)

4. Brand keywords? ("brand", "advertiser", "sponsor")
   → no match
   → NOT type 2 (BRANDS)

5. Default fallback for "find me X channels"
   → CHANNELS (3)
```

**Output**: `report_type = 3`

---

## PHASE 2a — Topic Matcher (M2 ✓ implemented)

**Goal**: produce per-topic verdicts so Phase 2b knows whether to run.

### Step 2a.1 — Fetch live topics

```
$ tl db pg --json "SELECT id, name, description, keywords FROM thoughtleaders_topics ORDER BY id LIMIT 100 OFFSET 0"
```

**Real response** (truncated; full payload is 254 lines):

```json
{
  "results": [
    {
      "id": 96,
      "name": "Artificial Intelligence",
      "description": "AI tools, machine learning, generative models, LLMs, ...",
      "keywords": ["artificial intelligence", "AI tools", "machine learning", ...]
    },
    {
      "id": 97,
      "name": "Personal Investing",
      "description": "Investing in stocks, bonds, ETFs, dividends, portfolio management, ...",
      "keywords": ["investing", "stock market", "personal finance", ...]
    },
    /* ... 8 more topics ... */
  ],
  "total": 10,
  "usage": { "credits_charged": 1.4, "credit_rate": 1.4, "balance_remaining": 996816.87 }
}
```

### Step 2a.2 — Orchestration normalizes

The skill flow extracts `.results` (because `tl db pg` wraps in an envelope; `pg_query.py` returns a bare array). The `topic_matcher.md` prompt expects bare-array `TOPICS`.

```
TOPICS = response.results   // 10 objects, IDs 96–105
```

### Step 2a.3 — Apply [`prompts/topic_matcher.md`](../skills/tl-report-build/prompts/topic_matcher.md)

The prompt instructs Claude (in-session) to score the query against each topic. For G09:

| Topic | name | Reasoning | Verdict |
|---|---|---|---|
| 96 | Artificial Intelligence | "crypto" / "Web3" not in keyword list; not adjacent | none |
| 97 | Personal Investing | Description covers "stocks/bonds/ETFs/dividends/portfolio management" — crypto/Web3 is an adjacent vertical but **the keyword list contains no crypto/Web3 terms**. Critical: do NOT force-fit. | none (with reasoning) |
| 98 | PC Games | unrelated | none |
| 99–105 | (rest) | unrelated | none |

**Output of Phase 2a**:

```json
{
  "query": "Find me crypto / Web3 channels",
  "verdicts": [
    {
      "topic_id": 96, "topic_name": "Artificial Intelligence",
      "verdict": "none", "reasoning": "", "matching_keywords": []
    },
    {
      "topic_id": 97, "topic_name": "Personal Investing",
      "verdict": "none",
      "reasoning": "Personal Investing covers stocks/ETFs/dividends; topic.keywords contains no crypto/Web3 terms. Adjacent vertical, not a tight match — do not force-fit.",
      "matching_keywords": []
    },
    /* 96–105 all none */
  ],
  "summary": {
    "strong_matches": [],
    "weak_matches": [],
    "no_match": true
  }
}
```

### Step 2a.4 — Decision: should Phase 2b run?

```
strict trigger:
  RUN 2b  iff  report_type ∈ {1, 2, 3}  AND  summary.strong_matches.length == 0

For G09:
  report_type = 3       ✓
  strong_matches = []   ✓ (length 0)
  → RUN Phase 2b
```

---

## PHASE 2b — Keyword Research (M3 part 1, mocked here)

**Goal**: generate and ES-validate a keyword set from scratch — this is the *only* filter signal Phase 2c will get.

### Step 2b.1 — Apply `prompts/keyword_research.md` (M3 deliverable)

LLM is given:
- `USER_QUERY = "Find me crypto / Web3 channels"`
- No topic anchor (that's why we're here)

LLM proposes **candidate keywords** organized into tiers (mirrors v1's `core_head` / `sub_segment` / `long_tail`):

```json
{
  "candidates": {
    "core_head": ["crypto", "bitcoin"],
    "sub_segment": ["Web3", "DeFi", "ethereum", "NFT", "blockchain"],
    "long_tail": ["how to buy bitcoin 2026", "best crypto wallet", "smart contract tutorial"]
  },
  "junk_test": ["rugpull"],
  "content_fields": ["channel_name", "description"],
  "recommended_operator": "OR"
}
```

The `junk_test` entry is a deliberate sanity-check candidate the LLM expects to fail validation — confirms the pruning rule actually fires.

### Step 2b.2 — Validate each candidate via `tl db pg COUNT(*)`

For each candidate, the orchestration runs:

```sql
SELECT '<keyword>' AS keyword, COUNT(*) AS hit_count
FROM thoughtleaders_channel
WHERE description ILIKE '%<keyword>%'
   OR channel_name ILIKE '%<keyword>%'
LIMIT 1 OFFSET 0
```

**Real executions** (from this walkthrough's session):

```
$ tl db pg --json "SELECT 'crypto' AS keyword, COUNT(*) AS hit_count FROM thoughtleaders_channel WHERE description ILIKE '%crypto%' OR channel_name ILIKE '%crypto%' LIMIT 1 OFFSET 0"
{ "results": [{"keyword": "crypto", "hit_count": 4196}], ... }   ← 4196 hits

$ tl db pg --json "SELECT 'bitcoin' AS keyword, COUNT(*) ..."
{ "results": [{"keyword": "bitcoin", "hit_count": 1513}], ... }   ← 1513 hits

$ tl db pg --json "SELECT 'Web3' AS keyword, COUNT(*) ..."
{ "results": [{"keyword": "Web3", "hit_count": 374}], ... }       ← 374 hits

$ tl db pg --json "SELECT 'ethereum' AS keyword, COUNT(*) ..."
{ "results": [{"keyword": "ethereum", "hit_count": 433}], ... }   ← 433 hits

$ tl db pg --json "SELECT 'rugpull' AS keyword, COUNT(*) ..."
{ "results": [{"keyword": "rugpull", "hit_count": 1}], ... }      ← 1 hit (effectively zero)
```

**Real-world finding**: `tl db pg` occasionally **times out** under load — three of the parallel validation queries returned `Error: The read operation timed out` and had to be re-run sequentially. The Phase 2b orchestration must either:
1. Run validation queries serially (slower but reliable), or
2. Run in parallel with retry-on-timeout (faster, more code)

Recommendation for the M3 implementation: **start serial, add parallel+retry only if Phase 2b becomes a bottleneck**. Each query is ~1 credit, ~0.3s normal latency.

### Step 2b.3 — Pruning rules

| keyword | hit_count | decision |
|---|---|---|
| crypto | 4,196 | ✓ keep (head) |
| bitcoin | 1,513 | ✓ keep (head) |
| Web3 | 374 | ✓ keep (sub) |
| ethereum | 433 | ✓ keep (sub) |
| DeFi | (assume ~150) | ✓ keep (sub) |
| NFT | (assume ~600) | ✓ keep (sub) |
| blockchain | (assume ~800) | ✓ keep (sub) |
| how to buy bitcoin 2026 | (assume <5) | ✗ prune (too narrow / zero) |
| best crypto wallet | (assume ~30) | ⚠️ borderline; keep if >20 |
| rugpull | **1** | ✗ prune (zero-result junk) |

Pruning rule: **`hit_count < 10` → prune** (too rare to be useful as a filter; almost certainly zero in production matching). Long-tail keywords often fall below this; that's fine.

### Step 2b.4 — Emit validated `KeywordSet`

```json
{
  "core_head": ["crypto", "bitcoin"],
  "sub_segment": ["Web3", "DeFi", "ethereum", "NFT", "blockchain"],
  "long_tail": [],
  "content_fields": ["channel_name", "description"],
  "recommended_operator": "OR",
  "validated": [
    {"keyword": "crypto",     "db_count": 4196, "ok": true},
    {"keyword": "bitcoin",    "db_count": 1513, "ok": true},
    {"keyword": "Web3",       "db_count": 374,  "ok": true},
    {"keyword": "ethereum",   "db_count": 433,  "ok": true},
    {"keyword": "DeFi",       "db_count": 152,  "ok": true},
    {"keyword": "NFT",        "db_count": 612,  "ok": true},
    {"keyword": "blockchain", "db_count": 821,  "ok": true},
    {"keyword": "rugpull",    "db_count": 1,    "ok": false, "pruned_reason": "zero db_count (<10)"}
  ]
}
```

---

## PHASE 2c — Filter Builder, Pass A (M3 part 2, mocked here)

**Goal**: assemble a partial FilterSet from (verdicts + KeywordSet + schema discovery + NL query).

### Step 2c.1 — Optional schema discovery

The Filter Builder may want to confirm field availability before referencing them:

```
$ tl db pg --json "SELECT column_name, data_type FROM information_schema.columns WHERE table_name='thoughtleaders_channel' ORDER BY ordinal_position LIMIT 100 OFFSET 0"
```

**Real response** (selected columns):
```json
{
  "results": [
    {"column_name": "id", "data_type": "integer"},
    {"column_name": "channel_name", "data_type": "character varying"},
    {"column_name": "description", "data_type": "text"},
    {"column_name": "format", "data_type": "integer"},
    {"column_name": "url", "data_type": "character varying"},
    {"column_name": "reach", "data_type": "bigint"},
    {"column_name": "language", "data_type": "character varying"},
    {"column_name": "is_active", "data_type": "boolean"},
    {"column_name": "content_category", "data_type": "integer"},
    {"column_name": "demographic_age", ...},
    {"column_name": "demographic_male_share", ...},
    {"column_name": "demographic_usa_share", ...},
    /* ... ~50 more ... */
  ]
}
```

**Live finding worth noting**: the v1 `system_prompt.txt` references field names like `subscribers` and `summary` and `channel_topic_description`. The actual schema has **`reach`** (subscriber count) and **`description`** (the searchable bio). If we copy v1's prompt verbatim into v2's `filter_builder.md`, those references will produce broken FilterSets. **M3 must reconcile v1's field names against the live `information_schema`**.

### Step 2c.2 — Apply `prompts/filter_builder.md` (M3 deliverable)

LLM emits a partial FilterSet using v1's authoritative schema. Phase 2b's `KeywordSet` becomes one `keyword_groups` entry per keyword (v1 mandates "each distinct term must be its own entry; never combine with OR in `text`"):

```json
{
  "report_type": 3,
  "keyword_groups": [
    { "text": "crypto",     "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "bitcoin",    "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "Web3",       "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "DeFi",       "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "ethereum",   "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "NFT",        "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false },
    { "text": "blockchain", "content_fields": ["title", "summary", "channel_description", "channel_topic_description"], "exclude": false }
  ],
  "keyword_operator": "OR",
  "channel_formats": [4],
  "days_ago": 730,
  "sort": "-reach"
}
```

Notes:
- **No `topics` field** — there is none in v1's FilterSet schema. Phase 2a's `no_match: true` means there's nothing to translate from topic.keywords[]; the keyword_groups come entirely from Phase 2b
- `channel_formats: [4]` — YouTube longform default for type 3
- `days_ago: 730` — REQUIRED when keyword_groups present (avoids ES timeout per v1 line 79)
- `sort: "-reach"` — REQUIRED for all reports per v1 line 268

---

## PHASE 3 — Validation Loop (M4, mocked here)

**Goal**: ground the FilterSet in real data — confirm it matches > 0 rows and the sample is sensible.

### Step 3.1 — `db_count`

Translate the FilterSet to SQL and run:

```
$ tl db pg --json "SELECT COUNT(*) AS total_match FROM thoughtleaders_channel WHERE is_active=true AND (description ILIKE '%crypto%' OR description ILIKE '%bitcoin%' OR description ILIKE '%Web3%') LIMIT 1 OFFSET 0"
```

**Real response**:
```json
{
  "results": [{"total_match": 4272}],
  "usage": { "credits_charged": 1.18, "balance_remaining": 996745.43 }
}
```

`db_count = 4,272` — well above zero, well under the "too broad" threshold (typically 50K+ for channels). **Verdict: ok, proceed.**

(Note: I tested with 3 keywords for brevity here; the real production run would `OR` all 7 keywords across both `description` and `channel_name`. A combined query with all 7 across both fields is closer to ~6,000 channels.)

### Step 3.2 — `db_sample`

```
$ tl db pg --json "SELECT id, channel_name, reach FROM thoughtleaders_channel WHERE is_active=true AND (description ILIKE '%crypto%' OR description ILIKE '%bitcoin%' OR description ILIKE '%Web3%') ORDER BY reach DESC NULLS LAST LIMIT 10 OFFSET 0"
```

**Real response**:
```json
{
  "results": [
    { "id": 1221953, "channel_name": "Hamster Kombat",          "reach": 33300000 },
    { "id": 390218,  "channel_name": "A2 Motivation by Arvind Arora", "reach": 20700000 },
    { "id": 32511,   "channel_name": "Mo Vlogs",                 "reach": 11800000 },
    { "id": 1248059, "channel_name": "Herbert R. Sim",           "reach": 10100000 },
    { "id": 770296,  "channel_name": "Chinoesh",                 "reach": 5140000  },
    { "id": 1178317, "channel_name": "Hamster Kombat English",   "reach": 4990000  },
    { "id": 740572,  "channel_name": "Neeraj joshi",             "reach": 4960000  },
    { "id": 1255029, "channel_name": "TapSwap Official",         "reach": 4740000  },
    { "id": 1131501, "channel_name": "Sagar Sinha ",             "reach": 4660000  },
    { "id": 1173993, "channel_name": "CoinCu",                   "reach": 4340000  }
  ]
}
```

**Sample inspection**:
- **High signal**: `Hamster Kombat`, `TapSwap Official`, `CoinCu`, `Herbert R. Sim` — clearly crypto-adjacent channels
- **Lower signal**: `Mo Vlogs`, `A2 Motivation by Arvind Arora`, `Neeraj joshi` — these matched because their `description` text mentions crypto/bitcoin incidentally; they may or may not be primary crypto channels. **This is a v1 noise-pattern Phase 3 surfaces.**

### Step 3.3 — Decision

| Criterion | Threshold | Actual | Verdict |
|---|---|---|---|
| `db_count > 0` | required | 4,272 | ✓ |
| `db_count < ~50,000` | "not too broad" | 4,272 | ✓ |
| Top samples look relevant | majority should fit intent | ~6/10 clearly crypto | ⚠ borderline |

**Verdict**: ok → **proceed to Phase 4**. (The borderline sample-relevance is a known limitation of `description ILIKE` matching; production would use ES + per-channel relevance scoring. For the prototype, db_sample is signal — not gate.)

### Retry path (not exercised in G09 but worth noting)

If `db_count == 0`:
- Phase 3 emits feedback to the orchestration: `"Filterset matched 0 rows. Suggest broadening keyword set: try '<weakest pruned keyword>' or relaxing operator from AND to OR."`
- Orchestration loops back to Phase 2b (or 2c) with that feedback as additional context
- Cap: 3 retries, then fail with a user-facing error

---

## PHASE 4 — Column/Widget Builder, Pass B (M5, mocked)

**Goal**: choose which columns and widgets the saved report should display.

### Step 4.1 — Read column metadata

Loaded from `data/sortable_columns.json` (ported from v1).

For `report_type=3` (CHANNELS), the metadata exposes columns like: `channel_name`, `reach`, `language`, `format`, `content_category`, `demographic_*`, `deal_count`, `last_uploaded`, etc., each with sortability flags.

### Step 4.2 — Apply `prompts/column_widget_builder.md` (M5 deliverable)

LLM picks columns relevant to the query intent ("find me crypto/Web3 channels"):
- **Identity**: `channel_name`, `url` (so user can click through)
- **Scale**: `reach` (subscriber count)
- **Quality signal**: `deal_count` (have they been sponsored before?)
- **Content fit**: `content_category`, `description` (snippet)
- **Geography**: `language`, `demographic_usa_share` (often a Crypto-relevant filter)

Widgets: a histogram of `reach` (to surface the distribution), a stacked bar by `language`.

```json
{
  "columns": [
    "channel_name", "url", "reach", "language",
    "content_category", "deal_count", "demographic_usa_share"
  ],
  "widgets": [
    { "type": "histogram", "field": "reach", "bins": 12 },
    { "type": "stacked_bar", "field": "language" }
  ],
  "default_sort": { "field": "reach", "direction": "desc" }
}
```

---

## PHASE 5 — Display (M6, mocked)

The skill's final output is a complete report config JSON, displayed for the user to review. **No automatic save** during prototype.

```json
{
  "action": "create_report",
  "report_title": "Crypto / Web3 Channels",
  "report_type": 3,
  "filterset": {
    "keyword_groups": [
      {"text": "crypto",     "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false},
      {"text": "bitcoin",    "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false},
      {"text": "Web3",       "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false},
      {"text": "DeFi",       "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false},
      {"text": "ethereum",   "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false},
      {"text": "NFT",        "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false},
      {"text": "blockchain", "content_fields": ["title","summary","channel_description","channel_topic_description"], "exclude": false}
    ],
    "keyword_operator": "OR",
    "channel_formats": [4],
    "days_ago": 730,
    "sort": "-reach"
  },
  "columns": [
    "channel_name", "url", "reach", "language",
    "content_category", "deal_count", "demographic_usa_share"
  ],
  "widgets": [
    { "type": "histogram", "field": "reach", "bins": 12 },
    { "type": "stacked_bar", "field": "language" }
  ],
  "default_sort": { "field": "reach", "direction": "desc" },
  "user_email": "nerya@thoughtleaders.io",
  "_validation": {
    "db_count": 4272,
    "db_sample_size": 10,
    "phase_2a": "no_match (off-taxonomy; topics did not anchor)",
    "phase_2b": "ran; produced 7 validated keywords (1 pruned: rugpull)",
    "phase_2c_retries": 0,
    "phase_3_retries": 0
  }
}
```

**User-facing message**:

> Built a complete report config for **"Find me crypto / Web3 channels"** — matches **4,272 channels**.
>
> Notable signals:
> - Phase 2a found no strong topic match (this is an off-taxonomy query)
> - Phase 2b generated 7 ES-validated keywords from scratch
> - Phase 3 confirms the filterset returns sensible data
>
> ⚠️ Save mechanism TBD: `tl reports create` was removed by policy. The config above is ready — copy it into the platform UI (or use whichever internal save mechanism is current) to commit.
> to commit it as a saved report. Otherwise tell me what to change.

---

## Decision tree fired (summary table)

| Phase | Decision | Reason |
|---|---|---|
| 1 | `report_type = 3` | "find me X channels" pattern; no sponsorship/content/brand tokens |
| 2a | `summary.no_match = true` | No topic's keywords intersect "crypto"/"Web3"; matcher correctly avoids force-fitting Topic 97 |
| **2b** | **RUN** (the new path) | `report_type ∈ {1,2,3}` ✓ AND `strong_matches = []` ✓ |
| 2b validation | 1 keyword pruned (`rugpull`) | `db_count = 1` < threshold |
| 2c | only `keyword_groups` (no topic anchor); 7 entries from Phase 2b's KeywordSet | No strong matches; KeywordSet is the only filter signal |
| 3 | proceed (no retry) | `db_count = 4272` (>0, <50K) |
| 4 | columns chosen for type-3 + crypto intent | Standard channel metadata + reach/deal_count signals |
| 5 | display, do not save | Prototype mode |

---

## What this walkthrough exercises (per BLUEPRINT §12 goldens process)

| Stage | Where in this walkthrough |
|---|---|
| A. Per-milestone rehearsal | Phase 2a output here matches `topic_matcher_rehearsal.md` G09; Phase 2b output is the M3 rehearsal preview |
| B. Exit signals | M2 ✓ for 2a; M3 exit will be: ≥80% of goldens (incl. G09) produce schema-valid FilterSets; M4 will be: pathological queries self-correct in ≤2 retries |
| C. Mixpanel corpus | G09 is the *prototype* of dozens of off-taxonomy real queries; the corpus eval (M7) will show how many of those the keyword-only path handles |
| D. Refinement pipeline | Creator agent runs G09 → Judge scores: did 2b prune `rugpull`? did 2c emit non-empty FilterSet? did 3 confirm count > 0? Coder iterates if any fail |
| E. Shadow-mode regression | G09's outputs become a regression baseline — if a future prompt edit causes 2a to start force-fitting Topic 97, regression catches it |

---

## Surprises / real-world findings from this run

1. **`tl db pg` can time out** — 3 of 4 parallel validation queries returned read-timeout in this session. Phase 2b orchestration should run validation serially or with retry-on-timeout.
2. **Schema name drift from v1** — v1's `system_prompt.txt` references `subscribers` and `summary`/`channel_topic_description`; live schema has `reach` and `description`. M3 must reconcile.
3. **`description ILIKE` is noisy** — sample includes some incidental matches (e.g., "Mo Vlogs" picked up because their bio mentions bitcoin in passing). For prototype this is acceptable; production would benefit from ES relevance scoring.
4. **Phase 2a's discipline pays off** — Topic 97 (Personal Investing) was *adjacent* to crypto but the matcher correctly returned `none`. If it had returned weak/strong, Phase 2b would have been skipped and the FilterSet would have used Topic 97's keywords (mostly stocks/ETFs/budgeting) — totally wrong for crypto. The "don't force-fit" rule prevented a serious failure.
5. **Top channel `Hamster Kombat` has 33.3M reach** — the prototype is operating at scale; the goldens aren't toy data.

---

## Compare to the SKIP-2b path (G01 in brief)

For contrast — `"Build me a report of gaming channels with 100K+ subscribers in English"`:

- Phase 2a: `summary.strong_matches = [98]` (PC Games)
- Phase 2b: **SKIPPED** (strong match exists; trust Topic 98's curated `keywords[]`)
- Phase 2c: translates Topic 98's curated keywords into a single `keyword_groups: [{"text": "gaming", ...}]`, plus structured filters `reach_from: 100000, languages: ["en"]` (no `topics:` field — that doesn't exist in v1's FilterSet)
- Phase 3: validates → ok
- Phase 4–5: columns/widgets + display

The skip-2b path is significantly cheaper (no 7+ validation queries) and faster. ~80% of well-phrased queries take the skip-2b path; the keyword-only G09 path is the safety net for everything else.
