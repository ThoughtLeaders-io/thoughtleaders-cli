---
name: tl-save-report
tl-blurb: save a session as a report
description: |
  Save the results of an in-chat data-exploration session as a TL report. Triggers when the user wants to persist a channels / brands / videos (uploads) / sponsorships list or filtered set they've been working with — phrases like "save this as a report", "save the list", "turn this into a campaign", "persist this", "make a report from what you found", "save the result", "I want to come back to this".
---

# tl-save-report

Persist what the user has been exploring as a saved TL report. The skill assumes the data-exploration phase already happened — it does not re-run queries, re-validate the result set, or ask the user what they were looking for. Its single job is **config-from-session**.

## The two paths

Every save goes through exactly one of these:

- **[Path A — List-style](#path-a--list-style)** uses `tl reports save-list`. Snapshot a curated set of entity IDs into a frozen list (no filter re-evaluation). One command; the platform applies sensible defaults for columns / widgets / sort, and the user refines via `tl reports update` afterwards if needed. Use when the user curated the set or when the session's filters can't be expressed as FilterSet fields.
- **[Path B — Filter-style](#path-b--filter-style)** uses `tl reports create --config-file`. Translate the session's criteria into a live FilterSet that re-evaluates against current data every time someone re-runs the report. Builds a full config (columns + widgets + sort). Use when the session was driven by criteria the FilterSet can express directly.

The only discovery-side work this skill performs is **name → ID resolution** (`tl brands find` / `tl channels find`) — required by the schema, not a re-evaluation of the result set. If the user has no prior session, run the relevant `tl db pg|fb|es` queries to produce a result set first, then invoke this skill on the result.

## Reference files (what each is for)

This skill is self-contained. Every reference it needs is in [`references/`](references/):

| File | Use when |
| --- | --- |
| [`intelligence_filterset_schema.json`](references/intelligence_filterset_schema.json) | Path B for **CONTENT / BRANDS / CHANNELS** FilterSets (report_type 1 / 2 / 3). Authoritative field catalogue; unknown keys are rejected by the platform with 400. |
| [`sponsorship_filterset_schema.json`](references/sponsorship_filterset_schema.json) | Path B for **SPONSORSHIPS** FilterSets (report_type 8). Disjoint field set from the intelligence schema — date axes, publish_status, no keyword fields. |
| [`columns_content.md`](references/columns_content.md) / [`columns_brands.md`](references/columns_brands.md) / [`columns_channels.md`](references/columns_channels.md) / [`columns_sponsorships.md`](references/columns_sponsorships.md) | Path B column choices per report type. Defaults, intent-driven additions, custom-formula guidance. |
| [`intelligence_widget_schema.json`](references/intelligence_widget_schema.json) / [`sponsorship_widget_schema.json`](references/sponsorship_widget_schema.json) | Path B widget choices. Each schema lists the aggregator catalogue, default widget sets per report type, intent overrides, and (for type 8) the date-axis branching rules. |
| [`widgets.md`](references/widgets.md) | Readable index of the widget catalogue. Equivalent content to the JSON schemas but easier to skim — start here, drill into the schema for the canonical shape. |
| [`sortable_columns.json`](references/sortable_columns.json) | Per-column sort metadata (asc-only / desc-only / both). The `sort` value on a report must reference a column listed here with an allowed direction. |
| [`report_glossary.md`](references/report_glossary.md) | Disambiguation: report-type synonyms, TL terminology (MSN / TPP / MBN / VG / Net revenue / TL profit), deal-stage jargon (numeric publish_status ↔ user phrasing), field-pair choices, common pitfalls. |

## Report types

| `report_type` | User-facing name | Row | Schema family |
| --- | --- | --- | --- |
| **1** | CONTENT / Uploads | one video / article / podcast episode | intelligence |
| **2** | BRANDS | one brand (aggregated across matching content) | intelligence |
| **3** | CHANNELS | one YouTube channel (or podcast) | intelligence |
| **8** | SPONSORSHIPS / Deals | one sponsorship record (AdLink — brand × channel × dates × status × price) | sponsorship |

Types 1 / 2 / 3 share the intelligence FilterSet and widget schemas (different rows, same predicate fields). Type 8 has its own schemas (disjoint fields, different aggregators, different data plane — Postgres against `v_adspot_brand_profiles` rather than Elasticsearch).

## When to invoke

**Invoke when** the user has been exploring data in the current session (running `tl db pg|fb|es` queries, structured `tl` commands, or both) and now wants to **save the result** as a report they can come back to. Trigger phrases include:

- "save this as a report" / "save the list" / "save the result"
- "turn this into a campaign" / "persist this"
- "make a report from what you found"
- "I want to come back to this" / "set up a report for these"

The entity being saved must be one of: **channels**, **brands**, **videos / uploads / articles**, or **sponsorships / deals**.

**Skip when**:

- The user wants to **add to an existing report** (`"add these channels to report 1234"`) → use the `tl bulk-import` command, not this skill.
- The user only wants the data **shown / counted / analysed in chat** without saving → stay in `tl`; don't invoke this skill.
- The user wants to build a report **from scratch** with no prior session exploration to capture — that's a different shape of request (the user has a goal, not a result set). Run the appropriate `tl db pg|fb|es` queries to produce a result set first; then this skill takes over for the save.

## Step 1 — Detect the report type

Match the session's primary entity to one of four report types:

| Session entity | Report type | `report_type` code |
| --- | --- | --- |
| Channels | CHANNELS | `3` |
| Brands | BRANDS | `2` |
| Videos / uploads / articles | CONTENT | `1` |
| Sponsorships / deals / adlinks | SPONSORSHIPS | `8` |

### Pick without asking when one entity is unambiguous

If the session's exploration focused on a single entity type — e.g. only channel queries, only brand lookups, only sponsorship listings — the report type is the matching row above. No need to ask.

### Ask the user when the entity is unclear

Don't guess in any of these cases — ask the user before proceeding to Step 2:

- **The session joined entities** — e.g. channels with their recent sponsorships, brands with their mentioning videos. Either side could plausibly be the saved row.
- **The save request is ambiguous** — e.g. *"save what we just looked at"* after the session touched multiple entity types.
- **The user's wording mixes terms** — e.g. *"save these creators and their deals"*; both `channels` (3) and `sponsorships` (8) are in play, the user has to pick one.

Suggested wording:

> The session touched a few different entity types. Which one should be the saved report's row?
>
> • **CHANNELS** — one row per YouTube channel
> • **BRANDS** — one row per brand, aggregated across mentions
> • **CONTENT** — one row per upload (video / podcast / article)
> • **SPONSORSHIPS** — one row per deal (brand × channel × dates × status × price)

Use the report-type name (CHANNELS / BRANDS / CONTENT / SPONSORSHIPS) when talking to the user — never the numeric `report_type` code. The numeric code is an internal config value; users don't think about reports as "type 3", they think about them as "a channels report".

Don't proceed without an answer — guessing the wrong row makes the rest of the workflow (FilterSet shape, columns, widgets) wrong too. The non-chosen side becomes either a column or a filter on the saved report, not the report's subject.

## Step 2 — Choose the path: list-style or filter-style?

This branch determines everything downstream. **Style is decided by intent, not entity** — both styles work for all four report types.

| Style | Populates | Re-evaluates? | When it's the right answer |
| --- | --- | --- | --- |
| **List-style** | M2M field (`channels` / `brands` / `articles` / `sponsorships`) | No — frozen list | Curated set, manual review, custom-SQL filters that don't map to FilterSet fields |
| **Filter-style** | Predicate fields (`keywords`, `reach_from`, dates, demographics, etc.) | Yes — every run | Criteria-driven discovery the user wants to keep refreshing |

### Pick without asking when intent is clear

Pick **list-style** when:

- The session used custom-SQL joins, multi-source aggregation, or filter logic that doesn't map to any FilterSet field — the honest move is to snapshot the IDs.
- The user said *"snapshot"*, *"freeze"*, *"this exact list"*, *"don't re-evaluate"*, *"the ones we picked"*, *"these N channels"*.
- The session pulled IDs through a manual review pass (user accepted/rejected candidates one by one).

Pick **filter-style** when:

- The session's full filter logic maps cleanly to FilterSet fields (keyword + subscriber floor + country + date range — nothing exotic).
- The user said *"refreshable"*, *"keep updating"*, *"any new channels that match"*, *"a saved search"*, *"channels in the X niche with >Y subs, all-time"*.

### When to ask

If both styles are plausible, ask before assembling anything:

> Two ways to save this:
>
> • **Filter-style** — I map the criteria from this session (subscriber floor, content categories, keywords, date range, etc.) into the report's filters. The report stays live: every time someone re-runs it, the filters re-evaluate against current data and the result set refreshes.
>
> • **List-style** — I snapshot the exact entity IDs we found in this session. The list is frozen — it always shows these IDs, no filter logic. Useful when you've curated the set and don't want re-evaluation.
>
> Which do you want?

### Hybrid (rare; confirm first)

Populating both predicate and M2M fields on the same FilterSet is *legal* but rarely intended. The result set becomes "IDs in the M2M that ALSO pass the predicate," which is almost never what the user said they wanted. The one common legit case is the `exclude_*` variants (e.g., *"channels matching X, except these specific IDs"*) — both halves get populated by design. Otherwise, confirm before mixing.

Once you've picked the path, follow it linearly to the end. **Don't mix steps between paths.**

---

# Path A — List-style

The simple path: one command, no columns / widgets / sort to assemble. The platform applies defaults; the user refines via `tl reports update` afterwards if needed.

## A1. Collect / resolve the entity IDs

| Entity | ID shape | Exclude variant |
| --- | --- | --- |
| Channels | integer IDs | `exclude_channels` |
| Brands | integer IDs | `exclude_brands` |
| Videos / uploads / articles | composite string `<channel_id>:<youtube_id>` (matches ES `_id`) | `exclude_articles` |
| Sponsorships | integer IDs (AdLink IDs) | `exclude_sponsorships` |

**Article IDs are the composite string form**, not bare YouTube video IDs. If the session has YouTube IDs (`dQw4w9WgXcQ`) without channel prefixes, fetch `channel.id` for each via `tl db es` and rebuild the composite form before saving.

If any IDs are still names (e.g., the session resolved channel names but not their numeric IDs), resolve before writing the IDs file:

```bash
tl brands find "NordVPN" --json   | jq -r '.results[0].id'   # → 21416
tl channels find "MrBeast" --json | jq -r '.results[0].id'   # → 11169
```

## A2. Title and description

Both are mandatory; `tl reports save-list` rejects blank values with HTTP 400.

- **Title** — ≤ 60 chars. Capture the niche or intent: *"TPP fintech — May 2026 curated"*, *"Speedcubing top videos"*, *"Q1 2026 sold sponsorships — beauty brands"*.
- **Description** — 1–3 sentences. **State explicitly "List-style"** so future readers know what they're looking at (the dashboard renders list-style and filter-style reports identically).

Propose values and let the user edit. Don't ship blank strings.

## A3. Save with `tl reports save-list`

```bash
# Write the IDs to a temp file, one per line —
# integers for channels/brands/sponsorships;
# composite `<channel_id>:<youtube_id>` strings for articles.
IDS=$(mktemp -t tl-save-list-XXXX.txt)
printf '5607\n12345\n67890\n' > "$IDS"

tl reports save-list channels --ids-file "$IDS" \
    --title "TPP fintech — May 2026 curated" \
    --description "List-style: 3 channels hand-picked after the May 2026 review pass." \
    --yes --json
```

- Entity must be one of: `channels`, `brands`, `articles`, `sponsorships`.
- `--yes` skips the confirmation prompt (the user already chose the path).
- `--json` makes the response parseable so you can extract `report_url` and `campaign_id` cleanly.

The command builds the minimal config (M2M field populated, no predicate fields, platform defaults for columns/widgets/sort) and POSTs in one call. Skip directly to [Step 3 — Report back](#step-3--report-back) when done.

## A4. List-style self-check (before posting)

1. `--title` is non-empty and ≤ 60 chars; `--description` is 1–3 sentences and explicitly says "list-style".
2. The entity argument matches the session's primary entity (`channels` / `brands` / `articles` / `sponsorships`).
3. Every line in the IDs file is the right shape — integers for channels/brands/sponsorships; composite `<channel_id>:<youtube_id>` strings for articles.
4. **No FilterSet predicate fields** to populate — list-style is the M2M IDs and nothing else. (If the user actually wants a predicate overlay, that's the hybrid case in Step 2; confirm and switch to Path B with a populated M2M.)

---

# Path B — Filter-style

Assemble FilterSet + columns + widgets + sort, then POST via `tl reports create --config-file`.

## B1. Map session criteria into the FilterSet

The authoritative field catalogues are in [`references/intelligence_filterset_schema.json`](references/intelligence_filterset_schema.json) (types 1 / 2 / 3) and [`references/sponsorship_filterset_schema.json`](references/sponsorship_filterset_schema.json) (type 8). **Don't invent fields.** The schema's keys are the only ones the platform accepts; unknown keys come back as a 400 with the offending field named in the error detail. Read the schema file for the field you're about to emit if you're not sure of its exact name or type.

### Resolve names → IDs BEFORE emitting

The platform rejects names in any field that expects an integer ID. Every brand name and channel name the user mentioned in the session must be resolved to an integer ID before it lands in the FilterSet:

```bash
tl brands find "NordVPN" --json   | jq -r '.results[0].id'   # → 21416
tl channels find "MrBeast" --json | jq -r '.results[0].id'   # → 11169
```

Fields that need integer IDs (not names):

- `channels`, `exclude_channels`, `brands`, `exclude_brands`, `sponsorships`, `exclude_sponsorships`, `topics`, `content_categories` (those last two take taxonomy IDs)
- `filters_json.sponsored_brand_mentions[]` — brand IDs as strings or ints depending on shape (check schema)

For type 8 specifically: a SPONSORSHIPS report with unresolved names is a hard failure — the saved report returns zero rows because the M2M write silently skipped the bad entries.

### `keyword_operator` — AND vs OR

Default `OR` (the platform defaults to OR when `keyword_operator` is null). Set `AND` only when the user's phrasing has clear intersection semantics:

- Composite-noun phrases: `"AI cooking"`, `"Roman naval warfare"`, `"vegan keto"`.
- Explicit conjunctions: `"both X and Y"`, `"covering both X and Y"`.

When in doubt, OR. Under AND, expand the keyword set conservatively — every keyword must match, so adding broad terms shrinks the result to near zero. If the session used `tl-keyword-research --operator AND`, mirror it; the skill emits the right operator already.

### `content_fields` per report type — narrow-first for type 3

`content_fields` is the field set the keyword search runs against. **Pick by report type, and for type 3 specifically use the narrow-first rule** — broader `content_fields` means more matches but more noise:

| `report_type` | Default `content_fields` | When to expand |
| --- | --- | --- |
| 1 (CONTENT) | `["title", "summary", "content"]` (video-level text) | Add `["transcript"]` only if the user explicitly mentioned "transcript" / "spoken-word" / "creators saying". |
| 2 (BRANDS) | `["title", "summary"]` (brand-mention surfaces) | Rarely expanded; brand reports aggregate over mentions, not deep text. |
| 3 (CHANNELS) | **`["channel.channel_name", "channel_description"]` ONLY** on the first save | Add `channel_description_ai` + `channel_topic_description` only if the narrow set obviously misses channels the session matched. The AI-summarised fields catalogue every topic a channel has *ever* touched — they answer *"has this channel ever mentioned X"* (too broad for discovery) rather than *"is this channel ABOUT X"* (what `channel_name` + `channel_description` answer). Field selection is the bigger dial; keyword pruning is the fine-tune. |
| 8 (SPONSORSHIPS) | n/a — keyword fields are inert for type 8 | Sponsorships filter by relations, not content text. Don't emit `keywords` / `keyword_operator` / `content_fields` at all for type 8. |

### Date scoping by report type

| `report_type` | Date fields | Notes |
| --- | --- | --- |
| 1 / 2 / 3 | `start_date`, `end_date`, `days_ago`, `days_ago_to` | Apply to `publication_date` of the underlying content. Prefer `days_ago` for rolling intent ("last 90 days") and `start_date`/`end_date` for absolute ("Q1 2026"). |
| 8 | **Send axis**: `start_date`, `end_date`, `days_ago`, `days_ago_to`. **Created axis**: `createdat_from`, `createdat_to`. | **Type 8 ALWAYS needs a date scope.** Unscoped type-8 reports return the entire AdLink table — almost never what the user wanted. Pick one axis based on intent: send axis = "deals scheduled / live / sold in this window"; created axis = "deals created in this window regardless of when they ship". Mix both axes only if the user named both explicitly. |

Date upper bounds: `start_date` / `end_date` are date-typed and use `< next_day` semantics internally, not `<=`. *"Through Feb 28"* → `end_date: "2026-02-28"`; don't add a day.

### `publish_status` (type 8 only) — numeric IDs, not strings

Sponsorship `publish_status` values are numeric IDs from the set `{3, 4, 5, 7, 9, 10}`, **never string labels**. Don't emit `["sold"]` or `["live"]`. The canonical user-phrase → ID mapping is in [`references/report_glossary.md`](references/report_glossary.md) under "Deal-stage jargon". Quick anchors:

- `[3]` = sold
- `[7, 10]` = pipeline / pre-sale (matched / open)
- `[3]` + `filters_json.ad_publish_status: "0"` = sold + currently live on the channel

The `publish_status` field lives inside `filters_json`, not as a top-level FilterSet field.

### Working defaults (override only on user signal)

Unless the user explicitly contradicts them, default these on the FilterSet:

- `languages: ["en"]` — most reports are English-content scoped.
- `channel_formats: [4]` — YouTube Video. Other formats: `1`=podcast, `2`=long-form audio, `3`=other, `4`=YouTube Video (default), `5`=Shorts.

If the user said *"any language"* or *"Spanish creators"* / *"podcasts"*, override accordingly.

### Cross-references and similar-to-channels

These compose with the rest of the FilterSet rather than replacing it:

- **`cross_references[]`** — named cross-cuts that resolve to channel ID include / exclude lists at save time. Catalog: `exclude_proposed_to_brand`, `include_proposed_to_brand`, `include_sponsored_by_mbn`. Each item is `{"type": "<name>", "brand_id": <int>, "since_days_ago": <int?>}`. Use for *"channels we haven't pitched to brand X"* / *"channels sponsored by MBN brands"*. The platform's `/reports/confirm` endpoint resolves these into `channels` / `exclude_channels` M2M arrays during the save.
- **`filters_json.similar_to_channels: [<id>, …]`** — vector-similarity expansion against seed channel IDs. Pair with **no `keywords` / `topics`** (similarity replaces topical filtering). Useful for *"channels like X and Y"* once you've resolved X/Y to IDs.

### Complete mapping (common session criteria → FilterSet field)

| Session criterion | FilterSet field |
| --- | --- |
| Topic keywords (`"crypto"`, `"biohacking"`) | `keywords[]` + `keyword_operator` + `content_fields[]` |
| Curated topic the user named by ID or exact name | `topics: [<id>]` (still expand the topic's curated `keywords[]` per the schema's `_tl_intent_hints`) |
| Subscriber floor | `reach_from` (or `min_reach` — check schema) |
| Views / impression floor | `views_from`, `impression_from`, etc. |
| Content category (when user explicitly named a TL category) | `content_categories: [<id>]` |
| Country / language | `creator_countries: [...]`, `languages: [...]` |
| MSN-only | `msn_channels_only: true` |
| TPP-only | resolve `SELECT id FROM thoughtleaders_channel WHERE is_tl_channel = TRUE AND is_active = TRUE` and pin into `channels: [...]` (no first-class TPP boolean on FilterSet) |
| Demographics (age / gender / geo / device) | `demographic_male_share`, `demographic_usa_share`, `demographic_geo`, `demographic_device`, `demographic_age_median_value`, etc. — see schema |
| Publication date range (types 1 / 2 / 3) | `start_date`, `end_date`, or `days_ago` / `days_ago_to` |
| Sponsorship send-date range (type 8) | `start_date` / `end_date` / `days_ago` / `days_ago_to` |
| Sponsorship created-date range (type 8) | `createdat_from` / `createdat_to` |
| Deal stage (type 8) | `filters_json.publish_status: [<int>, …]` (numeric IDs) |
| Currently-live deals (type 8) | `filters_json.publish_status: [3]` + `filters_json.ad_publish_status: "0"` |
| Cross-reference ("not pitched to brand X") | `cross_references: [{"type": "exclude_proposed_to_brand", "brand_id": <int>, "since_days_ago": 365}]` |
| Look-alike channels ("similar to X and Y") | `filters_json.similar_to_channels: [<id>, …]` (drop any `keywords` / `topics` on the same FilterSet) |
| Brand-mention filter | `filters_json.sponsored_brand_mentions: [<id_or_str>, …]` |
| TL-managed only (type 8) | `tl_sponsorships_only: true` |
| Brand / channel scoping by entity | `brands: [<int>, …]`, `channels: [<int>, …]` (resolve names FIRST) |

If the session used filters that don't map to any field above, tell the user: *"I can't express [the specific predicate] as a FilterSet field — the platform doesn't surface it directly. Want to fall back to list-style for this report?"* That's the honest move; don't fudge it into `filters_json` if a typed field doesn't already exist.

## B2. Title and description

Both are mandatory; `tl reports create` rejects with HTTP 400 if either is missing.

- **`report_title`** — ≤ 60 chars. Capture the niche or intent: *"TPP fintech channels — May 2026"*, *"Q1 2026 sold sponsorships, beauty brands"*.
- **`report_description`** — 1–3 sentences. Summarise what's in the report and how it was assembled. **State explicitly "Filter-style"** so future readers know what they're looking at (the dashboard renders list-style and filter-style reports identically).

Propose values and let the user edit. Don't ship blank strings.

## B3. Pick columns and sort

### Columns

Use the type's default column set; agents shouldn't compose columns from scratch when the session didn't specify any. Per-type catalogues (defaults, intent-driven additions, custom-formula guidance):

- Type 1: [`references/columns_content.md`](references/columns_content.md)
- Type 2: [`references/columns_brands.md`](references/columns_brands.md)
- Type 3: [`references/columns_channels.md`](references/columns_channels.md)
- Type 8: [`references/columns_sponsorships.md`](references/columns_sponsorships.md)

If the session showed the user specific columns (`"show reach, subscribers, country"`), include those PLUS the type's required defaults. Display names are case-sensitive and preserve spaces — `Subscribers` not `subscribers`, `Avg. Views` not `avg_views`. The platform key-matches exactly; a typo comes back as a 400 with the offending column name in the error detail.

Pick **5–10 columns** for most reports; the platform allows up to 13 if intent calls for it (the dashboard's column rail starts to feel crowded past 10).

### Sort

`sort` is a FilterSet field referenced by string like `"-reach"` (descending) or `"publication_date"` (ascending). Pick by intent first, then fall back to the type's default:

| Intent | Sort | Applies to |
| --- | --- | --- |
| User said "top X by [metric]" | the metric, `-` prefix for desc | any type |
| User said "most recent" / "latest" | `-publication_date` (1/2/3) or `-purchase_date` (8 sold) or `-send_date` (8 pipeline) | by report type |
| Outreach intent on channels | `-publication_date_max` (channels with recent uploads bubble up) | type 3 |
| **No explicit intent** — fall back to type default | `-reach` (type 3), `-views` (type 1), `-doc_count` (type 2), `-purchase_date` for sold + `-send_date` for pipeline (type 8) | by report type |

**Two hard requirements on the sort value:**

1. The column it references must be **present in the emitted `columns` dict**. If you sort on `-publication_date_max` but `Last Published` isn't in your columns, the report renders blank for that sort. If a mismatch exists, either add the column or pick a different sort.
2. The direction must match what `references/sortable_columns.json` allows. Some columns are asc-only (like `Channel`), some desc-only (like `Subscribers`), some both. A direction mismatch is silently downgraded to the column's natural direction — confusing if the user expected the opposite.

### Custom-formula columns

When the session showed a computed value the standard columns don't express (e.g. *"engagement = avg views / subscribers"*, *"profit = price − cost"*), emit a custom-formula column. The per-type `columns_<type>.md` files list suggested formulas for common intents (engagement, outreach efficiency, audience-share, profit, renewal-rate proxy).

Shape:

```json
"columns": {
  "Engagement": {"display": true, "custom": true, "formula": "{Avg. Views} / {Subscribers}", "cellType": "percent"}
}
```

- `{Variable Name}` references another standard column by display name (case-sensitive, spaces preserved).
- `cellType` controls dashboard rendering: `regular` / `percent` / `usd`.
- Use TL-glossary terms in narration ("Net revenue" / "TL profit", not "margin" — see [`references/report_glossary.md`](references/report_glossary.md)).

Don't silently activate a custom column. Propose it in the title / description (*"with a custom Engagement column = Avg. Views / Subscribers"*) so the user knows it's there.

## B4. Pick widgets and `histogram_bucket_size`

Widgets are the charts / metric boxes above the data table. Pick **4–6** per report. Catalogues live in:

- Types 1 / 2 / 3: [`references/intelligence_widget_schema.json`](references/intelligence_widget_schema.json)
- Type 8: [`references/sponsorship_widget_schema.json`](references/sponsorship_widget_schema.json)
- Readable index: [`references/widgets.md`](references/widgets.md)

### Default widget sets per report type

Each `aggregator` value below is from the matching schema's catalogue. The two catalogues are **disjoint** — never use an intelligence aggregator on a type-8 report or vice versa (server fails 400).

| `report_type` | Default widgets (5, indexed 1–5) |
| --- | --- |
| 1 (CONTENT) | `total` (M), `views_sum_metric` (M), `views_avg_metric` (M), `uploads_histogram` (H), `views_sum_histogram` (H) |
| 2 (BRANDS) | `brands_count_metric` (M), `total` (M), `views_sum_metric` (M), `brands_count_histogram` (H), `views_sum_histogram` (H) |
| 3 (CHANNELS) | `channels_count_metric` (M), `channel_reach_at_scrape_metric` (M), `views_avg_metric` (M), `channel_reach_at_scrape_histogram` (H), `uploads_histogram` (H) |
| 8 (SPONSORSHIPS) | `count_sponsorships` (M), `sum_price` (M), `count_channels` (M), `count_sponsorships_over_<axis>` (H), `sum_price_over_<axis>` (H) — `<axis>` per branching rule below |

M = metrics-box (`width: 2`), H = histogram (`width: 3`). `height: 1` always. Grid is 6 columns. Widget shape:

```json
{"aggregator": "<from catalogue>", "type": "metrics-box" | "histogram" | "histogram-category",
 "index": <1-based, sequential>, "width": 2 | 3, "height": 1}
```

Pick by intent when the session implied one — see `_tl_intent_overrides` in the schema (outreach swaps `sponsored_brands_count_metric` in for type 3; engagement focus on type 1 swaps `views_avg_metric` for `likes_sum_metric`; etc.). Don't pad to 6 if the extras don't earn their slot.

### `histogram_bucket_size`

One top-level value per report, applies to every histogram in it:

| Date scope on the FilterSet | `histogram_bucket_size` |
| --- | --- |
| < 90 days | `"week"` |
| 90 days – 2 years | `"month"` (default) |
| Multi-year | `"year"` |

Match the FilterSet's date scope. If the FilterSet has no date scope (rare for types 1 / 2 / 3, never legal for type 8), default to `"month"`.

### Type-8 axis branching (send_date vs purchase_date)

For type 8 only, the `_over_<axis>` histograms (`count_sponsorships_over_send_date` vs `count_sponsorships_over_purchase_date`, and same for `sum_price`) branch on deal stage:

| `filters_json.publish_status` includes | Use axis | Aggregator names |
| --- | --- | --- |
| Pre-sale (7, 10) — matched / open | `send_date` (pipeline view) | `count_sponsorships_over_send_date`, `sum_price_over_send_date` |
| Sold only (3) | `purchase_date` (won-deals view) | `count_sponsorships_over_purchase_date`, `sum_price_over_purchase_date` |
| Mix of pre-sale + sold | `send_date` (pipeline view dominates) | as pipeline |
| Performance grades (winners/losers) | `purchase_date` | as won-deals |

**Both `_over_<axis>` histograms in the same report must share the same axis.** Don't mix `send_date` and `purchase_date` within one report — the dashboard renders confusingly when the two axes disagree.

## B5. Assemble the config

Final config shape (`Campaign` + `FilterSet` + columns + widgets):

```json
{
  "type": 2,
  "report_type": 1 | 2 | 3 | 8,
  "report_title": "...",
  "report_description": "...",
  "filterset": { ... },
  "columns": { ... },
  "widgets": [ ... ],
  "histogram_bucket_size": "month",
  "sort": "-reach"
}
```

`type=2` (DYNAMIC) is the campaign-model contract; don't change it.

Write to a portable temp file and verify the file exists before saving:

```bash
TMP=$(mktemp -t tl-save-report-XXXX.json)
cat > "$TMP" <<'EOF'
{ ...config... }
EOF
ls -la "$TMP"   # verify before save
```

**Don't write the transport file under the user's project directory.** It's a transport, not a deliverable.

## B6. Pre-flight validation

Before posting, validate the assembled config against the schemas. The platform's own validation will catch most errors, but a pre-flight pass catches the cheap mistakes without burning a save-side round-trip:

1. **Required fields present**: `type`, `report_type`, `report_title`, `report_description`, `filterset`.
2. **`report_title`** is a non-empty string ≤ 60 chars.
3. **`report_description`** is a non-empty 1–3 sentence string that explicitly says "filter-style".
4. **`report_type`** is `1` | `2` | `3` | `8`; `type` is `2`.
5. **Every key in `filterset`** is a property in the matching schema (`intelligence_filterset_schema.json` for types 1/2/3, `sponsorship_filterset_schema.json` for type 8). Unknown keys → 400.
6. **For type 8**: a date scope is populated on one of the two axes (send or created). Unscoped type-8 → silent return-all-deals, not what the user asked for.
7. If `keywords` has > 1 entry, `keyword_operator` is set explicitly. The platform defaults to OR but explicit is clearer for the saved record.
8. **Every entry in `channels`** / `brands` / `sponsorships` is an integer (not a name). For `articles`, every entry matches `<channel_id>:<youtube_id>`.
9. **Every column in `columns`** is in the type's `columns_<type>.md` catalogue or is a custom-formula column with `custom: true`.
10. **The `sort` value** references a column in the emitted `columns` dict, with a direction allowed by `references/sortable_columns.json`.
11. **Every widget's `aggregator`** is in the matching schema (intelligence or sponsorship — they're disjoint).
12. **`histogram_bucket_size`** matches the FilterSet's date scope (week / month / year).
13. **For type 8** widgets: both `_over_<axis>` histograms in the same report share the same axis (send or purchase, not both).
14. **No M2M `channels` / `brands` / `articles` / `sponsorships` populated** unless the user explicitly asked for a narrow-to-these-IDs overlay (the hybrid case from Step 2).

If any check fails, fix in the working config before writing to the transport file. Don't post a config you can predict will 400.

## B7. Save with `tl reports create --config-file`

```bash
tl reports create --config-file "$TMP" --yes --json
```

- `--yes` skips the confirmation prompt (the user already chose the path).
- `--json` makes the response parseable so you can extract `report_url` and `campaign_id` cleanly.
- `--config-file` (not `--config`) sidesteps shell-quoting issues with apostrophes / dollar signs / backticks in titles or keywords.

---

## Step 3 — Report back

Both paths return the same envelope on success:

```json
{
  "results": [{
    "campaign_id": 12345,
    "report_url": "/dashboard/reports/12345/",
    "unresolved_names": []
  }],
  "usage": { "credits_charged": ..., "balance_remaining": ... }
}
```

Echo the saved URL + ID, plus a follow-up offer for refinement:

> Saved as report **12345**: https://app.thoughtleaders.io/dashboard/reports/12345/
>
> Want to refine the columns, widgets, title, or description? Tell me what to change and I'll run `tl reports update`.

The follow-up offer matters because **FilterSet changes (keywords, demographics, M2M lists) can't be patched in place** via `tl reports update` — they require saving a new variant. Surface that limitation only if the user actually asks to change FilterSet fields.

If the user requests a chart, create it as a SVG graphic.

### On failure

If the command exits non-zero, the CLI prints the error on stderr (shape: `Error (NNN): <detail>` for most codes; specific lines for 401/402/403). **Surface the error verbatim** — do NOT silently report success.

Map the visible code + detail to the likely cause:

- **`Error (400): …missing… title|description…`** → you skipped A2 / B2; the title or description was empty. Go back and fill it in.
- **`Error (400): …filterset…`** (Path B only) → the config has a key the platform doesn't recognise in `filterset`. Re-check against the matching schema (`intelligence_filterset_schema.json` or `sponsorship_filterset_schema.json`) and remove invented fields.
- **`Error (400): …columns…`** (Path B only) → the config references a column display-name the platform doesn't recognise. Re-check against the type's `columns_<type>.md` catalogue; display names are case-sensitive and preserve spaces.
- **`Error (400): …`** (any other detail) → read the detail; it usually names the offending field or value. Fix and retry.
- **`Access denied: …`** (HTTP 403) → the user lacks the plan required for this report type (Intelligence for 1/2/3 in some orgs; confirm with `tl whoami`).
- **`Insufficient credits.`** (HTTP 402) → the org is out of credits; tell the user to top up.

The above maps the visible CLI output to the underlying cause — match on a substring of the detail rather than the exact string, since the platform's wording may evolve.

## What this skill does NOT do

- **No discovery-side work** — no keyword research, no live-data sample validation, no result-set re-evaluation. The session already produced the data; re-running discovery would be wasted effort. Name resolution (`tl brands find` / `tl channels find` to turn names into IDs before they land in the FilterSet) is the one exception — it's required by the FilterSet schema, not discovery. If the user comes in with no prior session, run the relevant `tl db pg|fb|es` queries first to produce a result set, then invoke this skill on the result.
- **No editing of existing reports.** If the user wants to refine an already-saved report's columns, widgets, title, or description, run `tl reports update <id>` directly. For FilterSet refinements, the platform requires saving a new variant.
- **No bulk-importing into an existing report.** Use the `tl bulk-import` command for that. Save-report only creates new reports.
