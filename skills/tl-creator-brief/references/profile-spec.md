# Output specification

## The profile is the contract

`tl-creator-profiles/<channel_id>-profile.md` is **the stable interface**
other skills and future runs consume — briefs, gifts, outreach, negotiation
prep. The connections document is a result, not a second contract. Both are
files, never chat messages: chat scrolls away and these are made to be picked
up later. Write them into `tl-creator-profiles/` under the invocation
directory (create it if missing; never write inside the skill's own
directory), return the paths, and name files from resolved IDs only — IDs are
exact, names are fuzzy and change on rebrands, and deterministic names let a
re-run overwrite its own output.

## Mode A: `<channel_id>-profile.md`

Versioned YAML frontmatter, so machines consume it reliably:

```yaml
---
schema: tl-creator-profile/v1
channel_id: 123456
channel_name: "..."
generated_at: 2026-08-27
corpus_window: [2016-03-01, 2026-08-20]
videos_total: 412
videos_with_transcript: 287
transcript_coverage: 0.70
format: solo            # solo | interview | multi_host | faceless_scripted
format_evidence: "fp density 41/1k words median; 2 videos with interview markers"
credits_spent: 1840
---
```

Then the body:

1. **Who they are** — two or three lines from the identity lane, with the
   host name(s) that keyed attribution.
2. **Facts, grouped by life domain** (origin, family, pets, home, work,
   money, health, habits, tastes, beliefs, relationships, other). Each fact:
   - **claim** — one line, plain words;
   - **evidence** — for `transcript` provenance the verbatim quote, `&t=`
     deep link and video date; for `social` the profile URL and seen-date;
     for `web` the source URL;
   - **recurrence** — distinct videos/sources, never snippet count;
   - **confidence bucket** per `evidence-rules.md`; cross-lane corroborated
     facts state both lanes;
   - **sensitive** flag where it applies.
3. **Superseded facts** — latest-wins history with dates, kept visible.
4. **Socials** — each linked platform: read, or "linked but unread" with the
   reason (a login wall is a fact, not a silent skip).
5. **Coverage & caveats** — read/available ratio, the "absence is not
   evidence" line, dropped-as-unattributable count, unconfirmed count, the
   format's confidence cap, caption corrections made.

An empty profile still carries sections 1, 4 and 5 — "no evidence found",
bounded by the numbers, is a complete forwardable answer.

## Mode B: `<channel_id>-<brand_id>-connections.md`

A ranked connection map. Header: both IDs, profile file it was built from,
brand-read date. Then each connection, strongest first:

1. **The creator's own words** (or social/web fact, labelled as such) —
   verbatim, timestamped, from the profile.
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

## Reuse

Before Mode A, look for an existing `<channel_id>-profile.md`. Offer it —
when it was generated, its corpus window — and ask whether to reuse or
rebuild. Never reuse silently (it has missed everything uploaded since);
never refuse to rebuild.

## Never in either file

Prices, costs, rate cards, deal terms, other clients' internal data,
performance grades, or drafted ad copy. Both files are built to be forwarded.
