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
- For composite-noun queries with AND semantics (`"both Roman history and naval warfare"`), keep candidates inside the intersection — don't broaden across both components independently if the caller cares about the AND.

### Phase 2 — Rank (mechanical, via the bundled script)

Run the bundled script. It takes the candidate list, sends one `size:0` + `track_total_hits` phrase probe per keyword to `tl db es` against `["title", "summary", "transcript"]`, and prints the ranked JSON on stdout.

```bash
# Positional args
python3 <SKILL_DIR>/scripts/probe.py crypto bitcoin DeFi "smart contract"

# JSON array on stdin
echo '["crypto","bitcoin","DeFi","smart contract"]' | python3 <SKILL_DIR>/scripts/probe.py

# Newline-separated on stdin
printf 'crypto\nbitcoin\nDeFi\n' | python3 <SKILL_DIR>/scripts/probe.py

# Optional time window
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
  "keywords": [
    {"keyword": "crypto",  "count": 18742},
    {"keyword": "bitcoin", "count": 15103},
    {"keyword": "DeFi",    "count": 4221},
    {"keyword": "rugpull", "count": 0}
  ]
}
```

- Sorted **descending** by `count`.
- **Zero-count entries are kept** — they signal that the agent's suggestion didn't match anything in the corpus, which is informative to the caller.
- **Deduplicated case-insensitively** — `"Crypto"` and `"crypto"` collapse to one entry; the first spelling wins.
- Each entry has exactly two keys: `keyword` (string) and `count` (integer).
- The seed keyword(s) are always included in the output, ranked alongside the suggestions.

The skill's responsibility ends at the ranked JSON. The caller decides what to do with it — typically running `tl db es` with a `multi_match` over the surviving high-count keywords against the same `title` / `summary` / `transcript` fields.

## Cost

Each probe is `size:0` + `track_total_hits:true` with no aggregations — no rows are returned. At raw-DB pricing, expect roughly 1–2 credits per probe. For 10 keywords, expect ~10–20 credits total. Run `tl describe show db` to see the current rate.

## Self-check before emitting

1. Output is a single valid JSON object on stdout — no prose, no fences.
2. Every keyword is a generic term (no specific brand or channel names).
3. `keywords` array is sorted descending by `count`.
4. Each entry has exactly `keyword` (string) and `count` (integer).
5. The seed keyword(s) appear in the output.
