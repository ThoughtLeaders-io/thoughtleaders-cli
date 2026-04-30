# AI Report Builder v2 — Visual Architecture

Quick-reference diagrams for the daily. Companion to `SKILL_ARCHITECTURE.md`.

---

## Diagram 1 — The big inversion: v1 → v2

```
╔══════════════════════════════════════════════════════════════════════════╗
║                          v1 — SERVER-ORCHESTRATED                        ║
╚══════════════════════════════════════════════════════════════════════════╝

    USER                       CLI                      SERVER
   ┌────┐    "build a       ┌────────┐   forwards    ┌──────────────┐
   │    │   report about ─> │   tl   │  prompt to ─> │ AI Report    │
   │    │      AI"          │ reports│               │ Builder      │
   │    │                   │ create │               │ pipeline     │
   │    │                   └────────┘               │ (Python      │
   │    │                                            │ scripts +    │
   │    │   ┌─────────────────────────────────────── │ server LLM)  │
   │    │   │              report URL              <─┤              │
   └────┘   │                                        └───────┬──────┘
            │                                                │
            │                                                ▼
            │                                       ┌──────────────┐
            │                                       │   Postgres   │
            │                                       │      ES      │
            │                                       │   Firebolt   │
            └─────────────────────────────────────> │              │
                                                    └──────────────┘
                                                    All AI work happens
                                                    on the server.

╔══════════════════════════════════════════════════════════════════════════╗
║                          v2 — CLIENT-ORCHESTRATED                        ║
╚══════════════════════════════════════════════════════════════════════════╝

    USER                       CLAUDE                       SERVER
   ┌────┐    `tl ask        ┌─────────────┐    raw SQL     ┌──────────────┐
   │    │   "build a    ─>  │  tl-report- │   tl db pg     │  tl db pg    │
   │    │   report          │  build      │   (sandboxed   │  endpoint    │
   │    │   about AI"`      │  skill      │    SELECT)  ─> │  (live!)     │
   │    │                   │             │                │              │
   │    │                   │  + prompts  │                └───────┬──────┘
   │    │                   │  + flow     │                        │
   │    │                   │             │                        ▼
   │    │   ┌── config ── <─│             │                ┌──────────────┐
   └────┘   │    JSON       │             │                │   Postgres   │
            │               │             │                │      ES      │
            ▼               │  Two LLM    │                │   Firebolt   │
       (review +            │  passes +   │                │              │
        ship via            │  validation │                └──────────────┘
        existing            │  via tl     │                Server: pure
        tl reports          │  db pg SQL  │                data plane.
        create)             └─────────────┘
                            All AI work happens
                            in the user's Claude.
```

**The key shift**: AI orchestration moves from server (v1) to client (v2). Server's role narrows to "give me data when I ask."

---

## Diagram 2 — What happens when the user types `tl ask "..."`

```
USER TYPES:  tl ask "build me a report about gaming channels with energy drink sponsorships"
                                              │
                                              ▼
                       ┌─────────────────────────────────────────┐
                       │   Claude loads tl-report-build SKILL    │
                       │   (matches description trigger)         │
                       └────────────────┬────────────────────────┘
                                        │
                                        ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 1 — Report Type Selection                                  │
   │   Claude infers: "this is a CONTENT or BRANDS report"            │
   │   Tool used: just reasoning, no CLI calls yet                    │
   └────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 2 — Filter Builder, Pass A    (LLM CALL #1)                │
   │                                                                  │
   │   ┌─ Topic Matcher: tl db pg "SELECT ... FROM thoughtleaders_   │
   │   │                  topics ORDER BY id LIMIT 100 OFFSET 0"      │
   │   │  Verdicts: "PC Games: strong, Beauty: none, ..."             │
   │   │                                                              │
   │   ├─ Schema discovery: tl db pg against                          │
   │   │                    information_schema.columns                │
   │   │                                                              │
   │   └─ Output: partial FilterSet                                   │
   │      { topics: [98], keywords: ["energy drink"],                 │
   │        report_type: BRANDS, channel_format: ... }                │
   └────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 3 — Validation Loop   (MANDATORY per David)                │
   │                                                                  │
   │   tl db pg --json "SELECT COUNT(*) FROM channels c               │
   │                    WHERE topics @> '[98]'                        │
   │                      AND ... LIMIT 1 OFFSET 0"                   │
   │   tl db pg --json "SELECT id, name, ... FROM channels c          │
   │                    WHERE ... ORDER BY id LIMIT 10 OFFSET 0"      │
   │                                                                  │
   │   ┌─────────────────┐                                            │
   │   │  count: 247     │  ✅ Reasonable count                       │
   │   │  sample: [...]  │  ✅ Sample looks relevant                  │
   │   └─────────────────┘                                            │
   │                                                                  │
   │   If count == 0 → loop back to Phase 2 with feedback             │
   │   If count > some threshold → ask Phase 2 to narrow              │
   │   Otherwise → proceed to Phase 4                                 │
   │                                                                  │
   │   Constraints respected:                                         │
   │   • mandatory LIMIT/OFFSET    • max 500 rows                     │
   │   • read-only SELECT           • no top-level UNION              │
   └────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 4 — Column/Widget Builder, Pass B   (LLM CALL #2)          │
   │                                                                  │
   │   ┌─ Reads: data/sortable_columns.json                           │
   │   ├─ Reads: tl db pg → information_schema (if cross-check needed)│
   │   │                                                              │
   │   └─ Output: complete report config                              │
   │      { ...filters from Phase 2,                                  │
   │        columns: [name, subscribers, deal_count, ...],            │
   │        widgets: [chart-of-deals-over-time, ...] }                │
   └────────────────────────────┬─────────────────────────────────────┘
                                │
                                ▼
   ┌──────────────────────────────────────────────────────────────────┐
   │ PHASE 5 — Display (prototype) / Save (later)                     │
   │                                                                  │
   │   Prototype:  Claude shows the JSON config to the user           │
   │   Later:      Auto-POSTs to /api/dashboard/campaigns/            │
   │                                                                  │
   │   User runs `tl reports create "..."` if they want to commit     │
   └──────────────────────────────────────────────────────────────────┘
```

**Two LLM calls, not one** — Pass A (filters) and Pass B (columns/widgets). Validation between them is required.

---

## Diagram 3 — Where things live (the boundary)

```
┌──────────────────────────────────────────────────────────────────────────┐
│                      tl-cli REPO (where the skill lives)                 │
│                                                                          │
│   tl-cli/skills/tl-report-build/                                         │
│   ├── SKILL.md                  ← orchestration logic (markdown)         │
│   ├── prompts/                                                           │
│   │   ├── topic_matcher.md      ← LLM Pass A: query → topic verdicts     │
│   │   ├── filter_builder.md     ← LLM Pass A: builds FilterSet           │
│   │   └── column_widget_builder.md  ← LLM Pass B: chooses display        │
│   ├── data/                                                              │
│   │   └── sortable_columns.json ← available column metadata              │
│   │                              (topics fetched LIVE via tl db pg SQL)  │
│   └── examples/                                                          │
│       └── golden_queries.md     ← hand-curated test queries              │
│                                                                          │
│                                  ▲                                       │
└──────────────────────────────────┼───────────────────────────────────────┘
                                   │
                                   │ talks via existing `tl` CLI
                                   │
                                   ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                  thoughtleaders REPO (the platform)                      │
│                                                                          │
│   ┌─────────────────────────────────────────────────────────────────┐    │
│   │             v2 SKILL USES ONLY THESE 3+1 COMMANDS:              │    │
│   │   - tl ask           → entry point (skill loader)               │    │
│   │   - tl db pg         → ★ raw SQL — LIVE in sandbox              │    │
│   │   - tl db es         → ES (super-user, coming soon)             │    │
│   │   - tl db fb         → Firebolt (super-user, coming soon)       │    │
│   │                                                                 │    │
│   │   (Higher-level commands like tl channels / brands /            │    │
│   │    describe / reports still exist for human users but           │    │
│   │    are EXCLUDED from the v2 skill surface — per the             │    │
│   │    2026-04-23 daily: they are "layers that duplicate            │    │
│   │    schema knowledge + joins on top of these primitives.")       │    │
│   └────────────────────────────────┬────────────────────────────────┘    │
│                                    │                                     │
│                                    ▼                                     │
│   ┌────────────────┐    ┌────────────────┐    ┌────────────────┐         │
│   │   PostgreSQL   │    │ Elasticsearch  │    │    Firebolt    │         │
│   │                │    │                │    │                │         │
│   │ Topics, Brands,│    │   Articles,    │    │  Time-series   │         │
│   │  AdLinks,      │    │   Channels     │    │  metrics       │         │
│   │  FilterSets,   │    │                │    │                │         │
│   │  Channels      │    │                │    │                │         │
│   └────────────────┘    └────────────────┘    └────────────────┘         │
└──────────────────────────────────────────────────────────────────────────┘

CLEAN SEAM: skill never imports platform code. Every cross-boundary call
is an explicit `tl` invocation. Skill can be rewritten without touching
platform code, and vice versa.
```

---

## Diagram 4 — The five-phase state machine

```
                    USER NL QUERY ("build me a report about X")
                              │
                              ▼
        ╔══════════════════════════════════════════╗
        ║  Phase 1 — Report Type Selection         ║
        ║          (lightweight inference)         ║
        ╚════════════════════╤═════════════════════╝
                             │
                             ▼
        ╔══════════════════════════════════════════╗
        ║  Phase 2 — Filter Builder, Pass A        ║
        ║                                          ║
        ║  ┌──────────────────────────────────┐    ║
        ║  │ Topic Matcher                    │    ║
        ║  │  tl db pg "SELECT ... FROM       │    ║
        ║  │   thoughtleaders_topics ..."     │    ║
        ║  │  → topic verdicts                │    ║
        ║  └─────────────┬────────────────────┘    ║
        ║                ▼                         ║
        ║  ┌──────────────────────────────────┐    ║
        ║  │ Schema Discovery                 │    ║
        ║  │  tl db pg →                      │    ║
        ║  │   information_schema.columns     │    ║
        ║  └─────────────┬────────────────────┘    ║
        ║                ▼                         ║
        ║  Builds partial FilterSet (filters only) ║
        ╚════════════════════╤═════════════════════╝
                             │
                             ▼
        ╔══════════════════════════════════════════╗
        ║  Phase 3 — Validation Loop ✓ (MANDATORY) ║
        ║                                          ║
        ║  tl db pg --json "SELECT COUNT(*) ..."   ║
        ║  tl db pg --json "SELECT ... LIMIT 10"   ║
        ║  → count + sample rows                   ║
        ║                                          ║
        ║  ┌─ count == 0   ──── retry Phase 2 ─┐   ║
        ║  ├─ count >> ok  ──── narrow filters ─┤  ║
        ║  └─ count ok     ──── proceed       ──┘  ║
        ║                                          ║
        ║  Cap: 3 retries                          ║
        ║  Constraints: LIMIT/OFFSET, ≤500 rows    ║
        ╚════════════════════╤═════════════════════╝
                             │
                             ▼
        ╔══════════════════════════════════════════╗
        ║  Phase 4 — Column/Widget Builder, Pass B ║
        ║                                          ║
        ║  reads data/sortable_columns.json        ║
        ║  + tl db pg → information_schema         ║
        ║    (if live cross-check needed)          ║
        ║                                          ║
        ║  Builds columns + widgets                ║
        ╚════════════════════╤═════════════════════╝
                             │
                             ▼
        ╔══════════════════════════════════════════╗
        ║  Phase 5 — Display (prototype)           ║
        ║          / Save (later)                  ║
        ║                                          ║
        ║  Prototype:  show JSON to user           ║
        ║  Later:      auto-POST                   ║
        ╚════════════════════╤═════════════════════╝
                             │
                             ▼
                     COMPLETE CONFIG
                     (filters + columns + widgets)
```

---

## Diagram 5 — The refinement pipeline (Creator / Judge / Coder)

```
   GOLDENS                    MIXPANEL CORPUS
   (~20 hand-curated     +    (~100 real user queries
    queries)                   from #ai-report-builder)
       │                            │
       └─────────────┬──────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │   CREATOR (the skill)    │
        │                          │
        │  Runs full skill flow    │
        │  on each query, produces │
        │  config JSON outputs     │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │   JUDGE (eval scorers)   │
        │                          │
        │  Assertions library:     │
        │  - FilterSet shape valid?│
        │  - count > 0?            │
        │  - columns match type?   │
        │  - keywords plausible?   │
        │                          │
        │  Per-query score + diag  │
        └────────────┬─────────────┘
                     │
                     ▼
        ┌──────────────────────────┐
        │   CODER (refines skill)  │
        │                          │
        │  Reads judge feedback,   │
        │  proposes prompt edits,  │
        │  flow tweaks, new tools  │
        └────────────┬─────────────┘
                     │
                     │  iterate
                     │  until metrics
                     │  hold on test set
                     │
                     ▼
              SHIPPABLE SKILL
              → calibration in prod-like env
              → eventually port to platform Python
```

This is the **offline dev tool** for getting the skill ready before any production rollout.

---

## Diagram 6 — Where we are on the roadmap

```
PAST                          NOW                         FUTURE
═══                           ═══                         ══════

#3928 (destructive            #3926 SHIPPED ✓             SKILL PROTOTYPE
 migration) SHIPPED ✓          to staging + prod            (tl-cli)
─────────────────             ───────────────             ────────────────
Topics table emptied;         10 pipeline-grounded         Build the v2
schema additions made;        topics live in prod           skill flow,
sequence pre-set to 95.       at IDs 96–105 with            milestones 1–6.
                              182 ES-validated
Topics table actively          keywords.                   (Skill rides on
migrating in prod                                          tl db pg — no
(fresh data 2026-04-27)       ┌─────────────────┐          new CLI work.)
                              │  PR #3937       │
                              │  in review      │          Then refinement
                              │  (channel-field │          pipeline
                              │  bypass fix)    │          (milestones 7–8).
                              └─────────────────┘
                                                            Then calibration
                              ┌─────────────────┐          in shadow mode
                              │ thoughtleaders- │          (milestone 9).
                              │ cli on PyPI ✓   │
                              │ tl db pg LIVE   │           Then promote +
                              │ in sandbox ✓    │           Python port
                              └─────────────────┘           (milestones 10–11).
```

---

## Diagram 7 — One-screen summary for the daily

```
┌─────────────────────────────────────────────────────────────┐
│   v2 AI Report Builder — at a glance                        │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   WHERE     tl-cli/skills/tl-report-build/                  │
│   HOW       Claude skill — ZERO new CLI cmds (tl db pg live)│
│   ENTRY     tl ask "<NL request>"                           │
│   DATA      tl db pg (raw SQL, sandboxed, read-only)        │
│                                                             │
│   FLOW                                                      │
│     1. Topic match (tl db pg → topics table)                │
│     2. Filter build   ── LLM Pass A                         │
│     3. Validate ✓      ── tl db pg COUNT/sample             │
│     4. Cols/widgets    ── LLM Pass B                        │
│     5. Display config  (later: auto-save)                   │
│                                                             │
│   WHY                                                       │
│     • Iterate in seconds, not PR cycles                     │
│     • Skill = prompts + flow; platform = pure data API      │
│     • Clean seam for eventual Python port                   │
│     • Aligns with David's "joins across stores" UVP         │
│                                                             │
│   FOUNDATIONS LIVE TODAY                                    │
│     • #3928 — schema + table cleared    ✓                   │
│     • #3926 — 10 topics seeded in prod  ✓                   │
│     • thoughtleaders-cli on PyPI        ✓                   │
│     • tl db pg in sandbox               ✓                   │
│     • #3937 — channel-field fix         ⏳ in review        │
│                                                             │
│   NEXT                                                      │
│     M1: scaffold + golden queries                           │
│     M2: topic matcher prompt (tl db pg)                     │
│     M3: filter builder prompt                               │
│     M4: validation loop (tl db pg COUNT/LIMIT)              │
│     M5: columns/widgets prompt                              │
│     M6: end-to-end output                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## How to use these in the daily

- **Diagram 7** (one-screen summary) — best for the opening "here's the plan"
- **Diagram 1** (v1 → v2 inversion) — best for explaining *why* this is a shift, not a feature
- **Diagram 2** (full request flow) — best for "what happens when a user types this"
- **Diagram 3** (boundary) — best for "what changes for the platform team vs. CLI team"
- **Diagram 6** (roadmap) — best for "what's done, what's next"

Pick what matches the audience's question.
