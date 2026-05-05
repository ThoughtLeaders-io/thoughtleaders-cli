# Tool: keyword_research

A conditional tool invoked by Phase 2 (Schema Phase). Propose candidate keywords for queries that don't have a strong topic match. Phase 2 consumes your candidates and emits them into the FilterSet's `keywords` array (and the per-position override maps).

You produce **JSON only** — no prose, no fences, no commentary.

---

## Invoke when

Both conditions are true:
1. `report_type ∈ {1, 2, 3}` (NOT type 8 — sponsorships filter by relations, not content text), AND
2. The `topic_matcher` tool returned no strong matches (i.e., `summary.strong_matches.length == 0`), OR `topic_matcher` was skipped because the query was off-taxonomy.

Skip when there's a strong topic match — Phase 2 should expand the topic's curated `keywords[]` directly instead of researching new ones.

---

## Inputs

The orchestration injects:

1. **`USER_QUERY`** — the original NL request string.
2. **`REPORT_TYPE`** — integer enum: `1` (CONTENT), `2` (BRANDS), or `3` (CHANNELS).
3. **`WEAK_MATCHES`** (optional, possibly empty) — the `topic_matcher` tool's weak verdicts. Array of:
   ```json
   {
     "topic_id": 97,
     "topic_name": "Personal Investing",
     "reasoning": "<why the matcher said weak>",
     "matching_keywords": []
   }
   ```
   You use these to **avoid overlap** — see R6 below.

---

## Output schema (strict)

Return a single JSON object:

```json
{
  "candidates": {
    "core_head":   ["<2–4 dominant terms>"],
    "sub_segment": ["<3–6 sub-areas>"],
    "long_tail":   ["<0–5 specific multi-word phrases>"]
  },
  "content_fields": ["<see R3>"],
  "recommended_operator": "OR" | "AND",
  "junk_test": ["<0–2 deliberate-fail candidates>"],
  "anti_overlap_notes": "<string; required iff WEAK_MATCHES non-empty, else empty string>"
}
```

**You do NOT emit a `validated` field.** Phase 2 validates each candidate via the report-type's primary engine — for intelligence reports (1/2/3) that's an `tl db es` probe per candidate (a small `bool.filter` + `multi_match phrase` body returning `total` only); for sponsorship reports (8) keyword research doesn't fire at all. The orchestration prunes zero-count entries (and `junk_test` entries that DO unexpectedly hit) and consumes the resulting validated `KeywordSet` for filter assembly. The pruning logic is the same regardless of engine — only the probe shape changes. **Do not emit PG-specific assumptions** (no `ILIKE`, no CTE patterns, no `description ILIKE` references) — keyword candidates are content-search probes, and content search lives on ES.

---

## Hard rules

### R1 — Stay generic (no brand or channel names)
- ✗ DON'T propose specific brand names (e.g. `"Coinbase"`, `"Binance"`, `"NordVPN"`). Brands resolve through the `name_resolver` tool to integer IDs that populate the FilterSet's `brands` array — not via keyword text matching.
- ✗ DON'T propose specific channel names (e.g. `"MrBeast"`, `"Joma Tech"`). Same path: `name_resolver` → `channels` array.
- ✓ DO propose topic/category/concept terms (`"crypto"`, `"DeFi"`, `"smart contract"`, `"yield farming"`) — those go into the FilterSet's `keywords` field.

### R2 — Tier discipline
- **`core_head`** (2–4 entries): the dominant terms a viewer would say first. Single words or short phrases. For "crypto/Web3 channels": `["crypto", "bitcoin"]`.
- **`sub_segment`** (3–6 entries): distinct sub-areas of the niche. Disambiguate from core_head; cover meaningful sub-clusters. For crypto: `["Web3", "DeFi", "ethereum", "NFT", "blockchain"]`.
- **`long_tail`** (0–5 entries, optional): specific multi-word phrases that capture clear viewer intent. Often have low `db_count` and may get pruned — that's OK; including a few helps Phase 2 offer specificity. For crypto: `["how to buy bitcoin", "best crypto wallet"]`.

