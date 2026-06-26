---
name: tl-keyword-research
tl-blurb: find & validate channels by topic
description: |
  Find YouTube channels that *reliably* cover a topic — discovered by content keywords (topics, concepts, niches), then validated by the CONTEXT in which those keywords appear in the channel's videos. Invoke when the user wants channels for a topic ("find investing channels", "channels that cover tiktok shops"), not by channel ID/name. Default output: a ranked, context-validated set of channels with sponsorability flags (JSON), plus an offer to save as a TL report. The keyword-distribution mode (counts per keyword) is OPT-IN — only when the user explicitly asks for "keyword counts / distribution / how common is X".
---

# tl-keyword-research — topic → validated channels

Given a topic (seed keyword(s) or an NL phrase), return a ranked set of channels that
reliably cover it. The flow: widen the topic into keywords, find candidate channels by
**field-weighted** relevance (`title` > `summary` > `transcript`), spot-check the
**context** of the keyword in each candidate with cheap agents to drop channels that
only use the word in an unrelated sense, flag each survivor for sponsorability, and
(autonomously, within a bounded loop) narrow or expand the search based on what the
context check reveals.

**Default output = validated channels.** The old keyword-distribution output
(`{keyword, count}`) is now an **opt-in mode** — produce it only when the user
explicitly asks for keyword counts / distribution / "how common is X". See
[Opt-in: keyword distribution](#opt-in-keyword-distribution).

`<SKILL_DIR>` below is this skill's directory (the one holding `SKILL.md`).

## When to invoke / skip

Invoke when the user wants **channels for a topic** (concepts, niches), not a specific
channel/brand by ID or name.

Skip when:
- The user has explicit channel / brand IDs or names → `tl channels find` / `tl brands find`.
- The intent maps cleanly to a curated recommender tag (e.g. "Cooking channels") →
  `tl recommender top-channels "<tag>"`. Don't re-discover curated tags by text match.

## The pipeline (you orchestrate; scripts + cheap agents do the work)

1. **Expand** — you widen the seeds into keywords and pick AND/OR.
2. **Search channels** — `search_channels.py` → field-weighted candidate channels (the default result shape).
3. **Fetch context** — `fetch_context.py` → keyword-in-context evidence per candidate.
4. **Validate** — spawn cheap (Haiku) agents to judge each channel's keyword sense and surface adjacent terms.
5. **Assess & refine** — you read the verdicts, then narrow or expand and re-run 2–4. Bounded, autonomous (≈3 rounds).

---

## Stage 1 — Expand (you)

Broaden the seed(s) into **5–15** candidates: synonyms, sub-areas, specific multi-word
phrases, inflectional variants (ES text fields are **not stemmed** — `invest`/`investing`/`investments`
are distinct terms), and reasonable abbreviations. Hard rules:

- Generic topic/concept terms only. **No brand names** unless the seeds already contain
  one (then adjacent brands in the same category are fine). **No channel names.**
- No random-letter padding.

**AND vs OR** (pass to the scripts via `--operator`):
- Default **OR** (union: "crypto channels" = crypto / bitcoin / Web3 / …).
- **AND** only for composite-noun phrases ("AI cooking", "Roman naval warfare") or
  explicit "both X and Y". Under AND, keep candidates *inside the intersection* — don't
  broaden each component independently.

## Stage 2 — Search channels (default output)

```bash
python3 <SKILL_DIR>/scripts/search_channels.py --operator OR --size 200 \
  investing "index funds" "stock market" "personal finance"
# JSON array / newline list on stdin also accepted; --since/--until scope publication_date.
```

Runs ONE collapsed ES search (`collapse` on `channel.id`, sorted by `_score`) so each
channel surfaces its single best-matching video, then enriches with name +
sponsorability. **Field weighting is the priority you asked for:** title hits outscore
summary, which outscore transcript (default boosts `title^4,summary^2,transcript^1`,
tunable via `--fields`). Output per channel: `channel_id, name, score, top_video_id,
top_video_title, sponsorability{…}`. This is the candidate set for validation.

## Stage 3 — Fetch context

```bash
python3 <SKILL_DIR>/scripts/fetch_context.py --channels 466311,2105,199308 \
  --samples 4 --window 160 investing
```

For each candidate, pulls its top-scoring matching videos and extracts the text window
around each keyword occurrence. **`transcript` is YouTube caption XML** — the script
strips tags + unescapes entities + windows client-side (ES highlight can't be used: the
CLI API strips highlight, and transcript fragments would be full of `<text …>` tags
anyway). Returns per channel: `{channel_id, match_count, sampled, snippets:[{video_id,
title, field, keyword, text}]}`. `match_count` (how many of the channel's videos match)
is a useful breadth signal alongside the score.

## Stage 4 — Validate context (cheap / Haiku agents)

This is the core of "too weak → validated". Keyword matches are noisy: a search for
**investing** surfaces *"sports investing"* (betting) and church-sermon channels
("invest in your faith") right next to real finance channels. Spot-check the sense.

Spawn cheap agents (Agent tool, **`model: haiku`** or a similarly cheap one) using the prompt in
[`references/context-classifier.md`](references/context-classifier.md). Give each agent
a `TOPIC:` line (the intended sense) and usually a `NOT:` line (senses to exclude), plus
a batch of the Stage-3 evidence. Batch ≈50–100 channels per agent and run batches in
**parallel**. Each agent returns, per channel:

`{i, channel_id, verdict: on_topic|mixed|off_topic, confidence, evidence_quote, adjacent_terms[], notes}`

- **`adjacent_terms`** is the discovery signal — co-occurring topics/brands worth
  considering for expansion (e.g. "Amazon"/"affiliate" under "tiktok shop").
- Surface the interesting verdicts and adjacent terms back to yourself for Stage 5.

**Steer for completeness, then verify it — cheap models silently drop the tail of a
long list.** This is an output-generation behavior, not an input-context limit (the
evidence fits easily), so two guards:

1. **Anchor the count in the prompt.** Index the evidence (`i: 0…N-1`) and open the
   user message with the exact target, e.g. *"There are exactly 50 channels (indices
   0–49). Return exactly 50 objects. The last channel_id is 778812."* Keep per-item
   output terse (the classifier caps `evidence_quote` at ≤8 words) so the full list fits.
2. **Completeness check + re-send (the guarantee).** After each agent returns, diff the
   returned `channel_id`s against the batch you sent. If any are missing (or the agent
   emitted prose / invalid JSON), re-send just the missing channels to a fresh agent and
   merge. Never assume a batch came back whole. Smaller batches make this fire less often.

## Stage 5 — Assess & refine (autonomous, bounded ≈3 rounds)

Read the verdicts + adjacent terms and decide, then re-run Stages 2–4. Cap at **~3
refinement rounds**; stop earlier when the validated set is stable. Each round, briefly
report what you changed and why.

- **Narrow** when off-topic verdicts cluster around a confusable sense: add the wrong
  sense to the agents' `NOT:` line; drop transcript-only matches by tightening
  `--fields` to `title^4,summary^2`; or require co-occurrence (switch to `--operator AND`
  with a disambiguating term, e.g. `investing` + `stocks`).
- **Expand** when adjacent terms reveal a productive direction: add the discovered term
  as a new keyword and re-search. Example: investigating **"tiktok shop"**, the context
  check repeatedly surfaces **"Amazon"** and **"affiliate"** → conclude these are common
  affiliate providers for that niche and add them (OR) to widen reach.
- Keep a running set of validated channels across rounds (dedupe by `channel_id`).

## Sponsorability — rank all, flag (don't filter)

Return **all** topically-validated channels ranked by relevance; do not drop a channel
for being unbookable. Annotate each with the `sponsorability` block from Stage 2:
`is_active`, `is_tpp` (TPP partner), `is_msn` (Media Selling Network member — has a join
date), `has_outreach_email`, `sponsorship_price`, `reach` (subscribers). The user
decides what to do with non-sponsorable matches.

## Mixed-context channels — label all, drop only off-topic

Keep `on_topic` **and** `mixed` channels in the output, each carrying its verdict +
confidence. Exclude only channels the agents judged **clearly `off_topic`** (wrong
sense). Surface the count of dropped channels so the exclusion is visible.

## Output (default)

A single JSON object — validated channels ranked by relevance:

```json
{
  "topic": "financial investing",
  "operator": "OR",
  "keywords": ["investing", "index funds", "stock market"],
  "rounds": 2,
  "channels": [
    {
      "channel_id": 2105, "name": "Financial Education",
      "score": 55.37, "match_count": 312,
      "verdict": "on_topic", "confidence": "high",
      "evidence_quote": "how to build a stock portfolio",
      "adjacent_terms": ["index funds", "roth ira"],
      "sponsorability": {"is_active": true, "is_tpp": false, "is_msn": false,
                          "has_outreach_email": true, "sponsorship_price": 4710.0, "reach": 938000}
    }
  ],
  "excluded_off_topic": [{"channel_id": 199308, "name": "Cornerstone Church Sermons", "evidence_quote": "invest in your relationship with God"}]
}
```

Then **offer to save** the validated set: `tl-import` / `tl-save-report` (channels report).
Don't save unprompted — offer.

## Opt-in: keyword distribution

Only when the user explicitly asks for keyword counts / distribution, run the ranking
probe instead of (or before) the channel search:

```bash
# Channel-topic counts — default fields (title, summary, transcript)
python3 <SKILL_DIR>/scripts/probe.py crypto bitcoin DeFi Web3 "smart contract"
# Video-level counts — pass --fields title,summary (drop transcript noise)
python3 <SKILL_DIR>/scripts/probe.py --fields title,summary "budget meal prep" "cheap meal prep"
# Composite noun — --operator AND keeps candidates inside the intersection
python3 <SKILL_DIR>/scripts/probe.py --operator AND "3d printing" "resin printing minis"
```

Emits `{"operator", "keywords":[{"keyword","count"}, …]}` sorted descending. This is the
old default; it now serves the explicit "how common is X" question.

## Cost

- `search_channels.py`: 2 ES calls (collapse search + enrichment), ~`size` billed rows
  each, no expensive fields → cheap.
- `fetch_context.py`: 1 ES call per channel; it returns `transcript`/`summary` (priced
  fields), so cost ≈ channels × `--samples` × field-rate. Keep `--samples` small (default 4)
  and validate the top candidates, not the whole tail.
- Haiku validation: cheap by design; batch + parallelize.
- Use `tl db es … --pricing` to preview; `tl describe show db` for live rates.

## Self-check before emitting

1. Default output is the validated-channel JSON object (not keyword counts) unless the
   user explicitly asked for distribution.
2. Field weighting applied: title > summary > transcript.
3. Every channel sent for validation has a verdict — batch returns were diffed by
   `channel_id` and any missing were re-sent, not silently dropped; only clearly
   `off_topic` channels were excluded, and the dropped set is surfaced.
4. `operator` is `AND` only for composite-noun / explicit-conjunction phrasing.
5. Each channel carries its `sponsorability` flags (all ranked, none filtered out for being unbookable).
6. Refinement stayed within ~3 rounds, and changes per round were reported.
7. Offered to save the result as a TL report (did not save unprompted).
8. If the user requested a chart, render it as an SVG.
