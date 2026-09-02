# Transcript mining

How a channel's transcripts become a profile. One retrieval flow, one
extraction fan-out, then judgment. Query credits are not a budget here; the
budgets are model tokens and tiers — which is why retrieval is a single
script, extraction runs on sonnet agents that each see 25 windows and nothing
else, and the expensive context is spent only on judgment no script can
encode.

Measured end to end on three channels (Sydney Watson 20107, Alex Hormozi
253904 = 4,205 videos, Emma Chamberlain 3268): fetch 7–21 s regardless of
channel size; 310 gems / 500 windows, 405 / 497, 432 / 500; every quote exact
by construction; extractor agents 2.3–8 minutes each, gem-dense channels at
the long end.

## Layer 1+2: fetch the cue passages, one script

```bash
python3 <skill>/scripts/fetch_cues.py --channel <channel_id> \
  --host-terms "<surname>,<company>,<former role>"
```

Retrieval and selection are the same query. A boolean `should` of
`match_phrase` clauses over the cue phrases selects the videos, and the
index's `highlight` returns the passages around each hit with the timed-text
`start` attributes intact — so a 5,000-video channel costs a few dozen small
queries instead of a full transcript download, and every passage is born with
its `&t=` link. There is no local full-transcript scan any more; nothing is
downloaded that the model layer will not read.

**Flags:**

| flag | default | what it does |
|---|---|---|
| `--channel` | required | internal TL channel id, from `tl channels find` |
| `--host-terms` | none | comma-separated names/companies; a hit on one is a strong host anchor and scores double |
| `--out` | `tl-creator-profiles/.corpus` | corpus root; the channel id becomes a subdirectory, so concurrent channels never collide |
| `--phrases` | `references/cue-phrases.txt` | the cue list |
| `--max-windows` | 500 | the cap on what reaches the model layer (20 agents × 25) |
| `--batch-size` | 25 | windows per batch file, one per extractor agent |
| `--per-video-cap` | 8 | no single video may own the batch set |
| `--fragment-size` / `--fragments-per-doc` | 900 / 10 | passage width and how many per video |
| `--page-size` / `--concurrency` | 150 / 4 | paging and parallel year buckets |
| `--exclude` | none | a `classified.jsonl` from an earlier round: passages already judged (same video, start within 30 s) are skipped |

**`cue-phrases.txt`** is one phrase per line, `#` for comments. A leading
`~` marks a **recurring bit** — a greeting, a sign-off, a channel catchphrase
that fires in nearly every upload ("~welcome back to", "~my name is"). Those
still score, but they are capped hard, so a channel's fixed intro can seed a
few windows and never fill the batch set. Ordinary phrases are capped at the
larger of 12 windows or 8% of the cap; no single video passes
`--per-video-cap`; ties are spread across the channel's years, so a profile
spans the back catalogue rather than the last twelve months.

**Ad reads.** Windows are built with a regex heuristic in `in_sponsor_read`,
and once the cap is taken the kept windows' real sponsored spans are looked up
by video id (`scripts/sponsor_spans.py`) and the flag is decided from them —
a window overlaps a read when `[start, start+30]` meets a sponsored span
padded 75 s either side. The lookup is authoritative when it succeeds; the
heuristic stays when it fails. The summary's `sponsor_source` says which one
decided, and it belongs in the run report whenever it reads `regex_fallback`.

**Output**, under `<out>/<channel_id>/`:

- `windows.jsonl.gz` — every passage found, ranked (a window carries
  `video_id` + `start`, not an assembled watch URL; whoever shows one builds
  `…watch?v=<video_id>&t=<start>s` at that point).
- `batches/batch-NNN.json` — the capped set, 25 windows per file, one file per
  extractor agent.
- `corpus.jsonl.gz` — the same store shape the verifiers read, holding the
  fetched passages as cues, so `verify_quotes.py` and `quote_timestamp.py` run
  unchanged. It is **passages, not transcripts**: `channel_context.py`'s
  corpus stats over it are a format hint, not a coverage census.

The summary (stdout) and one `FUNNEL stage=fetch_cues …` line (stderr) carry
`videos_matched`, `passages`, `windows_capped`, `batches`, `sponsor_source`
and `elapsed_s`. `passages` minus `windows_capped` is what stayed out of this
round — carry it into the profile's coverage header, because "absence is not
evidence" needs it.

**A second round is additive, never a re-run.** The harness runs at most 20
subagents concurrently, so one round is 20 × 25 = 500 windows. To go deeper —
or to use host terms the socials lane turned up after the fetch — run
`fetch_cues.py … --exclude <out>/classified.jsonl`: passages already judged
are skipped, so the new batches are new material and the ledger grows instead
of repeating. Do not raise `--max-windows` past what one round can extract.

## Layer 3: extraction — one fan-out, classify and extract together

