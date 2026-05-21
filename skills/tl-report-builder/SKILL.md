---
name: tl-report-builder
description: |
  Build TL reports from natural-language requests. Produces an in-chat preview (sample-rows table + filter summary + takeaways) by default, or auto-saves a TL report when the user's wording is explicit about it ("save", "create the report", "make a campaign for me to come back to"). Covers the four report types: content/videos (1), brands (2), channels (3), sponsorships/deals (8).

  Triggers on every variant of "list me / find me / show me / give me / pull me / build me / make me X with filters Y", including:
  - **Channels**: "Find me gaming channels with 100K+ subs", "show me TPP fintech creators in MSN", "channels we haven't pitched to <brand>", "look-alike channels to X", "non-MSN travel channels", "build me a list of <niche> creators", "channels matching <criteria>".
  - **Brands**: "all brands flagged as Managed Services", "brand activity report for these specific brands: ...", "brands sponsoring <channel> in the past 6 months", "competitor brands of X".
  - **Sponsorships / deals**: "**show me partnerships from last quarter** for <niche> creators", "Q1 2026 sold sponsorships for personal investing", "all proposal_approved deals owned by <user>", "list sponsorships with status sold and send_date 2026-05-07", "sponsorships for channel <name>".
  - **Videos / uploads**: "videos sponsored by <brand>", "wellness videos but exclude anything sponsored by Nike or Adidas".

  Save-intent variants ("save a campaign of …", "create the report …", "make a TL report for …") trigger auto-save; everything else previews. Off-taxonomy keywords ("crypto / Web3"), brand-exclusion logic ("not pitched to X"), demographic floors ("US audience ≥30%"), TPP/MSN scoping, and competitive-pitch shapes are all this skill's job — not the general `tl-cli:tl` data-analyst skill.

  **Post-save refinements default to ASKING** — when the user's follow-up arrives after a successful save AND the topic overlaps with the prior save (same brand / niche / report type), the skill MUST surface the choice between updating the existing report, saving a separate variant, or treating as a fresh save. Refinement vocabulary (*instead*, *change*, *add*, *limit*, *only*, *filter*, *make it X*, etc.) strengthens the trigger but its absence does NOT bypass it — topic overlap alone is enough to ask. Do NOT auto-create a new report on every refinement-shaped prompt in a session. **Note**: the CLI edit endpoint can only patch campaign-level fields (title, description, columns, widgets, etc.); FilterSet changes (keywords, filters, demographics, cross-references) cannot be updated in place — those route to "save as a new variant" instead. See "Editing a saved report" in the body for the routing decision table + mechanics.

  **Skip this skill** for:
  - counts, metrics, trends, single-record show-by-ID lookups, raw exploratory queries, or analytical questions that aren't shaped as "give me a list" → route to `tl-cli:tl`.
  - **explicit intent to import a list of identifiers into a report — existing or new.** The routing test is the **user's import intent**, NOT the mere presence of a list. A user can paste 50 channel URLs and want analysis, comparison, similar-channel discovery, or filtered lookup — those still belong here (or in `tl-cli:tl`), not in tl-import. They can also paste 50 URLs and want exactly those channels to land in a report as-given — that is import, route to `tl-cli:tl-import`. The deciding question: *"Would the user be satisfied if the listed entities simply ended up as the report's contents exactly as-given, no transformation?"* If yes → import intent → `tl-cli:tl-import`. If they expect filtering, analysis, similarity expansion, or any other transformation on top of the list → it's not import, keep it here.

    Concrete phrasings that route to `tl-cli:tl-import` (intent: import + list = report contents): *"import these channels into report 1234"*, *"add these brands to campaign 5678"*, *"create a new report with these channels: <list>"*, *"build me a campaign from these adlinks: <list>"*, *"make a report containing these uploads: <list>"*.

    Phrasings that **stay here** even with a list attached (intent: discovery / analysis using the list as input, not as the answer): *"find me channels similar to these: <list>"*, *"build a report of TPP channels in the same niche as these: <list>"*, *"show me which of these have sponsored fintech brands"*, *"compare engagement across these channels"*.

    If you find yourself about to resolve a URL/handle to a channel ID *as the deliverable* (no analysis, no filtering, no discovery on top), stop and hand off — that's the import shape.
---

# TL Report Builder Skill

Translate natural-language report requests into the campaign config JSON the TL dashboard accepts (a `Campaign` + `FilterSet` payload, ready to commit). The skill owns the orchestration end-to-end; sub-tools are invoked conditionally from within the Schema phase based on explicit criteria. Every phase may pause for follow-up interaction with the user when input is ambiguous, incomplete, or invalid.

## Core Objective

Produce two artifacts on every successful run:

1. **A valid campaign config JSON** matching the platform's `dashboard.models.Campaign` + `dashboard.models.FilterSet` schemas. Ready to be POSTed to the report-creation API endpoint (and PUT for subsequent edits); the skill itself never writes to the database directly.
2. **A short list of key takeaway insights** about the resulting dataset — db_count, count_classification, top sample channels/deals, noise warnings, narrow-result notes, tool-output flags worth surfacing, and any unresolved follow-ups the user should know about.

## Architecture & Separation of Concerns

```
tl-report-builder/
├── SKILL.md          ← this file: orchestrates the 4 phases; defines tool-invocation criteria; describes follow-up rules
├── references/       ← supporting schemas, column definitions, glossaries — consumed by the phases
└── tools/            ← conditional executable markdown files; invoked from inside Phase 2 only when criteria fire
```

- **Scripts (the four phases) are deterministic functions as much as possible.** Each phase has a defined input contract, output contract, and a small set of decision rules. LLM judgment is reserved for cases where the input genuinely warrants it.
- **`references/` is the single source of truth** for schemas (filterset shape per report type) and column definitions. Phases consume them; phases don't duplicate or override them.
- **`tools/` are optional enrichments**, not phases. They live separately so they can be added or removed without touching the phase orchestration.

## User-facing language (READ FIRST)

Internally this skill thinks in phases (1–4), report types (1, 2, 3, 8), tool names (`name_resolver`, `keyword_research`, `sample_judge`, `database_query`, etc.), and decision enums (`looks_wrong`, `proceed`, `alternatives`). **None of these terms appear in messages the user sees** — not in chat narration, not in follow-up prompts, not in takeaways, not in error messages. The user is a TL operator, not a skill maintainer; jargon leaks make the tool feel broken.