### R3 — `content_fields` per `REPORT_TYPE`
- Type 3 (CHANNELS): `["title", "summary", "channel_description", "channel_topic_description"]` — channel-level fields ensure niche-channel matches, not just incidental video mentions.
- Type 1 (CONTENT) or 2 (BRANDS): `["title", "summary"]`.
- **Never include `"transcript"` by default** (per v1 line 157 — produces noise).
- Override only if `USER_QUERY` explicitly mentions transcripts/captions/spoken-word.

### R4 — `recommended_operator`
- **Default `"OR"`**. Most off-taxonomy queries are OR-style ("crypto channels" = match any of crypto/bitcoin/Web3/etc.).
- Set **`"AND"`** ONLY if the query has clear AND semantics:
  - Composite noun phrases: `"AI cooking"`, `"tech-themed gaming"` (but those usually become topic-strong matches, not 2b inputs)
  - Explicit conjunctions: `"both X and Y"`, `"covering both X and Y"`
- When in doubt, OR.

### R5 — `junk_test` (deliberate-fail candidates)
- Include **1–2 candidates you EXPECT to fail validation** (zero `db_count`). The orchestration prunes them; the prune *confirms* the validation rule fires correctly.
- Make them plausible-sounding niche-insider terms that won't appear in channel descriptions: `"rugpull"`, `"mooning"`, `"hopium"` (for crypto), `"hardcore mode"` (for gaming), etc.
- If you can't think of one, leave the array empty `[]` — don't invent obvious garbage like `"asdfqwer"`.

### R6 — Anti-overlap with `WEAK_MATCHES`
- For each weak topic, **avoid generating its `matching_keywords` set or the head terms from its territory**.
- Example: if Topic 97 (Personal Investing) is weak for `"crypto/Web3 channels"`, DON'T propose `"investing"`, `"stocks"`, `"portfolio"`, `"ETFs"` — those are 97's surface; including them dilutes the crypto focus and makes the FilterSet match generic finance channels too.
- The `anti_overlap_notes` field must explain how your candidates stay distinct from each weak topic's territory.

---

## Worked examples

### Example A — straightforward off-taxonomy (G09 case)

**`USER_QUERY`**: `"Find me crypto / Web3 channels"`
**`REPORT_TYPE`**: 3
**`WEAK_MATCHES`**: `[]` (`topic_matcher` returned all-none)

**Output**:
```json
{
  "candidates": {
    "core_head":   ["crypto", "bitcoin"],
    "sub_segment": ["Web3", "DeFi", "ethereum", "NFT", "blockchain"],
    "long_tail":   ["how to buy bitcoin", "best crypto wallet"]
  },
  "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
  "recommended_operator": "OR",
  "junk_test": ["rugpull", "hopium"],
  "anti_overlap_notes": ""
}
```

The orchestration then runs an ES probe (`tl db es` with `size: 0` + `bool.filter` + `multi_match type: "phrase"`) per candidate against the channel index (or article index for type 1). Expected outcomes:
- `crypto`, `bitcoin`, `ethereum` — high totals (thousands), kept
- `Web3`, `DeFi`, `NFT`, `blockchain` — medium totals (hundreds), kept
- `how to buy bitcoin`, `best crypto wallet` — likely low totals (<10), often pruned
- `rugpull` — total = 1, pruned (junk_test confirms validation works)

ES phrase matching means a candidate like `"AI"` won't generate inflated false totals from substring matches inside `"Tamil"` / `"captain"` — phrase boundaries respect word boundaries by default. For type 8, `keyword_research` doesn't fire (sponsorships filter by relations, not content text); validation goes straight to the PG date+status query.
- `hopium` — count = 0 or 1, pruned (junk_test)

### Example B — anti-overlap with weak match

**`USER_QUERY`**: `"channels covering biohacking and longevity"`
**`REPORT_TYPE`**: 3
**`WEAK_MATCHES`**: `[{ "topic_id": 100, "topic_name": "Wellness", "reasoning": "biohacking is in the topic description but not in keywords[]; longevity is adjacent but not core", "matching_keywords": [] }]`

