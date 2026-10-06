# Transcript mining

The script flags, the extraction and merge contracts, and the recipes for the
rounds SKILL.md names. `<corpus>` = `<profiles>/.corpus/<channel_id>`.

## 1. Fetch

```bash
python3 <skill>/scripts/fetch_cues.py --channel <channel_id> --host-names "<a>,<b>" [--reserve N]
```

One query selects the videos and returns the passages around each cue phrase
with their timestamps. The cue list is `references/cue-phrases.txt` (one
phrase per line, `phrase | weight`; a leading `~` marks a recurring bit that
is capped hard). Bare first-person markers run as a second pass only when the
phrase pass keeps fewer windows than `--generic-floor`. Every window records
which pass produced it in `retrieval`.

The selection takes every window at or above `--min-score`, fills to
`--min-windows` on a thin channel, and stops at `--max-windows`. Each kept
window is then re-read from the stored transcript, `--read-before` seconds
before its first cue to `--read-after` seconds after its last, and that text
is what the extractor sees; the cues the read added join `corpus.jsonl.gz`.
Host names are read off the window text, never queried: a self-naming sets
`host_anchor`; a third-person naming sets `second_voice_hint`. Two windows
from different videos that share more than half of their eight-word runs are
one passage; the kept copy's `recurrence_videos` counts the uploads.

| Flag | Default | Meaning |
|---|---|---|
| `--host-names` | none | person-name aliases only (first name, full name, surname, nickname). Never a brand, company, role, product or topic. |
| `--read-before` / `--read-after` | 30 / 30 | seconds re-read around each kept window; 0 and 0 keeps the bare fragments |
| `--anchor-before` / `--anchor-after` | 30 / 15 | extra reach around the window's heaviest cue phrase |
| `--max-windows` | 300 | ceiling per round |
| `--min-score` / `--min-windows` | 8.0 / 150 | the selection stops below the score once this many are kept |
| `--batch-size` | derived | windows per extractor; `ceil(kept / agent cap)`, 5 to 15 |
| `--per-video-cap` | 8 | windows one video may own |
| `--generic-floor` | `--max-windows` | run the first-person fallback only below this many phrase windows; 0 never |
| `--reserve` | 0 | agent slots other lanes hold during the fan-out; batches are sized against `cap - reserve` |
| `--exclude` | none | a `classified.jsonl`; passages already judged (same video, start within 30 s) are skipped |
| `--round` / `--since` | 1 / none | an incremental round: batches go to `batches-rN/`; `--since` is the ledger's `latest_video_date`, backfilled 90 days |
| `--phrases` | `references/cue-phrases.txt` | the cue list; a corroboration round passes its own |
| `--out` | `<profiles>/.corpus` | corpus root |

On an English-language channel a non-English transcript is an auto-dubbed
track: excluded, reported as `dubbed_excluded`. `in_sponsor_read` comes from
the platform's sponsored spans when the lookup succeeds (`sponsor_source`),
else from a regex.

Each window also carries `turns`, how many times the captions mark a change
of speaker (`>>`) inside it.

