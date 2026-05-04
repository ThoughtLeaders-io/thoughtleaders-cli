# Tool: name_resolver

A conditional tool invoked by Phase 2 (Schema Phase). The user often types brand or channel names ("PewDiePie", "MrBeast", "Logitech G", "Sanky") that the FilterSet expects as **integer IDs**. This tool resolves names → IDs against `thoughtleaders_channel` and `thoughtleaders_brand`.

You produce **JSON only** when emitting candidates; you may emit a short clarifying question to the user when disambiguation is needed.

---

## Invoke when

- The user mentions a specific channel or brand by name and the FilterSet needs the corresponding ID (`channels`, `exclude_channels`, `brands`, `exclude_brands`; plus the type-8 lookups that go through Brand/Channel).
- Cross-reference resolution (the `database_query` tool delegates to this for the cross-reference set).
- Type 8 — **mandatory**. A type-8 query that names a channel/brand without resolving is a hard failure.

Skip when:
- The user gave no specific names (Phase 2 doesn't need to invoke this for keyword-only queries).
- The "name" is actually a topic word, not an entity (e.g. "gaming channels" — that's `keywords` / `topics`, not `channels`). Stay disciplined: this tool is for proper-noun lookups.
- The user said "network" / "our network" / "MSN" / "MBN" / "TPP" — those are pool memberships, NOT publisher entities. Map them to FilterSet fields (`msn_channels_only`, `tl_sponsorships_only`) or to `cross_references` (`include_sponsored_by_mbn`); see `report_glossary.md`. The `networks` / `exclude_networks` FilterSet fields target Publication entities (publisher orgs that own one or more channels) and are an edge case populated by ID, not by name resolution.

---

## Inputs

The caller provides:

1. **`NAMES`** — array of strings to resolve. Order is preserved; output keeps the same order.
2. **`ENTITY`** — `channel` | `brand`. Determines which table to query.
3. **`MODE`** *(optional, default `"interactive"`)* —
   - `"interactive"`: surface ambiguity to the user when more than one candidate matches.
   - `"best_effort"`: silently pick the highest-confidence candidate; tag with `match_kind` so the caller can warn.

---

## Process — progressive matching

For each input name, walk the matching ladder until a single confident candidate is found:

### Step 1 — Exact (case-sensitive)

```sql
SELECT id, channel_name FROM thoughtleaders_channel
WHERE channel_name = '<name>' AND is_active = TRUE
LIMIT 5 OFFSET 0
```

For brands: `thoughtleaders_brand.name`.

If exactly one row → done, `match_kind: "exact"`.

### Step 2 — ILIKE (case-insensitive substring)

```sql
SELECT id, channel_name FROM thoughtleaders_channel
WHERE channel_name ILIKE '%<name>%' AND is_active = TRUE
ORDER BY reach DESC NULLS LAST
LIMIT 25 OFFSET 0
```

If exactly one row → `match_kind: "ilike"`.
If multiple rows → record all candidates and proceed to Step 4 (disambiguate).

### Step 3 — Emoji- / punctuation-stripped (channel names love emojis)

If Step 2 returned zero rows:

```sql
-- Strip emoji & non-ASCII from the stored name, compare against stripped input
SELECT id, channel_name FROM thoughtleaders_channel
WHERE regexp_replace(channel_name, '[^[:ascii:]]+', '', 'g') ILIKE '%<stripped_name>%'
  AND is_active = TRUE
ORDER BY reach DESC NULLS LAST
LIMIT 25 OFFSET 0
```

If single row → `match_kind: "emoji_stripped"`. Multiple → disambiguate.

### Step 4 — Fuzzy (last resort)

If Steps 1–3 all returned zero, fall back to PostgreSQL trigram similarity:

```sql
SELECT id, channel_name, similarity(channel_name, '<name>') AS score
FROM thoughtleaders_channel
WHERE channel_name % '<name>'      -- pg_trgm operator, threshold 0.3
  AND is_active = TRUE
ORDER BY score DESC, reach DESC NULLS LAST
LIMIT 10 OFFSET 0
```

Single row with `score >= 0.5` → `match_kind: "fuzzy"`. Otherwise → unresolved.

---

## Disambiguation

When more than one candidate has a credible match for a single input name:

### `MODE = "interactive"` (default)

Surface to the user with a numbered list of candidates, ranked by `reach` (or `mention_count` for brands). Format:

```
> "Sanky" matched 3 active channels — which did you mean?
>   [1] Sanky                              (reach 1.2M, US)
>   [2] sanky_official                     (reach 380K, BR)
>   [3] Sankey Ratings                     (reach 22K, GB)
> Reply with a number, or "skip" to leave it unresolved.
```

Wait for the user's reply before emitting the final output.

### `MODE = "best_effort"`

Pick the top candidate (highest `reach` for channels, highest mention count for brands), tag with `match_kind` and `disambiguated: false`. The caller is responsible for warning the user that disambiguation was skipped.

---

## Output schema

```json
{
  "entity": "channel" | "brand",
  "mode": "interactive" | "best_effort",
  "resolutions": [
    {
      "input": "<original name>",
      "id": <int> | null,
      "resolved_name": "<canonical name from DB>" | null,
      "match_kind": "exact" | "ilike" | "emoji_stripped" | "fuzzy" | "unresolved",
      "candidates_considered": <int>,
      "disambiguated": <bool>,
      "score": <float|null>           // only for fuzzy
    }
    // ... one entry per input, same order
  ],
  "all_resolved": <bool>,                // true iff every input has a non-null id
  "unresolved_inputs": ["<name>", ...]   // empty if all_resolved
}
```

---

## Hard rules

1. **`is_active = TRUE` for channel queries** — TL convention; inactive channels are out of scope for any report.
2. **No INSERT / UPDATE.** This tool reads only.
3. **Single-quote escape user names.** `O'Brien` → `'O''Brien'`.
4. **Order preservation.** `resolutions[i].input` MUST equal `NAMES[i]`. Callers index by position.
5. **Don't auto-pick when the user typed an exact specific name** that returned multiple candidates. Surface the disambiguation. Auto-picking the wrong PewDiePie is worse than asking.
6. **Cap fuzzy at trigram threshold 0.3** with a `score >= 0.5` accept gate. Lower-confidence matches are unresolved.
7. **Brands collapse aliases.** Some brands have a primary `name` plus an `aliases` array (or a separate `brand_alias` table). Search both.
8. **Don't strip emojis silently.** Always set `match_kind: "emoji_stripped"` so the caller can verify with the user.
9. **Avoid ID guessing.** If `match_kind` is `"unresolved"`, leave `id: null`. Never invent an ID.

---

## Edge cases

- **Generic words as names**: "Gaming" is a topic, not a channel. If the input matches > 50 candidates with weak `reach`, treat as unresolved and ask the user to be more specific.
- **YouTube handles vs channel names**: TL stores both. If the user typed `@MrBeast` (with the `@`), search `channel_handle` field first, then `channel_name`.
- **Casing**: the stored `channel_name` is the YouTube display name (often Title Case but inconsistent). Use ILIKE everywhere except the very first exact-match attempt.
- **Excluded entities**: when populating `exclude_channels` / `exclude_brands`, use the same resolver. Same lookup logic, different output array on the FilterSet.
