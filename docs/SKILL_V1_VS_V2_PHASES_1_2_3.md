# v1 vs v2 — Phases 1, 2, 3

**Audit date 2026-04-29.** Side-by-side of what the v1 `create-report` skill does today vs. what v2 should do for the first three phases. Companion to [SKILL_ARCHITECTURE.md](SKILL_ARCHITECTURE.md).

**v1 location:** `~/Desktop/ThoughtLeader/thoughtleaders-skills/create-report/`
**v2 target:** `~/Desktop/ThoughtLeader/tl-cli/skills/tl-report-build/`

---

## TL;DR

v1 is **server-side Python orchestrating multiple LLM calls + subprocess hops**. The functional pieces are mostly sound, but the *plumbing* (subprocesses, timeouts, post-hoc Critic/Judge loops) only exists because v1 runs server-side. v2 collapses most of it into prompt rules + a single Filter Builder LLM call + one cheap `db_count` check.

| Phase | v1 today | v2 strategy | Net effect |
|---|---|---|---|
| **1. Report type** | Pure Python string heuristics ([orchestrate_preview.py:356](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:356)) | Port heuristics → prompt rules; expand the sponsorship keyword set | Less code, more coverage |
| **2. Filter builder** | 3 LLM calls + 2 subprocesses (keyword-validate → prune → sort → main config) | Single LLM call with rich context; embed sort + keyword reasoning inline | 5 hops → 1 hop |
| **3. Validation** | Critic / Judge / Revise post-hoc LLM loop; **no DB check at all** | Single `db_count` query + 1 retry; failure-mode rules embedded in Filter Builder prompt | Replace LLM-only safety net with cheap real-data ground-truth |

---

## Phase 1 — Report Type Selection

### What v1 does
- [`_detect_report_type_hint`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:356) — pure-Python heuristics, no LLM, no DB
- [`_is_likely_sponsorship_query`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:201) checks the prompt + conversation history for one of these tokens:
  ```python
  _SPONSORSHIP_KEYWORDS = {"pipeline", "deal", "deals", "adlink", "adlinks"}
  ```
- Fallback ordering: similar-channels patterns ("similar to", "like X") → CONTENT (1) on "video/upload/content" → BRANDS (2) on "brand/advertiser/sponsor" → CHANNELS (3) default
- Respects an explicit `campaign_config.report_type` if one was passed in (edit-mode reuse)

### What v2 does
- Same heuristics, but expressed as **rules in a prompt**, not Python
- Expand the sponsorship token set — current one misses "sponsorship", "partnership", "promotion", "ad spot" (real terms users say)
- Keep edit-mode override: if a report config is passed in (a future flow), trust the type already set

### Reuse / Replace / Drop
- **Reuse**: the heuristic ordering and the similar-channels-pattern detection — they're battle-tested
- **Replace**: the `_SPONSORSHIP_KEYWORDS` set — broaden it
- **Drop**: the conversation-history loop ([:204–206](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:204)). Claude reads the whole conversation natively; no need for explicit string-concat over turns

### v2 deliverable
A short rule block at the top of `prompts/topic_matcher.md` (or its own `prompts/report_type.md` if it grows). No CLI calls in this phase — Phase 1 is intent inference only.

---

## Phase 2 — Filter Builder, Pass A

### What v1 does
Three sequential LLM calls + two subprocess hops:

1. **Keyword research** ([orchestrate_preview.py:227–314](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:227)):
   - LLM with [`KEYWORD_SYSTEM_PROMPT`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:71) suggests candidate keywords
   - Subprocess into `keyword-research/scripts/validate_keywords.py` — hits ES, returns hit counts per keyword (`KEYWORD_SUBPROCESS_TIMEOUT = 120s`)
   - Subprocess into `keyword-research/scripts/prune_keywords.py` — LLM removes too-broad / redundant terms, assigns `content_fields`, picks operator
   - Returns `keyword_groups` + `keyword_operator` (defaults to **`OR`**, even when user said "AND"/"both")
2. **Sort strategy** ([:416–458](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:416)) — separate LLM call with [`SORT_STRATEGY_SYSTEM_PROMPT`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:376), reads [`data/sortable_columns.json`](thoughtleaders-skills/create-report/data/sortable_columns.json) for column metadata
3. **Main config** ([:755–833](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:755)) — final LLM call with the **999-line `system_prompt.txt`** + the pre-validated keywords + the sort recommendation, produces full FilterSet JSON