**Forbidden in user-facing text** (chat narration, follow-up prompts, takeaways, Mode-B/C messages, error messages):
- Phase numbers (`Phase 1`, `Phase 2`, `Phase 2b`, `Phase 3`, `Phase 4`, internal step labels like `Step 2.V4`).
- Report-type numbers (`Type 1`, `Type 3`, `Type 8`) — say "channels report", "deals report", etc.
- Identifier-shaped names from `tools/` and `references/` — anything that reads like a code symbol (the `snake_case` tool / step / metadata names defined in this skill, the JSON keys you see in `references/*_schema.json`, internal data-layer model names). If a term reads like a programmer typed it, it doesn't belong in front of the user.
- JSON-y decision codes and classification codes the user has no reason to recognize (verdict strings emitted from validation, count-bucket labels emitted alongside them — anything that's a literal value in the validation output JSON).
- **Internal mechanism phrases** that describe HOW the skill works rather than WHAT the user is getting. Forbidden examples (verbatim regression markers — never say any of these to the user):
  - *"held in working memory"*
  - *"per the skill's rules"*
  - *"in working memory"*
  - *"the campaign config (held in working memory; not echoed to chat per the skill's rules)"*
  - *"campaign config JSON"* / *"the config"* / *"the JSON"* — when describing what the report contains, name the FILTERS, not the storage shape
  - *"per the policy"* / *"the orchestration"* / *"the FilterSet"*
  - **`Campaign` / `Campaign #N` / `campaign_id`** — these are Django model jargon. The TL platform calls these **reports**. Always say "**TL report**" / "**report #N**" / "**report id**" in user-facing text (chat replies, save-success messages, the save tail). The internal data model is named `Campaign` for historical reasons; the user has never heard that name. *"Report saved. … (Campaign #23801)"* is a leak — write *"TL report saved. … (report #23801)"* instead.
  - **`reach` / "by reach" / "Reach"** — internal SQL column name. The user-facing term is **subscribers** (canonical mapping lives in `thoughtleaders-skills/tl-data/references/business-glossary.md`: *"AMs say subscribers, SQL says reach"*). Use `reach_from` / `reach_to` when emitting the FilterSet, but **always narrate as "subscribers"** — in sample-table column headers ("Subscribers", not "Reach"), in distribution stats ("By subscribers: 1M+ → 2", not "By reach: …"), in filter summaries ("only channels with 100K+ subscribers"), in takeaways. *"By reach: 1M+ → 2 · 100K–1M → 57 · 10K–100K → 128"* is a leak.
  - **Raw internal IDs appended to names in sample-table rows** — e.g. `"Crypto Journey (id 1178513)"`, `"Altcoin Daily (id 28151)"`, `"FRÉ Skincare (brand_id 14625)"`. The numeric ID is implementation detail; the user is browsing channels/brands by name, not by primary key. **Show the name only**, hyperlinked per rule 20a (`[Crypto Journey](https://app.thoughtleaders.io/youtube/crypto-journey)`). The Markdown link is the addressable identifier — no raw ID needed alongside it. **Exception**: include the ID inline only when the user explicitly asked for it (*"give me the IDs too"*, *"include channel IDs"*) or when there's a real disambiguation case (two same-named channels in the sample). Otherwise the parenthetical `(id N)` is noise. *"Crypto Journey (id 1178513)"* in a normal sample row is a leak; write *"[Crypto Journey](https://app.thoughtleaders.io/youtube/crypto-journey)"*.

  These are internal terms from this SKILL.md. They describe the skill's own implementation, not the user's report. If you find yourself about to type any of these, stop and re-write the sentence as a plain-English summary of what the report does (see "Filter summary" pattern below).

**Filter summary pattern** — when narrating WHAT the report (saved or previewed) actually contains, use **outcome-focused plain English**, not "the config". Translate each filter into a sentence describing what the user will see:

| Internal field | User-facing summary phrasing |
|---|---|
| `topics: [98]` | "results will be focused on the gaming/PC games topic" |
| `keywords` / `keyword_groups[]` | "results will be filtered to channels mentioning <keywords>" |
| `reach_from: 100000` | "only channels with 100K+ subscribers will be included" |
| `languages: ["en"]` | "only English-speaking channels will be included" |
| `creator_countries: ["US"]` | "results will be limited to US creators" |
| `min_demographic_usa_share: 50` | "only channels with strong US audiences will be included" |
| `channel_formats: [4]` | "only YouTube long-form video channels will be included" (omit if it's the default) |
| `msn_channels_only: true` | "results will be limited to MSN channels" |
| `is_tl_channel = TRUE` (resolved into `channels` M2M) | "results will be limited to TPP channels" |
| `outreach_email: "exists"` | "only outreach-ready creators (with email on file) will be included" |
| `tl_sponsorships_only: true` | "results will prioritise creators with proven TL sponsorship history" |
| `cross_references[].exclude_proposed_to_brand: ["Webull"]` | "channels already pitched to Webull will automatically be excluded" |
| `cross_references[].include_sponsored_by_mbn` | "results will be limited to creators MBN brands are working with" |
| `sort: "-reach"` | "results will be sorted by largest subscriber count first" |
| `sort: "-mentions_count"` | "results will be sorted by strongest sponsorship performance" |
| `start_date` / `end_date` / `days_ago` | "results will cover <date range / last N days>" |
| `columns: { ... }` (the chosen column set) | "outreach-ready columns will be included automatically" — don't list them by code-name; describe the focus (outreach / discovery / pricing / pipeline) |
| `widgets: [...]` | "performance widgets will be added automatically" — describe the focus, not the aggregator names |

Compose 4–7 of these into a short bulleted summary directly in chat. Use the user's own brand and keyword wording verbatim where possible. Don't list every filter — only the ones that meaningfully shape what the user will see.

**Allowed**: specific channel / brand / video / advertiser names from the data, the user's own keywords, plain words like "results", "matches", "sample", "noise", "filter", "search", "report", "column", "chart". Plain-English words that happen to coincide with an internal label *as English* (e.g. "the result is narrow", "a normal-size result") are fine — the test is whether the user reads it as English or as a code symbol. The same word as `count_classification: "narrow"` is forbidden; in "the result is narrow" it's fine.

**Plain-English narration map** (use these phrasings — vary the wording, but never say the left column out loud):

| Internal step | User-facing narration (examples) |
|---|---|
| Phase 1 (Report Type) | "Looks like you want a channels report — creators to reach out to." / "I'll set this up as a deals report." |
| Phase 2 — name resolution (T4) | "Looking up investing.com in the brand list…" / "Resolving the brand name…" |
| Phase 2 — schema build | "Building the search filters…" / "Setting up the search…" |
| Phase 2 — keyword research | "Working out the right keywords for this niche…" |
| Phase 2 — topic matcher | "Checking which TL topics this falls under…" |
| Phase 2 — cross-reference | "Pulling the list of channels we've already pitched to investing.com…" |
| Phase 2 — db_count check | "Quick check on how many results this matches…" / "Running a count to size the result…" |
| Phase 2 — db_sample + sample_judge | "Sampling the top matches to make sure they look right for what you asked…" |
| Phase 3 — column builder | "Picking which columns to show in the report…" |
| Phase 4 — widget builder | "Choosing the charts and dashboards…" |
| Phase 4 — final composition | "Putting the final report together…" |
| Preview path (default) — show takeaways + sample table | "Here's what matches…" / "Found N channels — top by reach:" / "Top videos that match:" |
| Preview tail (ambiguous middle — close with this) | *"If you want this saved as a TL report you can come back to, say save."* |
| Save step (resolve portable temp path → write JSON → verify file exists → `tl reports create --config-file <path> --yes`) | "Saving the report…" |
| Save success (only after the CLI command returns success) | "**TL report saved.**" + link from the CLI response, optionally with "(report #N)" using the campaign_id rendered as a *report* number — never as "Campaign #N". Do NOT echo the JSON config back; do NOT say "saved as <path>.json" (temp file is transport, not the deliverable); do NOT say "Campaign #..." (Django model jargon — say "report"). |
| Save failure | "Couldn't save the report: <plain-English reason>" — surface the CLI's stderr verbatim if it's user-readable, otherwise summarise |
| User says "save" / "yes save it" / "save it" after a preview | "Saving…" — re-use the config from working memory; do NOT re-run Phases 1–4 |
| Mode B follow-up (looks_wrong) | "The top results don't look right — here are your options…" |
| Mode C (1 retry exhausted on empty/too_broad; data shape genuinely doesn't fit) | "I couldn't build a sensible result for this — here's what I tried…" |

**Report-type → user-facing label**:

| Internal | User-facing label |
|---|---|
| 1 (CONTENT) | "videos report" / "content report" |
| 2 (BRANDS) | "brands report" |
| 3 (CHANNELS) | "channels report" |
| 8 (SPONSORSHIPS) | "deals report" / "sponsorships report" |

Narrate like a colleague describing what they're doing — not like a logger announcing which step in the spec is firing. "Looking up investing.com…" beats "Phase 2 setup: I need to resolve `investing.com` to an internal identifier first." Every phase-number / identifier-shaped-name leak is a bug.

**Talk TO the user, not ABOUT them.** Second person, not third person. ❌ "The user wants channels for outreach." ✅ "You want channels for outreach — got it." Or just describe what you're doing without referring to the user at all.

### Narration shape — leaky vs clean

A save-mode run for *"Create a campaign of investing channels we haven't pitched to investing.com"* shows the gap between leaky and clean narration. Both describe the SAME execution; only the surface differs.

❌ **Leaky** (phase numbers, type numbers, identifier-shaped names, third-person framing):
> "I'll work through this as a TL outreach campaign... **Phase 1 — Report Type: Type 3 (CHANNELS)**. The user wants channels for outreach... **Phase 2 setup**: I need to resolve "investing.com" to a `[platform-id-name]`... Now composing the final campaign config. **Phase 3 (columns)** — outreach intent. **Phase 4 (widgets)** — Type 3 standard set."

✅ **Clean** (plain English, no leaks, second person):
> "I'll set this up as a channels report — creators for outreach, with anyone already pitched to investing.com filtered out. Looking up investing.com... **Found it.** Pulling channels pitched in the last year so I can exclude them. **668 already pitched** — out. **1,838 unpitched investing channels**, 9 of 10 in the spot-check are on-target — Pushkar Raj Thakur, Mark Tilbury, warikoo, Pranjal Kamra. Putting it together now (outreach-focused columns + standard charts). *(saving…)* **TL report saved.** [Investing channels](https://app.thoughtleaders.io/...) (report #12345)."

What's preserved (brand resolution outcome, real exclusion count, noise example with specific names, reasoning, sample names, saved-report link, takeaways) vs stripped (every phase number, type number, identifier-shaped name, "The user wants…", raw IDs, the campaign-config JSON itself — that lives in the portable-temp transport file, never the chat). Clean is also *more informative* — describes what's happening to the data, not which step in the spec is firing.

The same shape applies to **preview mode** (no save intent): same Phase 1-4 execution, but the reply ends with the sample-rows table + takeaways + save tail instead of the saved-report URL. If the user replies *"yes save it"* / *"save"* → run the save step using the **same config that's already in working memory**; don't re-run Phases 1-4.

### Editing a saved report (post-save refinement flow)

When the user's follow-up after a successful save is a **refinement** of the report we just created — *"change X to Y"*, *"use Z instead"*, *"add an A column"*, *"sort by last published"*, *"rename the report"* — the right response depends on **what** the user wants to change. The CLI edit endpoint accepts only a narrow set of fields; FilterSet changes need a different path.

**What `tl reports update` CAN edit today** (campaign-level fields only):

- `title`, `description`, `report_type`, `type`
- `columns`, `widgets`, `histogram_bucket_size`
- `emoji`, `display_mode`
- `owner`, `subscribers`, `link`
- `webhook_url`, `notifications_on`, `message_template`

**What `tl reports update` does NOT edit** (the backend explicitly rejects these — `CliReportEditView` docstring: *"Filterset edits are not supported here"*):

- `filterset` and any of its fields (`keywords`, `keyword_groups`, `channels`, `brands`, `start_date`, `end_date`, `days_ago`, `msn_channels_only`, `creator_countries`, etc.)
- `filters_json` (the catch-all containing `publish_status`, `ad_publish_status`, etc.)
- `cross_references`

The backend's `_reject_unknown_fields` validation is **atomic** — if the update payload contains any unsupported key (e.g. `filterset`), the WHOLE request returns HTTP 400, including any legitimate field edits in the same payload. The skill must therefore send ONLY editable fields in the patch, never the full working-memory config.

**Routing decision** — what kind of refinement the user is asking for:

| User wants to change | Editable via `tl reports update`? | Skill's action |
|---|---|---|
| Title, description, emoji, display mode | ✅ Yes | Update in place via the mechanics below |
| Columns (add/remove/reorder) | ✅ Yes | Update in place |
| Widgets, histogram bucket size | ✅ Yes | Update in place |
| Subscribers, webhook, notifications | ✅ Yes | Update in place |
| **Any filter field** — keywords, brands, channels, language, date range, MSN flag, demographics, cross_references, filters_json | ❌ **No** | **Cannot update in place.** Tell the user: *"The CLI edit endpoint can't patch FilterSet fields today (server-side limitation — `CliReportEditView`'s filterset path isn't wired up). I can save this as a new variant of the report instead — same shape with the filter change applied — and link it back to the original. OK to proceed?"* On confirmation: run Phase 1–4 with the prior config as the starting point + the user's filter delta, save as a NEW report. NOT an edit.

**Recognition** — treat the follow-up as an edit candidate based on these signals:

1. The most recent terminal action in this session was a successful `tl reports create` invocation. The resulting `report_id` and the full config it wrote are in working memory.
2. The new prompt's topic overlaps with the prior save — same report type, same primary brand / niche / channel set, same competitive frame. (If the new prompt opens a fundamentally different topic, it's a new save.)
3. The new prompt contains a **refinement signal** — broadly defined. Refinement signals include:
   - **Refinement vocabulary**: *instead*, *change*, *swap*, *drop*, *add*, *tighter*, *broader*, *narrower*, *without*, *except*, *now with*, *but with*, *use … instead of …*
   - **Filter / sort modifiers**: *filter*, *limit*, *only*, *remove*, *replace*, *include*, *exclude*, *sort by [field]*
   - **"Make it X" framings**: *make it [country]-only*, *make it [category]-only*, *make it [demographic-shape]*
   - **Partial-filter prompts** that name a single filter axis without naming a new topic: *"with AdSpot price < $2K"* after a save on the same niche

**Decision rule** (not binary — ask when in doubt):

| 1 (prior save) | 2 (topic overlap) | 3 (refinement signal) | Action |
|---|---|---|---|
| ✓ | ✓ | strongly fires | Post-save trigger fires (Follow-Up Interactions). Ask update vs. variant; default-highlight **update**. |
| ✓ | ✓ | ambiguous OR absent | **Still ask** — topic overlap alone is reason enough to surface the choice. Default-highlight update; user can override to "save a separate variant" or "it's a new report." |
| ✓ | ✗ | n/a | Different topic → treat as new save; no clarifier needed. |
| ✗ | n/a | n/a | No prior save in working memory → standard preview/save flow; nothing to edit. |

The failure mode the skill is preventing: silent auto-create on every refinement prompt, producing N duplicate reports instead of one updated report. A clarifier is one ignorable line if the user wanted a new variant anyway; the cost of getting it wrong is the duplicate.

**Mechanics — when the user confirms "update the existing one" AND the change is in the editable-field whitelist above:**

1. **Source the current config from working memory.** Recognition criterion 1 requires the prior save happened in this session, so the full config the skill emitted is still in working memory. **The CLI does NOT today expose a `tl reports show` / refetch command** — if for any reason the prior config is NOT in working memory (session was cleared, or the user is editing a report from a different session by ID), STOP and ask the user to (a) confirm the `report_id` and (b) describe the specific change. Do NOT guess at the current config.
2. **Compose the patch — ONLY editable fields.** Build a JSON object containing **only the fields the user explicitly asked to change**, drawn exclusively from the editable-field whitelist (title, description, columns, widgets, histogram_bucket_size, emoji, display_mode, subscribers, webhook_url, notifications_on, message_template, report_type, type, owner, link). **Do NOT send the full working-memory config** — it contains `filterset`, `cross_references`, `filters_json`, and other create-only fields that the backend's `_reject_unknown_fields` validation will atomically 400 even if the user's actual edit is to a legitimate field like `columns`.
3. **Resolve a portable temp path** for the patch JSON (same mechanics as save — `python -c "import tempfile, os; print(...)"`). Hard-coding `/tmp/` fails on Windows.
4. **Write the patch and verify** — write the JSON to the resolved path, then `test -f <path>` before invoking the CLI.
5. **Invoke the update** — `tl reports update <report_id> "$(cat <that-exact-path>)"`. The `update` command's second positional argument is a JSON object of fields to update (not a `--config-file` flag — that flag is only on `tl reports create`, not `update`). Passing inline as `'<json>'` breaks on apostrophes in brand names; the safe shape is `"$(cat <path>)"` against the verified temp file.
6. **Reply** with the updated report's URL + a one-line summary of what changed (*"changed: columns added Y; description rewritten"*). Same wording rules as the save-success message — say "TL report" not "Campaign", say "report #N" not "Campaign #N".

**Patch shape — what the JSON should and shouldn't contain:**

```json
// ✅ Correct: only editable fields the user changed
{
  "columns": { "channel_name": true, "subscribers": true, "last_published": true, "outreach_email": true },
  "description": "Updated description text"
}

// ❌ Wrong: merged full config — `filterset` and `cross_references` will atomically 400 the request
{
  "title": "...", "description": "...", "filterset": {...}, "cross_references": [...], "columns": {...}
}
```

**Anti-patterns to avoid** (failure modes observed in real runs):

- ❌ Re-running Phase 1–4 on a non-filter refinement (column/title/widget) — composes a parallel config instead of patching
- ❌ `tl reports create` instead of `tl reports update` for column/widget/title refinements
- ❌ Sending the full working-memory config as the update payload — `_reject_unknown_fields` is atomic and 400s the whole request if `filterset`/`cross_references`/`filters_json` are included. Send ONLY editable fields.
- ❌ Patching any FilterSet field via `tl reports update` — backend explicitly rejects ("Filterset edits are not supported here"). Route to "save as a new variant" instead.
- ❌ Over-correcting to "CLI can't edit anything" — title/description/columns/widgets/histogram_bucket_size/emoji/display_mode/subscribers/webhook/notifications ARE editable
- ❌ Inventing `tl reports show` to refetch config — doesn't exist. If config isn't in working memory, ask the user.
- ❌ Passing the patch via `--config-file` — that flag exists only on `create`, not `update`. For `update`, JSON goes as the second positional argument.

When in doubt: ask. Cost of asking when the user wanted a new variant = one ignorable line; cost of guessing wrong = duplicate report or unrecoverable 400.

What changes between save-mode and preview-mode:

| | Save (explicit intent) | Preview (default) |
|---|---|---|
| Phases 1–4 run? | Yes | Yes (identical) |
| Campaign row in DB? | Yes | No |
| What ends in chat | Takeaways + saved-report URL | Takeaways + sample table + "say save" tail |
| Portable-temp transport file (`<system-temp>/tl-report-builder-<slug>.json`) written? | Yes (transport for `tl reports create`) | No (config stays in working memory) |
| `tl reports create` invoked? | Yes (`--config-file <path> --yes`) | No |
| Campaign-config JSON in chat? | **No** | **No** |

## Process Flow (Strictly Sequential)

Each phase consumes the previous phase's output. No phase runs out of order or in parallel. Every phase may pause for a follow-up question before proceeding.

```
USER_QUERY → Phase 1 → Phase 2 → Phase 3 → Phase 4 → deliverable
              (type)   (schema   (columns)  (widgets + final
                       + valid.)             JSON validation)
```

### Phase 1 — Report Selection
- **In/Out**: `USER_QUERY` → `ReportType ∈ {1 CONTENT | 2 BRANDS | 3 CHANNELS | 8 SPONSORSHIPS}`
- **Tools**: none (heuristic over USER_QUERY)
- **Routing**: see "Phase 1 — Report Type Selection (detail)" + golden examples (G07, G06)
- **Follow-up**: ambiguous / invalid input → ask user

### Phase 2 — Schema Phase + Validation
- **In/Out**: `(USER_QUERY, ReportType)` → `{filterset, filters_json, cross_references, _routing_metadata, _validation}`
- **Loads**: `references/<intel|sponsorship>_filterset_schema.json`; `references/report_glossary.md` on-demand; `tools/sample_judge.md` for validation
- **Responsibilities**: compose FilterSet (filterset + filters_json + cross_refs), apply ReportType defaults (`days_ago`, `channel_formats`, `sort`), then VALIDATE against live data: `db_count` → threshold classify → `db_sample` (LIMIT 10) → `sample_judge` → decide `proceed | retry | alternatives | fail`. **Retry cap: 1** (feedback to T1/T2 on empty/too_broad).
- **Conditional Tool Invocation** (Phase 2 only — tools are NOT phases):
  - **T1** `tools/topic_matcher.md` — taxonomy match
  - **T2** off-taxonomy keyword set (delegates to the `tl-keyword-research` skill)
  - **T3** `tools/database_query.md` — cross-reference query
  - **T4** `tools/name_resolver.md` — brand/channel name → ID
  - **T5** `tools/similar_channels.md` — look-alike channels
  - `sample_judge` `tools/sample_judge.md` — validation sub-step
- **Follow-up triggers**: filters missing/incomplete, filter inputs ambiguous, tool-output needs confirming, T4 multi-candidate ambiguity, T3 unexpected size / timeout, `sample_judge` `looks_wrong` → Mode B (save anyway / refine / cancel), 1 retry exhausted on empty/too_broad → alternatives

### Phase 3 — Columns Phase
- **In/Out**: `(validated schema, ReportType)` → `{columns, dataset_structure, pending_refinement_suggestions}`
- **Loads**: `tools/column_builder.md` (always); `references/columns_<type>.md`; `references/sortable_columns.json`
- **Responsibilities**: pick columns by `ReportType + filters + intent`; validate (schema compliance, type alignment with sort+filters, pagination defaults applied)
- **Follow-up triggers**: column selection needs confirmation (template + user-enumerated extras); incompatible columns; no columns + no clear intent → suggest defaults

### Phase 4 — Widget Phase (FINAL)
- **In/Out**: `(validated schema, columns, ReportType)` → FINAL `{campaign_config_json, takeaways}`
- **Loads**: `tools/widget_builder.md` (always); `references/<intel|spons>_widget_schema.json`; `references/<intel|spons>_filterset_schema.json` for final JSON validation
- **Responsibilities**: define aggregations (sums/averages/counts/breakdowns); pick widgets per `ReportType + filters + columns`; set `histogram_bucket_size` per date range; **generate `report_title` + `report_description` BEFORE final validation** (both mandatory on save; CLI 400s if missing); then run **FINAL JSON-shape validation** (all phase outputs compose; API-contract: `type=2` DYNAMIC, valid report_type, non-empty columns, sort references an emitted column, title ≤60 chars non-empty, description 1–3 sentences non-empty); compose takeaways.
- **Type-3** aggregators: subscriber/views.
- **Type-8** aggregators: `count_sponsorships`, `sum_price` with axis branching on `publish_status` (`send_date` for proposals, `purchase_date` for sold).
- **Follow-up triggers**: widget/aggregation preferences need confirmation; breakdowns ambiguous; no aggregation requested → suggest defaults; final validation surfaced issues.

**There is no fifth phase.** Phase 4's output IS the deliverable. The skill never writes to the database directly — reads via `tl db es` (types 1/2/3) or `tl db pg` (type 8); writes via `tl reports create --config-file <path> --yes`.

**The deliverable can land in the chat in two shapes — pick the right one based on the user's intent:**

> **Save-or-preview policy** (READ THIS — saving has been over-eager in the past):
>
> Every request goes through Phases 1–4 and ends up with a fully-formed campaign config in working memory. The only branching is whether to **save** it (write a Campaign row to the DB) or **preview** it (show the takeaways + sample results in chat without persisting). **Default to preview.** Only save when the user's wording is **explicit and unambiguous** about wanting a saved deliverable.
>
> **Save** (auto-invoke `tl reports create --config-file`) when the prompt contains explicit save intent:
> - "save", "save it as a campaign", "save a report", "create the report", "create the campaign", "build me a saved report", "make a campaign for me", "publish", "persist", "store this", "I'll need to come back to this"
> - The user explicitly references the saved deliverable: "set up a campaign for", "make a dashboard for", "set up a report I can revisit"
> - The user's follow-up after a preview ("yes save it", "save", "do it", "go ahead", "create it now") — re-use the config that's already in working memory; do NOT re-run the phases
>
> **Preview** (default — show results in chat, do NOT save) when the prompt is exploratory, informational, or search-oriented:
> - "find me", "show me", "give me", "list", "who are", "what are", "are there any", "look up", "search for", "check"
> - "build me X channels / videos / brands / deals" — bare noun, no "report" / "campaign" / "save"
> - "tell me about", "explore", "scan", "analyse"
>
> **Ambiguous middle** ("build a report on X", "create a campaign for Y", "report on Z", "campaign for X"):
> - The user said "report" / "campaign" but didn't say "save" / "create the report" / "I'll come back to this".
> - **Default to preview**, then close the reply with one line: *"If you want to save this as a campaign you can come back to, just say save."*
> - Conservative move — never persist on ambiguity. If the user wanted it saved they will say so.
>
> **Save mechanics** (when save is triggered): three strict steps. **Step 1 alone is not the save** — the file write is just transport for step 3. Saying "Saved as foo.json" or "Saved to <path>" after only doing step 1 is a regression bug.
>
> 1. **Resolve a portable temp path FIRST** — never hardcode `/tmp/`. Use `Bash` to query the system temp directory at runtime so the path works on Linux, macOS, AND Windows:
>    ```bash
>    python -c "import tempfile, os; print(os.path.join(tempfile.gettempdir(), 'tl-report-builder-<short-slug>.json'))"
>    ```
>    Capture the printed path verbatim. On Linux/macOS this resolves to something like `/tmp/tl-report-builder-foo.json`; on Windows it resolves to `C:\Users\<user>\AppData\Local\Temp\tl-report-builder-foo.json`. **Hardcoding `/tmp/` on Windows silently fails** — the Write tool may report success but the file lands somewhere the CLI can't read in step 3. The `python -c "import tempfile..."` pattern works on every platform Claude Code runs on.
> 2. **Write the JSON to that resolved path via the `Write` tool, then verify it landed.** Immediately after the write, run `Bash`:
>    ```bash
>    test -f "<resolved-path>" && wc -c "<resolved-path>" || echo "MISSING"
>    ```
>    If the verification reports `MISSING` (or the byte count is 0), STOP and surface a clean error to the user — **do NOT instruct them to save it themselves** (that would conflict with rule 15's ban on user self-save fallbacks). Phrase it as a bug-report-shaped message acknowledging the save couldn't run, with the JSON attached as a recovery artifact (not as a save instruction):
>
>    ```
>    Couldn't save the report — the temp directory at <resolved-path>
>    isn't writable, so I couldn't stage the config for the CLI. This
>    is a bug in the skill / environment, not something you need to do.
>
>    The validated config is below as a recovery artifact in case you
>    want to retry from a different machine. I haven't sent it to TL.
>
>    <inline JSON in a code block, fenced>
>    ```
>
>    Do not invoke the CLI in this branch; that would just produce a confusing "No such file or directory" error. The inline JSON is a fallback **artifact**, not an instruction — the user is not expected to run anything themselves.
> 3. **Invoke `tl reports create --config-file <that-same-resolved-path> --yes`** via the `Bash` tool. This is what actually saves the report. Read the CLI's response: success returns a `campaign_id` and `report_url` to echo to the user; failure returns a non-zero exit and an error message — surface that error verbatim, do NOT silently mark the report as saved. **Use the EXACT same path string** the verification step in (2) confirmed; don't paraphrase or convert slashes between Unix/Windows styles. Never write to the user's current working directory or any project path — the file is a transport, not a deliverable.
>
> **Preview mechanics** (default): show **the sample-rows table FIRST**, then takeaways, then the closing "say save" tail. The table is the deliverable in preview mode — takeaways describe it, but the table itself is what the user asked for. **Skipping the table is a regression bug** (Phase 4 hard rule 14). Use the `db_sample` rows Phase 2 already collected (top 5–10 by sort key) and format as a tight Markdown table with 2–4 type-relevant columns:
> - Type 3 (channels): `Channel | Subscribers | Last published`
> - Type 1 (videos/uploads): `Title | Channel | Views | Date`
> - Type 2 (brands): `Brand | Mentions | Channels`
> - Type 8 (deals/sponsorships): `Channel | Brand | Status | Send date`
>
> After the table, give 2–4 takeaways (count, niche fit, noise warnings, sort note). Then close with the **save tail**: *"If you want this saved as a TL report you can come back to, just say save."*
>
> **The save tail is MANDATORY in every preview reply** — including when the user's wording sounds informational ("find me…", "show me…", "are there any…"). The previous "skip when purely informational" exemption was too easy to over-apply: a real run for *"Find creators for FRÉ Skincare — should be female creator, US-based, majority female audience, filter out everyone already submitted, include a CPM column, min 2,000 projected views"* produced a polished preview with notes-for-the-AM and follow-up refinement options — but no save tail — even though the prompt was clearly designing a TL report (specific filters, custom column, brand-exclusion intent). Cost of including the tail when the user didn't want it: one ignorable line. Cost of skipping it when they did: they don't know the option exists. Always include it.
>
> If the user's preview-intent prompt happens to also include implicit save signals (specific column requests, structural design choices, request for a "list" they intend to act on), append a slightly more directive variant of the tail: *"If you want this as a saved TL report, just say save."* Same outcome; the tail is always there.
>
> **The JSON config never appears in chat in either path.** In save mode it lives in the portable-temp transport file; in preview mode it stays in working memory. JSON in chat is implementation noise and a regression we already shipped a fix for once.
>
> **Edits** to a saved report use `tl reports update <id> '<json>'` — same shell-quoting caveat as save: when the patch contains apostrophes, write to a portable temp file (resolved at runtime per step 1) and use `tl reports update <id> "$(cat <that-path>)"`. Don't tell users to paste JSON into the platform UI; that's an obsolete pre-v0.6.12 fallback.
>
> **Reads via `tl db es` / `tl db pg` (engine routed by report type — see Step 2.V1), writes via the CLI** is the architectural split.

## Phase 1 — Report Type Selection (detail)

Phase 1 is heuristic-only — no `tl db pg`, no tool prompts. It reads `USER_QUERY` and emits one of `{1, 2, 3, 8}` (or asks a clarifying question). Phase 1's correctness is the foundation everything downstream rests on; getting the type wrong forces the wrong schema, the wrong column catalog, and the wrong widget catalog.

### Routing logic

Read `USER_QUERY` and apply in order:

1. **Explicit type signals** — if the user said "uploads / videos / individual videos / per-video" → type 1. "Brands report / advertisers report / competitor research" → type 2. "Channels / creators / youtubers / publishers" → type 3. "Sponsorships / deals / adlinks / pipeline / sales pipeline / sponsorship management" → type 8.
2. **Deal-stage jargon** — see `report_glossary.md` "Deal-stage jargon" table. If the user says "booked / sold / won / closed / proposed / pending / matched / reached out / partnership / partnerships", they almost certainly mean type 8 — the deal pipeline. **Don't let "channels" / "creators" inside the same sentence override this** — "partnerships with beauty creators" is type 8 with a clarification opportunity, not type 3 with keyword-routing.
3. **Ambiguous terms from `report_glossary.md` "Ambiguous / dangerous terms"** → surface a clarifying question rather than guess. Examples: "campaign report", "sponsors report", "creator report" (singular), "performance report", "pipeline" without context.
4. **Default when "report" is unqualified + the request is about creators** → type 3.
5. **Vague / under-specified** ("Build me a report") → ask: "What kind of report? Channels (creators), uploads (videos), brands, or sponsorship deals?"

### Authoritative routing examples

These two examples anchor the highest-risk routing failures. The skill MUST handle them per the expected behavior.

#### G07 — partnership routing (silent-ship trap)

**`USER_QUERY`**: `"Show me partnerships from last quarter for beauty creators"`

**Trap**: a naïve heuristic sees "creators" → routes to type 3 (CHANNELS). That's wrong.

**Correct routing**: type 8 (SPONSORSHIPS). "Partnerships" is type-8 deal-stage jargon per `report_glossary.md`. The "beauty creators" phrase is a *channel-filter clarification opportunity*, not a topic-keyword for a channels report.

**Phase 1 output**:
```
report_type: 8
clarifying_question (optional): "Which beauty creators specifically — by name, or filter by content_categories: ['beauty']?"
```

This is a v1-known weakness (`_SPONSORSHIP_KEYWORDS = {pipeline, deal, deals, adlink, adlinks}` did NOT contain "partnership") that the v2 skill must catch.

#### G06 — vague query (ask, don't guess)

**`USER_QUERY`**: `"Build me a report"`

**Trap**: hallucinate a default report type and start emitting filters.

**Correct routing**: surface a follow-up question, do not proceed to Phase 2.

**Phase 1 output**:
```
follow_up: "What kind of report would you like? Choose one:
  - Channels (creators) — find YouTube channels matching some criteria
  - Uploads (videos) — find specific videos
  - Brands — find advertisers / sponsors aggregated across mentions
  - Sponsorships — track deal pipeline and sold deals"
```

Phase 2 doesn't fire until the user picks.

### Hand-off to Phase 2

Phase 1 emits `{ report_type: <int>, clarifying_questions: [...] | [] }`. Phase 2 reads `report_type` to pick the right schema (`intelligence_filterset_schema.json` for 1/2/3, `sponsorship_filterset_schema.json` for 8) and to gate which Phase 2 tools fire (e.g., `topic_matcher` skips for type 8; `keyword_research` skips for type 8).

## Conditional Tool Invocation

Tools fire from inside Phase 2 to resolve filter gaps the user's NL didn't name directly:
- *"gaming channels"* → `topic_matcher` resolves topic IDs + curated keywords
- *"channels we've proposed to Logitech"* → `database_query` resolves cross-reference IDs
- *"MrBeast and PewDiePie"* → `name_resolver` resolves channel IDs
- *"no strong topic match"* → `keyword_research` builds a keyword candidate set from scratch

Each tool fires only on explicit criteria. May emit `warnings: [...]` propagating to Phase 4 takeaways. Tools inform composition; they don't reshape filters already composed.

### T1 — `tools/topic_matcher.md`
- **Fires when**: `ReportType ∈ {1, 2, 3}` AND USER_QUERY mentions a topic that could map to `thoughtleaders_topics`.
- **Skipped when**: `ReportType == 8` OR USER_QUERY is purely entity-name lookup.
- **Fetch**: canonical SQL at [`tl/references/postgres-schema.md` → `thoughtleaders_topics` → Fetch query](../tl/references/postgres-schema.md#fetch-query-canonical--use-verbatim). Single query, no `WHERE`. Behavior rules: no name-pattern WHERE clauses, no `information_schema` inspection, **empty fetch ≠ off-taxonomy** (data-plane failure — surface, don't fall through). Off-taxonomy = matcher emits `summary.no_match: true`.
- **Output**: per-topic verdicts (strong/weak/none) + summary. Strong match → topic's `keywords[]` drives FilterSet `keywords`; can also emit `topics: [<id>]` directly.

**Narrow-first FilterSet assembly** (mandatory — applies to both topic-strong and keyword-research paths). Assemble with narrowest viable shape, validate, expand only if below narrow threshold. Two levers, ranked by impact:

**Lever 1 (HIGHEST impact) — Field selection (Type 3 only)**

Initial `content_fields` for Type 3 MUST be `["channel.channel_name", "channel_description"]` ONLY. Do NOT include `channel_description_ai` or `channel_topic_description` on the first cycle. (Schema enum values from `intelligence_filterset_schema.json` — FilterSet rejects unknown values.)

The AI-summarised fields catalogue every topic a channel has ever touched — they answer *"has this channel ever mentioned the niche"* (too broad for discovery) rather than *"is this channel ABOUT the niche"* (what `channel_name` + `channel_description` answer). Once `content_fields` is right, even broad keywords converge; with AI fields included, even tight keywords stay noisy. Field selection is the bigger dial; keyword pruning is the fine-tune.

**Lever 2 — Keyword selection**

Topic-strong: include `topic.keywords[]` entries fitting user's language scope. Multilingual prompts (LATAM/EU/APAC) need 5–8 native-language head terms — not just 2–3 English. Drop generic-overlap terms (single-word generics a lifestyle/family/entertainment channel might use in passing). Keep niche-specific (multi-word phrases or native-language vocab lifestyle channels wouldn't casually use).

Keyword-research outputs (the `tl-keyword-research` ranked list): take the **top 5–10 entries by `count`** for the initial FilterSet. Hold the remaining non-zero entries as expansion fuel for the one allowed expansion cycle below. Prefer mid-band counts when the highest-count entries are obviously generic (a head term like `crypto` ranks above more discriminating sub-area terms like `DeFi` / `ethereum` because it's broader — picking only the head terms re-introduces the noise the narrow-first rule exists to avoid). Drop zero-count entries; flag any suspiciously-low non-zero counts as `validation_concerns` for the takeaways.

**Expansion trigger — Type 3 only, ONE cycle max**

If initial Type 3 `db_count` is `narrow` / `very_narrow` (≤ 50 channels per Step 2.V3): one expansion step — add `channel_description_ai` + `channel_topic_description` to `content_fields`. Then:
- Post-expansion `normal` / `broad` → proceed to sample
- Post-expansion still `narrow` / `very_narrow` OR `empty` / `too_broad` → `decision: "alternatives"`, surface to user. No second skill-side cycle.

**Type 1 / Type 2**: expansion rule does NOT apply (no AI-summary content fields to expand into — types 1/2 default to video-level `content`/`title`/`transcript`). Narrow / very_narrow → directly `decision: "alternatives"`.

### T2 — Off-taxonomy keyword set
- **Fires**: `ReportType ∈ {1, 2, 3}` AND `topic_matcher.summary.strong_matches.length == 0` AND no entity-name anchor in USER_QUERY.
- **Skipped**: any condition above fails. Especially when user enumerates specific channels/brands (those are the anchor; keyword research is wasted). Type 8 also skipped — sponsorship reports filter by relations, not content text.
- **Mechanics**: delegate to the `tl-keyword-research` skill. Its `SKILL.md` is the canonical procedure (Phase 1 seed expansion → Phase 2 ranking script → strict JSON output). Apply two report-builder-specific adjustments on top of that procedure:
  - **WEAK_MATCHES anti-overlap (Phase 1)**: for each weak topic in `topic_matcher`'s output, avoid generating its `matching_keywords` set or the head terms from its territory. Example: if Topic 97 (Personal Investing) is weak for a crypto query, do NOT propose `"investing"`, `"stocks"`, `"portfolio"` — those dilute the niche.
  - **`--fields` per REPORT_TYPE (Phase 2)**: override the skill's default (`title,summary,transcript`) so probe counts reflect the actual field set the downstream FilterSet matches against.
    - Type 1 (CONTENT) / Type 2 (BRANDS): `title,summary` (transcript excluded by default — too noisy).
    - Type 3 (CHANNELS): `title,summary,channel_description,channel_topic_description` — channel-level fields ensure niche-channel matches, not just incidental video mentions.
    - Only add `transcript` if `USER_QUERY` explicitly mentions transcripts / captions / spoken-word.
- **Operator**: agent infers `OR` (default) or `AND` (composite-noun phrases like `"AI cooking"`, or explicit `"both X and Y"`) from USER_QUERY and passes via `--operator`.
- **Output**: `{operator: "AND"|"OR", keywords: [{keyword, count}, …]}` sorted desc by count. Zero-count entries are pruned at consumption (Lever 2 above); `operator` stamps onto the FilterSet's keyword combinator.

### T3 — `tools/database_query.md` (cross-reference)
- **Fires**: USER_QUERY has a cross-reference condition (sponsorship/proposal/pipeline history gating the main channel set). E.g. *"NOT proposed to Brand X"* → `cross_references`; *"channels from 2025 gaming pipeline with >$5K price"* → `multi_step_query`.
- **Skipped**: report type 2 / 8 (cross_references applies to 1 + 3 only); condition expressible as typed FilterSet field (`msn_channels_only`, `tl_sponsorships_only`); name lookup (use T4).
- **Catalog**: `exclude_proposed_to_brand`, `include_proposed_to_brand`, `include_sponsored_by_mbn` + `multi_step_query` (defaults, status IDs unchanged from v1).
- **Output**: `cross_references_entry` (appends to create_report config) OR full `multi_step_query` payload.
- **Hard rule**: sponsorship-side `multi_step_query` source queries default to last 12 months for "currently / active" framing without explicit dates.

### T4 — `tools/name_resolver.md`
- **Fires**: USER_QUERY enumerates specific channel or brand names.
- **Skipped**: no entity names.
- **Behavior**: progressive matching (exact → ILIKE substring → emoji-stripped → fuzzy). Surfaces match-quality + ambiguity (>1 active candidate).
- **Output**: `{ name → entity_id }` + `ambiguities: [...]` for follow-up.

### T5 — `tools/similar_channels.md`
- **Fires**: USER_QUERY contains "like X" / "similar to X" / "creators inspired by X" AND seeds resolve via T4.
- **Skipped**: no similarity phrasing, or report type 8.
- **Output**: `{ filterset_patch: { filters_json: { similar_to_channels: [...] } }, anti_overlap: { drop_if_present: [...] } }`. Caller merges + drops overlapping keyword/topic fields.

### Phase 2 validation sub-tool — `tools/sample_judge.md`

- **Fires**: `ReportType ∈ {1, 2, 3}` AND **post-V3-routing** `db_count` is `normal` (51–10000) or `broad` (10001–50000). Type 3 narrow-initial cases ONLY when post-expansion reclassifies to normal/broad.
- **Skipped**: Type 8 (deal sample shape ≠ channel sample shape); initial `empty`/`too_broad` (V3 routes to V5 retry); Types 1/2 narrow/very_narrow (no Lever-1 expansion path → direct alternatives); Type 3 narrow that stays narrow post-expansion (alternatives, not re-sample). One-cycle cap is total, not per-direction.
- **Output**: `{ judgment: matches_intent | looks_wrong | uncertain, reasoning, noise_signals, matching_signals }`. `looks_wrong` → Phase 2 follow-up (save anyway / refine / cancel). `widget_builder` (Phase 4) only fires after Phase 2 emits a validated FilterSet.

### Phase 3 sub-tool — `tools/column_builder.md`
Always fires in Phase 3. Reads `REPORT_TYPE`, `FILTERSET`, `ROUTING_METADATA` + `references/columns_<type>.md` + `references/sortable_columns.json`. Picks 5–10 columns (up to 13 with intent), validates sort, queues custom-formula refinement suggestions.
**Output**: `{ columns, dataset_structure, pending_refinement_suggestions, _column_metadata }`.

### Phase 4 sub-tool — `tools/widget_builder.md`
Always fires in Phase 4 (Phase 2 validation already cleared the FilterSet). Reads `REPORT_TYPE`, `FILTERSET`, `COLUMNS`, `ROUTING_METADATA` + matching widget schema (intel for 1/2/3, sponsorship for 8). Picks 4–6 widgets; applies `_tl_intent_overrides`; handles type-8 axis branching per `_tl_axis_branching`; sets `histogram_bucket_size`.
**Output**: `{ widgets, histogram_bucket_size, _widget_metadata }`.

## Sort field — which phase owns it

`sort` is a `FilterSet` field on the Django model, so **Phase 2 picks the value when composing the FilterSet** — defaulting to the type's pagination default (`-reach` for type 3, `-views` for type 1, `-doc_count` for type 2, `-purchase_date` / `-send_date` for type 8 per axis branching) unless the user's intent overrides (e.g., outreach intent on type 3 → `-publication_date_max`).

**Phase 3 doesn't pick the sort value — it validates it.** The sort field must reference a column that's both (a) present in the emitted `columns` dict AND (b) has an allowed direction per `sortable_columns.json`. If a mismatch exists, Phase 3 either adds the column (so the sort is valid) or surfaces a follow-up. Phase 3 never silently changes the sort value Phase 2 set.

This split means: **sort value = Phase 2; sort viability = Phase 3**.

## Phase 2 — Validation step (detail)

Phase 2's validation step is the **mandatory gate** between FilterSet composition and downstream phases. The skill MUST validate the composed FilterSet against live data before handing off to Phase 3 — silent emission of a broken FilterSet is the failure mode this step exists to prevent.

**What validation actually does** (in plain terms): once the FilterSet is composed, run a script that fetches the data those filters would actually return — both the **count of matching entities** (how many channels / uploads / brands / deals the predicate matches) and a **small sample of representative rows** (10 rows, ordered by the canonical sort). Then compare both back against the user's original prompt and judge: *would shipping this FilterSet plausibly complete the user's request?* If yes → proceed. If no → surface alternatives or fail rather than silently emit. The judgment is the validation gate's whole point.

### Step 2.V1 — Translate FilterSet to count + sample query

Determined by `report_type`. Phase 2 builds two queries: `db_count` (scalar) and `db_sample` (LIMIT 10). **The data plane depends on the report type:**

| ReportType | Primary engine | Why |
|---|---|---|
| 1 (CONTENT) | **Elasticsearch** (`tl db es`) | Content text search at scale — keyword/phrase matching across uploads is what ES is built for. |
| 2 (BRANDS) | **Elasticsearch** (`tl db es`) | Same — brand mention detection and aggregation runs on ES. |
| 3 (CHANNELS) | **Elasticsearch** (`tl db es`) | Channel description/topic search at scale. |
| 8 (SPONSORSHIPS) | **Postgres** (`tl db pg`) | AdLink relations + status / owner / date filters live in PG; sponsorships are not text-searched. |

The skill's previous "everything via `tl db pg`" framing was the v1 prototype's smoke-check assumption. Postgres lacks trigram / FTS indexes on `description` and times out on multi-keyword OR predicates against the full channels table. **Use ES as the primary plane for intelligence reports**; PG remains a narrow fallback only when (a) the report type is 8, or (b) ES is unavailable AND the FilterSet has tight indexed-column predicates (reach floor, single keyword, narrow language) so the PG CTE workaround can complete.

#### Intelligence reports (1 / 2 / 3) — Elasticsearch query

Compose an ES search body. The index is fixed server-side; the client only sends the search body. **The doc-type filter, target fields, sort, and `_source` differ per report type — pick the matching block below.**

##### Type 3 (CHANNELS) — search the channel doc type

**Critical**: the ES index is sharded by quarter (`tl-platform-{year}-{quarter}` per `skills/tl/references/elasticsearch-schema.md` line 38), and channel parent docs are duplicated across every quarter shard the channel was active in. Without deduplication, both `track_total_hits` and a flat sample return inflated/duplicated results — verified against live data (a 614-distinct-channel result inflated to 20,876 docs; sample of 10 returned 10 identical rows). Type-3 ES queries MUST use a `cardinality` aggregation for the count and `collapse` on `id` for the sample.

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "channel" } },
        { "term":  { "is_active": true } },
        { "terms": { "language": ["en"] } },
        { "terms": { "format":   [4] } },
        { "range": { "reach": { "gte": 100000 } } }
      ],
      "must": [
        {
          "multi_match": {
            "query":   "<keyword>",
            "type":    "phrase",
            "fields":  ["name", "description", "ai.description", "ai.topic_descriptions"]
          }
        }
      ]
    }
  },
  "aggs": {
    "distinct_channels": { "cardinality": { "field": "id" } }
  }
}
```

The `must` array carries one `multi_match` entry per keyword, combined per `keyword_operator`: AND → list every `multi_match` inside `must` (each is required); OR → move them to a sibling `should` array and add `"minimum_should_match": 1`. The example above shows the single-keyword case; multi-keyword extensions follow that pattern.

> ⚠️ **The `fields` array inside `multi_match` uses ES document field paths**, NOT the FilterSet `content_fields` enum values. ES uses `["name", "description", "ai.description", "ai.topic_descriptions"]`; the FilterSet enum (documented in [Lever 1 — Field selection](#lever-1-highest-impact--field-selection-type-3--channel-discovery) above and in [`intelligence_filterset_schema.json`](references/intelligence_filterset_schema.json)) uses `["channel.channel_name", "channel_description", "channel_description_ai", "channel_topic_description"]`. They're two different APIs touching the same underlying data — keep them distinct when composing the validation query vs the FilterSet emission.

For `db_count` on type 3: read `aggregations.distinct_channels.value`, NOT `total`. The `total` field counts documents (channel-doc duplicates included); `distinct_channels` counts unique channel IDs.

For `db_sample` (size 10) on type 3: same `query` body, plus:
```json
{
  "size": 10,
  "sort": [{ "reach": "desc" }],
  "_source": ["id", "name", "reach", "description"],
  "collapse": { "field": "id" }
}
```

**`collapse: { field: "id" }`** returns the top doc per channel ID, deduplicating across quarter shards. Without it, the sample returns the same channel multiple times.

**Note**: ES returns `name` for channels; the orchestration aliases it to `channel_name` before passing to `sample_judge` so the row shape matches the contract.

##### Type 1 (CONTENT) — search the article doc type

```json
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        { "term":  { "doc_type": "article" } },
        { "terms": { "channel.language": ["en"] } },
        { "terms": { "channel.format":   [4] } },
        { "range": { "publication_date": { "gte": "now-180d/d" } } }
      ],
      "must": [
        {
          "multi_match": {
            "query":   "<keyword>",
            "type":    "phrase",
            "fields":  ["title", "summary", "content"]
          }
        }
      ]
    }
  }
}
```

For `db_sample` on type 1: `size: 10`, `sort: [{ "publication_date": "desc" }]` (or `[{ "views": "desc" }]` per intent), `_source: ["id", "title", "channel.id", "publication_date", "views"]`.

**Important — channel name is NOT on article docs.** Per `skills/tl/references/elasticsearch-schema.md`, the embedded `channel.*` object on article docs contains only `{ id, country, language, content_category, format, publication_id }` — no `channel.name`. Filtering or selecting `channel.name` returns nothing silently.

To populate `channel_name` for the type-1 `sample_judge` row contract, the orchestration does a single PG batch lookup after the ES sample returns:

```sql
SELECT id, channel_name FROM thoughtleaders_channel WHERE id = ANY(<distinct channel.id values from ES sample>) LIMIT 50 OFFSET 0
```

Then enriches each sample row: `{ id: <article id>, title: <title>, channel_name: <from PG>, views: <views>, publication_date: <publication_date> }`. If the orchestration skips this enrichment, `sample_judge` will receive type-1 rows without `channel_name` — the contract treats it as optional secondary context (the primary identifier for type 1 is `title`), so judgment still works but with less context.

##### Type 2 (BRANDS) — aggregate over articles, group by brand

Brand-aggregated, so the ES query is an aggregation. **`tl db es` accepts at most one aggregation per request (top-level + sub-agg counts as 2 and is rejected per `skills/tl/references/elasticsearch-schema.md` line 28)** — type-2 validation therefore needs multiple separate ES calls, merged client-side.

**Call 1 (db_count)** — `cardinality` over `sponsored_brand_mentions` (or `organic_brand_mentions` / `all_brand_mentions` per intent): returns the distinct-brand count in `aggregations.distinct_brands.value`. Filter clause: `doc_type=article` + language + date range + `multi_match` keyword (`type: "phrase"`, fields `[title, summary, content]`).

**Call 2 (db_sample)** — `terms` agg over the same field with `size: 10` and the same filter clause. Each bucket has `key` (brand ID) and `doc_count` (per-brand mentions count). Use `doc_count` directly; do NOT add a `value_count` sub-agg (violates the one-agg limit).

**Optional Call 3** (per-brand channels count) — only when `sample_judge` needs the distinct-channels drill-down. Reuse Call 2's query body, add a `term` filter on the single brand ID, replace the agg with `cardinality` over `channel.id`. Most type-2 validations skip Call 3.

**Field-source notes** (per `skills/tl/references/elasticsearch-schema.md`):
- "Sponsored vs organic" distinction = which keyword array you aggregate over (`sponsored_brand_mentions` / `organic_brand_mentions` / `all_brand_mentions`). There is NO `brand_mention_type` filter field.
- Aggregation field is the keyword array name, NOT `brands.id`. Bucket keys ARE the brand IDs.
- Brand names are not in ES — after Call 2, PG batch lookup: `SELECT id, name FROM thoughtleaders_brand WHERE id = ANY(<bucket_keys>) LIMIT 50 OFFSET 0`.

**Sample-row shape for `sample_judge`**: `{ id: bucket.key, brand_name: <PG lookup>, mentions_count: bucket.doc_count, channels_count: <Call 3 or null>, last_mention_date: null }`. The standard path omits `last_mention_date` (would need another ES call per brand; not critical for judgment).

**Why `multi_match type: "phrase"`**: contiguous phrase matching respects word boundaries — no substring noise (`AI` matching `Tamil`/`captain`).

#### Sponsorship reports (8) — Postgres query

Type 8 stays on Postgres because the data plane is the sponsorship deal record (relations + status + dates), not text search.

**Use the denormalized view `v_adspot_brand_profiles`, not raw `thoughtleaders_adlink`.** The base adlink table does NOT carry `brand_id` or `channel_id` columns — those relations live on the view. Direct joins like `JOIN thoughtleaders_brand ON adlink.brand_id = ...` will be rejected by the planner because the FK doesn't exist on adlink.

The view exposes one row per (adlink × brand × channel) and surfaces these columns the skill cares about:
- `adlink_id`, `adlink_publish_status`, `adlink_created_at`, `adlink_updated_at`
- `brand_id`, `brand_name`
- `channel_id`, `channel_name`, `channel_msn_join_date`
- `organization_id`, `organization_name`, `organization_is_managed_services`
- `adlink_owner_advertiser_email`, `adlink_owner_sales_email`

**Important: count and sample MUST be deduped by `adlink_id`.** The view holds one row per `(adlink × brand × channel)` — a sponsorship spanning multiple brands or channels produces multiple rows. Type-8 counts sponsorship records (AdLinks), not view rows. **Always `COUNT(DISTINCT adlink_id)` for `db_count`; dedupe samples by `adlink_id`.** Direct `COUNT(*)` overcounts multi-brand/multi-channel adlinks.

##### Filter predicate mapping (must mirror the saved FilterSet)

The validation SQL must apply every populated type-8 FilterSet predicate that affects deal inclusion. It is not enough to validate only date + publish status; otherwise Phase 2 can approve rows the saved report will later exclude.

| FilterSet / `filters_json` input | SQL predicate pattern | Notes |
|---|---|---|
| `sponsorships` | `v.adlink_id = ANY(<resolved sponsorship_ids>)` | Direct AdLink include list. |
| `exclude_sponsorships` | `NOT (v.adlink_id = ANY(<excluded sponsorship_ids>))` | Direct AdLink exclude list. |
| `brands` | `v.brand_id = ANY(<resolved brand_ids>)` | Row-level include is OK because the view contains brand rows per adlink. |
| `channels` | `v.channel_id = ANY(<resolved channel_ids>)` | Row-level include is OK for the same reason. |
| `exclude_brands` | `NOT EXISTS (SELECT 1 FROM v_adspot_brand_profiles vx WHERE vx.adlink_id = v.adlink_id AND vx.brand_id = ANY(<excluded brand_ids>))` | Must be adlink-level. Row-level `v.brand_id <> ...` is wrong for multi-brand adlinks. |
| `exclude_channels` | `NOT EXISTS (SELECT 1 FROM v_adspot_brand_profiles vx WHERE vx.adlink_id = v.adlink_id AND vx.channel_id = ANY(<excluded channel_ids>))` | Must be adlink-level for multi-channel adlinks. |
| `filters_json.publish_status` | `v.adlink_publish_status = ANY(<publish_status ids>)` | Conditional; omit entirely when unset. |
| `filters_json.ad_publish_status: "0"` | `al.publish_date IS NOT NULL` | "Live/currently running" means sold AND published. This is base-table only, so it forces Path B. |

If a populated FilterSet field has no documented SQL predicate yet (for example a future `filters_json` key), Phase 2 should surface a follow-up / validation gap instead of silently dropping it from validation.

##### Date-scope mapping (deterministic — no intent branching)

The FilterSet exposes exactly TWO date pairs for type 8, each pinned to a single underlying column. Validation never tries to infer a "smart" date axis from intent — that would be undefined when intent is unset and would silently disagree with the user's framing.

Per `references/sponsorship_filterset_schema.json`:

| FilterSet field | Underlying column on `thoughtleaders_adlink` | Where it lives |
|---|---|---|
| `start_date` / `end_date` / `days_ago` | `send_date` | base table only (NOT on view) |
| `createdat_from` / `createdat_to` | `created_at` | exposed on the view as `adlink_created_at` |

**Hard rule: `start_date`/`end_date`/`days_ago` ALWAYS validate against `send_date`, regardless of report intent (sold, live, pipeline, anything).** Intent affects column choices and widget axis branching (per `_tl_axis_branching` in `sponsorship_widget_schema.json`) — it does NOT affect the validation date column. v1's `_tl_axis_branching` is for displayed widgets, not for the data plane filter predicate.

**Out of scope for the FilterSet today:** filtering by `purchase_date`, `publish_date`, `outreach_date`, `sold_date`, etc. as a primary date predicate. These columns exist on the base table but the FilterSet exposes no first-class field for them, and the skill must NOT invent one (`purchase_date_from`, `publish_date_from`, etc. are unknown to the server and would be silently dropped). `filters_json` is the platform's catch-all and *might* be a future home for these scopes, but no concrete keys are documented today — if a user explicitly needs one of those axes as a filter (not just as a widget axis), surface a Phase 2 follow-up explaining the gap rather than guessing at keys. Track as a server-side gap, not a skill bug.

The validation query branches on which axes the FilterSet populates: `send_date` axis (`start_date`/`end_date`/`days_ago`/`days_ago_to`), `created_at` axis (`createdat_from`/`createdat_to`), or both. Before composing SQL, Phase 2 materializes the FilterSet's date inputs into a normalized lower/upper bound pair per axis — the FilterSet exposes four overlapping send-axis inputs that collapse to (≤ 1 lower bound, ≤ 1 upper bound), and similarly two created-axis inputs.

##### Bounds materialization (preprocessing — Phase 2 does this BEFORE composing SQL)

Each axis has up to two FilterSet inputs for the lower bound and up to two for the upper bound. Resolve them in this order, picking the first non-null on each side. **Upper bounds always materialize as the next calendar day (lower-bound-of-next-day) for half-open `<` semantics — see "Half-open upper bound" below; this applies to every upper-bound input on every axis.**

**`send_date` axis** — column type `timestamp with time zone`

| Bound | Resolution order (first wins) | Predicate shape |
|---|---|---|
| Lower (`send_lo`) | `start_date` → `today - <days_ago> days` → unbounded | `send_date >= '<send_lo>'` |
| Upper (`send_hi_next`) | (`end_date` + 1 day) → (`today - <days_ago_to> days` + 1 day) → unbounded | `send_date < '<send_hi_next>'` |

**`created_at` axis** — column type `timestamp with time zone`

| Bound | Resolution order (first wins) | Predicate shape |
|---|---|---|
| Lower (`created_lo`) | `createdat_from` → unbounded | `adlink_created_at >= '<created_lo>'` |
| Upper (`created_hi_next`) | (`createdat_to` + 1 day) → unbounded | `adlink_created_at < '<created_hi_next>'` |

**Half-open upper bound (`< next_day`, NOT `<= upper`)** — per `references/report_glossary.md` "Date upper bounds": the platform's underlying DateTime filtering uses `__lt next_day`, not `__lte`. Using `<= '2026-02-28'` against a timestamp column matches only midnight at the *start* of Feb 28 — silently dropping 23h59m of the user's intended last day. Apply this rule to BOTH `createdat_to` AND `days_ago_to` AND `end_date` — every upper-bound input on every axis materializes the same way: take the user's date, add 1 calendar day, emit a `<` predicate. So `createdat_to: "2026-02-28"` → `created_hi_next = '2026-03-01'` → `adlink_created_at < '2026-03-01'`. Same for `end_date` (→ `send_hi_next`) and `days_ago_to: 7` (→ `send_hi_next = today - 7d + 1d = today - 6d`). Lower bounds use `>=` unchanged.

**Hard rule (carried over from the type-8 edge-case in Phase 2):** at least ONE bound must resolve to a concrete value across one of the two axes — otherwise the request is unscoped and Phase 2 emits `decision: "fail"`. One-sided is legal: "since 2025-01-01" → only `send_lo`; "before Q4" → only `send_hi_next`; "in the last 30 days" → only `send_lo` (materialized from `days_ago`).

**When both axes are populated:** the FilterSet schema permits a single FilterSet to set BOTH a send-axis bound AND a created-axis bound simultaneously (e.g., "deals with `send_date` in Q1 2026 that were entered into the pipeline before Dec 2025"). The platform applies both as typed AND filters on the underlying columns. **The validation query MUST do the same** — emit predicates for every axis whose bounds resolved. There is no precedence, no silent dropping, no axis selection by intent. The composed SQL takes the joined-base-table shape (Path B's join is required because send_date isn't on the view) and adds `adlink_created_at` predicates from the created axis on top of `send_date` predicates from the send axis. The "Path A" view-only shape applies ONLY when the send axis has zero resolved bounds.

**Materialization choice — date literal vs. `NOW()`/`CURRENT_DATE`:** Phase 2 substitutes both materialized dates as literals (e.g., `'2026-04-05'`) computed at query-build time, NOT inline `CURRENT_DATE - INTERVAL` SQL. This gives the validation count a stable definition the orchestration can log and reproduce; rolling-window drift between `db_count` and a slow follow-up `db_sample` is a real bug class otherwise. Use `CURRENT_DATE - INTERVAL` only if the orchestration cannot resolve the date locally.

After materialization, the SQL templates emit only the predicates whose corresponding FilterSet input is set.

##### Canonical-sort resolution (parameterizes `db_sample` ORDER BY)

`db_sample` MUST order rows by the FilterSet's canonical sort — the same `sort` field Phase 3 surfaces and the saved report uses. Phase 2's contract on this is in line ~281: *"a small sample of representative rows (10 rows, ordered by the canonical sort)"*. Hard-coding `ORDER BY send_date DESC` violates the contract for sold-only reports (`-purchase_date`), live-only reports (`-publish_date`), or anything with an explicit user-set sort.

Phase 2 reads `filterset.sort` (default `"-send_date"` per `references/sponsorship_filterset_schema.json`) and resolves it into TWO SQL ORDER BY fragments:

- `<inner_sort_expr>` — table-qualified, used inside the `DISTINCT ON` subquery. The inner SELECT references columns through table aliases (`v.<col>` from the view, `al.<col>` from the base table), so the inner ORDER BY must use the same qualified form.
- `<outer_sort_expr>` — UNqualified, used in the outer `ORDER BY ... LIMIT` after the subquery. The aliases `v` / `al` are out of scope outside the subquery; only the projected column names are visible. So the outer expression references the column by its bare name (e.g. `purchase_date`, not `al.purchase_date`).

The two fragments share direction (`DESC` / `ASC`) and `NULLS LAST` — they only differ in qualification.

**Direction:** `filterset.sort` uses the same convention as `sortable_columns.json`'s `backend_code` — a leading `-` means descending, no prefix means ascending. Both directions are legal for every type-8 sort column (`sortability: "both"` in `sortable_columns.json`). Phase 2 strips the `-` prefix to identify the column and uses it to pick the direction:

```
sort: "-purchase_date"  → DESC NULLS LAST  (sold-only default, newest-sold first)
sort:  "purchase_date"  → ASC  NULLS LAST  (oldest-sold first; legal but less common)
sort: "-price"          → DESC NULLS LAST  (most expensive first)
sort:  "price"          → ASC  NULLS LAST  (cheapest first)
sort: "-send_date"      → DESC NULLS LAST  (schema default — newest-scheduled first)
sort:  "send_date"      → ASC  NULLS LAST  (chronological forward — oldest-scheduled first)
```

**Sort-key → SQL column mapping** (sort key as it appears in `filterset.sort`, stripped of the `-` prefix; matches `sortable_columns.json` `backend_code`):

| `filterset.sort` key | Path-A column | Path-B column | Path A allowed? |
|---|---|---|---|
| `send_date` (schema default) | n/a | `al.send_date` | ❌ — column not on view; forces Path B |
| `purchase_date` (sold-only intent default) | n/a | `al.purchase_date` | ❌ |
| `publish_date` (live-only intent default) | n/a | `al.publish_date` | ❌ |
| `created_at` | `adlink_created_at` | `v.adlink_created_at` | ✅ — view exposes it as `adlink_created_at` |
| `updated_at` | `adlink_updated_at` | `v.adlink_updated_at` | ✅ |
| `price` / `cost` / `weighted_price` / `matching_engine_score` | n/a | `al.<col>` | ❌ |
| `creator` (Advertiser) / `ad_spot__channel__channel_name` (Channel) / `ad_spot__channel__impression` (Projected Views) / `publish_status` | n/a | resolve via `al` joins or view columns; Phase 2 falls back to `<send_date> DESC NULLS LAST` if the column path is ambiguous and surfaces a follow-up | ❌ |

Two notes on the table:

1. **The `filterset.sort` key is the `backend_code` from `sortable_columns.json`, NOT the view's column name.** A user / Phase 3 emitting `sort: "created_at"` is a normal sort against the AdLink creation date. Phase 2 maps that backend_code onto `adlink_created_at` (Path A) or `v.adlink_created_at` (Path B) when composing SQL — the sort *value itself* stays `created_at`, matching the saved report's serialized form.
2. **Joined-relation sort keys (`creator`, `ad_spot__channel__channel_name`, `ad_spot__channel__impression`)** are platform ORM paths that don't translate cleanly to a single PG column. Phase 2 either resolves them via existing joins (`al.creator_id`, `v.channel_name`, etc.) or falls back to the schema default (`-send_date`) and surfaces a Phase 2 follow-up — silent rewrite to a different sort would mislead `sample_judge`.

**Concrete `<inner_sort_expr>` / `<outer_sort_expr>` examples:**

| `filterset.sort` | Path | `<inner_sort_expr>` | `<outer_sort_expr>` |
|---|---|---|---|
| `-purchase_date` | B | `al.purchase_date DESC NULLS LAST` | `purchase_date DESC NULLS LAST` |
| `purchase_date` (ASC) | B | `al.purchase_date ASC NULLS LAST` | `purchase_date ASC NULLS LAST` |
| `-send_date` (default) | B | `al.send_date DESC NULLS LAST` | `send_date DESC NULLS LAST` |
| `-price` | B | `al.price DESC NULLS LAST` | `price DESC NULLS LAST` |
| `-created_at` | A | `adlink_created_at DESC NULLS LAST` | `adlink_created_at DESC NULLS LAST` |
| `-created_at` | B | `v.adlink_created_at DESC NULLS LAST` | `adlink_created_at DESC NULLS LAST` |

**`NULLS LAST` is non-negotiable.** Many sponsorship date columns are populated only at specific lifecycle stages (e.g. `purchase_date` is null until sold, `publish_date` is null until live). Without `NULLS LAST` the sample fills with NULL-date rows that are uninformative for `sample_judge`. Apply `NULLS LAST` to every sort, both directions.

**Path-selection consequence:** if the canonical-sort key references a base-table column not on the view (anything in the table above whose Path-A column is `n/a`), Phase 2 MUST take Path B even when only the created axis is populated. Path A's "view-only optimization" is only valid when the canonical sort is also a view column (`created_at` / `updated_at`).

**SELECT-list addition:** the sort column must appear in the inner SELECT (PostgreSQL requires `DISTINCT ON` columns and `ORDER BY` columns to all be projected, AND the outer ORDER BY references the projected name). When the inner SELECT doesn't already include the sort column (e.g., `al.purchase_date` for sold reports), Phase 2 adds it. See Worked Example C below for the resolved shape.

##### Path A — `created_at` axis ONLY (view-only optimization; use only when send-axis bounds are absent AND canonical sort is a view column AND no base-table-only filters are set)

All predicates wrapped in `[ ... ]` are conditional — emit them ONLY when the corresponding FilterSet input is set and non-empty. Bare predicates outside brackets are unconditional. (`publish_status` is conditional too: when `filters_json.publish_status` is unset, the SQL must omit the clause entirely — `= ANY(NULL)` matches nothing and would silently zero the count.)

```sql
-- db_count
SELECT COUNT(DISTINCT adlink_id) FROM v_adspot_brand_profiles
WHERE 1=1
  [AND adlink_id = ANY(<resolved sponsorship_ids>)]                   -- if sponsorships set
  [AND NOT (adlink_id = ANY(<excluded sponsorship_ids>))]              -- if exclude_sponsorships set
  [AND adlink_publish_status = ANY(<filters_json.publish_status>)]   -- emit only if publish_status set
  [AND adlink_created_at >= '<created_lo>']                           -- emit only if created_lo set
  [AND adlink_created_at <  '<created_hi_next>']                      -- emit only if created_hi_next set
  [AND brand_id   = ANY(<resolved brand_ids>)]                        -- if brands set
  [AND channel_id = ANY(<resolved channel_ids>)]                      -- if channels set
  [AND NOT EXISTS (                                                    -- if exclude_brands set
        SELECT 1 FROM v_adspot_brand_profiles vx
        WHERE vx.adlink_id = v_adspot_brand_profiles.adlink_id
          AND vx.brand_id = ANY(<excluded brand_ids>)
      )]
  [AND NOT EXISTS (                                                    -- if exclude_channels set
        SELECT 1 FROM v_adspot_brand_profiles vx
        WHERE vx.adlink_id = v_adspot_brand_profiles.adlink_id
          AND vx.channel_id = ANY(<excluded channel_ids>)
      )]
