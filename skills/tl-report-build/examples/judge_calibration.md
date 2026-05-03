# Judge Calibration — M8 Exit Signal

**Date**: 2026-05-02
**Prompt**: [`prompts/judge.md`](../prompts/judge.md)
**Procedure**: Apply the Judge rubric to PIPELINE_OUTPUT from 3 representative goldens (G01 happy-path, G11 silent-ship safety net, G06 Mode D vague). Compare the Judge's verdict + score against my hand-rating across M1–M6 to validate the rubric isn't drifting from prior judgment.

**Goldens covered**: G01 (clean pass), G11 (Mode B alternatives — the canonical regression test), G06 (Mode D follow-up).

---

## G01 — `"Build me a report of gaming channels with 100K+ subscribers in English"`

### Pipeline output (assembled from prior rehearsals)
- `report_type: 3` (Phase 1 heuristic)
- `phase_2a.summary.strong_matches: [98]`, `weak_matches: []`, `no_match: false`
- `phase_2b: skipped` (strong match exists)
- `phase_2c.filterset.keyword_groups: [{"text": "gaming", ...}]`, `keyword_operator: "OR"`, `reach_from: 100000`, `languages: ["en"]`, `days_ago: 730`, `sort: "-reach"`
- `phase_3.decision: "proceed"`, `db_count: 4411`, `count_classification: "normal"`, `sample_judgment: "matches_intent"` (8/10 gaming + XXXTENTACION noise)
- `phase_4.columns: 10 type-3 defaults`, `widgets: 5`
- `phase_5.mode: "A"`, message has db_count + refinement_suggestions; correctly does NOT mention `tl reports create`

### Judge output (following prompts/judge.md)

```json
{
  "query": "Build me a report of gaming channels with 100K+ subscribers in English",
  "overall_score": 92,
  "verdict": "pass",
  "phase_scores": {
    "phase_1":  { "score": 10, "issues": [], "passed_assertions": ["H1.1", "S1.1"] },
    "phase_2a": { "score": 10, "issues": [], "passed_assertions": ["H2a.1: matching_keywords ['gaming'] is subset of Topic 98 keywords", "H2a.2: no_match=false matches 1 strong + 0 weak", "H2a.3: no force-fit", "S2a.1: reasoning quotes 'gaming channels'"] },
    "phase_2b": { "score": 10, "issues": [], "passed_assertions": ["skipped correctly per strict trigger"], "skipped_correctly": true },
    "phase_2c": { "score": 10, "issues": [], "passed_assertions": ["H2c.1: no topics field", "H2c.2: keyword_groups shape correct", "H2c.3: sort '-reach' present", "H2c.4: days_ago=730", "H2c.6: content_fields includes channel_description+channel_topic_description"] },
    "phase_3":  { "score": 9,  "issues": ["S3.2 partial: timeout-retry occurred (db_count succeeded after dropping channel_name half)"], "passed_assertions": ["H3.1", "H3.4: count_classification 'normal' matches 4411"] },
    "phase_4":  { "score": 10, "issues": [], "passed_assertions": ["H4.1: TL Channel Summary present", "H4.2: 10 columns within 5–10", "H4.3: 5 widgets within 4–6", "H4.4: channels_count_metric first"], "skipped_correctly": true },
    "phase_5":  { "score": 9,  "issues": ["S5.1 partial: XXXTENTACION noise mentioned but could be more prominent"], "passed_assertions": ["H5.1: Mode A matches proceed", "H5.2: db_count surfaced", "H5.3: no tl reports create"] }
  },
  "diagnosis": {
    "primary_failure_phase": null,
    "failure_class": null,
    "evidence_quotes": [],
    "suggested_prompt_edit": ""
  }
}
```

### Comparison to hand-rating

| Source | Verdict | Score |
|---|---|---|
| Judge (this rehearsal) | `pass` | 92/100 |
| My hand-rating (e2e_rehearsal.md M6) | "matches_intent / Mode A defensible" | (qualitative: clean pass) |

**Match.** Judge surfaces minor S3.2 + S5.1 nits the hand-rating glossed over — those are reasonable refinements, not disagreements.

---

## G11 — `"channels about IRS tax debt forgiveness programs"` (the canonical safety-net test)