### What v2 does
**Single Filter Builder LLM call.** Inputs: NL query + report type (from Phase 1) + live topics array + relevant schema (via `tl db pg` against `information_schema` — `tl describe` is excluded from the v2 surface per the 2026-04-23 daily). Output: partial FilterSet (filters only — no columns/widgets yet, those are Pass B).

The 999-line `system_prompt.txt` is the **most valuable v1 asset** — it's the encoded FilterSet schema (filter names, valid values, examples, common mistakes). v2 should port it largely as-is into `prompts/filter_builder.md`, with these adjustments:
- Replace `data/sortable_columns.json` references with live `information_schema` lookups via `tl db pg` *or* keep the static file copy for prototype — both work
- Inline the keyword reasoning (instead of subprocess hop)
- Inline the sort-strategy reasoning (instead of separate LLM call)
- Add the failure-mode rules from v1's Critic prompt (see Phase 3 below) up-front so we don't generate broken configs in the first place

### Reuse / Replace / Drop
- **Reuse**:
  - `system_prompt.txt` content (filters, examples, multi-step queries, custom columns) — port to `prompts/filter_builder.md`
  - `sortable_columns.json` — copy into `tl-cli/skills/tl-report-build/data/`
  - The keyword-research skill's **stages 3 (validate) + 4 (prune)** if we want grounded keyword sets; skip stages 1+2 (define_niche, generate_candidates) — overkill for interactive use
- **Replace**:
  - The 3-LLM-call cascade with **one LLM call** that has all the context inline
  - Subprocess-based ES validation with either **inline LLM reasoning** ("does this keyword sound real?") or a **direct `pg_query.py` count** for cheap ground-truth
  - Hardcoded `keyword_operator = "OR"` default with **explicit operator inference** (look for "and"/"both"/"+" in the query → AND; default OR otherwise)
- **Drop**:
  - `KEYWORD_SUBPROCESS_TIMEOUT` and `SIMILAR_CHANNELS_TIMEOUT` constants — irrelevant in a skill
  - The silent fallback to empty `keyword_groups` when ES is down ([:323–325](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:323)) — let Phase 3's `db_count == 0` retry catch this instead

### v2 deliverable
- `prompts/topic_matcher.md` (Phase 2a — runs first, populates `topics`)
- `prompts/filter_builder.md` (Phase 2b — produces the partial FilterSet, ported from `system_prompt.txt`)
- `data/sortable_columns.json` (copied from v1)

---

## Phase 3 — Validation Loop

### What v1 does — and the **biggest finding** of this audit
**v1 has no DB-grounded validation at all.** It runs a Critic / Judge / Revise post-hoc LLM loop instead:

- [`CRITIC_SYSTEM_PROMPT`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:463) — checks the LLM's config against ~10 known failure modes (missing entity filters, over-constraining, keyword relevance, missing date range, sort/type mismatch, etc.)
- [`JUDGE_SYSTEM_PROMPT`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:508) — adjudicates whether the Critic's complaints are real, decides accept vs revise
- **Revise** re-runs the main LLM with Critic feedback, capped by [`REVIEW_LOOP_TIME_BUDGET = 200s`](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:67) — silently skipped if the pipeline is already slow ([:673](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:673))

That's it. **v1 never asks the database whether the FilterSet returns rows.** A user can get a slick-looking FilterSet that returns zero results, and the only safety net is "the Critic LLM thought it looked over-constrained."

### What v2 does
The architecture doc's Phase 3 is **brand new**, not a port. Two changes:

1. **Move the Critic's failure-mode rules upfront** — embed them as constraints in `prompts/filter_builder.md` so the LLM doesn't generate broken configs in the first place. Cheaper than catching them post-hoc.
2. **Add the actual `db_count` + `db_sample` check** — translate the partial FilterSet into a SQL query, run it via `pg_query.py` (interim) or `tl db pg` (once deployed):
   - `db_count == 0` → retry Filter Builder with feedback ("your filterset matched 0 rows, relax `<which constraint>`")
   - `db_count` reasonable → proceed to Pass B
   - `db_count` too large (e.g., > 50K) → narrow

   Cap retries at 3 to prevent loops.

