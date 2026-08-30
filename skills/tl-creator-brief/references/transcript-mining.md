# Transcript mining

How a channel's transcripts become a profile. Four layers, in order: one
deterministic fetch, one generous local recall pass, one cheap-API
classification pass, and one small model layer where the remaining judgment
lives. Query credits are not a budget here; the budgets are model tokens and
tiers — which is why everything selective runs locally, classification runs
on a cheap API model, and Claude is spent only on judgment no script can
encode.

## Layer 1: fetch everything, one query

```bash
python3 <skill>/scripts/fetch_corpus.py --channel <channel_id>
```

A single paged sweep (`search_after`, transcript in `_source`) walks the
channel's whole history into a local store,
`tl-creator-profiles/.corpus/<channel_id>/corpus.jsonl` — caption XML
stripped, cue start-seconds kept, so every future quote is born with its
`&t=` link. Videos without transcripts come back from the same sweep without
the field: coverage census for free, no second query.

- **No per-video fetch loops, anywhere.** One video = one line in a store the
  sweep already wrote.
- **No sampling, no read cap, no probe battery.** The whole catalogue comes
  home.
- **Failures abort loudly.** An auth, credit or network error stops the run
  with the error in hand. It is never recorded as "video had no transcript" —
  an outage must not produce a confident empty profile.

## Layer 2: generous local recall pass

```bash
python3 <skill>/scripts/selftalk_scan.py \
  --corpus tl-creator-profiles/.corpus/<channel_id>/corpus.jsonl \
  --host-terms "<surname>,<company>,<former role>"
```

Windows every transcript into ~260-char passages and keeps anything with a
first-person marker or a fuzzy entity hit. This layer exists solely to cut
model spend, so it is tuned for recall, never precision:

- **Nothing with first-person content is hard-rejected.** The old disclosure
  and exclusion lexicons are ranking features: they order what the models read
  first, they reject nothing. The only hard drop is provable boilerplate
  ("subscribe", "link in the description") with no other first-person content.
- **Fuzzy means token-bounded edit-distance + phonetic matching** on host
  terms, family and pet names, and later brand names — the layer that survives
  caption mangling ("Maddox" for Matiks, "social channel" for Social Chain).
  Token-bounded: a term matches whole tokens only, so a surname "Lee" can
  never match "sleep".
- Deterministic attribution features are attached to every window as **model
  inputs, not verdicts**: sponsored-span overlap, cross-video recurrence of
  rare phrases, fuzzy host-anchor hits. Nothing is silently discarded by them.

Output: `windows.jsonl` (every kept window, ranked) plus
`batches/batch-*.json`, rank-ordered ~50-window files already capped at
`--max-windows` (default 500) for the classification layer. The kept share
varies hugely by format (measured: ~18% on a faceless narration channel,
60–85% on talk-heavy solo and interview channels) — which is why cost control
does NOT rely on this layer alone: it comes from the rank ordering, the
window cap, and the cheap classifier below.

**The cap is enforced by the scan, not by judgment.** Ranked windows keep
their top scores, and unranked (non-English) windows are stride-sampled
across the channel's whole history, so a giant back-catalogue costs the same
as a mid-sized one. The summary's `windows_over_cap` reports what stayed
local — carry that number into the profile's coverage header, because
"absence is not evidence" needs it. Do not raise the cap on your own
initiative; the corpus and `windows.jsonl` keep everything, so a deeper pass
is one free re-scan away when a human asks for it. 500 top-ranked windows
demonstrably covers the facts a brief actually uses; with the script
classifier the cap is a latency/quality knob more than a cost knob.

## Layer 3: classification — a script, not a fan-out

```bash
python3 <skill>/scripts/classify_gems.py \
  --batches tl-creator-profiles/.corpus/<channel_id>/batches \
  --context context.json
```

`classify_gems.py` sends the batched windows to an OpenAI-compatible chat
endpoint (JSON mode enforced, resumable, malformed responses retried and
recorded rather than dropped). The rubric has ONE home —
`references/gem-classifier.md`, which points to `evidence-rules.md` — and the
script embeds both files in its prompt verbatim, so every path runs the same
classifier. Configuration is env-only (nothing machine-specific lives in this
skill):

- `CREATOR_BRIEF_LLM_API_KEY` — required; no key means this layer falls back
  to agents (below).
- `CREATOR_BRIEF_LLM_BASE_URL` — default `https://openrouter.ai/api/v1`.
- `CREATOR_BRIEF_LLM_MODEL` — default `deepseek/deepseek-v3.2`. The
  reference config is OpenRouter with that model: roughly 5–10× cheaper than
  a haiku agent fan-out and two orders of magnitude cheaper than doing it in
  the orchestrating context.

Write `context.json` first — the same context block the classifier contract
requires: channel name, host name(s), known facts, format label with its
evidence. The script writes `classified.jsonl` (every window + verdict, the
resume record) and `gems.jsonl` (the self-disclosure subset with
`speaker_guess` host or unclear).

**Quality gate, mandatory on a fresh channel:** before trusting a full run,
spot-check ~30 verdicts by hand — read a mix of accepted and rejected windows
from `classified.jsonl` and confirm the calls against the rubric. Systematic
misses (a domain always rejected, guest voices accepted as host) mean the
cheap model is not holding the contract: switch to the agent fallback rather
than patching verdicts by hand.

**Fallback: the classifier agent fan-out.** When no API key is configured
(the script exits with code 2 and says so), fan the batch files out to the
`gem-classifier` agent type — the plugin registers it from
`agents/gem-classifier.md` at the repo root (namespaced by the plugin, e.g.
`tl-cli:gem-classifier` in Claude Code) — one agent per batch. Say clearly
which path the run is on and that the agent path costs roughly 5–10× more in
model spend. The fan-out's hard rules:

- **Emit ALL the Agent calls as multiple tool_use blocks in ONE assistant
  message.** One spawn per message is a bug, not a slow success. The same
  one-message rule applies to every other fan-out in this skill (the identity
  lane, the CONNECT brand lanes).
- Each agent gets the spec path, the context block, and one batch file path,
  and returns strict JSON per the spec. Validate the shape; a malformed
  return is re-run, never hand-patched. Track which batches you have
  spawned — never spawn the same batch twice.
- **Results come back as return values — never through the filesystem.**
  Never instruct an agent to write results to a file (the shipped
  `gem-classifier` can't anyway — `tools: Read` only). Never poll for
  completion — no `ls`-and-count loops. Never `sleep` to wait, and
  specifically never `sleep` with `run_in_background: true` — a backgrounded
  sleep returns instantly, so it waits for nothing while looking like a
  wait; a genuine timed wait on external state uses `Monitor` with an
  until-condition. After emitting the fan-out message, stop the turn and
  consume the agents' returned JSON as the completion notifications arrive.
- **If agents exist but this agent type doesn't resolve** (running from a
  checkout rather than an installed plugin): spawn the host's
  general-purpose agent with a haiku model override, hand it the same three
  inputs, and hold it to the same contract.
- **If the host cannot spawn agents at all**: run the batches sequentially
  with `references/gem-classifier.md` used inline as the prompt, discarding
  each batch's raw text before the next.

The model catches what no lexicon can: "I'm allergic to peanuts", "we finally
finished the nursery", proper nouns read through misspellings, sarcasm and
hypotheticals. That is why the recall pass gates nothing.

## Layer 4: code verifies, one model pass judges

The old confirmation wave (a sonnet agent per gem cluster) is gone. Its
mechanical bulk — verbatim checking — is code; its judgment slice is ONE
small Claude pass.

**One fact pass (≤2 agents, or the main loop when the gem list is small).**
Hand `gems.jsonl` plus the identity lane's findings to a single pass that
does only what a script cannot:

- compose candidate facts: claim, the verbatim quote excerpt lifted from the
  window text, life domain, recurrence (distinct videos), provenance;
- attribution reasoning over the deterministic features under
  `evidence-rules.md` — including the rules no feature can encode
  (recurrence never confirms on a multi-host channel; an ad-read fact must
  recur outside reads); resolve `speaker_guess: "unclear"` windows or drop
  them;
- sensitivity calls, superseded-fact resolution (latest wins, history kept),
  confidence buckets, and the `selected` picks for the one-pager.

It returns candidate facts as JSONL lines (the `facts.jsonl` shape in
`references/profile-spec.md`), claims grounded in window text only — the
verifier, not the model, is the verbatim authority.

**Then verify in bulk, locally:**

```bash
python3 <skill>/scripts/verify_quotes.py --in candidates.jsonl \
  --corpus tl-creator-profiles/.corpus/<channel_id>/corpus.jsonl
```

Every transcript-provenance quote is located in the stored captions. Only
`match: "exact"` publishes, and its located timestamp is authoritative.
`partial` and `none` are flagged, never accepted: fix the quote to the
caption text the result shows, or drop the fact. A quote that needs more
than a mechanical fix goes back through the fact pass, not past it. Verified
facts become `<channel_id>-facts.jsonl`; the one-pager and HTML render from
there per `references/profile-spec.md`.

**The orchestrating context never sees raw transcripts.** It sees the scan
summary, the classifier summary, the spot-check windows, the fact pass's
returns, and the profile.

## Entity expansion, fuzzy and free

When a gem surfaces a new entity — "my dog Luna", a spouse's name, a company
— re-scan the local corpus for it and its neighbours:

```bash
python3 <skill>/scripts/selftalk_scan.py --corpus ... \
  --host-terms "..." --entity-terms "Luna,<other new entities>"
```

The corpus is on disk, so the re-scan costs nothing. New windows it surfaces
go through the same classification layer (`classify_gems.py` resumes: only
the new windows get classified). Confirmed entities also feed Mode B's
connection probes and improve attribution (a fact tied to a known family name
anchors the host).

## The channel context brief

```bash
python3 <skill>/scripts/channel_context.py --channel <id> --corpus <corpus.jsonl>
```

After the corpus is local, format is measured, not guessed: first-person
density per video, interview markers, question density, title hints. A model
read of a small sample (3–5 videos' worth of windows) plus these stats calls
the label — solo / interview / multi-host / faceless-scripted — **with
evidence**. The label exists for two reasons only:

1. It is the attribution context handed to the classifier: interview means
   guest voices contaminate; solo means everything is the host.
2. Near-zero first-person density flags "likely faceless" early, so model
   tokens aren't spent on a channel with nothing to find.

Nothing exits early. A faceless channel with one personal Q&A upload still
surfaces it; the flag only reorders effort and sets expectations in the
profile header.

## Speed

Wall-clock is dominated by the classification layer, and it is concurrent by
construction: `classify_gems.py` runs parallel requests, and the identity &
socials lane runs alongside the whole sweep. The fetch is a few sequential
paged requests (seconds); the recall pass is local (seconds); verification
is local (seconds). Claude's share of a profile build is a handful of turns:
the identity lane, the format call, the spot-check, and one fact pass —
**≤5 subagents total**, not a fan-out per batch. Target: a full profile in
single-digit minutes on a large channel.
