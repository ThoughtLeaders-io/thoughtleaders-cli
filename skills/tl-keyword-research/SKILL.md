---
name: tl-keyword-research
tl-blurb: find & validate channels by topic
description: |
  Find YouTube channels that *reliably* cover a topic — discovered by content keywords (topics, concepts, niches), then validated by the CONTEXT in which those keywords appear in the channel's videos. Invoke when the user wants channels for a topic ("find investing channels", "channels that cover tiktok shops"), not by channel ID/name. Default output: a ranked, context-validated set of channels with sponsorability flags (JSON), plus an offer to save as a TL report. The keyword-distribution mode (counts per keyword) is OPT-IN — only when the user explicitly asks for "keyword counts / distribution / how common is X". By default it runs ≥3 refinement rounds and checks in with you before finalizing — say "run autonomously" (or pass `autonomous` / `--auto`) to skip the pauses and let it finish on its own.
---

# tl-keyword-research — topic → validated channels

Given a topic (seed keyword(s) or an NL phrase), arrive at **a CNF (Conjunctive Normal
Form) keyword expression** that reliably selects channels covering it — *and* the ranked,
validated set of channels that expression selects. The flow: widen the topic into
keywords, find candidate channels by **field-weighted** relevance (`title` > `summary` >
`transcript`), spot-check the **context** of the keyword in each candidate with cheap
agents to drop channels that only use the word in an unrelated sense, flag each survivor
for sponsorability, and over **≥3 refinement rounds** compose/recompose the boolean query
— narrowing and expanding — based on what the context check reveals.

**The final result is the CNF expression** — an AND of OR-clauses with negated exclusions,
e.g. `(investing OR "stock market") AND (stocks OR etf) AND (NOT sermon) AND (NOT betting)`
— together with the validated channels it selects. The CNF is the distilled, reusable
artifact: it re-runs verbatim via `search_channels.py --any/--not` and saves with the report.

**Default output = the CNF + validated channels.** The old keyword-distribution output
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
5. **Refine** — compose AND/OR/NOT to narrow & expand, probe fitness, backtrack; **≥3 rounds**, then checkpoint with the user (and interview them if they want more).

## Pacing & autonomy

**Default is interactive.** At the **start** of a run, tell the user in one line how this
will go — e.g. *"I'll refine over at least 3 rounds, then check in before finalizing. Say
'run autonomously' if you'd rather I not pause."* That lets them opt out **before** the
first interview, not just after round 3.

**Opt-out triggers — any of these → run autonomously** (full behavior in Stage 5): the
user says run autonomously / without pausing / "don't stop to ask", **or** invokes the
skill with an `autonomous` / `--auto` argument. The preference holds for the rest of the
session unless the user revokes it.

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
# Flat OR (broad first pass)
python3 <SKILL_DIR>/scripts/search_channels.py --operator OR --size 200 \
  investing "index funds" "stock market" "personal finance"

# Composed boolean — the lever for narrowing/expanding (see Stage 5):
#   (investing OR "stock market" OR "index funds") AND (stocks OR portfolio OR etf)
#   AND NOT (sermon OR gospel OR "sports investing" OR betting)
python3 <SKILL_DIR>/scripts/search_channels.py --size 200 \
  --any "investing,stock market,index funds" \
  --any "stocks,portfolio,etf" \
  --not "sermon,gospel,sports investing,betting"