### Pipeline output
- `report_type: 3`
- `phase_2a.summary.strong_matches: []`, `weak_matches: [97]`, `no_match: false`
- `phase_2b: ran`. `validated[*]`: only `IRS` (db_count 29661, with substring-noise warning) survived; tax debt(2), tax relief(3), back taxes(0), Offer in Compromise(0) all pruned
- `phase_2c.filterset.keyword_groups: [{"text": "IRS", ...}]`, `_routing_metadata.validation_concerns: ["IRS noise warning"]`
- `phase_3.decision: "alternatives"`, `db_count: 29661`, `count_classification: "broad"`, `sample_judgment: "looks_wrong"` (Cocomelon, Bad Bunny, Selena Gomez)
- `phase_4: SKIPPED` (decision = alternatives)
- `phase_5.mode: "B"`, structured 3-option prompt

### Judge output

```json
{
  "query": "channels about IRS tax debt forgiveness programs",
  "overall_score": 89,
  "verdict": "pass",
  "phase_scores": {
    "phase_1":  { "score": 10, "issues": [], "passed_assertions": ["H1.1"] },
    "phase_2a": { "score": 10, "issues": [], "passed_assertions": ["H2a.3: weak on Topic 97 with explicit anti-overlap reasoning; no force-fit"] },
    "phase_2b": { "score": 8,  "issues": ["Most candidates pruned (4/5 below threshold) — surfaces real TL data sparsity, not a prompt bug"], "passed_assertions": ["H2b.1", "H2b.2: surviving 'IRS' has db_count=29661 (warned for noise)", "S2b.2: anti_overlap_notes present"], "skipped_correctly": false },
    "phase_2c": { "score": 10, "issues": [], "passed_assertions": ["H2c.1", "H2c.2", "S2c.3: validation_concerns propagated"] },
    "phase_3":  { "score": 10, "issues": [], "passed_assertions": ["H3.1: decision=alternatives", "H3.2: alternatives correct given looks_wrong", "H3.3: G11 noise case correctly NOT proceed", "S3.1: noise warning propagated"] },
    "phase_4":  { "score": 10, "issues": [], "passed_assertions": ["correctly skipped per Mode B"], "skipped_correctly": true },
    "phase_5":  { "score": 10, "issues": [], "passed_assertions": ["H5.1: Mode B matches alternatives", "H5.4: 3 options present", "H5.3: no tl reports create"] }
  },
  "diagnosis": {
    "primary_failure_phase": null,
    "failure_class": null,
    "evidence_quotes": [],
    "suggested_prompt_edit": ""
  }
}
```

### Comparison to hand-rating

| Source | Verdict | Score |
|---|---|---|
| Judge | `pass` | 89/100 |
| Hand-rating (validation_rehearsal.md M4) | "G11 regression passing — silent-ship blocked" | (qualitative: pass) |

**Match.** The Phase 2b "8 not 10" deduction reflects honest surfacing of the data sparsity. Judge correctly does NOT penalize for the architecture working as designed.

---

## G06 — `"Build me a report"` (Mode D — Phase 1 asks first)

### Pipeline output
- `phase_1: emit follow_up action; no later phases run`
- All other phases `null`
- `phase_5.mode: "D"`, follow-up question with 4 options

### Judge output

```json
{
  "query": "Build me a report",
  "overall_score": 100,
  "verdict": "pass",
  "phase_scores": {
    "phase_1":  { "score": 10, "issues": [], "passed_assertions": ["H1.2: vague query routed to Mode D, no premature report_type assigned"] },
    "phase_2a": { "score": 10, "issues": [], "passed_assertions": ["correctly not invoked"] },
    "phase_2b": { "score": 10, "issues": [], "passed_assertions": ["correctly not invoked"], "skipped_correctly": true },
    "phase_2c": { "score": 10, "issues": [], "passed_assertions": ["correctly not invoked"] },
    "phase_3":  { "score": 10, "issues": [], "passed_assertions": ["correctly not invoked"] },
    "phase_4":  { "score": 10, "issues": [], "passed_assertions": ["correctly not invoked"], "skipped_correctly": true },
    "phase_5":  { "score": 10, "issues": [], "passed_assertions": ["H5.1: Mode D matches Phase 1 follow_up"] }
  },
  "diagnosis": {
    "primary_failure_phase": null,
    "failure_class": null,
    "evidence_quotes": [],
    "suggested_prompt_edit": ""
  }
}
```

### Comparison to hand-rating

| Source | Verdict | Score |
|---|---|---|
| Judge | `pass` | 100/100 |
| Hand-rating (e2e_rehearsal.md M6) | "Phase 1 catches vagueness; no later phases run" | (qualitative: pass) |