### Reuse / Replace / Drop
- **Reuse**: the Critic's 10 failure-mode rules — those are real, hard-won. Port them into `prompts/filter_builder.md` as the "do-not-generate" list
- **Replace**: the Critic / Judge / Revise loop with the proactive prompt rules + DB-grounded check
- **Drop**:
  - `REVIEW_LOOP_TIME_BUDGET` (silent skipping of validation under time pressure is dangerous; better to have a hard fail-fast)
  - The Judge LLM call entirely — when the Critic's rules live in the Filter Builder prompt, there's nothing to adjudicate

### v2 deliverable
- Validation logic lives in `SKILL.md` flow rules (not a separate prompt file): "after filter_builder produces a FilterSet, translate to SQL, run `db_count`, if 0 then loop; cap at 3"
- Add the failure-mode rules to `prompts/filter_builder.md`

---

## Surprises worth flagging

These came out of the v1 audit and aren't in any current doc:

1. **Sponsorship keyword set is dangerously narrow** — only `{pipeline, deal, deals, adlink, adlinks}`. Misses the actual user-facing terms ("sponsorship", "partnership", "promotion"). v2 must broaden this.
2. **`keyword_operator` silently defaults to `OR`** — even when the user said "and" or "both". Real users say "AND" most of the time; v1 ships OR. v2 should infer or ask.
3. **`system_prompt.txt` (999 lines) is not version-locked to the backend schema.** If FilterSet changes server-side, the prompt rots. v2 should at minimum date-stamp it; ideally check schema via `tl db pg` against `information_schema` and warn on drift.
4. **Sort direction is silently clamped** ([orchestrate_preview.py:454](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:454)) — LLM picks "asc", column metadata says "desc-only", v1 overrides without telling the user. v2 should surface the override.
5. **ES subprocess failure → empty `keyword_groups`** ([:323–325](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py:323)) — silent. Report has zero results, user gets no error.
6. **Cross-references aren't validated upfront** — if a brand name is misspelled, v1's resolver returns no IDs and the LLM silently drops the cross-ref. v2 should validate before generating.
7. **Similar-channels detection is hardcoded patterns** — "creators inspired by MrBeast" doesn't match any v1 pattern. v2 can ask the LLM to detect this in Phase 1.

---

## What I need from you before writing code

Three decisions, low-stakes but worth aligning on:

1. **Keyword research** — keep calling out to `keyword-research/scripts/{validate_keywords,prune_keywords}.py` from the v2 skill (preserves ES grounding), or inline keyword reasoning into Filter Builder and rely on `db_count` to catch zeroes? My default: **inline for the prototype, keep the keyword-research skill scripts available as a fallback if Filter Builder produces too many zero-count FilterSets.**

2. **Schema discovery cadence** — ~~call `tl describe show` once at skill load and cache, or per-invocation?~~ **Decided 2026-04-29**: drop `tl describe` entirely (per the 2026-04-23 daily, higher-level commands are duplicative). Schema discovery is `tl db pg` against `information_schema`, queried inline as needed. No caching layer — the queries are cheap (single round-trip to PG, ≤200 rows from system catalogs).

3. **`system_prompt.txt` port** — copy it into `prompts/filter_builder.md` mostly verbatim and edit incrementally, or rewrite from scratch using v1 only as reference? My default: **copy verbatim, mark sections to keep / change / drop as we hit them in M2–M5.** It's 999 lines of hard-won schema knowledge; rewriting risks losing institutional memory.

If those three defaults sound right I'll start scaffolding `tl-cli/skills/tl-report-build/` (Milestone 1) — folder structure, `SKILL.md` stub, ported `sortable_columns.json` and `system_prompt.txt`, golden-queries seed file. About 30 minutes of mechanical work.

---

## Files referenced

| Reference | Purpose |
|---|---|
| [orchestrate_preview.py](thoughtleaders-skills/create-report/scripts/orchestrate_preview.py) | v1's Phase 2–3 orchestration (1063 lines) |
| [orchestrate_keywords.py](thoughtleaders-skills/create-report/scripts/orchestrate_keywords.py) | Keyword-research subprocess wrapper (315 lines) |
| [system_prompt.txt](thoughtleaders-skills/create-report/prompts/system_prompt.txt) | v1's main LLM system prompt — the 999-line FilterSet bible |
| [sortable_columns.json](thoughtleaders-skills/create-report/data/sortable_columns.json) | Column metadata for sort-strategy LLM call |
| [keyword-research/SKILL.md](thoughtleaders-skills/keyword-research/SKILL.md) | 4-stage keyword pipeline; v2 keeps stages 3+4 |