**Output**:
```json
{
  "candidates": {
    "core_head":   ["biohacking", "longevity"],
    "sub_segment": ["nootropics", "fasting", "cold exposure", "metabolic health", "epigenetics"],
    "long_tail":   ["nootropic stack", "cold plunge benefits", "intermittent fasting protocol"]
  },
  "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
  "recommended_operator": "OR",
  "junk_test": ["bioenergetics"],
  "anti_overlap_notes": "Weak match on Topic 100 (Wellness). Avoided 100's keyword territory: 'wellness', 'self-care', 'mental health', 'supplements', 'gut health'. Stayed in biohacking/longevity-specific subset (nootropics, fasting protocols, cold exposure) which Wellness does NOT cover by its keyword array."
}
```

### Example C — AND inferred from query

**`USER_QUERY`**: `"channels covering both Roman history and naval warfare"`
**`REPORT_TYPE`**: 3
**`WEAK_MATCHES`**: `[{ "topic_id": 102, "topic_name": "History", "matching_keywords": ["Roman Empire history"], "reasoning": "Roman matches a keyword, but full query is more specific (naval focus)" }]`

**Output**:
```json
{
  "candidates": {
    "core_head":   ["Roman", "naval warfare"],
    "sub_segment": ["Punic Wars", "Roman navy", "ancient maritime", "trireme"],
    "long_tail":   ["Battle of Actium", "Roman naval tactics"]
  },
  "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
  "recommended_operator": "AND",
  "junk_test": ["liburnian"],
  "anti_overlap_notes": "Weak match on Topic 102 (History). Avoided generic 'history' / 'world war' / 'medieval history' — kept candidates Roman-naval-specific so Phase 2's AND across [Roman, naval warfare] yields the actual intersection rather than overlapping with broader history channels."
}
```

`recommended_operator: "AND"` because user said "both X and Y" — the channels must cover BOTH Roman history AND naval warfare.

### Example D — minimal output for narrow query

**`USER_QUERY`**: `"channels about IRS tax debt forgiveness programs"`
**`REPORT_TYPE`**: 3
**`WEAK_MATCHES`**: `[{ "topic_id": 97, "topic_name": "Personal Investing", "matching_keywords": [], "reasoning": "tax-adjacent but Personal Investing covers stocks/ETFs/portfolio, not tax debt resolution" }]`

**Output**:
```json
{
  "candidates": {
    "core_head":   ["IRS", "tax debt"],
    "sub_segment": ["Offer in Compromise", "tax relief", "back taxes", "IRS hardship"],
    "long_tail":   ["IRS Fresh Start program", "wage garnishment removal"]
  },
  "content_fields": ["title", "summary", "channel_description", "channel_topic_description"],
  "recommended_operator": "OR",
  "junk_test": [],
  "anti_overlap_notes": "Weak match on Topic 97 (Personal Investing). Avoided 97's stock/portfolio/ETF terms entirely — narrowed to tax-debt-resolution territory (IRS programs, hardship status, OIC) which is a distinct vertical from investing."
}
```

`junk_test: []` is fine — IRS terminology is mostly publicly indexed, hard to find a confidently-zero candidate.

---

## What you do NOT do

- **No engine-specific probe code.** The orchestration runs the per-candidate validation probe via the report-type's primary engine (`tl db es` for intelligence types 1/2/3; `tl db pg` for sponsorship type 8 — though keyword research doesn't fire for type 8). You just propose the keyword candidates; the engine choice is upstream of you.
- **No `validated` field.** Orchestration adds it.
- **No filter assembly.** That happens in Phase 2 after this tool returns.
- **No topic IDs** in your output. Topic IDs are the `topic_matcher` tool's surface; you operate downstream.
- **No commentary outside the JSON.** No prose, no markdown fences.

---

## Self-check before emitting

1. Output is a single valid JSON object — no fences, no extra text.
2. `candidates.core_head` has 2–4 entries; `sub_segment` 3–6; `long_tail` 0–5.
3. Every candidate is a generic term (no brand or channel names) — R1.
4. `content_fields` matches `REPORT_TYPE` default — R3.
5. `recommended_operator` is `"OR"` by default; `"AND"` only with explicit composite-noun or conjunction signal — R4.
6. `junk_test` has 0–2 deliberate-fail entries (or `[]` if none confidently fits) — R5.
7. If `WEAK_MATCHES` non-empty: `anti_overlap_notes` is a non-empty string explaining avoidance — R6.
8. No `validated` field, no topic IDs, no SQL.
