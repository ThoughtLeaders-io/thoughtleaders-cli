# Golden Queries — Report Builder v2

Hand-curated natural-language requests used to evaluate the skill end-to-end.
Each entry captures the request as a user would say it, the report type the
skill should infer, the topic(s) it should match, and what a "good" output
looks like. Use these for manual sanity checks during Milestones 2–5 and as
seed inputs to the offline Creator/Judge/Coder loop in Milestone 8.

> **Status: Milestone 1.** Examples below are seeds, not yet exercised against
> a working skill. As prompts come online, annotate each with actual results
> and flag failures.

## How to read an entry

```
### N. <one-line summary of the request>

**User says**: "<verbatim NL request>"

**Expected report type**: <CONTENT | BRANDS | THOUGHTLEADERS | ...>

**Expected topic match(es)**: <topic name(s) from data/topics_v1.json>

**Expected filter shape**: <bullet list of must-have filters>

**Validation expectation**: <rough non-zero count band, or "should narrow"
                            if the first attempt is too broad>

**Notes**: <gotchas, ambiguities, or what the skill should ask about>
```

---

## Channel-discovery requests

### 1. Mid-size US gaming channels

**User says**: "build me a report tracking US gaming channels with 100k–1M subs"

**Expected report type**: CHANNELS

**Expected topic match**: Gaming (strong)

**Expected filter shape**:
- `category:gaming` (or topic match → gaming keyword expansion)
- `min-us-share:50`
- `min-subs:100k`
- `max-subs:1m`

**Validation expectation**: hundreds to low thousands of channels.

**Notes**: a `max-subs` filter may not exist as a CLI key — the skill should
verify via `tl describe show channels` and fall back to post-filter if needed.

---

### 2. Mobile-first cooking channels in the UK

**User says**: "I want to monitor UK cooking channels whose audience is mostly on mobile"

**Expected report type**: CHANNELS

**Expected topic match**: Food & Drink (strong)

**Expected filter shape**:
- topic / category alignment with cooking
- `primary-device:mobile`
- `min-gb-share:50`

**Validation expectation**: tens to low hundreds.

**Notes**: tests demographic filter handling.

---

### 3. Look-alike cohort

**User says**: "set up a dashboard for channels similar to MrBeast"

**Expected report type**: CHANNELS

**Expected topic match**: none (request is identity-based, not topic-based)

**Expected filter shape**:
- skill should suggest `tl channels similar` as a more direct path,
  *or* construct a saved report based on similar channels' shared traits
  (subs band, category, demo profile)

**Validation expectation**: ~10–50 channels.

**Notes**: edge case — skill should ask the user whether they want a static
list (look-alike snapshot) or a live filter.

---

## Sponsorship / deal pipeline requests

### 4. Sold deals this quarter

**User says**: "build me a report of all sold deals in Q2 2026"

**Expected report type**: SPONSORSHIPS (or DEALS)

**Expected topic match**: none

**Expected filter shape**:
- `status:sold`
- `purchase-date-start:2026-04-01`
- `purchase-date-end:2026-06-30`

**Validation expectation**: should match the user's actual booked count;
non-zero unless they have no Q2 sales.

**Notes**: tests date-range handling and the bookings convention
(filter sold by `purchase_date`, not `created_at`).

---

### 5. Pending matches in tech

**User says**: "I want to track pending matches with tech channels"

**Expected report type**: SPONSORSHIPS

**Expected topic match**: Technology / Computing (strong)

**Expected filter shape**:
- `status:matched` (or `status:pending` — skill should verify via describe)
- topic / category alignment with tech

**Validation expectation**: tens to hundreds.

---

### 6. High-CPM live ads last 90 days

**User says**: "show me sold sponsorships with high CPM in the last 90 days"

**Expected report type**: SPONSORSHIPS

**Expected topic match**: none

**Expected filter shape**:
- `status:sold`
- `publish-date-start:<90 days ago>`
- (CPM is post-filter only — skill should note this)

**Validation expectation**: result depends on user's pipeline.

**Notes**: tests the documented CPM constraint — no range filter on the
server, so the skill should either pull a wider set and apply CPM in
post-processing or ask the user to relax the request.

---

## Brand / advertiser requests

### 7. Brands in fitness

**User says**: "build a report of brands advertising in the fitness space"

**Expected report type**: BRANDS

**Expected topic match**: Fitness / Health & Wellness (strong)

**Expected filter shape**:
- topic / category alignment with fitness

**Validation expectation**: tens to a few hundred.

---

### 8. Brand history on a specific channel

**User says**: "what brands has channel 12345 worked with — make it a saved report"

**Expected report type**: SPONSORSHIPS (filtered by channel)

**Expected topic match**: none

**Expected filter shape**:
- `channel:12345`
- `status` filter to whatever the user means by "worked with" (likely sold)