Every batch file is read by exactly one `tl-cli:gem-classifier` agent (the
file name is historical; the role is a **gem extractor**, `model: sonnet` —
haiku truncated its output at this size in testing). One pass decides whether
the window is self-disclosure AND writes what it says: the third-person claim,
the span of the window that proves it, the life domain, the speaker guess and
the sensitivity tier. The rubric has ONE home:
`references/gem-classifier.md`, which points to `evidence-rules.md`.

Run the fan-out exactly like this:

1. **The batch files already exist.** `fetch_cues.py` wrote them. Do not
   re-fetch, do not re-batch, do not read `windows.jsonl.gz`.
2. **`ls <batches_dir>/batch-*.json`** for the N paths. That list is the work
   queue; each path is claimed exactly once.
3. **Spawn all N agents as N `Agent` tool_use blocks in ONE assistant
   message.** One spawn per message is a bug, not a slow success — the same
   one-message rule governs every fan-out in this skill.
4. **Each agent gets exactly four things**: the path to
   `references/gem-classifier.md`, the context block (verbatim, inline in the
   prompt), ONE batch file path, and the path to write
   `returns/batch-NNN.extract.json`. Windows only — never a transcript, never
   `corpus.jsonl.gz`, never a second batch.
5. **Each agent writes its file and returns one line**
   (`batch=NNN windows=<n> gems=<n>`). Results live in the file; the return
   line is a receipt. Then stop the turn and consume the completion
   notifications as they arrive.
6. **Never validate returns by hand** — `assemble_extracts.py` does it
   mechanically (Layer 3b). Track claimed batches; never spawn the same batch
   twice.

Each agent is held to **exactly five tool calls** (four Reads, one Write) so a
batch cannot turn into an open-ended session: no verification scripts, no
Bash, no re-reads.

**Forbidden in this fan-out, without exception:**

- **No polling.** No `ls`-and-count loops, no re-reading the returns directory
  to see whether agents finished.
- **No `sleep`**, and specifically never `sleep` with
  `run_in_background: true` — a backgrounded sleep returns instantly, so it
  waits for nothing while looking like a wait. A genuine timed wait on
  external state uses `Monitor` with an until-condition.
- **No sequential spawning**, no batching-of-batches, no "start with two and
  see how it goes".
- **No default-model stand-ins.** If `tl-cli:gem-classifier` does not resolve
  (running from a checkout rather than an installed plugin), spawn
  `general-purpose` with an explicit `model: sonnet` override and the
  extractor rubric inlined in the prompt. A general-purpose agent on the
  inherited (expensive) model is the failure mode this list exists to prevent
  — it is how one past run reached 30M tokens.

**If the host cannot spawn agents at all**: run the batches sequentially with
`references/gem-classifier.md` used inline as the prompt, discarding each
batch's raw text before the next.

Print the stage's own funnel line from the returned receipts:
`FUNNEL stage=extract batches=… agents=… windows=… gems=… respawned=… elapsed_s=…`.

The model catches what no cue list can: "I'm allergic to peanuts", "we finally
finished the nursery", proper nouns read through misspellings, sarcasm and
hypotheticals. That is why the fetch layer gates nothing beyond the cap.

## Layer 3b: assemble — the contract is checked, not trusted

```bash
python3 <skill>/scripts/assemble_extracts.py \
  --batches <corpus>/<channel_id>/batches \
  --returns <corpus>/<channel_id>/returns \
  --out <corpus>/<channel_id>
```

Per batch it checks that every index `0 … N-1` appears exactly once across
`gems` and `not_gems`; that each verdict's echoed `start` matches the window
it claims (a hard check — a verdict about a different window is not a
verdict); that the enums are valid; and that the `quote_span` resolves to a
contiguous substring of the window text, which it **cuts mechanically**, so
every published quote is verbatim by construction rather than by trust. The
five-word `anchor` is advisory — agents normalise punctuation — and mismatches
are only counted.

