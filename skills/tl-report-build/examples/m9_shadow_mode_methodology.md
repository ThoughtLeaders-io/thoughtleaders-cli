# M9 — Shadow-Mode Calibration Methodology

**Date**: 2026-05-02
**Status**: Methodology + framework. Actual run is operational (deferred to when both paths are running in parallel against real users).

---

## Purpose

Validate that v2's outputs are **at least as good as v1's** before promoting v2 to default. Run both paths against the same queries; measure agreement; surface divergences for human review.

The exit signal — "v2 is ready to be the default path" — is a **measurable agreement rate** plus zero **regressions on the safety-net cases**.

---

## What "shadow-mode" means here

For each query in the eval corpus, run BOTH paths concurrently (or near-concurrently) and capture both outputs without showing v2's output to the user. Continue with v1's output as the user-facing result. After a sustained window (~weeks), compare the captured pairs.

```
USER_QUERY
   │
   ├──→ v1 path:  tl reports create  →  server orchestration  →  CONFIG_V1 (user sees this)
   │
   └──→ v2 path:  v2 skill            →  Phase 1–5 outputs    →  CONFIG_V2 (captured silently)

Compare: CONFIG_V1 vs CONFIG_V2  →  agreement metric
```

The user only sees v1's output during shadow-mode. v2 runs purely for measurement.

---

## What to compare (the comparison surfaces)

For each `(USER_QUERY, CONFIG_V1, CONFIG_V2)` triplet, compute these dimensions independently:

### Dim 1 — Report type agreement (binary)

```
v1.report_type == v2.report_type ?
```

Trivial check; should agree ~100% of the time. Disagreements indicate Phase 1 heuristic drift.

### Dim 2 — FilterSet structural agreement (per-field)

| Field | Agreement check |
|---|---|
| `keyword_groups[*].text` | Set comparison after lowercasing; exact match required for full credit |
| `keyword_operator` | Exact match |
| `reach_from` / `reach_to` | Numeric within ±10% (small variance acceptable) |
| `languages` | Exact set match |
| `channel_formats` | Exact set match |
| `days_ago` | Both must be set; values can differ (730 vs 365 acceptable) |
| `brand_names`, `channel_names` | Set comparison after case-fold |
| `cross_references` | Structural diff: same `type` + same `brand_names`/`statuses` |