**Validation expectation**: matches `tl brands history --channel 12345 --json` count.

**Notes**: skill should consider whether the user wants `tl brands history`
(one-shot) versus a saved report (recurring).

---

## Content / upload requests

### 9. Recent gaming long-form videos

**User says**: "save a report of long-form gaming videos uploaded this month"

**Expected report type**: CONTENT (uploads)

**Expected topic match**: Gaming (strong)

**Expected filter shape**:
- topic / category alignment with gaming
- `type:longform`
- `publish-date-start:<first of month>`

**Validation expectation**: hundreds to low thousands.

---

### 10. AI-themed videos with high views

**User says**: "track high-performing AI videos from the last 30 days"

**Expected report type**: CONTENT

**Expected topic match**: Artificial Intelligence (strong)

**Expected filter shape**:
- topic / keyword expansion for AI
- `publish-date-start:<30 days ago>`
- view threshold (post-filter, depending on schema)

**Validation expectation**: hundreds.

---

### 11. Multi-topic ambiguity

**User says**: "I want a dashboard for AI cooking shows"

**Expected report type**: CONTENT

**Expected topic match**: AI **and** Food & Drink (both potentially strong)

**Expected filter shape**: depends on disambiguation — skill should ask
whether the user means AI-about-cooking, cooking-by-AI, or videos that hit
both topics.

**Validation expectation**: small (intersection); broad if the user
clarifies they mean union.

**Notes**: this is the canonical disambiguation case from Q2 of the
architecture doc.

---

## Edge cases / failure modes

### 12. Zero-result narrow query

**User says**: "track UK kids' DIY origami channels with at least 1M subs"

**Expected report type**: CHANNELS

**Expected topic match**: weak (no clean topic for origami)

**Expected filter shape**: keyword-expansion heavy.

**Validation expectation**: zero — should trigger Phase 3 retry with
broader keywords or `min-subs` relaxation.

**Notes**: tests the validation loop's narrowing logic.

---

### 13. Enormous query

**User says**: "show me all sponsorships ever"

**Expected report type**: SPONSORSHIPS

**Expected filter shape**: nothing → everything.

**Validation expectation**: millions — should trigger Phase 3 narrowing.

**Notes**: tests guardrails. Skill should ask for narrowing rather than
build a filter-less report.

---

### 14. Vague request

**User says**: "make me a report"

**Expected report type**: ambiguous.

**Expected behaviour**: skill asks a clarifying question rather than
guessing. No FilterSet should be produced.

---

### 15. Wrong tool request

**User says**: "how many sold deals last week?"

**Expected behaviour**: this is a one-shot data question, not a
report-building request. Skill should defer to the `tl` data-analyst
skill or directly answer with `tl deals list status:sold ...`.

**Notes**: tests the trigger boundary.

---

## Demographics-driven requests

### 16. Young US mobile audience

**User says**: "build a report for channels with a young US audience that watches on mobile"

**Expected report type**: CHANNELS

**Expected filter shape**:
- `min-us-share:60`
- `primary-device:mobile`
- (age demographics — skill should verify available filters via describe)

**Notes**: tests demographic-filter discovery.

---

### 17. International-skewing channels

**User says**: "monitor channels whose audience is more than half outside the US"

**Expected report type**: CHANNELS

**Expected filter shape**:
- inverse of `min-us-share` — verify whether `max-us-share` exists or
  fall back to post-filter.

**Notes**: tests negative-share filter handling.

---

## Time-based requests

### 18. Booked-this-week tracker

**User says**: "I want a recurring report of deals booked this week"

**Expected report type**: SPONSORSHIPS / DEALS

**Expected filter shape**:
- `status:sold`
- `purchase-date-start:<start of week>`

**Validation expectation**: small to medium.

**Notes**: tests rolling-window date semantics. Skill should consider
whether the saved report uses an absolute or relative date range
(`today`, `yesterday` keywords).

---

### 19. Year-over-year comparison

**User says**: "build me a report comparing this quarter's sold deals to the same quarter last year"

**Expected report type**: SPONSORSHIPS

**Expected filter shape**: depends on whether the report supports
side-by-side periods or whether the skill should suggest two saved reports.

**Notes**: edge case — saved-report schema may not support multi-period.
Skill should explain the limitation if it exists.

---

## Identifier-based requests

### 20. Specific brand pipeline

**User says**: "save a tracker for everything Nike-related in the pipeline"

**Expected report type**: SPONSORSHIPS

**Expected topic match**: none (brand-specific).

**Expected filter shape**:
- `brand:Nike` (or numeric brand ID — skill should resolve via
  `tl brands show Nike`)

**Validation expectation**: depends on Nike's actual pipeline volume.

**Notes**: tests entity-resolution flow (name → ID).