LIMIT 1 OFFSET 0
```

```sql
-- db_sample (DISTINCT ON dedupes by adlink_id; outer ORDER BY enforces canonical sort)
-- Path A canonical sort is necessarily a view column (adlink_created_at / adlink_updated_at).
-- The SELECT list MUST include the resolved sort column; add adlink_updated_at when
-- sorting by updated_at (adlink_created_at is already projected below).
SELECT * FROM (
  SELECT DISTINCT ON (adlink_id)
         adlink_id, brand_name, channel_name, adlink_publish_status,
         adlink_created_at  -- add adlink_updated_at here when canonical sort is updated_at
  FROM v_adspot_brand_profiles
  WHERE 1=1
    [AND adlink_id = ANY(<resolved sponsorship_ids>)]
    [AND NOT (adlink_id = ANY(<excluded sponsorship_ids>))]
    [AND adlink_publish_status = ANY(<filters_json.publish_status>)]
    [AND adlink_created_at >= '<created_lo>']
    [AND adlink_created_at <  '<created_hi_next>']
    [AND brand_id   = ANY(<resolved brand_ids>)]
    [AND channel_id = ANY(<resolved channel_ids>)]
    [AND NOT EXISTS (                                                  -- if exclude_brands set
          SELECT 1 FROM v_adspot_brand_profiles vx
          WHERE vx.adlink_id = v_adspot_brand_profiles.adlink_id
            AND vx.brand_id = ANY(<excluded brand_ids>)
        )]
    [AND NOT EXISTS (                                                  -- if exclude_channels set
          SELECT 1 FROM v_adspot_brand_profiles vx
          WHERE vx.adlink_id = v_adspot_brand_profiles.adlink_id
            AND vx.channel_id = ANY(<excluded channel_ids>)
        )]
  ORDER BY adlink_id, <inner_sort_expr>         -- inner: qualified; required for DISTINCT ON
) deduped
ORDER BY <outer_sort_expr>                      -- outer: unqualified (aliases out of scope)
LIMIT 10 OFFSET 0
```

##### Path B — `send_date` axis (join base table; also handles both-axes FilterSets)

Path B is the canonical shape whenever the send axis has any resolved bound. It also covers the both-axes case: simply emit predicates from BOTH axes, since the platform applies them as AND filters and a both-axis FilterSet must validate the same way the server will execute it.

```sql
-- db_count
SELECT COUNT(DISTINCT v.adlink_id)
FROM v_adspot_brand_profiles v
JOIN thoughtleaders_adlink al ON al.id = v.adlink_id
WHERE 1=1
  [AND v.adlink_id = ANY(<resolved sponsorship_ids>)]
  [AND NOT (v.adlink_id = ANY(<excluded sponsorship_ids>))]
  [AND v.adlink_publish_status = ANY(<filters_json.publish_status>)]
  [AND al.publish_date IS NOT NULL]                                  -- if filters_json.ad_publish_status = "0"
  [AND al.send_date >= '<send_lo>']                                   -- send axis: emit only if send_lo set
  [AND al.send_date <  '<send_hi_next>']                              -- send axis: emit only if send_hi_next set
  [AND v.adlink_created_at >= '<created_lo>']                         -- created axis: emit only if created_lo set
  [AND v.adlink_created_at <  '<created_hi_next>']                    -- created axis: emit only if created_hi_next set
  [AND v.brand_id   = ANY(<resolved brand_ids>)]
  [AND v.channel_id = ANY(<resolved channel_ids>)]
  [AND NOT EXISTS (                                                    -- if exclude_brands set
        SELECT 1 FROM v_adspot_brand_profiles vx
        WHERE vx.adlink_id = v.adlink_id
          AND vx.brand_id = ANY(<excluded brand_ids>)
      )]
  [AND NOT EXISTS (                                                    -- if exclude_channels set
        SELECT 1 FROM v_adspot_brand_profiles vx
        WHERE vx.adlink_id = v.adlink_id
          AND vx.channel_id = ANY(<excluded channel_ids>)
      )]
