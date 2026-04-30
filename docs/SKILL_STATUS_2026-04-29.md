# AI Report Builder v2 — Status Snapshot

**As of 2026-04-29 (Wed) · Owner: Arik Aviv (per 2026-04-23 daily) · Companion to [SKILL_ARCHITECTURE.md](SKILL_ARCHITECTURE.md) and [SKILL_VISUAL_ARCHITECTURE.md](SKILL_VISUAL_ARCHITECTURE.md)**

This is a one-screen "where are we today." For the full architecture, read the companion docs.

---

## 1. Live foundations (verified against prod)

### Topics table — verified live just now via `tl-data` skill
```sql
-- python scripts/pg_query.py "SELECT ... FROM thoughtleaders_topics ORDER BY id"
```

| ID  | Name                      | Source               | Keyword count | Created (UTC)            |
|-----|---------------------------|----------------------|---------------|--------------------------|
| 96  | Artificial Intelligence   | pipeline_analysis_v1 | 17            | 2026-04-28 05:52:23      |
| 97  | Personal Investing        | pipeline_analysis_v1 | 18            | 2026-04-28 05:52:23      |
| 98  | PC Games                  | pipeline_analysis_v1 | 18            | 2026-04-28 05:52:23      |
| 99  | Cooking                   | pipeline_analysis_v1 | 18            | 2026-04-28 05:52:23      |
| 100 | Wellness                  | pipeline_analysis_v1 | 21            | 2026-04-28 05:52:23      |
| 101 | Computing                 | pipeline_analysis_v1 | 19            | 2026-04-28 05:52:23      |
| 102 | History                   | pipeline_analysis_v1 | 18            | 2026-04-28 05:52:23      |
| 103 | Political Issues & policy | pipeline_analysis_v1 | 17            | 2026-04-28 05:52:23      |
| 104 | Beauty                    | pipeline_analysis_v1 | 17            | 2026-04-28 05:52:23      |
| 105 | Travel Locations          | pipeline_analysis_v1 | 19            | 2026-04-28 05:52:23      |

**Total: 10 topics, 182 keywords. Matches the doc. Note**: the prior memory said "fresh data 2026-04-27" — actual `created_at` is **2026-04-28 05:52 UTC** (which is 04-28 08:52 IDT, mid-morning). Minor — calling it out so timeline references are precise.

### Schema (`information_schema.columns`)
```
id           integer                  NOT NULL
created_at   timestamp with time zone NOT NULL
updated_at   timestamp with time zone NOT NULL
name         varchar                  NOT NULL
keywords     jsonb                    NULL
description  varchar                  NULL
source       varchar                  NULL
```
Keywords is a JSONB array of strings. Use `jsonb_array_length(keywords)` for counts; `jsonb_array_elements_text(keywords)` to unnest.

### Sample (Topic 96 — AI)
- **Description**: "AI tools, machine learning, generative models, LLMs, and AI-assisted software. Includes generative AI, AI agents, and emerging AI tooling — currently a leading-edge category with growing creator-side coverage but limited advertiser-side evidence in our current pipeline."
- **Keywords**: `artificial intelligence`, `AI tools`, `machine learning`, `LLM`, `AI coding`, `AI video editor`, `AI agent`, `prompt engineering`, `generative AI`, `AI assistant`, `AI automation`, `AI startups`, `ChatGPT tutorial`, `Claude AI`, `AI agents for coding`, `AI tools for creators`, `best AI tools` (17)

This is exactly what the matcher needs to read at the start of every query.

---

## 2. CLI status

