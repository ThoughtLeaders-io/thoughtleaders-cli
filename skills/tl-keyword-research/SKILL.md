---
name: tl-keyword-research
description: |
  Broaden and rank a set of content-search keywords. Invoke when the user wants to find videos or channels by content keywords (topics, concepts, niches) — not by ID or exact name. Takes one or more seed keywords (or an NL phrase), proposes related candidates, probes Elasticsearch for each one against the `title` / `summary` / `transcript` fields, and returns a strict JSON object `{"keywords":[{"keyword","count"},...]}` sorted descending by document count. The output is meant to feed the next step (typically a `tl db es` content search with the surviving high-count keywords).
---

# tl-keyword-research

Widen and rank content-search keywords before running the actual ES content search. Two phases: the agent expands the seed keyword(s) into a broader candidate set; the bundled script probes ES for each candidate and returns the ranked counts.

## When to invoke

Invoke this skill — directly, or as a delegated step from another skill / agent — when:

- The user wants to find **videos or channels by content keywords** (topics, concepts, niches), not by ID or by exact name.
- The user supplies at least one seed keyword, or an NL phrase from which seeds can be derived.
- The goal is to **widen** the keyword set the user came in with before running the actual content search.

Skip when:

- The user has explicit channel / brand IDs or names → use `tl channels find` / `tl brands find` instead.
- The user's intent maps cleanly to an existing recommender tag (e.g. "Cooking channels") → use `tl recommender top-channels "<tag>"` instead. Recommender tags are curated; don't re-discover them through keyword text matching.

## Inputs

- **Seed keywords** — one or more strings supplied by the caller (or extracted from an NL phrase).
- **Optional time window** — `--since YYYY-MM-DD` and / or `--until YYYY-MM-DD`. Scopes the probes to `publication_date` within that range. Default: all-time.

## Two phases

### Phase 1 — Expand (you, the agent)

Take the seed keyword(s) and broaden them with:

- **Synonyms** — `"crypto"` → `"cryptocurrency"`, `"digital currency"`.
- **Sub-areas / adjacent concepts** — `"crypto"` → `"bitcoin"`, `"ethereum"`, `"DeFi"`, `"NFT"`, `"blockchain"`, `"Web3"`.
- **Specific multi-word phrases** — `"crypto"` → `"how to buy bitcoin"`, `"smart contract"`.
- **Inflectional variants** — ES text fields aren't stemmed (see the [ES schema reference](../tl/references/elasticsearch-schema.md#text-analyzer-behavior)), so each surface form is counted independently. Propose singular, plural, base verb, `-ing` form, and irregular past tense as needed; skip possessives — they rarely add reach. For example: `"review"` / `"reviews"`, `"invest"` / `"investing"`, `"swim"` / `"swam"`.
- **Reasonable alternate spellings / abbreviations** — `"ethereum"` → `"ETH"`.

Produce **5–15** candidates including the seed(s). Cap at ~20 — every candidate costs one ES probe.

Hard rules:

- DO propose generic topic / concept terms.
- **Brand names — only mirror the seeds.** If the seed set is purely topic-shaped (`"crypto"`, `"productivity"`, `"home renovation"`), do NOT introduce brand names; brands should be resolved by `tl brands find` to integer IDs and queried through `sponsored_brand_mentions` / `organic_brand_mentions`, not by free-text match. Only if the seeds **already contain at least one brand name** (e.g. the caller is hunting for competitor coverage or adjacent sponsorship mentions in transcripts) is it appropriate to expand with adjacent brand names in the same category — e.g. seed `"NordVPN"` → `"Surfshark"`, `"ExpressVPN"`, `"Mullvad"` is fine; seed `"crypto"` → adding `"Coinbase"` is not.
- DON'T propose specific channel names (e.g. `"MrBeast"`). Same path: `tl channels find`.
- DON'T propose random-letter junk to pad the list.

#### Determine AND vs OR semantics

Decide upfront how the caller will combine the keywords downstream, and pass the result to the script with `--operator AND|OR`. The decision shapes both the expansion (next bullet) and the output envelope:

- **Default `OR`.** Most off-taxonomy queries are union-style ("crypto channels" matches any of crypto / bitcoin / Web3 / …).
- **`AND` only when the user's phrasing carries clear intersection semantics:**
  - **Composite noun phrases** — `"AI cooking"`, `"Roman naval warfare"`, `"vegan keto"`.
  - **Explicit conjunctions** — `"both X and Y"`, `"covering both X and Y"`.
- When in doubt, OR.

**Expansion shape under `AND`:** keep candidates **inside the intersection** — don't broaden across each component independently. For `"Roman naval warfare"`, expand within Roman-naval territory (`Punic Wars`, `Roman navy`, `trireme`, `Battle of Actium`); do NOT add generic Roman-empire or generic naval-warfare terms, because the downstream AND combine would then over-match unrelated channels.

### Phase 2 — Rank (mechanical, via the bundled script)

Run the bundled script. It takes the candidate list, sends one `size:0` + `track_total_hits` phrase probe per keyword to `tl db es` against `["title", "summary", "transcript"]`, and prints the ranked JSON on stdout.