LIMIT 1 OFFSET 0
```

```sql
-- db_sample (DISTINCT ON dedupes by adlink_id; outer ORDER BY enforces canonical sort)
-- The inner SELECT MUST project the column referenced by <inner_sort_expr>; for
-- non-default sorts (e.g. -purchase_date for sold reports), add `al.<col>` to the SELECT.
SELECT * FROM (
  SELECT DISTINCT ON (v.adlink_id)
         v.adlink_id, v.brand_name, v.channel_name, v.adlink_publish_status,
         al.send_date  -- replace with al.purchase_date / al.publish_date / etc. per canonical sort
  FROM v_adspot_brand_profiles v
  JOIN thoughtleaders_adlink al ON al.id = v.adlink_id
  WHERE 1=1
    [AND v.adlink_id = ANY(<resolved sponsorship_ids>)]
    [AND NOT (v.adlink_id = ANY(<excluded sponsorship_ids>))]
    [AND v.adlink_publish_status = ANY(<filters_json.publish_status>)]
    [AND al.publish_date IS NOT NULL]                                -- if filters_json.ad_publish_status = "0"
    [AND al.send_date >= '<send_lo>']
    [AND al.send_date <  '<send_hi_next>']
    [AND v.adlink_created_at >= '<created_lo>']
    [AND v.adlink_created_at <  '<created_hi_next>']
    [AND v.brand_id   = ANY(<resolved brand_ids>)]
    [AND v.channel_id = ANY(<resolved channel_ids>)]
    [AND NOT EXISTS (                                                  -- if exclude_brands set
          SELECT 1 FROM v_adspot_brand_profiles vx
          WHERE vx.adlink_id = v.adlink_id
            AND vx.brand_id = ANY(<excluded brand_ids>)
        )]
    [AND NOT EXISTS (                                                  -- if exclude_channels set
          SELECT 1 FROM v_adspot_brand_profiles vx
          WHERE vx.adlink_id = v.adlink_id
            AND vx.channel_id = ANY(<excluded channel_ids>)
        )]
  ORDER BY v.adlink_id, <inner_sort_expr>       -- inner: qualified (e.g. al.purchase_date DESC NULLS LAST)
) deduped
ORDER BY <outer_sort_expr>                      -- outer: unqualified (e.g. purchase_date DESC NULLS LAST)
LIMIT 10 OFFSET 0
```

**When to take which path:**

| FilterSet bounds populated | Canonical sort column | Path | Why |
|---|---|---|---|
| `created_at` only and no base-table-only filters | view column (e.g. `adlink_created_at`) | A (view-only) | Optimization — skip the base-table join when not needed |
| `created_at` only | base-table column (e.g. `purchase_date`) | B | Sort column lives on `al`; join required to project + ORDER BY it |
| `created_at` only plus `filters_json.ad_publish_status` | any | B | Live-only validation needs `al.publish_date IS NOT NULL` |
| `send_date` only | any | B | Join required for `send_date` predicate |
| Both axes | any | B | Join required for `send_date`; created-axis predicates emit on top |
| Neither | — | (Phase 2 emits `decision: "fail"` upstream) | Unscoped type-8 is rejected per the hard rule |

In practice Path A only fires for the narrow case "created_at-only AND sort is a view column AND no base-table-only filter is populated" — a real but uncommon shape. Most type-8 reports take Path B.

**Why `WHERE 1=1`:** all the bracketed predicates are conditional, and the type-8 unscoped-rejection rule only guarantees one DATE bound resolves — every other clause (publish_status, brands, channels) may be entirely absent. The `1=1` placeholder lets every conditional clause omit independently while keeping the SQL valid. Cosmetic; the planner discards it.

##### Include/exclude relation filters apply to BOTH paths

If `sponsorships`, `exclude_sponsorships`, `brands`, `exclude_brands`, `channels`, or `exclude_channels` is set on the FilterSet, the predicate MUST appear in BOTH `db_count` and `db_sample`, and in BOTH Path A and Path B when that path is eligible. Earlier drafts dropped channel filters from the sample query — that's a regression: channel-filtered reports could surface validation samples outside the requested set. Exclude filters are even riskier because the view is multi-row per adlink; apply them at adlink level with `NOT EXISTS`, not as row-local `<>` checks.

##### Worked-example summary

Three canonical shapes (templates documented above):
- `days_ago` only — `send_lo` materialized as date literal, `send_hi_next` unbounded
- `end_date` only — half-open `< next_day` (so `end_date: "2026-02-28"` → `< '2026-03-01'`), never `<= '2026-02-28'` which drops 23h59m
- Sold-only with `sort: "-purchase_date"` — Path B with `al.purchase_date` projected into inner SELECT; outer ORDER BY references the bare column name with `NULLS LAST`

**Why the inner/outer split**: `DISTINCT ON (adlink_id)` forces `ORDER BY adlink_id, ...` in the same SELECT — a syntactic Postgres requirement. Adding `LIMIT 10` to that returns the 10 smallest adlink IDs, not the 10 most recent. Wrap dedupe in a subquery; apply canonical sort + LIMIT in the outer SELECT.

#### Postgres CTE fallback (smoke-check only — niche path)

If ES is unavailable AND the FilterSet has tight indexed predicates, fall back to a PG CTE with **`AS MATERIALIZED`** (Postgres 12+ inlines CTEs without it, collapsing the pattern into a flat WHERE the sandbox planner rejects). Do NOT use `ILIKE ANY(ARRAY[...])` in the outer SELECT — sequential scan with N comparisons per row. Use explicit OR chains. **Don't use this as the production path** — ES is the right tool.

#### "Known ID set + keyword filter" pattern

When the FilterSet pins a small ID set in `channels: [...]` AND has keyword filters, don't query PG with `id IN (long list)` + multi-keyword ILIKE — sandbox cost cap. Use ES with a `terms` filter on `id` (scoping) + `match_phrase` for keywords (indexed). The resolved IDs are the scoping mechanism; ES doesn't need an `is_tl_channel`-like field.

### Step 2.V2 — Run the count query (with timeout / fallback handling)

```
# Intelligence report (1 / 2 / 3):
tl db es --json '<es_query_body>'