| Surface | Status | Notes |
|---|---|---|
| `thoughtleaders-cli` on PyPI | ✓ v0.6.2 published | `pip install thoughtleaders-cli` |
| Local install (Nerya's machine) | ✓ **v0.6.2 (upgraded 2026-04-29)** | `tl db pg` working end-to-end, verified live. |
| `tl db pg` (raw SQL endpoint) | ✓ **Live in sandbox; verified locally** | Returns `{"results": [...]}` envelope (skill orchestration extracts `.results`). |
| `tl db es` / `tl db fb` | Pending | Super-user only initially per 2026-04-29 plan. |
| `tl ask` | ✓ live | Skill entry point. |
| `tl describe show <resource>` | ✓ live | **Excluded from v2 skill surface** (per 2026-04-23 daily — duplicative of raw SQL). |
| `tl channels` / `uploads` / `sponsorships` / `brands` | ✓ live | **Excluded from v2 skill surface** (same reason). |
| `tl reports create / run` | ✓ live | Used by humans for save; v2 skill displays JSON during prototype. |

---

## 3. Data plane — primary vs fallback

The architecture's data plane is `tl db pg` raw SQL. **As of 2026-04-29 v0.6.2 is installed locally and `tl db pg` works end-to-end.** The `tl-data` skill's `pg_query.py` is now a *fallback* (for users without sandbox access), not the primary path.

| Concern | Primary (tl-cli ≥ v0.6.2) | Fallback (no sandbox access) |
|---|---|---|
| Topics fetch | `tl db pg --json "SELECT ... FROM thoughtleaders_topics ... LIMIT 100 OFFSET 0"` | `python scripts/pg_query.py "..."` |
| Validation `db_count` | `tl db pg --json "SELECT COUNT(*) ... LIMIT 1 OFFSET 0"` | `python scripts/pg_query.py "..."` |
| Validation `db_sample` | `tl db pg --json "SELECT ... LIMIT 10 OFFSET 0"` | `python scripts/pg_query.py "..."` |
| Auth | Same as `tl whoami` | Local env: `TL_DATABASE_URI` |
| Sandbox constraints | `LIMIT/OFFSET` mandatory, ≤500 rows, forbidden-functions list | None enforced (skill self-enforces) |
| Output | JSON envelope `{"results": [...]}` (orchestration extracts `.results`) | Bare array `[...]` |

**Migration is done.** The skill orchestration uses `tl db pg` as primary; `pg_query.py` retained as a documented fallback for users who lack sandbox access.

**Key discipline:** write SQL as if all constraints applied (mandatory `LIMIT n OFFSET m`, no top-level `UNION`, no forbidden functions) so primary and fallback paths produce identical results.

---

## 4. What's unblocked right now

Everything needed to start Milestone 1 (skill scaffolding) is in place today:

- ✓ Topics table populated, queryable
- ✓ DB access via `tl-data` skill works
- ✓ `tl ask` exists as the entry point
- ✓ `information_schema.columns` accessible via `tl db pg` / `pg_query.py` for schema discovery (replaces `tl describe show`, which is excluded from the v2 surface)
- ✓ `evals/topics/seed_topics_v1.json` (audit trail) is at `~/Desktop/ThoughtLeader/thoughtleaders/evals/topics/`
- ✓ `sortable_columns.json` exists in `thoughtleaders/.claude/skills/create-report/data/`
- ✓ `tl-cli/skills/` directory structure exists (currently holds the `tl` data-analyst skill)
- ✓ Architecture doc + visual companion finalized

**Conclusion:** the skill prototype can start today. No platform-side blockers.

---

## 5. What's blocked (and on whom)

| Blocker | Owner | ETA / signal |
|---|---|---|
| Broader `tl db pg` rollout (so users beyond the dev sandbox can use the skill end-to-end) | Pepa | After Ivan's CLI green-light review — already given per 2026-04-28 Slack |
| Server-side `tl db pg` issues (NaN, numeric float precision, timezone) | Ivan | None of these block the skill's read paths; tracked in `db-pg-server-issues.md` |
| `tl db es` / `tl db fb` super-user enable | Ivan | Sequential after `tl db pg` stabilizes |
| PR #3937 (channel-field bypass) | Existing review | Independent; doesn't block skill prototype |

Nothing on this list blocks Milestones 1–6 of the skill prototype.

---

## 6. Immediate next steps (this week)

In dependency order. Each is a small, scoped chunk.

1. **Scaffold `tl-cli/skills/tl-report-build/`** (Milestone 1)
   - `SKILL.md` stub with the five-phase flow + trigger description
   - `data/sortable_columns.json` copied from TL repo
   - `examples/golden_queries.md` — start with 5–10 hand-curated queries from #ai-report-builder Slack history; expand later
   - **No `data/topics_*.json` file** — fetch live every invocation
2. **Write `prompts/topic_matcher.md`** (Milestone 2)
   - Inputs: NL query + live topics array (from `pg_query.py` for now)
   - Output: per-topic verdict JSON (`strong`/`weak`/`none` + reasoning + matching keywords)
3. **Hand-test the matcher** against the golden queries; iterate on the prompt
4. **Migration prep**: write the SQL with `LIMIT/OFFSET` + forbidden-function compliance from day one — so the `pg_query.py` → `tl db pg` swap is a one-line change later

Defer everything past Milestone 2 until step 3 produces ≥80% defensible verdicts on the goldens.

---

## 7. Open architectural questions (still unresolved)

These were flagged in the architecture doc and remain open:

1. **Skill state across phases** — runtime memory? scratch table? session store?
2. **Multi-topic disambiguation** — "AI cooking shows" → both AI and Cooking; how does the matcher resolve overlap?
3. **Clarification vs assume** — when to ask the user vs make a best guess?
4. **IAB taxonomy fit** — is it a coarser navigation layer, or out of scope?
5. **Eval-file access** — does the skill ship with read access to `seed_topics_v1.json` (richer per-topic context) or only the DB?

None of these block Milestones 1–2; they get answered as the prompts mature.

---

## 8. Diff against earlier doc revisions

| When | Change |
|---|---|
| 2026-04-28 (initial) | Snapshot file `data/topics_v1.json`, no new CLI |
| 2026-04-29 morning | Replaced snapshot with `tl topics list --json` (new wrapper subcommand) |
| 2026-04-29 (now) | Replaced wrapper with `tl db pg` raw SQL (zero new subcommands; aligns with David's "joins across stores" UVP). Interim path: `tl-data` skill's `pg_query.py` until `tl db pg` rolls out broadly. |

The data plane has narrowed twice and is now at "use the existing primitives, write SQL." That's the resting place.

---

## 9. References (live & verified)

- **Companion docs (this repo)**: [SKILL_ARCHITECTURE.md](SKILL_ARCHITECTURE.md), [SKILL_VISUAL_ARCHITECTURE.md](SKILL_VISUAL_ARCHITECTURE.md)
- **`tl-data` skill** (interim DB transport): `~/Desktop/ThoughtLeader/thoughtleaders-skills/tl-data/SKILL.md`
- **TL repo evidence**: `~/Desktop/ThoughtLeader/thoughtleaders/evals/topics/{seed_topics_v1.json, METHODOLOGY_v2.md, V2_FINDINGS.md, brand_verdicts/}`
- **CLI on PyPI**: https://pypi.org/project/thoughtleaders-cli/
- **Slack thread context**: #r&d 2026-04-28 (Pepa: PyPI live), 2026-04-29 (Pepa: PgSQL working; Ivan: green light)
- **Daily Gemini notes (last week)**:
  - 2026-04-23 — David's "joins across stores" UVP framing; Arik owns "Develop Report Flow"
  - 2026-04-28 — DB views structure, RLS strategy, skill governance
  - 2026-04-29 — PgSQL deployment, monitoring setup, metering plan