Score per query: percentage of fields that agree out of fields that *both* paths set. Don't penalize for fields one path sets that the other doesn't (that's a separate "completeness" metric).

### Dim 3 — db_count overlap

Run both FilterSets through Phase 3's `db_count` SQL translation. Compare:

```
overlap_pct = abs(count_v1 - count_v2) / max(count_v1, count_v2)
```

Acceptable: < 20% relative difference. > 50% → flag as significant divergence.

### Dim 4 — db_sample overlap (the hardest)

Run both at LIMIT 10 for the same sort. Compute:

```
sample_overlap = |sample_v1.ids ∩ sample_v2.ids| / 10
```

Acceptable: ≥ 6 of 10 in both samples. Sample overlap is the strongest signal that "the two paths produce the same report" — same predicate, same top results.

### Dim 5 — Column choice agreement

```
columns_v1 = set(v1.columns.keys())
columns_v2 = set(v2.columns.keys())
column_jaccard = |intersection| / |union|
```

Acceptable: ≥ 0.7. Lower means the two paths are emphasizing different attributes — could be intent_signal threading working in v2 (a feature, not a bug).

### Dim 6 — Mode agreement (Phase 5)

| v1 outcome | v2 outcome | Verdict |
|---|---|---|
| Created (v1 always commits unless follow_up) | Mode A (proceed) | ✓ agree |
| follow_up | Mode D (vague) | ✓ agree |
| Created with results | Mode B (alternatives) | ⚠ v2 is stricter — investigate |
| Created with results | Mode C (fail) | ⚠ v2 fails where v1 ships — could be regression OR could be v2 catching what v1 missed |
| Failed / error | Mode A | ✗ v2 ships where v1 failed — investigate carefully |
| Created (success) | Mode B (looks_wrong) | ★ **v2 caught a silent ship** — record as a calibration win, NOT a regression |

The Mode B / G11-class cases are where v2 is *intentionally* different from v1. These are the architecture's whole point — sample_judge catching what v1 ships silently. **Count these as wins, not divergences.**

---

## Aggregated metrics

For a corpus of N queries, compute:

| Metric | Formula | Target |
|---|---|---|
| Report type agreement | `count(dim1 agreed) / N` | ≥ 95% |
| FilterSet field agreement (mean) | `mean(dim2 score across N)` | ≥ 0.80 |
| db_count proximity | `count(dim3 < 0.2 relative diff) / N` | ≥ 75% |
| db_sample overlap | `count(dim4 ≥ 6/10) / N` | ≥ 70% |
| Column Jaccard (mean) | `mean(dim5)` | ≥ 0.65 |
| Mode agreement | `count(dim6 ✓ or ★) / N` | ≥ 95% (strict ✓) or ≥ 90% (incl. ★ wins) |
| **G11/G02 noise catches by v2** | absolute count | as many as exist; each is a calibration win |

A **promotable** v2 hits all six green targets simultaneously over a sustained 2-week window. Anything red on the safety-net dimensions (mode agreement, noise catches) is a hard block.

---

## Run methodology (when actually executing)

### Setup
1. Pull a query stream — Mixpanel events from `nl_search` view + `tl reports create` CLI invocations + a parametrized golden set
2. Aim for ≥ 100 queries spanning all 4 modes + Mode B safety-net stress cases
3. Both paths must be wired to capture full outputs at each phase (v1 needs a "config-only mode" or DB-write-disabled mode)

### Concurrency
- Run sequentially per query is fine; avoids race conditions on shared resources
- Keep the gap between v1 and v2 run < 1 minute (so live data is consistent)
- Tag each captured pair with timestamp + query_id

### Storage
- One JSON file per query: `{ query, v1_config, v2_config, comparison_metrics }`
- Aggregate into a daily roll-up showing per-dim agreement trends

### Review cadence
- Daily: glance at totals; alert on regression in safety-net dim
- Weekly: human reviews the ⚠ cases — confirm whether v2 is improving on v1 or breaking
- End-of-window: aggregate report; promote-or-iterate decision

### Bypass for write paths
v2 in shadow-mode must NOT actually save reports — it only computes the would-be config. v1's save still fires (since the user expects their report to exist). Easy to enforce: v2's Phase 5 in shadow-mode is forced to "display-only" regardless of `TL_DATABASE_URI`.

---

## Expected divergences (so they're not surprises)

Based on M3–M6 architecture, here's where I expect v2 to **legitimately differ** from v1:

| Class | v1 behavior | v2 behavior | Verdict |
|---|---|---|---|
| **Substring noise queries (G11/G02 class)** | Ships silently with bad samples | Mode B alternatives | v2 wins |
| **Multi-topic queries with explicit AND** | OR-defaults silently | AND-inferred from query | v2 wins |
| **Sponsorship synonyms** ("partnership"/"promotion") | Misclassified to type 3 | Correctly routed to type 8 | v2 wins |
| **Narrow-result reports** (G03/G08 class) | Ships without warning | Mode A with narrow-result note | v2 has more transparent UX |
| **Off-taxonomy queries with weak match** | Force-fits to nearest topic | Phase 2b runs; explicit anti-overlap | v2 produces tighter keyword sets |
| **Vague queries** ("build me a report") | Server returns follow_up question | Mode D with same options | should agree |
| **Type 8 with Topic match** | Topic-as-keywords applied (incorrect) | Topic ignored for type 8 (correct) | v2 wins |
| **Date-scoped cross-references (G10)** | Server orchestration handles it | v2 emits multi_step_query action | should agree if both implementations match |

These divergences should be **expected and counted**. They're not regressions; they're the architectural improvements the v2 design baked in.

---

## What "M9 done" looks like

Specifically:
1. Eval corpus assembled (≥100 queries, ≥4 weeks of real production traffic)
2. Both paths run silently against every query for 2+ weeks
3. Aggregate metrics computed; all 6 dim targets green for the same window
4. G11/G02-class noise catches: ≥ 5 documented (proves the safety net is firing in production)
5. No silent regressions: zero cases where v2 ships where v1 failed cleanly
6. One human review per ⚠ case to confirm direction (v2 improving vs breaking)

When all six are green, M9 → M10 (promote).

---

## Why shadow-mode matters

v2 is the new path. It hasn't been battle-tested at production scale. Even with M1–M6's hand-rated rehearsals + M8's Judge calibration, real-user queries will surface edge cases the goldens didn't. Shadow-mode is the **catch-net for those**.

It also produces the corpus M7 wanted but couldn't pull: real Mixpanel queries, real outputs, real divergences. M9 effectively executes M7 *while* doing the validation, killing two milestones with one operation.

---

## Implementation notes (for whoever wires this up later)

- **v1 capture**: easy if `tl reports create` is still alive; just `--json` flag captures the config without saving. If the server endpoint is removed before M9 runs, this milestone needs an alternate v1 path (probably the legacy `orchestrate_preview.py` script run with `--dry-run`).
- **v2 capture**: skill orchestration in shadow-mode forces Phase 5 to display-only, then the orchestration captures all phase outputs into a single JSON.
- **Storage**: simple flat directory of JSON files is fine for ≤ 1000 captures; switch to a small DB (sqlite or Postgres) beyond that.
- **Comparison engine**: Python script with the per-dim functions above; output a daily roll-up CSV/JSON.
- **Slack integration**: optional — daily metric digest posted to `#ai-report-builder` channel during the run.

---

## Status / next

- ✅ **M9 methodology**: documented (this file)
- ⏳ **M9 actual run**: deferred — requires both paths running in production parallel mode + a 2-week measurement window. Not skill-construction work; it's deployment activity.
- ⏳ **M10**: promote — gated on M9 metrics being green
- ⏳ **M11**: sunset legacy v1 — gated on M10 sustained at 100% rollout

The skill is functionally complete after M8 Part 1. M9 forward is calibration + deployment, not construction. The remaining work is operational — better suited to actually shipping what we have than building more skill artifacts.