# Sponsorship report (8):
tl db pg --json "<count_sql>"
```

For ES queries:
- ES timeouts on intelligence searches are rare with proper `bool.filter` use; if one occurs, narrow the keyword set or tighten the indexed filters.
- ES phrase matching (`type: "phrase"`) handles substring-noise risk by default — no equivalent of the PG ILIKE `AI`-matches-`Tamil` problem.

For PG queries (type 8 or smoke-check fallback):
1. If a PG query times out, drop the `channel_name ILIKE` half of each keyword predicate (description-only).
2. Retry once.
3. If still timing out: split predicate by `AND`, run sides separately, estimate intersection arithmetically.
4. If that fails too: `decision: "fail"` with diagnostic.

### Step 2.V3 — Apply threshold rules

The routing has two tables: **initial** (first validation cycle, all types) and **post-expansion** (Type 3 only, fires once after a Lever 1 expansion). Each cell maps a classified `db_count` to exactly one downstream action; no cell loops back to a previous step.

**Initial routing** (any type, first validation cycle):

| `db_count` | classification | next (Type 3) | next (Type 1 / 2) |
|---|---|---|---|
| 0 | `empty` | Step 2.V5 (retry — broaden) | Step 2.V5 (retry — broaden) |
| 1–4 | `very_narrow` | **Lever 1 expansion** (one cycle: add `channel_description_ai` + `channel_topic_description`); on the post-expansion `db_count`, use the **post-expansion routing table below** — NOT this table | **`decision: "alternatives"`** — no skill-side expansion path for Type 1/2 |
| 5–50 | `narrow` | **Lever 1 expansion** (same as above) | **`decision: "alternatives"`** |
| 51–10000 | `normal` | Step 2.V4 (sample) | Step 2.V4 (sample) |
| 10001–50000 | `broad` | Step 2.V4 (sample); proceed with narrow-suggest | Step 2.V4 (sample); proceed with narrow-suggest |
| > 50000 | `too_broad` | Step 2.V5 (retry — narrow) | Step 2.V5 (retry — narrow) |

**Post-expansion routing** (Type 3 only, after the single Lever 1 expansion cycle):

| post-expansion `db_count` | classification | next |
|---|---|---|
| 0 | `empty` | **`decision: "alternatives"`** (no second narrowing cycle; expansion is one cycle by Lever 1's definition) |
| 1–4 | `very_narrow` | **`decision: "alternatives"`** |
| 5–50 | `narrow` | **`decision: "alternatives"`** |
| 51–10000 | `normal` | Step 2.V4 (sample) |
| 10001–50000 | `broad` | Step 2.V4 (sample); proceed with narrow-suggest |
| > 50000 | `too_broad` | **`decision: "alternatives"`** (no second narrowing cycle; the expansion overshot — emit the count and let the user decide whether to add a stricter filter) |

Only `normal` and `broad` route post-expansion to sample inspection. Everything else — `empty`, `very_narrow`, `narrow`, `too_broad` — routes to `alternatives` with no further skill-side cycles. This is the unambiguous "one cycle by definition" cap from Lever 1, enforced as a table.

The pre-`d395ae2` initial table said `very_narrow` / `narrow` go to *"sample; proceed with warning/note."* That was the historical universal-flow behaviour (used pre-Lever-1). The new Lever 1 rule for Type 3 replaces "proceed with warning" with "expand once first"; the Type 1/2 rule replaces it with "alternatives." Old prose elsewhere in the file describing "proceed with warning" on narrow counts is stale relative to these tables — follow the tables.

### Step 2.V4 — Run sample query, then `sample_judge`

The sample runner branches by report type, mirroring Step 2.V2's count runner:

```
# Intelligence reports (1 / 2 / 3) — primary path:
tl db es --json '<es_query_body_with_size_10_and_sort>'

