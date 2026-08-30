# Transcript mining

How a channel's transcripts become a profile. Three layers, in order: one
deterministic fetch, one generous local recall pass, one model layer where the
actual intelligence lives. Query credits are not a budget here; the only
budgets are model tokens and tiers, which is why everything selective runs
locally and everything intelligent runs on the cheapest model that can do it.

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
model-token spend, so it is tuned for recall, never precision:

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

Output: `windows.jsonl` (ranked) plus `batches/batch-*.json`, rank-ordered
~50-window files ready to fan out. The kept share varies hugely by format
(measured: ~18% on a faceless narration channel, 60–85% on talk-heavy solo
and interview channels) — which is why token control does NOT rely on this
layer alone: it comes from the rank ordering (the model reads the promising
windows first) and the model tiering below.

## Layer 3: the model layer — where the intelligence lives

**Haiku screens.** The classifier's rules live in ONE place:
`references/gem-classifier.md` (this skill), so every host runs the same
classifier. Fan the batch files out to the `gem-classifier` agent
(`agents/gem-classifier.md`, a thin shim over that spec), one agent per
batch, **all batches in parallel** — they are independent, so none waits on
another. Each agent gets the spec path, the context block (channel, host
names and known facts, format label with evidence) plus one batch file
path, and returns strict JSON: self-disclosure verdict, life domain,
speaker guess, sensitivity flag, caption-spelling corrections, one-line
summary. Validate the JSON against the expected shape; a malformed return
is re-run, never hand-patched.

The model catches what no lexicon can: "I'm allergic to peanuts", "we finally
finished the nursery", proper nouns read through misspellings, sarcasm and
hypotheticals. That is why the recall pass gates nothing.

**Sonnet confirms.** Windows haiku judged as gems (`self_disclosure: true`,
`speaker_guess` host or unclear) get a sonnet confirmation pass, also fanned
out in parallel batches. Sonnet checks, per gem: verbatim fidelity against the
window text, bracketed proper-noun corrections, and attribution reasoning over
the deterministic features under the rules in `evidence-rules.md` — including
the rules no feature can encode (recurrence never confirms on a multi-host
channel; an ad-read fact must recur outside reads). Sonnet's output is the
gem list that goes into the profile, each with claim, verbatim quote, video,
start seconds, life domain, sensitivity flag, and confidence bucket.

**If the host cannot spawn agents** (the skill is public; not every host is
Claude Code): run the same batches sequentially with
`references/gem-classifier.md` used inline as the prompt — it installs with
the skill on every host — discarding each batch's raw text before the next.
Same sweep, same rules, just slower.

**The orchestrating context never sees raw transcripts.** It sees the scan
summary, the classifier returns, and the profile. On a very large channel the
batches process rank-ordered, so stopping early loses the least-promising
windows, not random ones — but prefer more parallel agents over stopping.

## Entity expansion, fuzzy and free

When a gem surfaces a new entity — "my dog Luna", a spouse's name, a company
— re-scan the local corpus for it and its neighbours:

```bash
python3 <skill>/scripts/selftalk_scan.py --corpus ... \
  --host-terms "..." --entity-terms "Luna,<other new entities>"
```

The corpus is on disk, so the re-scan costs nothing. New windows it surfaces
go through the same model layer. Confirmed entities also feed Mode B's
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

Wall-clock is dominated by the model layer, and it is embarrassingly
parallel: batches fan out simultaneously, sonnet confirmations fan out the
same way, and the identity & socials lane runs alongside the whole sweep. The
fetch is a few sequential paged requests (seconds); the recall pass is local
(seconds). Target: a full profile in single-digit minutes on a large channel.