Outputs under `<corpus>`: `windows.jsonl.gz` (every passage, ranked),
`batches/batch-NNN.json` (one file per extractor), `corpus.jsonl.gz` (the
cues the verifier reads: passages, not whole transcripts), `intros.jsonl`
(one row per kept video: its opening, the captions of its first 90 seconds,
and the description lines that name people; the cast sheet's input). The
summary and the `FUNNEL stage=fetch_cues` line carry `videos_matched`,
`passages`, `windows_capped`, `generic_fallback`, `batches`,
`sponsor_source`, `read_span`, `intros`, `self_named`,
`third_person_host_share` and `elapsed_s`. `third_person_host_share` above
about 0.25 makes the format `multi_host` (SKILL.md, step 2).

## 2. Cast sheet

```bash
python3 <skill>/scripts/cast_sheet.py render --intros <corpus>/intros.jsonl \
  --context-full <corpus>/context-full.json --host-names "<a>,<b>" \
  --out-dir <corpus>/prompts --returns-dir <corpus>/returns [--per-agent 25]
# one `cast-sheet` agent per prompts/cast-NNN.md, all in one message, then
python3 <skill>/scripts/cast_sheet.py apply --sheets <corpus>/cast-sheets.json \
  --returns <corpus>/returns --batches <corpus>/batches --out <corpus>/cast.json \
  --host-names "<a>,<b>" --context-full <corpus>/context-full.json
```

`start_run.py` runs the render itself after the fetch. One message per sheet
of 25 videos: the rubric (`references/cast-sheet.md`), the channel context
and the videos (title, opening, description lines). Each agent returns, per
video, `format` (`solo`, `interview`, `collab`, `multi_host`, `staged`,
`faceless`, `unclear`), `hosts`, and `guests` with `name`, `aliases` and
`role`; the names are spelled as the captions spell them so a script can
find them in the windows.

`apply` validates every sheet (every video once, known enums), merges the
verdicts into `cast.json` (earlier rounds' verdicts stay) and rewrites the
batch files before the extractor prompts are rendered: each window of a
judged video gets `cast` (`format`, `hosts`, `guests`), `guest_anchor` (the
listed guests naming themselves in the window), `guest_named` (the listed
guests named or addressed in the window) and, when the sheet calls the
video a shared-voice upload and the title gave no hint, a `format_hint` of
`interview_or_collab` or `staged`, which the merge's deterministic drops
then honour. Given no `--host-names`, a host the sheets name in two or more
videos stamps the host flags (`host_anchor`, `second_voice_hint`) as the
fetch would have, and is reported as `host_names_from_cast`. With
`--context-full`, the host's name is cached on the channel record as
`ai_description.host_name` (through `tl-internal channels ai-description
set`) when it is certain: the sheets name the same host in two or more
videos and a second source agrees (the names the fetch used, a name said
outright on camera, a name the descriptions give), or the sheets alone name
it in five or more videos and in at least half of the videos that name any
host. The fullest spelling is stored (`Joe Rogan` over `Joe`). A host known
by a first name alone is stored under the channel title when the title is
exactly two name words, the first is that first name, and the second is
corroborated (the About text names the full title, the host says it outright
on camera, or the upload descriptions give it); a title that fails any test
leaves the first name. A name already cached is never rewritten; a missing or refused `tl-internal` is
reported as `skipped`. `host_name_cache` in the summary carries the name,
`confidence`, `sources` and the outcome. Exit 3 lists the sheets with no
return in `cast-respawn.json`. The summary and the `FUNNEL stage=cast` line
carry `judged`, `with_guests`, `formats`, `shared_voice_hinted`,
`guest_anchor`, `guest_named`, `host_names_from_cast` and
`host_name_cache`. Every round that writes batches runs the sheet over its
own `intros-rN.jsonl` before that round's extractor prompts.

## 3. Extraction fan-out

```bash
python3 <skill>/scripts/extractor_prompt.py --batch <corpus>/batches/batch-007.json \
  --context <corpus>/context.json --write-to <corpus>/returns/batch-007.extract.json \
  --out <corpus>/prompts/batch-007.md
```

One self-contained message per batch: the rubric, the two evidence-rules
sections it names, the context block and the windows. One extractor agent
per message, all spawned in one message (SKILL.md, step 3). Each agent reads
its file, writes its JSON, replies with the one-line receipt.

IF `<plugin>:gem-classifier` or `<plugin>:cast-sheet` does not resolve: copy
`agents/gem-classifier.md` and `agents/cast-sheet.md` into
`~/.claude/agents/` before the session starts, or spawn the host's generic
subagent pinned to the extraction tier's model with the same two-line
prompt. Never an agent on the inherited model.

Print `FUNNEL stage=extract batches=… agents=… windows=… gems=… elapsed_s=…`
from the receipts.

## 4. Assemble

```bash
python3 <skill>/scripts/assemble_extracts.py --batches <corpus>/batches \
  --returns <corpus>/returns --out <corpus> [--min-coverage 0.95] [--append]
```

Per batch: every index exactly once, `start` matches the window, enums
valid, the quote span cut mechanically from the window text, then extended
to the end of its caption line, then the claim checked against the quote
(names, numbers, family words), `likely` with no named reason read as
`confirmed`, `people` kept only where the quote holds the name. A window that
fails is unjudged: out of every output, listed in `respawn.json`.

Exit 0 when the assembled share is at least `--min-coverage`; exit 3 below
it, or when a batch has no return file. Then re-judge exactly the listed
windows (`extractor_prompt.py --indexes 3,7 --write-to
…/batch-NNN.extract.r2.json`, one agent per batch) and re-run assemble.
`--append` on a later round replaces that round's earlier rows for the same
windows. Never edit a return file.

Outputs: `classified.jsonl` (every judged window; the `--exclude` input for
a later round), `gems.jsonl`, `candidates.jsonl`, `respawn.json`.

## 5. Cluster and merge

```bash
python3 <skill>/scripts/cluster_gems.py --in <corpus>/gems.jsonl && \
python3 <skill>/scripts/merge_pass.py prepare --clustered <corpus>/gems-clustered.jsonl \
  --format <label> --channel <id> --out <corpus> \
  [--existing <profiles>/<id>-facts.jsonl --state <corpus>/merge-state.json] [--shards N]
```

`cluster_gems.py` merges gems that share domain, speaker and tier, whose
claims agree on polarity and numbers, and whose members all match. Never
hand-merge what it left apart. Each cluster line carries `occurrences` and
`members` (`video_id`, `start`, `published`).

`prepare` numbers the clusters `c001…`, applies the drops that need no
judgment (`guest` lines; `unclear` on a shared-voice upload: interview or
multi-host format, or a `format_hint` of interview_or_collab, reaction or
staged), writes one compact line per cluster to judge (`c`, `domain`,
`speaker`, `speaker_evidence`, `people`, `last_seen`, `tier`, `conf`,
`claim`, `quote`, `title`, `published`, `videos`, `occ`, `ad_read`, `anchor`,
`format_hint`, `staged`, `lang`, `notable`; no window text), and shards by
whole domains (`clusters / 40`, 1 to 6 files). With `--channel` it runs
`authenticate.py`: one channel-scoped search per staged line and per
conflicting pair (two homes, a husband and a boyfriend), up to `--max-queries`
(60); the result lands on the line as `probe` and in `probe.json`.

One `merge-shard` agent per file, all in one message; the contract it
returns is in `agents/merge-shard.md`. Save each reply as
`<corpus>/merge-decisions-r1-sN.json`.

```bash
python3 <skill>/scripts/merge_pass.py expand --clustered <corpus>/gems-clustered.jsonl \
  --decisions <corpus>/merge-decisions-r1-s1.json [--decisions …] \
  --format <label> --channel <id> --out <corpus>/facts.jsonl [--existing … --state …] [--fallback-original]
```

`expand` validates every decision (every judged cluster once, known ids,
`keep | fold | drop`, fold targets kept, no fold or supersession cycle, a
supersession that points against the dated evidence, a narrowed claim that
adds a name or number the quote and cluster claim lack, identity records with
a tier) and exits 3 with the ids. IF exit 3: re-ask the shard for those ids
once and pass the reply as another `--decisions` file; on a second failure
add `--fallback-original`.

Then it builds each fact: claim (dated by the script when it said "X years
ago"), quote, video, start, url, `published`, `last_seen`, recurrence
(distinct videos over the cluster and its folds), confidence (the shard's
override, else the extractor's call; `unclear` or `narration` on a solo
upload, a staged claim no non-staged upload confirms, and a claim found only
in a staged upload's opening hook are `unconfirmed`), tier, `speaker`, `people`, `ended`,
`superseded_by`, `members`, `selected` (the shard's confirmed picks ranked,
then confirmed facts by recurrence and recency to 40; never unconfirmed or
ended). It writes `facts.jsonl`, `merge-state.json`, `people.json`, and
`FUNNEL stage=merge …`.

## 6. Verify and write the ledger

```bash
python3 <skill>/scripts/verify_quotes.py --in <corpus>/facts.jsonl \
  --corpus <corpus>/corpus.jsonl.gz --channel-language <language> --drop-unverified && \
python3 <skill>/scripts/ledger_meta.py write --channel <id> --from <corpus>/facts.jsonl.verified.jsonl \
  --channel-name "…" --format <label> --format-evidence "…" --context <corpus>/context-full.json \
  --cast <corpus>/cast.json --host-names "<a>,<b>" [--lanes …] [--rounds N]
```

Only `match: "exact"` publishes, on whole words; `partial`, `none` and
`dubbed` are rejected to `facts.jsonl.rejected.jsonl` and `selected` is
refilled from what verified. The ledger write refuses a non-exact transcript
fact. The orchestrating context never reads a transcript: it reads the
summaries, the receipts and the page.

With `--context`, the write caches three attributes on the channel record
(`ai_description`, through `tl-internal channels ai-description set`):
`format_label`, when the cast sheets
judged ten or more videos and their most frequent format agrees with the
label (`interview` with interview or collab sheets, `multi_host` with
multi-host or collab, `solo` with solo or staged, `faceless_scripted` with
faceless); `host_aliases`, once `host_name` is cached, as the names the run
used, the spellings the sheets give the host in two or more videos and the
names said outright in two or more uploads, never a part of `host_name`
itself (a surname is not an alias); and
`sibling_channels`, the record's own candidates as `{link, source}`. A key
already cached is never rewritten; `cache` in the summary says `set`,
`already set` or `skipped` and why per key.

## 7. Incremental round (`refresh`)

`start_run.py` runs the fetch with these flags filled in from `ledger_meta.py
check`; the rest is:

```bash
# cast_sheet.py render/apply over <corpus>/intros-rN.jsonl, batches-rN and returns-rN (section 2),
# extractors over <corpus>/batches-rN only, then
python3 <skill>/scripts/assemble_extracts.py --batches <corpus>/batches-rN --returns <corpus>/returns-rN --out <corpus> --append && \
python3 <skill>/scripts/cluster_gems.py --in <corpus>/gems.jsonl && \
python3 <skill>/scripts/merge_pass.py prepare --clustered <corpus>/gems-clustered.jsonl --format <label> --channel <id> \
  --existing <profiles>/<id>-facts.jsonl --state <corpus>/merge-state.json --out <corpus>
# merge agents, then expand with the same --existing --state, verify, and ledger_meta.py write --rounds N
```

`prepare --existing --state` matches re-clustered clusters to existing facts
by member key (`<video_id>:<window start>`): all members known to one fact
is additive (judgment carried, recurrence recomputed); members known to two
facts, or one dropped last round, is re-judged with the `f…` ids listed; all
members dropped stays dropped; nothing known is new. `expand` keeps every
fact id, numbers new facts after the existing maximum, and marks superseded
facts instead of deleting them.

## 8. Host-alias round

When the socials lane returns a new person-name alias for the host, offer
one additive round; never start it unasked (SKILL.md, step 1):

```bash
python3 <skill>/scripts/fetch_cues.py --channel <id> --host-names "<existing>,<new alias>" --exclude <corpus>/classified.jsonl
```

A pet, spouse, company or product name belongs in a `--phrases` file, never
in `--host-names`.

## 9. Bio corroboration round

The bio batch has no video and its `start` is a text offset:
`assemble_extracts.py` refuses it; `bio_lane.py facts` mints its records.
Corroboration is one additive fetch round over terms taken from the bio
facts:

```bash
python3 <skill>/scripts/bio_lane.py terms --facts <corpus>/bio-facts.json --channel <id> --out <profiles>/.corpus --round 2 \
  --host-names "<host_names from context.json>"
# run the recipe it prints: the round's fetch, one extractor_prompt.py per batches-r2/ batch,
# one extractor per prompts-r2/ file in one message, then
python3 <skill>/scripts/assemble_extracts.py --batches <corpus>/batches-r2 --returns <corpus>/returns-r2 --out <corpus> --append
```

`--append` is required: without it the round replaces `classified.jsonl` and
round 1 is lost. `--generic-floor 0` keeps the round on its terms.

## 10. Channel context

```bash
python3 <skill>/scripts/channel_context.py --channel <id> > <corpus>/context-full.json          # before the fetch
python3 <skill>/scripts/channel_context.py --channel <id> --corpus <corpus>/corpus.jsonl.gz \
  --per-video-out <corpus>/per-video.jsonl > <corpus>/context-full.json                        # after the fetch
python3 <skill>/scripts/channel_context.py --from <corpus>/context-full.json \
  --format-label <label> --format-evidence "…" [--host-names "…"] [--known-facts "…"] --write-context <corpus>/context.json
```

`context-full.json` holds the platform's record (name, About text, AI
profile, language, sibling candidates including the cached ones with source
`cached`), what earlier runs cached on the channel record
(`cached_host_name` and `cached_host_aliases`, which end the host-name
discovery when set; `cached_format_label`, with
`cached_format_label_evidence` when the record has one;
`cached_sibling_channels`), the creator's
`websites` and
`social_links` (emails dropped), `description_anchors` (what the newest 60
upload descriptions call the host: promo-code stems, vanity-link slugs
reused under two or more domains, and the names a recurring description line
gives the host, each with its upload count; handles are left out because in
descriptions they name the other people on the video), `name_candidates`
harvested from the passages (search terms for the identity lane, never
facts; a candidate that is a relative of a description anchor is marked
`description_anchor`), and the format
stats over the fetched passages (first-person density, interview markers,
question density, `staged_share`, `likely_faceless`). The format label is
called from the `FUNNEL stage=context` line and `third_person_host_share`
as SKILL.md step 2 says; `--write-context` writes the `context.json` every
extractor message takes. Nothing exits early on `likely_faceless`.