# Sponsorship reports (8) — primary path:
tl db pg --json "<sample_sql>"

# PG smoke-check fallback (intelligence only, when ES unavailable AND tight pre-filters):
tl db pg --json "<cte_sample_sql>"
```

For ES intelligence samples: same `bool.filter` + `multi_match phrase` body as the count, but `size: 10`, `sort: [{ "reach": "desc" }]` (or the canonical sort per type), and `_source` listing the type-appropriate fields (see `sample_judge` row-shape contract below).

Pipe the sample (≤ 10 rows) into `tools/sample_judge.md` with `USER_QUERY`, `DB_SAMPLE`, `REPORT_TYPE`, and `VALIDATION_CONCERNS` (inherited from `keyword_research`'s warnings, if any). The row shape in `DB_SAMPLE` differs per report type — see `tools/sample_judge.md` "Inputs" section for the type-specific contracts.

Decision based on judgment:
- `matches_intent` → `decision: "proceed"` — emit validated FilterSet to Phase 3.
- `looks_wrong` → `decision: "alternatives"` — Mode-B follow-up to user (save anyway / refine / cancel). Skip Phase 3 + Phase 4.
- `uncertain` → `decision: "alternatives"` favoring "Refine" — surface ambiguity rather than ship silently.

### Step 2.V5 — Retry orchestration (cap: 1)

When `db_count` is `empty` or `too_broad`, emit structured feedback to whichever upstream signal produced the failing FilterSet:

| Source | Retry target | Feedback shape |
|---|---|---|
| Matched topics → `keywords` field | re-compose FilterSet with broader keywords from `topic.keywords[]` (beyond head) or relax operator AND→OR | `{issue, suggestion, previous_filterset}` |
| `keyword_research` output | re-invoke T2 with the failing keywords + retry hint | `{issue, suggestion}` |

Cap at **1 retry**. After 1 retry, if the second cycle still returns `empty` or `too_broad`, emit `decision: "alternatives"` and surface the count + the failing FilterSet to the user — let them pick refine / save anyway / cancel.

**Why 1, not 3** (mechanism + calibration evidence):

- Each retry costs **30–90 seconds** of full Phase 2c → Phase 3 cycle (LLM compose + ES count + ES sample + sample_judge LLM).
- After the first retry, if the count is *still* empty/too_broad, the underlying failure shape is almost always **data sparsity / inherent niche-language noise** — not a shape issue further iteration can fix. The 2nd and 3rd retries usually fail the same way as the first, costing 60–180s for the same signal.
- The shape-mismatch case (which retry IS valuable for — wrong AND/OR, missing field) is almost always caught on the first retry. So 1 retry catches the only failure mode where iteration helps; capping at 1 just bails on the failure modes where iteration doesn't.

*Calibration evidence — multilingual niche-discovery runs (LATAM cooking, fitness/wellness)*: in the historical 3-cap regime, runs that hit the retry path consistently went broad → tighter → AI-anchored → name+description-only over three cycles. Cycles 2 and 3 each saved ~10% additional noise but added 60s+ each. The user value of "10% less noise on the long tail" is small relative to the 2+ extra minutes per run; better to surface the noise after one retry and let the user decide. The principle generalises to any noisy-niche shape (beauty, aviation, crypto-vs-finance edge, etc.).

**What does NOT trigger retry** (unchanged):
- `sample_judge` returning `looks_wrong` — substantive failure (data sparsity or noise), not a shape failure. Retrying produces more noise. Go straight to `alternatives`. **A noisy spot-check is NOT a license for the agent to self-initiate a keyword-refinement loop.** The agent has been observed running `looks_wrong → tighten → re-validate → looks_wrong → tighten → re-validate` cycles outside the official retry path on multilingual niche-discovery prompts (LATAM cooking being one documented case), costing ~3 minutes for marginal noise reduction. If the first sample looks noisy, surface it via `alternatives`; do not silently iterate. The agent does not have license to chain validation cycles based on its own subjective noise judgment — that's the user's call after the alternatives prompt.
- `db_count` in `narrow` (5–50) or `very_narrow` (1–4) — does NOT trigger the V5 retry path (V5 is for `empty` and `too_broad` only). The narrow / very_narrow routing is owned by Step 2.V3's threshold table: **Type 3 → Lever 1 expansion (one cycle); Type 1 / Type 2 → `decision: "alternatives"`.** Neither path involves V5. The pre-`d395ae2` text here said "narrow (1–4) — proceed with warning" — that's stale on two counts (1–4 is `very_narrow`, not `narrow`, per V3's bucket labels; AND "proceed with warning" is the historical universal-flow behaviour that the new Lever 1 rule replaces).

### Step 2.V6 — Compose decision output

Pseudo-shape (not runnable JSON — `<int>`, `|`-unions, and `/* notes */` are placeholders for the actual values the orchestration emits):

```text
{
  "decision": "proceed" | "alternatives" | "fail",
  "_validation": {
    "db_count": <int>,
    "db_sample": [<rows>],
    "count_classification": "empty" | "very_narrow" | "narrow" | "normal" | "broad" | "too_broad",
    "sample_judgment": "matches_intent" | "looks_wrong" | "uncertain" | null,
    "sample_judgment_reasoning": "<from sample_judge>",
    "validation_concerns": [/* accumulated from T2 + sample_judge */],
    "retries": <int>,
    "errors": [/* if fail */]
  },
  "alternatives_for_user": { /* present iff decision == "alternatives" */ }
}
```

Phase 3 reads `decision == "proceed"` to know it's safe to run. The `_validation` block carries through to Phase 4's takeaways (narrow-result notes, noise warnings, etc.).

### Phase 2 validation edge cases

| Case | Behavior |
|---|---|
| Type 8 with no date scope | Reject upfront (`decision: "fail"`) — sponsorship queries without dates are unbounded and meaningless. |
| Cross-references present | Resolve cross-reference IDs first via T3, then count/sample the main predicate. Adds 1–2 preliminary queries. |
| Brand/channel name lookups | All string-name resolutions happen via T4 BEFORE this validation step. The FilterSet entering validation has IDs, not names. |
| Inherited `validation_concerns` from T2 | Pass through to `sample_judge`'s `VALIDATION_CONCERNS` input verbatim. The judge biases toward `looks_wrong` when these are present and confirmed in samples. |

### Authoritative validation example — G11 (substring noise → Mode B)

This example anchors the canonical silent-ship-risk that Phase 2 validation exists to prevent. The skill MUST handle it per the expected behavior.

**`USER_QUERY`**: `"channels about IRS tax debt forgiveness programs"`

**Phase 2 composes a FilterSet**:
```json
{
  "filterset": {
    "keywords": ["IRS", "tax debt", "tax debt forgiveness", "tax debt relief"],
    "keyword_operator": "OR",
    "content_fields": ["channel_description", "channel_description_ai", "channel_topic_description"],
    "languages": ["en"],
    "channel_formats": [4],
    "sort": "-reach"
  },
  "_routing_metadata": {
    "intent_signal": null,
    "tool_warnings": [],
    "validation_concerns": [
      "'IRS' is a 3-character keyword and risks substring noise (matches 'first', 'irish', etc.) — keyword_research flagged this"
    ]
  }
}
```

**Step 2.V2 — `db_count`**:
```sql
SELECT COUNT(*) FROM thoughtleaders_channel
WHERE is_active = TRUE
  AND (description ILIKE '%IRS%' OR channel_name ILIKE '%IRS%' OR ...)
  AND language = 'en'