# JSON array / newline list on stdin also accepted; --since/--until scope publication_date.
```

Runs ONE collapsed ES search (`collapse` on `channel.id`, sorted by `_score`) so each
channel surfaces its single best-matching video, then enriches with name +
sponsorability. **Field weighting is the priority you asked for:** title hits outscore
summary, which outscore transcript (default boosts `title^4,summary^2,transcript^1`,
tunable via `--fields`). **Boolean composition:** each `--any "a,b"` is one required
OR-group (a dimension); repeating `--any` ANDs the groups; `--not` excludes a sense.
So adding a group narrows, adding terms to a group widens, `--not` prunes — this is the
machinery Stage 5 drives. Output: `query` (the boolean it ran), `total_matching_videos`,
and per channel `channel_id, name, score, top_video_id, top_video_title, sponsorability{…}`.

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

## Stage 5 — Iterative compositional refinement (≥3 rounds, then ask the user)

This is the heart of the skill. You **research the topic by composing and recomposing a
boolean keyword query** — combining `--any` OR-groups (AND'd together) and `--not`
exclusions — to narrow and expand the channel set, examining the results each round,
probing their fitness, and **backtracking** when a move makes things worse. This is not
a single pass with a flat operator; it is a search through query-space. Each composed
query **is** a CNF expression — an AND of OR-clauses plus negated literals — so refinement
is the incremental construction of the final CNF, the skill's end-product.

**Run at least 3 rounds.** Three is the floor, not a cap — do not stop before three even
if round 1 looks good.

### Each round

1. **Compose / recompose** the boolean query. Round 1 is usually broad: one OR-group of
   the Stage-1 expansion. Later rounds add structure (below).
2. **Search** — `search_channels.py` with the `--any` / `--not` you composed → candidates.
3. **Probe for fitness** — run Stages 3–4 (fetch context + Haiku validation) on the top
   candidates. Read the verdicts and `adjacent_terms`.
4. **Score the round's fitness** from what you see, e.g.: the share of `on_topic` vs
   `off_topic`/`mixed`; whether off-topic verdicts cluster on one confusable sense;
   how many **sponsorable, high-reach** channels are `on_topic`; and how much the set
   changed. Write this down.
5. **Decide the next move** and **record** (query, fitness, decision) so you can backtrack:
   - **Narrow** when off-topic clusters on a sense, or the set is too broad/noisy: add a
     required dimension (`--any "stocks,portfolio,etf"`), and/or exclude the bad sense
     (`--not "sermon,sports investing"`).
   - **Expand** when fitness is high but reach is thin, or `adjacent_terms` reveal a
     productive direction: widen a group, or add a discovered term. Example: under
     **"tiktok shop"** the context check repeatedly surfaces **"Amazon"** / **"affiliate"**
     → add them (`--any "tiktok shop,amazon,affiliate"`) as common affiliate providers.
   - **Backtrack** when a move *reduced* fitness (fewer good channels, more noise, lost a
     strong channel): discard it, return to the previous recorded query, and try a
     **different** axis. Backtracking is expected, not failure.
6. Keep a **running validated set** across rounds (dedupe by `channel_id`); carry forward
   confirmed `on_topic`/`mixed` channels even as the query shifts.

Each round, briefly report: the boolean query you ran, the fitness read, and the move
(narrow / expand / backtrack) with the reason.

### After round 3 (and every round thereafter) — checkpoint with the user

**Default (interactive):** do **not** finalize autonomously. Present the current validated
set with a short summary (the CNF expression, fitness, what changed across rounds), then
**ask the user to validate the results and choose**: accept as-is · run more refinement
rounds · adjust direction.

**Autonomy override — honor a stated preference.** If the user has told you to run
autonomously / without pausing / "don't stop to ask" — **or** invoked the skill with an
`autonomous` / `--auto` argument — (in this message or earlier in the session),
**skip this checkpoint and the intent interview**: keep refining on your own
judgement, still run **≥3 rounds**, stop when fitness stops improving (or at a sane cap,
~6 rounds), and return the CNF + channels directly. Honor that preference for the rest of
the session unless the user revokes it, and note in the result that you ran autonomously.

**If the user chooses more rounds, interview them about the *intent* behind the keywords
first** — so the next rounds are steered, not guessed. Ask what would sharpen the
composition, e.g.: which sense of the topic they actually mean (and which to exclude);
the audience / intent / format they care about (beginner vs advanced, reviews vs news);
must-have vs nice-to-have sub-topics; brands/products that should count or must not; and
any reach / language / recency constraints. Fold the answers into the `--any` groups,
`--not` exclusions, and the validator's `TOPIC:` / `NOT:` lines, then run the next rounds
and checkpoint again.

## Sponsorability — rank all, flag (don't filter)

Return **all** topically-validated channels ranked by relevance; do not drop a channel
for being unbookable. Annotate each with the `sponsorability` block from Stage 2:
`is_active`, `is_tpp` (TPP partner), `is_msn` (Media Selling Network member — has a join
date), `has_outreach_email`, `sponsorship_price`, `subscribers`. The user
decides what to do with non-sponsorable matches.

## Mixed-context channels — label all, drop only off-topic

Keep `on_topic` **and** `mixed` channels in the output, each carrying its verdict +
confidence. Exclude only channels the agents judged **clearly `off_topic`** (wrong
sense). Surface the count of dropped channels so the exclusion is visible.

## Output (default)

A single JSON object. The **CNF expression is the headline result**; the channels are the
set it selects. `cnf` comes straight from the final `search_channels.py` run.

```json
{
  "topic": "financial investing",
  "cnf": {
    "expression": "(investing OR \"stock market\" OR \"index funds\") AND (stocks OR portfolio OR etf) AND (NOT sermon) AND (NOT \"sports investing\")",
    "clauses": [["investing", "stock market", "index funds"], ["stocks", "portfolio", "etf"], ["NOT sermon"], ["NOT sports investing"]]
  },
  "rounds": 3,
  "channels": [
    {
      "channel_id": 2105, "name": "Financial Education",
      "score": 55.37, "match_count": 312,
      "verdict": "on_topic", "confidence": "high",
      "evidence_quote": "how to build a stock portfolio",
      "adjacent_terms": ["index funds", "roth ira"],
      "sponsorability": {"is_active": true, "is_tpp": false, "is_msn": false,
                          "has_outreach_email": true, "sponsorship_price": 4710.0, "subscribers": 938000}
    }
  ],
  "excluded_off_topic": [{"channel_id": 199308, "name": "Cornerstone Church Sermons", "evidence_quote": "invest in your relationship with God"}]
}
```

Then **offer to save** the validated set: `tl-import` / `tl-save-report` (channels report);
record the CNF `expression` alongside so the report is reproducible. 

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
4. Refinement composed `--any` / `--not` (not just a flat operator) to narrow & expand,
   probed fitness each round, and backtracked when a move hurt fitness.
5. **At least 3 rounds** were run; each round reported its query, fitness, and move.
6. The final result includes the **CNF expression** (AND of OR-clauses + negated literals)
   as the headline artifact, alongside the channels it selects.
7. Checkpoint honored: by default, after round 3 you **asked the user to validate and
   choose**, and **interviewed them about keyword intent** before any further rounds —
   **unless** the user asked to run autonomously, in which case you ran ≥3 rounds and
   returned directly, noting the skipped checkpoint. Nothing was saved without confirmation
   (or per the user's autonomy preference).
8. Each channel carries its `sponsorability` flags (all ranked, none filtered out for being unbookable).
9. Offered to save the result (CNF + channels) as a TL report (did not save unprompted).
10. If the user requested a chart, render it as an SVG.