It writes `classified.jsonl` (every judged window, and the `--exclude` input
for a later round), `gems.jsonl` (the cluster step's input), `candidates.jsonl`
and `respawn.json`, and exits **3** when any window needs re-running.
`respawn.json` maps batch → the window indexes that failed or were skipped:
re-spawn exactly those as one mini-batch of extractor agents and re-run
assemble. **Nothing is hand-patched** — a hand-edited return is an
unverifiable quote.

## Layer 4: cluster, then one merge pass judges

The mechanical bulk — verbatim checking — is code; the judgment slice is ONE
small Claude pass over the clustered candidates.

**First collapse the repeats, locally:**

```bash
python3 <skill>/scripts/cluster_gems.py --in gems.jsonl
```

A long back catalogue answers the same question hundreds of times: one
channel's 172 gems held "BioShock is my favorite game" 29 times over. The
script writes `gems-clustered.jsonl` beside the input — one line per claim, in
the same shape as a gem line, so there is exactly one format downstream.
Singletons pass through as clusters of 1. Each line adds `occurrences` and
`members` (`video_id`, `start`, `published` for every member, the
representative included), and the representative is the cluster's
highest-information member, so nothing the merge pass needs is left behind.

Merging is conservative on purpose: gems must share a life domain, a speaker
guess and a sensitivity call, their one-line claims must agree — including on
polarity ("has kids" never merges into "does not have kids") and on numbers
("has 2 cats" never merges into "has 3 cats") — and every
member must match every other member. Near-duplicates that fail any of those
stay separate — a missed merge costs a few tokens, a false merge would delete
a distinct fact. Do not hand-merge what the script left apart.

**One merge pass — ONE agent.** It reads `gems-clustered.jsonl` plus the
identity lane's findings (when that lane ran) and **never the windows, never a
transcript**: the extractor already lifted the claim and the quote, so the
merge pass only decides what a script cannot:

- finalize recurrence and provenance on each candidate — recurrence is the
  count of **distinct `video_id`s among the cluster's `members`**, never
  `occurrences` itself (`evidence-rules.md`);
- attribution reasoning over the deterministic features under
  `evidence-rules.md` — including the rules no feature can encode
  (recurrence never confirms on a multi-host channel; an ad-read fact must
  recur outside reads); resolve `speaker_guess: "unclear"` windows or drop
  them;
- deduplication across clusters the script left apart for good reason but
  which say the same thing about the same fact;
- the sensitivity tier (`evidence-rules.md`), including **re-tiering where the
  extractor missed an obvious case** — a stated allergy is `lifestyle`, not
  `none` and not `clinical`;
- **dropping any candidate whose claim asserts more than its quote supports.**
  The extractor is told the claim must stand on the span alone; this pass is
  where that is enforced against the assembled record. Narrow the claim to
  what the quote says, or drop the fact — never publish the wider claim.
- superseded-fact resolution (latest wins, history kept), confidence buckets,
  and the `selected` picks for the one-pager.

It writes `facts.jsonl` (the shape in `references/profile-spec.md`), claims
grounded in the assembled quotes only — the verifier, not the model, is the
verbatim authority — and prints
`FUNNEL stage=merge clusters=… facts=… selected=… dropped=… elapsed_s=…`.

**Then verify in bulk, locally:**

```bash
python3 <skill>/scripts/verify_quotes.py --in facts.jsonl \
  --corpus tl-creator-profiles/.corpus/<channel_id>/corpus.jsonl.gz
```

Every transcript-provenance quote is located in the stored passages. Only
`match: "exact"` publishes, and its located timestamp is authoritative.
`partial` and `none` are flagged, never accepted: fix the quote to the
caption text the result shows, or drop the fact. A quote that needs more
than a mechanical fix goes back through the merge pass, not past it. Verified
facts become `<channel_id>-facts.jsonl`; the one-pager and HTML render from
there per `references/profile-spec.md`.

**The orchestrating context never sees raw transcripts.** It sees the fetch
summary, the extractors' receipt lines, the assemble summary, the merge pass's
returns, and the profile.

## Entity expansion: a second round, not a re-scan

When a gem surfaces a new entity — "my dog Luna", a spouse's name, a company —
or the socials lane returns a name the first fetch did not have, deepen the
ledger with another additive round:

```bash
python3 <skill>/scripts/fetch_cues.py --channel <id> \
  --host-terms "…,Luna,<other new entities>" \
  --exclude <corpus>/<channel_id>/classified.jsonl
```

Passages already judged are skipped, so the round costs one fetch (seconds)
plus one extraction fan-out over genuinely new material. Confirmed entities
also feed Mode B's connection probes and improve attribution (a fact tied to a
known family name anchors the host).

## The channel context brief

```bash
python3 <skill>/scripts/channel_context.py --channel <id> --corpus <corpus.jsonl.gz> --per-video-out <dir>/per_video.json
```

After the fetch, format is measured rather than guessed: first-person
density, interview markers, question density, title hints. The corpus it reads
is now the fetched **passages**, not whole transcripts, so the densities are a
format hint on the material the profile is actually built from, never a
coverage census. A model
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

Wall clock is the extraction fan-out and nothing else. Measured: the fetch is
**7–21 s for any channel size**, the local scripts (assemble, cluster, verify)
are seconds, and the extractor agents run **2.3–8 minutes each** in parallel —
gem-dense channels at the long end, because a batch with 20 gems in it is
simply more writing. Claude's share of a profile build is the fan-out plus a
handful of turns: the identity lane, the format call, one merge pass —
**≤22 subagents total** (up to 20 extractors, one merge, one socials lane),
not one per window and not one per fact.

Every stage prints its own `elapsed_s` on its `FUNNEL` line, so "it was slow"
is always answerable with a stage name. Rounds are the knob that matters: one
round is 500 windows because the harness runs at most 20 subagents at once,
and going deeper means another `--exclude` round rather than a bigger cap.