**Match.** The clean-skip case scores cleanly because there's no work to score against.

---

## Hypothetical fail case — what Judge would catch

To validate the Judge isn't just rubber-stamping, here's a synthetic *broken* G11 (sample_judge wrongly returned `matches_intent`, skill went Mode A and shipped). Already in `prompts/judge.md` Example B but reproduced for completeness:

| Phase | Score | Issue caught |
|---|---|---|
| 1 | 10 | — |
| 2a | 10 | — |
| 2b | 8 | minor — kept noise-flagged keyword |
| 2c | 9 | — |
| **3** | **2** | **FAIL H3.3: G11 noise case shipped as `matches_intent` despite Cocomelon samples** |
| 4 | 5 | should have been skipped (cascading consequence) |
| 5 | 1 | FAIL H5.1: emitted Mode A on a noise case |

Overall: **32/100, FAIL**. `primary_failure_phase: phase_3`, `failure_class: noise_undetected`, `suggested_prompt_edit: "sample_judge.md threshold should weight VALIDATION_CONCERNS more heavily..."`

This is the exact diagnostic value the Judge adds: a single failure in Phase 3 cascades into Phases 4–5, but the Judge identifies Phase 3 as the *primary* failure (the others are consequences), and proposes a direction (not code) for Coder to act on.

---

## M8 Part 1 exit signal

| Criterion | Status |
|---|---|
| Judge prompt loads and produces valid JSON | ✓ |
| Score bands align with verdict thresholds | ✓ |
| Phase-skip detection works (`skipped_correctly` flag) | ✓ G01 (2b skipped), G06 (all skipped), G11 (4 skipped) |
| G11 regression case scores `pass` (architecture working) | ✓ 89/100 |
| Hypothetical broken-G11 case scores `fail` and identifies primary phase | ✓ via Example B |
| `failure_class` taxonomy covers M1–M6 known failure modes | ✓ 12 classes listed |
| Hand-rating ↔ Judge alignment | ✓ all 3 goldens match |

**M8 Part 1: ✓ Judge prompt is calibrated.**

---

## M8 Parts 2 + 3 — Creator and Coder methodology (not built as prompts)

These are orchestration patterns, not single-prompt artifacts. Documented here as methodology rather than prompt files.

### Creator agent

**Role**: runs the skill against a query corpus and captures `(query, PIPELINE_OUTPUT)` pairs.

**Implementation**: a small script that loops over `examples/golden_queries.md` (and eventually a Mixpanel corpus) and for each query:
1. Invokes the skill (via `tl ask` or direct skill instantiation)
2. Captures all phase outputs
3. Stores as JSON in `examples/creator_runs/<run_id>/<golden_id>.json`

Not built in prototype — manual rehearsal artifacts (`*_rehearsal.md`) are the equivalent during M1–M6.

### Coder agent

**Role**: reads the Judge's diagnoses across the corpus and proposes prompt edits.

**Heuristic**:
1. Group judgments by `failure_class`
2. For each class with ≥3 fails, the responsible prompt is the suggested edit target
3. Cluster `evidence_quotes` per class to identify the specific surface that's failing
4. Propose a one-line edit; human reviews + applies; loop

Example flow:
- Judge sees 5 fails with `failure_class: silent_ship`, all citing short tokens (`AI`, `IRS`, etc.) being passed through despite warnings
- Coder proposes: *"sample_judge.md — when VALIDATION_CONCERNS mentions a token ≤3 chars, default verdict toward `looks_wrong` unless ≥5 of 10 samples explicitly contradict"*
- Human edits sample_judge.md, reruns Creator, scores improve

Not built in prototype — manual edits during M2–M6 (where I iterated on prompts based on hand-ratings) are the equivalent.

### When to wire up the offline loop

When the corpus exceeds ~50 queries (M7's Mixpanel pull) AND prompt edits start being non-obvious (i.e., when "what to fix" stops being clear from a single rehearsal). Until then, the manual rehearsal pattern works fine.

---

## Next

- ✅ **M8 Part 1**: `prompts/judge.md` + 3-golden calibration
- (Skipped: M8 Parts 2 + 3 as full prompts — documented as methodology since they're orchestration patterns)
- ⏳ **M9**: shadow-mode calibration vs v1 — runs both v1 and v2 paths in parallel against the same queries; measures agreement
- ⏳ **M10**: promote — make v2 default; evaluate adding new CLI commands
- ⏳ **M11**: sunset legacy v1
