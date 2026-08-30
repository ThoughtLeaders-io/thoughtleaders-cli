# Output specification

## Two layers, one contract

A profile build emits two files into `tl-creator-profiles/` under the
invocation directory (create it if missing; never write inside the skill's
own directory):

- **`<channel_id>-facts.jsonl`** — the machine ledger, one fact per line.
  This is **the stable interface** other skills, personas and CONNECT runs
  consume. Full thoroughness lives here; no human is expected to read it.
- **`<channel_id>-profile.md`** — the human one-pager, hard-capped at
  **~600–800 words**. A person forwards this; it never carries the evidence
  ledger in its body.

The connections document is a result, not a third contract. All outputs are
files, never chat messages: chat scrolls away and these are made to be
picked up later. Return the paths, and name files from resolved IDs only —
IDs are exact, names are fuzzy and change on rebrands, and deterministic
names let a re-run overwrite its own output.

## The machine ledger: `<channel_id>-facts.jsonl`

One JSON object per line, only quote-verified and judgment-passed facts:

```json
{"fact_id": "f012",
 "claim": "adopted a rescue dog named Luna",
 "domain": "pets",
 "provenance": "transcript",
 "quote": "we finally adopted luna from the shelter last spring",
 "video": "48247:dQw4w9WgXcQ",
 "start": 512,
 "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=512s",
 "published": "2024-05-01",
 "recurrence": 3,
 "confidence": "confirmed",
 "sensitive": false,
 "superseded_by": null,
 "selected": true}
```

- `domain`: one of `origin`, `family`, `pets`, `home`, `work`, `money`,
  `health`, `habits`, `tastes`, `beliefs`, `relationships`, `other`.
- `provenance`: `transcript` | `social` | `web`, per `evidence-rules.md` —
  lanes never masquerade. `social`/`web` facts carry `source_url` and
  `seen_date` instead of `quote`/`video`/`start`/`url`.
- `quote`: verbatim, in the source language; exact-verified by
  `scripts/verify_quotes.py` before it lands here. A non-English quote may
  carry a `gloss` (English translation, labelled — never the quote itself).
- `recurrence`: distinct videos/sources, never snippet count.
- `confidence`: `confirmed` | `unconfirmed`, per `evidence-rules.md`
  (dropped facts never enter the ledger; their count goes in the coverage
  caveats).
- `superseded_by`: the `fact_id` of the newer fact when latest-wins applies;
  superseded facts stay in the ledger as history.
- `selected`: true on the 15–20 strongest facts — the ones the one-pager
  shows. Selection favors confirmed, recurring, cross-lane-corroborated and
  connection-fertile facts.

CONNECT loads this file, not the markdown.

## The human one-pager: `<channel_id>-profile.md`

Versioned YAML frontmatter, so machines can still index it:

```yaml
---
schema: tl-creator-profile/v2
channel_id: 123456
channel_name: "..."
generated_at: 2026-08-31
corpus_window: [2016-03-01, 2026-08-20]
videos_total: 412
videos_with_transcript: 287
transcript_coverage: 0.70
format: solo            # solo | interview | multi_host | faceless_scripted
format_evidence: "fp density 41/1k words median; 2 videos with interview markers"
facts_file: 123456-facts.jsonl
facts_total: 291
credits_spent: 1840
---
```

Then the body, **~600–800 words total**:

1. **Who they are** — two or three lines from the identity lane, with the
   host name(s) that keyed attribution.
2. **Channel format** — one line: the label and what it means for
   attribution confidence.
3. **The strongest facts** — the 15–20 `selected` facts, grouped by life
   domain. Each is ONE line: the claim, plus a short verbatim quote with its
   `&t=` link when it earns its place; confidence and sensitive flags as
   bracketed tags. No per-fact evidence blocks — the ledger holds those.
4. **Other channels** — sibling/second channels the identity lane surfaced:
   name, id, video count, and "not mined" unless a human asked (see
   SKILL.md). Each linked social platform: read, or "linked but unread" with
   the reason.
5. **Coverage & caveats** — read/available ratio, `windows_over_cap`, the
   "absence is not evidence" line, dropped-as-unattributable count,
   unconfirmed count, the format's confidence cap, caption corrections made.

An empty profile still carries sections 1, 4 and 5 — "no evidence found",
bounded by the numbers, is a complete forwardable answer.

## Mode B: `<channel_id>-<brand_id>-connections.md`

A ranked connection map. Header: both IDs, the facts file it was built from,
brand-read date. Then each connection, strongest first:

1. **The creator's own words** (or social/web fact, labelled as such) —
   verbatim, timestamped, from the ledger.
2. **What the brand offers that meets it**, and which brand-read lane that
   came from.
3. **How this could be used** — one neutral line. Connection material, not ad
   copy; nobody is handed words to read aloud.

Type each connection: **direct** (fact ↔ product), **adjacent**
(lifestyle/context fit), or **category precedent** (the creator already does
what the product enables, from the confirm-only probe). Sensitive-flagged
facts do not appear unless a human opted one in. If nothing honestly
connects, the document says so, lists what was searched, and stops — a no-fit
verdict is the deliverable, not a failure.

## HTML views

Both human documents also render to self-contained HTML via
`scripts/build_html.py` (deterministic template — never hand-written per
run): `<channel_id>-profile.html` (pass `--facts` for the ledger strip) and
`<channel_id>-<brand_id>-connections.html`. Markdown + JSONL remain
canonical; the HTML is the human view. When the host supports publishing
artifacts, publish the HTML so the user gets a link; the files in
`tl-creator-profiles/` are the durable copies.

## Reuse

Before Mode A, look for an existing `<channel_id>-facts.jsonl` +
`<channel_id>-profile.md` pair. Offer it — when it was generated, its corpus
window — and ask whether to reuse or rebuild. Never reuse silently (it has
missed everything uploaded since); never refuse to rebuild. A v1 profile
(`schema: tl-creator-profile/v1`, no facts file) predates the ledger split:
offer it as context but a CONNECT run needs a rebuild to get its ledger.

## Never in any file

Prices, costs, rate cards, deal terms, other clients' internal data,
performance grades, or drafted ad copy. Every output is built to be
forwarded.
