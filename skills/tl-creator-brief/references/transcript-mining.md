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
`references/gem-classifier.md`, which points to `evidence-rules.md`. The
script's wire prompt carries a condensed statement of that same contract (gem
test, attribution, domain taxonomy, sensitivity, output schema) instead of the
two docs verbatim, because they were resent on every chunk and that payload,
not the windows, dominated the prompt bill and the latency. `--full-spec`
sends the docs verbatim; the agent fallback below always reads them.
Configuration is env-only (nothing machine-specific lives in this skill):

- `CREATOR_BRIEF_LLM_API_KEY` — required; no key means this layer falls back
  to agents (below).
- `CREATOR_BRIEF_LLM_BASE_URL` — default `https://openrouter.ai/api/v1`.
- `CREATOR_BRIEF_LLM_MODEL` — default `deepseek/deepseek-v3.2`. The
  reference config is OpenRouter with that model: roughly 5–10× cheaper than
  a haiku agent fan-out and two orders of magnitude cheaper than doing it in
  the orchestrating context.
- `CREATOR_BRIEF_LLM_CONCURRENCY` — parallel requests, default 16 (bounded
  1–64). At 25 windows per request a 500-window cap is ~20 requests, so the
  default clears the whole cap in about two rounds.

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

**Fallback: the classifier agent fan-out.** Triggered mechanically, not by
judgment: `classify_gems.py` exits **20** and prints

```
FALLBACK_REQUIRED reason=missing_api_key batches_dir=<path> batch_files=<N> windows=<M>
```

to stderr. Exit 20 is the only signal to read — exit 1 means "finished with
errors, rerun to resume", exit 2 is a usage error, and neither is a fallback.
Run this checklist exactly:

1. **The batch files already exist.** `selftalk_scan.py` wrote them and
   `classify_gems.py` counted them (`batch_files=N` in the marker). Do not
   re-run the scan, do not re-batch, do not read `windows.jsonl`.
2. **`ls <batches_dir>/batch-*.json`** to get the N paths. That list is the
   work queue; each path is claimed exactly once.
3. **Spawn all N agents as N `Agent` tool_use blocks in ONE assistant
   message.** Agent type `tl-cli:gem-classifier` (the plugin registers it
   from `agents/gem-classifier.md` at the repo root). One spawn per message
   is a bug, not a slow success — the same one-message rule governs every
   fan-out in this skill (the identity lane, the CONNECT brand lanes).
4. **Each agent gets exactly three inputs**: the path to
   `references/gem-classifier.md`, the context block (verbatim, inline in the
   prompt), and **one** batch file path. Windows only — never a transcript,
   never `corpus.jsonl`, never a second batch.
5. **Each agent returns the strict JSON array as its final message.** Then
   stop the turn and consume the returns as the completion notifications
   arrive.
6. Validate every return's shape (one object per window, same order, valid
   enums). A malformed return is re-spawned for that batch, never
   hand-patched. Track claimed batches — never spawn the same batch twice.
7. Concatenate the returns into `gems.jsonl` in the same shape the script
   writes (`{"window": …, "verdict": …, "error": null}` lines, keeping only
   `self_disclosure` verdicts whose `speaker_guess` is host or unclear), print
   `FUNNEL stage=classify path=haiku_fanout windows_total=… classified=…
   errors=… gems=… elapsed_s=…` from the returned verdicts (this — not the
   script's `path=fallback_required` line — is the classification stage's
   entry in the run report's funnel table), then continue at Layer 4
   unchanged.

**Forbidden in this fan-out, without exception:**

- **No write-to-file-and-poll contract.** Never instruct an agent to write
  its results anywhere (the shipped `gem-classifier` can't anyway — `tools:
  Read` only). Results are return values.
- **No polling.** No `ls`-and-count loops, no re-reading a directory to see
  whether agents finished.
- **No `sleep`**, and specifically never `sleep` with
  `run_in_background: true` — a backgrounded sleep returns instantly, so it
  waits for nothing while looking like a wait. A genuine timed wait on
  external state uses `Monitor` with an until-condition.
- **No sequential spawning**, no batching-of-batches, no "start with two and
  see how it goes".
- **No default-model stand-ins.** If `tl-cli:gem-classifier` does not resolve
  (running from a checkout rather than an installed plugin), spawn
  `general-purpose` with an explicit `model: haiku` override and the
  `gem-classifier` rubric inlined in the prompt. A general-purpose agent on
  the inherited (expensive) model is the failure mode this list exists to
  prevent — it is how one past run reached 30M tokens.

**If the host cannot spawn agents at all**: run the batches sequentially with
`references/gem-classifier.md` used inline as the prompt, discarding each
batch's raw text before the next.

Report the path taken and its approximate cost once, in the run report: the
agent path costs roughly 5–10× the API path.

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
python3 <skill>/scripts/channel_context.py --channel <id> --corpus <corpus.jsonl> --per-video-out <dir>/per_video.json
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
**≤5 subagents total**, not a fan-out per batch. Target: **≤2 minutes for
the model-bound stages** (classify + fact pass + verify) of a PROFILE run
(the old fan-out build took ~40). The local scan is CPU-bound and scales
with transcript count, not the window cap — measured ~3 minutes over a
5,000-video corpus — so total wall clock on a large channel is scan time
plus the model budget, with the fetch and identity lanes overlapping it.

Every stage prints its own `elapsed_s` on its `FUNNEL` line, so "it was slow"
is always answerable with a stage name. The classification barrier is
deliberate: at the default 16-way concurrency a 500-window cap is ~20
requests ≈ two rounds, so the fact pass waits well under a minute and
streaming partial batches into it would buy noise, not time. Revisit only if
a measured run shows classification dominating the wall clock.