```
Returns `6,601`. Classification: `normal` (51–10000 bucket).

**Step 2.V4 — `db_sample` + `sample_judge`**:

`db_sample` returns the top 10 channels by reach. Top results include:
```
Cocomelon, Bad Bunny, Bruno Mars, BRIGHT SIDE, Selena Gomez,
That Little Puff, Taarak Mehta Ka Ooltah Chashmah, ...
```

`sample_judge` is invoked with `USER_QUERY` + `DB_SAMPLE` + `VALIDATION_CONCERNS`. It returns:

```json
{
  "judgment": "looks_wrong",
  "reasoning": "All 10 samples are music artists, children's content, or general entertainment — none are about IRS tax debt or financial services. Confirms the substring-noise warning from keyword_research: 'IRS' is matching inside 'first', 'irish', etc.",
  "noise_signals": ["3-char keyword 'IRS' matching unrelated channel descriptions"],
  "matching_signals": []
}
```

**Step 2.V6 — Decision**:

```json
{
  "decision": "alternatives",
  "_validation": {
    "db_count": 6601,
    "count_classification": "normal",
    "sample_judgment": "looks_wrong",
    "sample_judgment_reasoning": "Top 10 by reach: Cocomelon, Bad Bunny, Bruno Mars... — none about IRS tax debt; substring noise from short keyword 'IRS'",
    "validation_concerns": ["'IRS' substring noise confirmed in samples"]
  },
  "alternatives_for_user": {
    "mode": "B",
    "options": [
      "Save anyway — useful if you want to inspect the long tail manually",
      "Refine — drop 'IRS' as a standalone keyword; keep 'tax debt' / 'tax debt forgiveness' / 'tax debt relief' (longer phrases, less noise)",
      "Cancel — TL data may not have meaningful coverage for this niche"
    ]
  }
}
```

**Phase 3 and Phase 4 do NOT fire.** The skill surfaces the Mode-B prompt to the user. This is the architectural promise: catch substring-noise silent ships at validation time, before columns and widgets are wasted on a broken FilterSet.

This is the canonical regression test. Whenever Phase 2 validation changes, walk this example through and verify the outcome is still `decision: "alternatives"` with a Mode-B prompt — not a silent emit.

### User-facing rendering (Mode B)

`alternatives_for_user` is internal state. When the skill surfaces it to the user, it MUST be rendered in plain English per the **"User-facing language (READ FIRST)"** rules at the top of this file (forbidden-terms list, plain-English narration map, second-person framing).

**Canonical user-facing rendering for the G11 example** (translate the JSON above into this — do NOT show the JSON):

> Hmm — I ran the search but the top results don't look right for **"channels about IRS tax debt forgiveness programs"**. The first 10 by reach are channels like **Cocomelon**, **Bad Bunny**, **Bruno Mars**, and **Selena Gomez** — music and kids' content, not tax/finance. The short word "IRS" is matching inside unrelated words in channel descriptions, which is pulling in a lot of noise.
>
> How do you want to proceed?
> 1. **Save it anyway** — if you want to dig through the long tail manually.
> 2. **Refine the search** — for example, drop "IRS" on its own and keep the longer phrases ("tax debt", "tax debt forgiveness", "tax debt relief").
> 3. **Cancel** — there may not be much coverage for this niche in the data.

Notice what's preserved (the actual sample names, the user's keywords, what went wrong in human terms) and what's stripped (every internal label). The same translation rule applies to Mode-C (failure) and any other follow-up message — name what the user sees, never name the machinery.

## Phase 3 — Columns Phase (detail)

Phase 3 picks the columns the saved report displays and the dataset shape that hangs off them. It runs after Phase 2 has produced a validated FilterSet and before Phase 4 emits widgets.

### Inputs

- `REPORT_TYPE` (1 / 2 / 3 / 8) from Phase 1.
- The validated schema produced by Phase 2: `filterset` + `filters_json` + `cross_references` (if any) + `_routing_metadata` (carries `intent_signal`, tool warnings, etc.).
- **Loaded on demand**:
  - `tools/column_builder.md` — the column-selection prompt (always invoked).
  - `references/columns_<type>.md` — full column catalog for the report type, consumed by `column_builder`.
  - `references/sortable_columns.json` — sort metadata, consumed by `column_builder` for sort validation.

### Process

1. **Pick columns via `tools/column_builder.md`.** Inject `REPORT_TYPE`, `FILTERSET`, `ROUTING_METADATA`, the `references/columns_<type>.md` content, and `references/sortable_columns.json`. The builder owns four explicit decisions:
   - **Which columns to emit** — defaults + intent-driven additions + niche-driven additions, capped at 5–10 standard (up to 13 with intent justification).
   - **Column order** — anchors first (e.g. `Channel`, `TL Channel Summary` for type 3; `Channel`, `Advertiser`, `Status` for type 8), then identity columns, then the data columns the user's intent emphasizes (outreach surface / engagement surface / pricing surface), then context columns last. The order in the emitted `columns` dict IS the display order.
   - **Column width** — most columns use the platform's default width. Wide-text columns (`TL Channel Summary`, `Topic Descriptions`, `Channel Description`, `Talking Points`, `Adops Notes`) get wider; numeric / status columns get narrower. The builder emits a `width` hint per column when it deviates from the default.
   - **Custom column formulas** — propose at least one per type's "Suggested formulas" table (e.g. `{Avg. Views} / {Subscribers}` for type-3 engagement, `{Price} - {Cost}` for type-8 TL profit). Custom columns are surfaced as `pending_refinement_suggestions` for the user to opt into — never silently activated.
   The builder also validates the sort viability (per "Sort field — which phase owns it" above) and emits a `dataset_structure` with pagination defaults.
2. **Hand off to Phase 4.** The `pending_refinement_suggestions` carry through to Phase 4's takeaway message; the `columns` dict (with order and widths) plus `dataset_structure` feed `widget_builder` and final composition.

### Follow-up triggers (Phase 3)

These triggers are surfaced by `column_builder` when conditions arise:

- The user enumerated specific columns AND the type's default set differs → ask: "Use the template's columns, the columns you listed, or both?"
- A requested column doesn't exist for the report type (e.g., user asked for `Views` on a type-3 report) → ask: "[column] isn't available for [report type]; closest is [alternative]"
- No columns specified AND no clear intent → ask: "I'll use [type]'s default set unless you want a different focus (outreach / discovery / sponsorship-pitch)"
- Sort field references a column not in the emitted set → `column_builder` adds the column and flags in `_column_metadata.concerns_surfaced`; if the direction is invalid, surfaces a follow-up.

(The full output schema, hard rules, worked examples, and self-check live in [`tools/column_builder.md`](tools/column_builder.md). SKILL.md owns orchestration; the tool file owns the selection rules.)

## Phase 4 — Widget Phase + FINAL Validation (detail)

Phase 4 is the terminal phase. It picks widgets, performs FINAL JSON-shape validation against both schemas, and composes the user-facing deliverable: the campaign config + key-takeaway insights. (The live-data validation already happened in Phase 2 — Phase 4 trusts the FilterSet.)

### Inputs

- All Phase 2 + Phase 3 outputs (Phase 2's output is already validated against live data — no re-validation here).
- **Loaded on demand**:
  - `tools/widget_builder.md` — the widget-selection prompt (always invoked).
  - `references/intelligence_widget_schema.json` (types 1/2/3) and `references/sponsorship_widget_schema.json` (type 8) — JSON Schemas defining widget shape, the disjoint aggregator catalogs, default sets, intent overrides, and (for sponsorship) axis-branching rules. Consumed by `widget_builder`.
  - `references/widgets.md` — readable index pointing at the two schemas above.
  - `references/intelligence_filterset_schema.json` and `references/sponsorship_filterset_schema.json` — final JSON-shape validation source of truth.

### Process

1. **Pick widgets via `tools/widget_builder.md`.** Inject `REPORT_TYPE`, `FILTERSET`, `COLUMNS`, `ROUTING_METADATA`, and the matching widget schema (`references/intelligence_widget_schema.json` for types 1/2/3; `references/sponsorship_widget_schema.json` for type 8). The builder emits `{ widgets, histogram_bucket_size, _widget_metadata }`. **The selection rule is: emit only widgets that add value to the user's original prompt.** A widget earns its slot if it answers a question the user implicitly cares about (intent), surfaces a metric tied to a filter the user named (niche), or shows a trend over the date scope they specified. Don't pad to hit 6 — emit fewer (down to 4) if the extras don't answer something. The builder handles type-8 axis branching and intent-driven swaps per the schema's `_tl_intent_overrides`.
2. **Generate `report_title` and `report_description`** from the FilterSet + the user's original NL request. Title ≤ 60 chars; description 1–3 sentences summarizing intent + key filters. **Do this BEFORE step 3's validation pass** — both fields are mandatory on save, so the validation in step 3 needs to see them populated.
3. **FINAL JSON-shape validation pass.** Verify the composed config:
   - **`report_title` is a non-empty string ≤ 60 chars AND `report_description` is a non-empty 1–3 sentences.** Both fields are **MANDATORY** on `tl reports create` — the CLI rejects with HTTP 400 `Missing required field: report_title` (or `report_description`) if either is missing. If step 2 (title/description generation) hasn't run yet, run it FIRST, then come back to this check. Verbatim regression marker (real run, LATAM cooking 2026-05-11): saved config omitted `report_title`; first `tl reports create --config-file <path> --yes` returned `Error (400): Missing required field: report_title` and the agent had to edit the transport file and retry. **Fail closed at this validation step rather than discovering the missing field at save time** — a save-side 400 wastes a CLI round-trip and a credit charge.
   - Every field in `filterset` exists in the schema and matches its declared type.
   - Every column in `columns` is in the type's column file.
   - Every aggregator in `widgets` is in the matching catalog (intelligence for 1/2/3, sponsorship for 8).
   - `sort` references an emitted column with allowed direction.
   - Type 8 has at least one resolved date bound across the two axes (`send_date` axis from `days_ago` / `start_date` / `end_date` / `days_ago_to`, or `created_at` axis from `createdat_from` / `createdat_to`). Both axes MAY be populated simultaneously — the platform applies both as typed AND filters; final validation accepts that and does not reject coexistence. (See Step 2.V1's "When both axes are populated" rule.)
   - When `cross_references` is present, `report_type ∈ {1, 3}`.
   - When `filters_json.similar_to_channels` is present, no overlapping `keywords` / `topics` fields.
   - `type = 2` (DYNAMIC) and `report_type ∈ {1, 2, 3, 8}` — Campaign-model contract for the API endpoint.
4. **Compose key takeaway insights** — see "Takeaway-composition rules" below. These are the headline observations the user reads in the Phase 4 message. The `_validation` block from Phase 2 carries through here — narrow-result notes, sample_judge reasoning, and validation_concerns are all surfaced as takeaways.
5. **Emit the final deliverable.**

### Takeaway-composition rules

Takeaways are 2–4 plain-language insights drawn from the validated config + sample. Each takeaway falls into one of these patterns:

| Pattern | Example |
|---|---|
| **Result size** | "Found 247 channels matching your criteria — a normal-size result, ready to act on." |
| **Intent reflection** | "Optimized for outreach: the column set emphasizes deal history (`Sponsorships Sold`, `Last Sold Sponsorship`, `Outreach Email`) and demographic fit." |
| **Tool-warning surface** | "⚠️ The seed channel 'Sanky' had three TL candidates — confirmed with you that you meant the 1.2M-reach US channel." |
| **Sample-judge note** | "Top 10 sample channels look on-target — content matches the intended niche; no obvious noise." |
| **Narrow / broad note** | "📌 Result is narrow (8 channels). Consider broadening the reach floor or expanding the keyword set." |
| **Refinement nudge** | "Want a 'Views Per Subscriber' custom column to spot high-engagement creators? Reply 'add formula' and I'll add it." |

Keep it tight: 2–4 takeaways total. Don't write essays. Cite specific numbers/names so the user can verify.

### Follow-up triggers (Phase 4)

- Aggregation/widget preferences need confirmation — "Default widgets for [type] are [list]; want to add/remove anything?"
- FINAL JSON-shape validation surfaced an unfixable issue (e.g., emitted column doesn't exist, aggregator from wrong catalog) → "Can't ship config because [reason]. Fix [thing]?"

(The `sample_judge looks_wrong` Mode-B follow-up is a Phase 2 trigger now — it surfaces upstream of Phase 3 / Phase 4.)

### Output (the deliverable)

Pseudo-shape (not runnable JSON — `<int>`, `|`-unions, and `/* notes */` are placeholders for the actual values the orchestration emits):

```text
{
  "campaign_config_json": {
    "type": 2,
    "report_type": <int>,
    "report_title": "<string ≤ 60 chars>",
    "report_description": "<1–3 sentences>",
    "filterset": { /* validated, from Phase 2 */ },
    "filters_json": { /* validated, from Phase 2 */ },
    "cross_references": [ /* optional, from T3 */ ],
    "columns": { /* from Phase 3 */ },
    "widgets": [ /* from Phase 4 */ ],
    "histogram_bucket_size": "week" | "month" | "year"
  },
  "takeaways": [
    "<insight 1>",
    "<insight 2>",
    "<optional insight 3>",
    "<optional insight 4>"
  ],
  "_phase4_metadata": {
    "json_shape_validation_passed": <bool>,
    "tool_warnings_surfaced": [ /* the ones from _routing_metadata that ended up in takeaways */ ],
    "validation_inherited_from_phase2": {
      "db_count": <int>,
      "count_classification": "narrow" | "normal" | "broad" | ...,
      "sample_judgment": "matches_intent" | null
    }
  }
}
```

### Hard rules (Phase 4)

1. **`campaign_config_json` is the deliverable**, not a draft. After Phase 4, no further skill steps modify it.
2. **`type: 2` (DYNAMIC) is the Campaign-model contract** for the reports the skill produces. The skill always emits `type: 2`; server-side fields like `created_by_campaign_maker` are filled by the API endpoint, not by the skill.
3. **Trust Phase 2's validation.** Phase 4 does NOT re-run db_count / db_sample / sample_judge — those already passed upstream. If Phase 2 emitted `decision: "proceed"`, the FilterSet is good. (Sample-judging is the architectural promise to catch silent ships of bad samples — it just lives in Phase 2 now.)
4. **JSON-shape validation rejection is a stop, not a warn.** If the final-shape validation finds an unfixable problem (column doesn't exist, aggregator from wrong catalog, missing required field), Phase 4 emits an error follow-up rather than emitting a partial config.
5. **Takeaways cite specifics.** Numbers, names, intent labels. Vague takeaways ("the report looks good") add no value.
6. **No new filters or columns in Phase 4.** Phase 4 doesn't reshape the FilterSet or add columns — it picks widgets, validates, and composes. Reshape requires looping back to Phase 2 or 3.
7. **Type-8 axis consistency.** Both `_over_<axis>` histograms in the same type-8 report use the SAME axis (per `sponsorship_widget_schema.json`'s `_tl_axis_branching`).
8. **Don't echo `campaign_config_json` back to chat — ever.** In save mode the JSON lives in the portable-temp transport file passed to `tl reports create --config-file <path> --yes` (path resolved at runtime per Save-or-preview policy step 1). In preview mode it stays in working memory. **There is no flow where the campaign-config JSON belongs in the chat output.** See the Save-or-preview policy at the top of this file for the full split between save mode and preview mode.
9. **When saving, use `--config-file <path>`, not `--config '<json>'`.** Passing JSON inline through a single-quoted shell argument breaks the moment any string value contains an apostrophe (which is common — "McDonald's", "L'Oréal", channel/title text). The temp-file transport sidesteps shell quoting entirely.
10. **Temp file MUST be under the system temp directory** — resolved at runtime via `python -c "import tempfile, os; print(os.path.join(tempfile.gettempdir(), '<name>'))"` so the path is correct on every platform (Linux/macOS: typically `/tmp/...`; Windows: `C:\Users\<user>\AppData\Local\Temp\...`). Never hardcode `/tmp/` — that fails silently on Windows. Never write the transport file to the user's current working directory, project root, repo, or any other path they might be looking at. Pollution of cwd with `foo_report.json` is a regression bug.
11. **Writing the file is NOT saving the report.** The save happens when `tl reports create --config-file <path> --yes` returns success. Until that command's exit code is read, the report does not exist. **Never tell the user "saved as <path>.json"** — that confuses the transport file (which is throwaway) with the saved TL report (which is what they asked for). The save-success message must come from the CLI response: a `campaign_id` (rendered to the user as **"report #N"**, NOT "Campaign #N") and `report_url`.
12. **Default to preview, not save.** Phases 1–4 always run, but the chat output is takeaways + a sample-rows table by default. **Only save when the user's prompt contains explicit save intent** — see the Save-or-preview policy near the top for the trigger word lists. Ambiguous middle ("build a report on X", "create a campaign for Y") → preview + the closing "say save" tail. Save is the explicit, opt-in path; preview is the conservative default.
13. **In preview mode the agent does not invoke `tl reports create`** and does not write a temp file. The campaign config stays in working memory. If the user follows up with "save" / "yes" / "go ahead", re-use that same in-memory config — do not re-run Phases 1–4.
14. **Preview output MUST include a sample-rows table.** Use the `db_sample` rows Phase 2 already collected (top 5–10 by sort key) and render them as a tight Markdown table with type-specific columns per the Save-or-preview policy:
    - Type 3 (channels): `Channel | Subscribers | Last published`
    - Type 1 (videos/uploads): `Title | Channel | Views | Date`
    - Type 2 (brands): `Brand | Mentions | Channels`
    - Type 8 (deals/sponsorships): `Channel | Brand | Status | Send date`
    **Takeaways alone are not a preview** — the user asked for results; takeaways describe the result, the table IS the result. Skipping the sample table because the result feels narrow, or because the prompt felt "report-y", is a regression bug. The table comes from data Phase 2 already pulled; it costs nothing extra to render.
15. **When save intent is detected, the agent MUST invoke `tl reports create` itself.** Telling the user "Save it via POST to the report-creation API endpoint when ready" or "to save, run `tl reports create --config '<json>'`" or any other form of "you save it yourself" is a regression bug — that's the obsolete pre-v0.6.12 fallback. If the prompt contains any save-intent word (see Save-or-preview policy: "save", "create the report", "create a campaign", "make a campaign for me to come back to", "publish", "persist") the flow is the three steps in Save-or-preview policy step 1+2+3: **resolve a portable temp path → Write the JSON → verify the file exists → invoke `tl reports create --config-file <that-exact-path> --yes`** → echo the campaign_id + report_url from the CLI's response. The user never sees the JSON, never gets told to do something themselves. If the CLI returns an error, surface it; do not fall back to "here's the JSON, you do it".
16. **Forbidden phrases** (these are regression markers — if you see yourself about to type any of these, stop and re-read rule 15):
    - "Save it via POST to the report-creation API endpoint when ready"
    - "Save it via the report-creation API endpoint when ready"
    - "to save, run `tl reports create --config '<json>'`"
    - "Saved as <path>.json" (without a campaign_id from the CLI)
    - "Saved to <path>" (without a campaign_id)
    - "held in working memory; not echoed to chat per the skill's rules"
    - "the campaign config (held in working memory…)"
    - "per the skill's rules" / "per the policy"
    - Any instruction telling the user to take a save action themselves when the original prompt was a save-intent prompt.
17. **Always render a plain-English filter summary in the user-facing reply** — both in save mode and preview mode. The summary is 4–7 short bullets describing **what the report contains**, not how it's stored. Use the "Filter summary pattern" translation table in the user-facing-language section near the top of this file. Mention only the filters that meaningfully shape what the user will see; skip platform defaults (e.g. don't bullet `channel_formats: [4]` when it's the type-3 default). Use the user's own brand and keyword wording verbatim where it fits. Example: *"results will be focused on fintech creators in MSN; only English-speaking channels with strong US audiences will be included; channels already pitched to Webull will be automatically excluded; results will prioritise creators with proven sponsorship history; outreach-ready columns and performance widgets will be added automatically"*. **Don't describe the report as "the config" or "the JSON" or "held in working memory"** — those are internal terms; the user wants to know what the report does.
18. **Save-mode preflight on the temp file is mandatory.** Per the Save-or-preview policy step 1+2: resolve a portable temp path via `python -c "import tempfile, os; print(...)"` BEFORE writing, then verify with `test -f <path>` AFTER writing. Hardcoding `/tmp/` on Windows fails silently. If the verification fails, surface a clean error explaining what happened (path, why) and offer the user the inline JSON as a fallback. Do not invoke `tl reports create --config-file` if the file isn't confirmed to exist — that just produces a confusing "No such file or directory" error.
19. **Narrate at phase-outcome level, not tool-call level.** The user doesn't need to see "Ran 19 commands, read 2 files" enumerated, or the raw text of every `tl db pg` query the skill issued during validation. Surface the phase outcomes in plain English: "Looking up StoryBlocks in the brand list… found it (47 deals on file)." not "Ran tl db pg --json 'SELECT id, name FROM thoughtleaders_brand WHERE name ILIKE %StoryBlocks%' which returned: {results: [{id: 868, name: 'StoryBlocks'}], total: 1, ...}". The harness shows tool-call detail in collapsible UI; the skill's narration is the high-level story alongside it.
20. **Save tail mandatory in every preview reply.** Always close with *"If you want this as a saved TL report, just say save."* The "skip when purely informational" exemption was over-applied; never skip it. Refinement offers do NOT substitute — both can appear (refinements first, save tail last on its own line — the last line is what the user sees most recently reading bottom-up).
20a. **Channel/video/brand names in the sample-rows table MUST be hyperlinked to the TL platform page** (not to YouTube). The user is browsing the result *in TL*; the link is the affordance to drill into a row's full TL profile. URL patterns:

| Sample-table column | Link target | Slug source |
|---|---|---|
| **Channel** (type 3 / type 8) | `https://app.thoughtleaders.io/youtube/<slug>` | `thoughtleaders_channel.slug` (resolve in Phase 2 alongside the sample) |
| **Brand** (type 2) | `https://app.thoughtleaders.io/brands/<slug>` | brand-side equivalent slug |
| **Title** (type 1 / videos) | `https://app.thoughtleaders.io/articles/<id>` (or whatever the platform's video-detail URL is) | the article id |

Render as Markdown links in the table cell — *not* the bare ID, *not* the YouTube URL, *not* both. Example for type 3:

```
| Channel                  | Subscribers | Last published |
|--------------------------|------------:|----------------|
| [Jubilee](https://app.thoughtleaders.io/youtube/jubilee) | 12.4M | 2 days ago     |
| [PewDiePie](https://app.thoughtleaders.io/youtube/pewdiepie) | 110M  | yesterday      |
```

If the slug is missing or empty for a row, fall back to the ID-based path the platform exposes (e.g. `https://app.thoughtleaders.io/youtube/id-<channel_id>`); never fall back to the YouTube URL — that takes the user *away* from TL. The Phase 2 sample query must include the slug column alongside the rendered fields, otherwise the table can't link properly.

**Sample-row enrichment column names — read from the canonical schema, do NOT improvise.** When the rendered table needs columns beyond what the initial ES sample returned (typically a slug for the hyperlink and a "last published" date), look up the column names in [`tl/references/postgres-schema.md` → `thoughtleaders_channel`](../tl/references/postgres-schema.md#thoughtleaders_channel-youtube-channels) before composing the PG query. Agents have improvised semantically-plausible column names from intuition (date-shape variants, platform-name-prefixed ID forms, bare-noun forms without table prefix, user-facing-term forms), hit a 400 with *"column '\<name\>' does not exist"*, then run an `information_schema.columns` fishing query to recover — a wasted round-trip that the canonical column catalogue eliminates. **If you find yourself about to write a `SELECT ... FROM thoughtleaders_channel WHERE ...` query and you're not sure of a column name, consult the schema reference first** — do not guess and rely on the 400 to correct you, and do not fall back to `information_schema.columns` as the recovery path. See the schema reference's "Hallucination shapes to avoid" subsection for the recurring guess patterns.

21. **No side-channel deliverables.** Two output shapes only: (a) saved TL report + report URL (save mode), (b) in-chat preview with sample-rows table + takeaways + save tail (preview mode). NO CSVs, NO Markdown report files, NO data dumps. If the user wants more than the preview shows, the answer is *"save it as a TL report and run it"* (NEVER "save it as a campaign" — rule 6). Only filesystem write allowed is the portable-temp transport file in save mode — transport, never deliverable.
22. **Phases 1–4 always run; never short-circuit to chat-only.** Output is ALWAYS a saved TL report (save mode) or a Phase-4 preview (preview mode). Bypassing Phase 1–4 to produce a free-floating markdown table / verification list / analyst summary is a regression bug. The analytical insight is welcome as a takeaway; it's NOT a substitute for the report. If you find yourself about to reply with a markdown table directly, ask: am I shipping a Phase-4 preview or bypassing the phases? Answer must always be the former.
23. **No ad-hoc data-engineering pipelines.** No Python consolidation scripts, no multi-stage CSV merge tools, no dedupe scripts, no false-positive filters as standalone files. The data plane is fixed: `tl db pg`, `tl db es`, `tl db fb`. Phase 2 issues queries directly to compose + validate the FilterSet — that's the entire data-side surface. If narration starts reading like a data engineer's bash session ("Run consolidation script", "Resolve /tmp via cygpath", "Find where /tmp files actually are"), STOP — restart from Phase 1 with a single composed query.

## Follow-Up Interactions

Every phase has explicit conditions where it must pause and ask the user, rather than guess. Follow-ups are not failures — they're a design feature that prevents silent-ship regressions.

| Phase | Follow-up trigger | What the skill asks |
|---|---|---|
| **1** | ReportType ambiguous (e.g., "show me Nike" — brand report? sponsorship deals?) | "Should this be a [type X] report or [type Y]?" + 2–3 suggested options |
| **1** | Input invalid (no recognizable ReportType signal) | Suggest valid types with one-sentence each |
| **2** | Required filter missing (e.g., type 8 without a date range — unbounded query) | "What time period should I cover?" |
| **2** | Filter input vague (e.g., "high-engagement channels" — what threshold?) | "Define [threshold]: by [metric A] above N? by [metric B]?" |
| **2** | T4 returned ambiguous name resolution (>1 active candidate per name) | "Which one of these did you mean?" + option list |
| **2** | T3 cross-reference returned unexpectedly large or zero result set | "The preliminary query matched [N] entities — narrow the date range or status filter?" |
| **2** | Validation: sample_judge returned `looks_wrong` (G11-class noise) | Mode B prompt: save anyway / refine / cancel — plain English only, citing 2–3 specific sample names; never expose internal terms (phase numbers, tool names, `validation_concerns`, `db_count`, `looks_wrong`). See "User-facing rendering (Mode B)" in the Phase 2 section. |
| **2** | Validation: 1 retry exhausted on empty/too_broad | Emit `decision: "alternatives"` — surface the count + failing shape; let the user choose refine / save anyway / cancel. Skill does NOT chain further validation cycles. |
| **3** | Column template + extra columns the user listed differ from each other | "Use the template's columns, the columns you listed, or both?" |
| **3** | Selected columns incompatible (e.g., requested `Views` on a type 3 report) | "[column] isn't available for [report type]; closest is [alternative]" |
| **3** | No columns provided AND no clear intent | "I'll use [type]'s default set unless you want a different focus (outreach / discovery / sponsorship-pitch)" |
| **4** | Aggregation/widget preferences need confirmation | "Default widgets for this report type are [list]; want to add/remove anything?" |
| **4** | Final JSON-shape validation surfaced unresolved issues | "Can't ship config because [reason]. Fix [thing]?" |
| **Post-save** | New prompt arrives after a successful save AND the topic overlaps with the prior save (same brand / niche / report type). Refinement signals strengthen the trigger but their absence does NOT bypass it when topic overlap is strong — refinement signals include vocabulary (*instead*, *change*, *swap*, *drop*, *add*, *tighter*, *broader*, *narrower*, *without*, *except*, *now with*, *but with*), filter/sort modifiers (*filter*, *limit*, *only*, *remove*, *replace*, *include*, *exclude*, *sort by …*), "make it X" framings, or partial-filter prompts that name a single filter axis without naming a new topic. | *"Looks like a refinement of the report you just created (#N — `<title>`). Update it in place, or save a separate variant?"* — default-highlight the update option; user can override. See "Editing a saved report" subsection above for the full mechanics. |

Skills that follow up are skills users trust. Silent assumptions are silent regressions.

## Data Sources & What They Own

| Source | Authoritative For | Connection |
|---|---|---|
| **`tl db es`** | Live content / channel / brand text search at scale (intelligence reports — types 1/2/3 primary validation engine) | tl-cli ≥ v0.6.2; sandboxed read-only ES search bodies; phrase-matching avoids the PG-ILIKE substring-noise problem |
| **`tl db pg`** | Live data: topics, sponsorships (AdLink relations — type 8 primary), small lookup queries; smoke-check fallback for intelligence reports when ES is unavailable AND the FilterSet pre-filters narrowly | tl-cli ≥ v0.6.2; sandboxed read-only SELECT, mandatory `LIMIT/OFFSET`, max 500 rows; CTE pattern required for any keyword-bearing intelligence query |
| **`references/intelligence_filterset_schema.json`** | Canonical filterset shape for types 1/2/3 (filter fields, defaults, validation rules) | Static file; consulted in Phase 2 (compose + validate) and Phase 4 (final JSON-shape validation) |
| **`references/sponsorship_filterset_schema.json`** | Canonical filterset shape for type 8 (status IDs, owner fields, date filters, filters_json semantics) | Static file; consulted in Phase 2 (compose + validate) and Phase 4 (final JSON-shape validation) |
| **`references/columns_<type>.md`** | Available columns + intent-driven default sets per ReportType | Static; consulted in Phase 3 |
| **`references/intelligence_widget_schema.json`** | Widget shape + aggregator catalog + default sets + intent overrides for types 1/2/3 | Static file; consulted in Phase 4 (compose) and Phase 4 (final JSON-shape validation) |
| **`references/sponsorship_widget_schema.json`** | Widget shape + aggregator catalog + default set + intent overrides + axis-branching rules for type 8 | Static file; consulted in Phase 4 (compose) and Phase 4 (final JSON-shape validation) |
| **`references/widgets.md`** | Readable index pointing at the two widget schemas | Static; convenience reference |
| **Conditional tools** (T1–T5) | Dynamic enrichment of the unified schema | Markdown files in `tools/` |

**Trust hierarchy:**
- For "does this row exist / how many" questions: **`tl db es`** for intelligence-report content / channel / brand search (types 1/2/3); **`tl db pg`** for sponsorship deal counts and small lookup queries (type 8 + topic / brand / channel name resolution).
- For filter shape and validation rules: the filterset + widget schema files (`*_filterset_schema.json` / `*_widget_schema.json`) — they're the ground truth for what's valid.
- For "what's available to display": the column files (`columns_<type>.md`) — they're the canonical list per report type.

If a tool's resolved ID disagrees with the user's name (e.g., emoji-stripped match), surface the discrepancy rather than silently substitute.

## Quick Start

### Run the skill on a query (in a Claude Code session that has this skill loaded)

```
USER: Build me a report of gaming channels with 100K+ subscribers in English
```

Claude follows this SKILL.md, executing each phase in order. No external command needed — the skill IS the orchestration; `tl db pg` is invoked from within Phase 2/3/4 as needed; tools fire conditionally per their criteria.

> **Save vs preview**: by default the skill runs Phases 1–4 and replies with takeaways + a sample-rows table — **no save**. Only when the user's prompt contains explicit save intent ("save", "create the report", "make a campaign for me to come back to") does the skill run the three save-mechanics steps: (1) **resolve a portable temp path** via `python -c "import tempfile, os; print(...)"`, (2) **Write** the JSON to that path and **verify** with `test -f`, (3) run `tl reports create --config-file <that-exact-path> --yes` via `Bash`. The file transport is shell-safe; passing the JSON inline as `--config '<json>'` breaks the moment any value contains an apostrophe ("McDonald's", "L'Oréal"). Hardcoding `/tmp/` fails on Windows. The user sees the takeaways and (in save mode) the resulting campaign link. **The JSON config never appears in chat in either mode.** For edits to an existing saved report, use `tl reports update <report_id> '<json patch>'` (same shell-quoting caveat — use a portable temp file when the patch contains apostrophes). Do NOT tell users to paste into the platform UI — that's an obsolete fallback from before the CLI commands existed. See the Save-or-preview policy near the top for the full trigger word lists.

## Reference Files

Load on-demand — don't read all upfront:

**Schema canonical sources** (consulted in Phase 2 + Phase 4)
- **[references/intelligence_filterset_schema.json](references/intelligence_filterset_schema.json)** — Filterset + filters_json shape for types 1 (CONTENT), 2 (BRANDS), 3 (CHANNELS). Mirrors `dashboard.models.FilterSet` 1:1: keyword fields (`keywords`, `keyword_operator`, `content_fields`, `keyword_content_fields_map`, `keyword_exclude_map`), `topics` (ChoiceArrayField IntegerField), date scopes, demographic shares, channel-formats, languages, reach / projected_views / youtube_views ranges, M2M relations (channels / brands / networks), defaults (`languages: ["en"]`, `channel_formats: [4]`), and `_tl_intent_overrides` for intent-driven population.
- **[references/sponsorship_filterset_schema.json](references/sponsorship_filterset_schema.json)** — Filterset shape for type 8 (SPONSORSHIPS). Same model as intelligence schemas, different relevant slice: M2M relations (sponsorships / channels / brands), date scopes (send / purchase / created), `filters_json.publish_status` for deal-stage encoding, `tl_sponsorships_only` flag. Type-8 reports filter by relations, not content text — keyword fields are inert here.

**Available columns per ReportType** (consulted in Phase 3)
- **[references/columns_content.md](references/columns_content.md)** — Type 1: video-level columns. Each column block: display_name, backend_code, when-to-use, default-on flag.
- **[references/columns_brands.md](references/columns_brands.md)** — Type 2: brand-aggregated columns.
- **[references/columns_channels.md](references/columns_channels.md)** — Type 3: channel-level columns. Includes intent-driven default sets: discovery / outreach / sponsorship-pitch.
- **[references/columns_sponsorships.md](references/columns_sponsorships.md)** — Type 8: deal-level columns. Includes Channel-info columns reused from type 3 (TL Channel Summary, Topic Descriptions, Subscribers, USA Share, Demographics - Age Median).

**Widget catalog** (consulted in Phase 4)
- **[references/intelligence_widget_schema.json](references/intelligence_widget_schema.json)** — JSON Schema for widget objects on types 1/2/3 reports. Disjoint aggregator catalog; per-type default 5-widget sets (`_tl_default_widget_set_by_type`); intent overrides (`_tl_intent_overrides`); selection rules.
- **[references/sponsorship_widget_schema.json](references/sponsorship_widget_schema.json)** — JSON Schema for widget objects on type 8 reports. Disjoint aggregator catalog (sponsorship pipeline / live ads / performance / assets-drafts groupings); axis-branching rules (`_tl_axis_branching`: pipeline → `send_date`, sold → `purchase_date`); default 5-widget set; intent overrides for the major sponsorship views (forecasting / won-deals / ROI / assets QA).
- **[references/widgets.md](references/widgets.md)** — Readable index pointing at the two schemas above.

**Filter semantics (cross-cutting)**
- **[references/report_glossary.md](references/report_glossary.md)** — Vocabulary disambiguation across the whole skill: report-type synonyms (uploads = content; channels = creators; campaign report ⇒ ambiguous), TL-specific terminology (Reach / PV / VG / MSN / TPP / MBN), deal-stage jargon (booked = sold = status 3; pipeline = active non-sold), field-pair disambiguation (reach vs projected_views vs youtube_views), defaults, filter-source decisions (typed field vs `filters_json`), common pitfalls.
- **[references/sortable_columns.json](references/sortable_columns.json)** — Sort metadata per column (asc-only / desc-only / both). Consulted in Phase 3's sort selection.

**Conditional tools** (loaded only when Phase 2 invokes them)
- **[tools/topic_matcher.md](tools/topic_matcher.md)** — Topic verdicts against live `thoughtleaders_topics`.
- **[tools/database_query.md](tools/database_query.md)** — Cross-reference query: resolves a prerequisite condition into a set of IDs that the main FilterSet includes/excludes.
- **[tools/name_resolver.md](tools/name_resolver.md)** — Progressive name → entity_id matching with ambiguity surface.
- **[tools/similar_channels.md](tools/similar_channels.md)** — Look-alike helper: emits `filters_json.similar_to_channels` for the platform's vector-similarity engine.
- **[tools/sample_judge.md](tools/sample_judge.md)** — Sample inspection inside Phase 2's validation step. Type-aware row contract: type 3 cites `channel_name`, type 1 cites `title`, type 2 cites `brand_name`. Intelligence reports only (skipped for type 8). Catches substring noise and intent mismatch (G11-class) before the FilterSet ships to Phase 3.
- **[tools/column_builder.md](tools/column_builder.md)** — Phase 3's column-selection prompt. Same builder-prompt pattern as `widget_builder`: explicit inputs, JSON output schema, selection process (defaults → intent additions → niche additions → sort validation → formula proactivity), worked examples per report type, hard rules. Consumes `references/columns_<type>.md` as the catalog.
- **[tools/widget_builder.md](tools/widget_builder.md)** — Phase 4's widget-selection prompt. Mirrors v1's widget-builder approach: selection guidelines, intent-driven swaps, type-8 axis branching, and worked examples per report type. Consumes the matching `*_widget_schema.json` (intelligence or sponsorship) as the catalog.

**Examples & golden corpus**
- **[examples/golden_queries.md](examples/golden_queries.md)** — 13 hand-curated NL inputs (G01–G13) covering all four report types and the full mode space (proceed / alternatives / vague). Documentation/regression corpus — not loaded at runtime. Test fixtures for shadow-mode comparison and skill maintenance. Note: G07 (`partnership` routing) and G11 (`IRS` substring noise) are inlined in SKILL.md's Phase 1 and Phase 2 detail sections as authoritative regression baselines.

## Pagination Defaults (Phase 3 applies these unless USER_QUERY overrides)

| ReportType | Page size | Sort default | Notes |
|---|---|---|---|
| 1 (CONTENT) | 50 | `-views` | Per-video; longer pages tolerable |
| 2 (BRANDS) | 25 | `-doc_count` | Aggregated rows; smaller pages |
| 3 (CHANNELS) | 25 | `-reach` (default) / `-publication_date_max` (outreach intent) | Sort branches on intent_signal |
| 8 (SPONSORSHIPS) | 50 | `-purchase_date` (sold) / `-send_date` (proposal stages) | Axis branches on `publish_status` per `sponsorship_widget_schema.json`'s `_tl_axis_branching` |

## Safety

- **`tl db pg`**: read-only SELECT only. The skill never attempts INSERT/UPDATE/DELETE through this surface. Mandatory `LIMIT n OFFSET m`, max 500 rows. Forbidden function list: `random`, `pg_sleep`, `current_user`, `version`, `pg_read_file`, `lo_export`, `dblink`, `current_setting`, `set_config`.
- **`tl db es`**: read-only search bodies only. Index is fixed server-side (no client-side index selection). Always include explicit `size` (default to small values; cap at the ES sandbox's allowed maximum). Use `bool.filter` for non-scoring constraints and `must` / `should` for keyword scoring. Never request `_source: false` then rely on stored fields the sandbox doesn't expose.
- **Tool warnings**: every tool that resolves names with non-exact matching MUST surface the match-quality in `_routing_metadata.tool_warnings`. Phase 4 surfaces these in takeaway insights — silent name-substitution is forbidden.
- **Follow-ups over assumptions**: when a phase encounters ambiguity that affects the output, the skill MUST ask rather than guess. Phase-by-phase trigger list is in the "Follow-Up Interactions" section above.

## Self-Improvement

After every significant report-build task, ask:

1. **New filter field encountered or schema mismatch with the dashboard?** → Update `references/intelligence_filterset_schema.json` or `references/sponsorship_filterset_schema.json`.
2. **New column requested that isn't in the column list?** → Add to `references/columns_<type>.md` with `display_name`, `backend_code`, when-to-use.
3. **Conditional tool fired wrongly (false positive or false negative)?** → Refine the criterion in this SKILL.md's "Conditional Tool Invocation" section AND in the tool's own front-matter.
4. **Name resolution failed silently?** → Update `tools/name_resolver.md` matching strategy. Surface the discrepancy in tool warnings; never silently substitute.
5. **Pagination, sort, or aggregation default felt wrong?** → Update the "Pagination Defaults" table above + `references/columns_<type>.md` intent-default tables.
6. **Sample judge mis-routed (silent ship of bad sample, or false `looks_wrong`)?** → Update `tools/sample_judge.md` thresholds.
7. **Follow-up trigger missed (skill assumed instead of asking)?** → Add the trigger to the "Follow-Up Interactions" table; codify the question wording.
8. **New takeaway insight worth standardizing?** → Add to Phase 4's takeaway-composition rules in this SKILL.md.

The reference files are the source of truth for schemas and columns. SKILL.md is the orchestration spec. Tools are conditional sub-routines. Each layer's responsibility stays separate; bleeding logic across layers (e.g., column rules into the schema file) creates the duplication this architecture is designed to avoid.
