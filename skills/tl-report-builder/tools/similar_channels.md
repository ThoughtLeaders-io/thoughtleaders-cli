# Tool: similar_channels

A simple Phase 2 helper. When the user asks for **look-alike** channels — "find me channels like MrBeast", "creators similar to Canterbury Cottage" — this tool emits the FilterSet patch the platform's vector-similarity engine consumes.

You produce **JSON only**.

---

## Invoke when

The user's request contains a look-alike phrase referencing one or more **named seed channels**:

- "channels similar to / like / resembling [name]"
- "creators / publishers / youtubers like [name]"
- "more channels like these: [list]"

Skip otherwise.

---

## Inputs

1. **`SEED_NAMES`** — array of channel name strings the user named.

---

## Process

1. Call `name_resolver` with `ENTITY: "channel"` for `SEED_NAMES`. Surface any disambiguation back to the user before proceeding.
2. Take the **canonical names** from the resolver (not the user's spelling).
3. Emit the patch.

That's the whole tool.

---

## Output

```json
{
  "filterset_patch": {
    "filters_json": {
      "similar_to_channels": ["<canonical name>", "<canonical name>", ...]
    }
  },
  "anti_overlap": {
    "drop_if_present": ["keywords", "keyword_operator", "keyword_content_fields_map", "keyword_exclude_map", "topics"]
  }
}
```

The caller merges `filterset_patch` into the FilterSet and removes any field listed under `anti_overlap.drop_if_present` (the v1 rule: vector similarity already captures topic relevance, so keyword/topic overlap noisy-doubles the predicate).

---

## Hard rules

1. **The Django `FilterSet` model has no `similar_to_channels` field** — the platform interprets it from `filters_json`. Always emit there, never as a top-level FilterSet key.
2. **Canonical names only.** Use what `name_resolver` returned, not what the user typed.
3. **Drop overlapping keyword/topic fields** when emitting `similar_to_channels`. Other narrowing filters (`languages`, `reach_from`, `channel_formats`, demographics) are fine to keep.
4. **Type 8 doesn't use this tool.** If the report type is sponsorships, surface a clarifying question instead of emitting.