Three invocations cover almost every case. **Pick by the question shape** (channel vs video vs AND-composite):

```bash
# (a) Channel search by topic — default fields (title, summary, transcript)
python3 skills/tl-keyword-research/scripts/probe.py crypto bitcoin DeFi Web3 blockchain "smart contract"

# (b) Video search by topic — REQUIRED: pass --fields title,summary
#     The default field set includes `transcript`, which inflates counts via
#     incidental mentions inside long videos. For video-level discovery the
#     downstream ES query also uses title+summary, so the probe MUST match.
python3 skills/tl-keyword-research/scripts/probe.py --fields title,summary \
  "budget meal prep" "cheap meal prep" "meal prep on a budget" "frugal recipes"

# (c) Composite noun ("both X and Y") — pass --operator AND so candidates stay
#     inside the intersection (don't broaden each component independently)
python3 skills/tl-keyword-research/scripts/probe.py --operator AND \
  "3d printing" "miniature painting" "tabletop miniatures" "resin printing minis"
```


**Pick the invocation shape by what the user is searching for:**

```bash
# (a) Channel search by topic — default fields (title, summary, transcript)
python3 <SKILL_DIR>/scripts/probe.py crypto bitcoin DeFi

# (b) Video search by topic — REQUIRED: pass --fields title,summary
#     Without it, the probe includes transcript matches (noise from passing
#     mentions inside long videos), and the count won't match the field set
#     the downstream ES query uses for video-level discovery.
python3 <SKILL_DIR>/scripts/probe.py --fields title,summary \
  "budget meal prep" "cheap meal prep" "meal prep on a budget"

# (c) Composite-noun phrase ("both X and Y" / "X-themed Y") — pass --operator AND
#     to keep candidates inside the intersection
python3 <SKILL_DIR>/scripts/probe.py --operator AND \
  "Roman naval warfare" "Punic Wars" trireme "Roman navy"
```

Other input / scoping forms:

```bash
# JSON array on stdin
echo '["crypto","bitcoin","DeFi"]' | python3 <SKILL_DIR>/scripts/probe.py

# Newline-separated on stdin
printf 'crypto\nbitcoin\nDeFi\n' | python3 <SKILL_DIR>/scripts/probe.py

# Time window (optional, applies to publication_date)
python3 <SKILL_DIR>/scripts/probe.py --since 2025-01-01 --until 2026-01-01 crypto bitcoin
```

The script:

1. Reads keywords from argv (preferred) or stdin (JSON array or newline-separated). Deduplicates case-insensitively; the first spelling wins.
2. For each keyword, sends a `multi_match` phrase query against `["title", "summary", "transcript"]` with `size:0` and `track_total_hits:true`. Optionally scopes by `publication_date`.
3. Reads `total` from the response envelope (falls back to `hits.total.value` if absent).
4. Sorts descending by count.
5. Prints the canonical JSON object on stdout.

If a single probe fails (auth, transport, server error), the script exits non-zero and writes the error to stderr — partial output is not produced.

## Output (strict)

A **single JSON object** on stdout — no prose, no markdown fences:

```json
{
  "operator": "OR",
  "keywords": [
    {"keyword": "crypto",  "count": 18742},
    {"keyword": "bitcoin", "count": 15103},
    {"keyword": "DeFi",    "count": 4221},
    {"keyword": "rugpull", "count": 0}
  ]
}
```

- `operator` is always present and is one of `"OR"` (default) or `"AND"`. It echoes whatever was passed via `--operator` and tells the caller how to combine the surviving keywords downstream (`bool.should` for OR, `bool.must` for AND, or the FilterSet equivalent).
- `keywords` sorted **descending** by `count`.
- **Zero-count entries are kept** — they signal that the agent's suggestion didn't match anything in the corpus, which is informative to the caller.
- **Deduplicated case-insensitively** — `"Crypto"` and `"crypto"` collapse to one entry; the first spelling wins.
- Each entry has exactly two keys: `keyword` (string) and `count` (integer).
- The seed keyword(s) are always included in the output, ranked alongside the suggestions.

The skill's responsibility ends at the ranked JSON. The caller decides what to do with it — typically running `tl db es` with a `multi_match` over the surviving high-count keywords against the same `title` / `summary` / `transcript` fields.

## Cost

Each probe is `size:0` + `track_total_hits:true` with no aggregations — no rows are returned. At raw-DB pricing, expect roughly 1–2 credits per probe. For 10 keywords, expect ~10–20 credits total. Run `tl describe show db` to see the current rate.

## Self-check before emitting

1. Output is a single valid JSON object on stdout — no prose, no fences.
2. `operator` is `"AND"` only when the user phrasing carries clear intersection semantics (composite-noun phrase or explicit "both X and Y"); otherwise `"OR"`.
3. Under `operator: "AND"`, candidates stay inside the intersection — no broadening across components independently.
4. Every keyword is a generic term (no specific brand or channel names).
5. `keywords` array is sorted descending by `count`.
6. Each entry has exactly `keyword` (string) and `count` (integer).
7. The seed keyword(s) appear in the output.
