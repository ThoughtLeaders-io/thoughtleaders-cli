# Funnel design — the ThoughtLeaders methodology, not a generic CRM

Don't design a workflow like a generic sales CRM ("Lead → MQL → SQL → Won").
Design it from how ThoughtLeaders actually sources and closes sponsorships. The
funnel stages fall out of the methodology.

## The sourcing methodology (how the pool is found)

The core play for finding the right channels for a brand:

1. **Identify the brands** — through competitor research and **Guide Brands**
   (brands that are *proven* sponsors in the category). A guide brand is a
   working example of "who already pays to sponsor this kind of content".
2. **Find the winner channels** — the channels those guide brands *renewed*
   with. A **TRUE renewal** (the brand came back and paid again) is the real
   signal that the channel converts, not a vanity metric.
3. **Find look-alike channels** — channels similar to the winners (same
   audience/niche/shape) that haven't been booked yet. This is the addressable
   pool.
4. **Analyse value vs price** — for each candidate, is the projected value
   (views, audience fit) worth the price? This is the qualification gate.

The entry stage of a workflow is the output of steps 1–3 (the look-alike pool),
expressed as a **query**. Qualification (step 4) is the first downstream list
stage.

## Terminology to keep straight (TL uses its own words)

- **Brands** = the sponsors (usually companies, sometimes a single product).
- **Channels** = the creators being sponsored (YouTube channels, sometimes
  podcasts).
- **Sponsorship** is the umbrella; it narrows through a funnel of its own:
  *Sponsorships ⊃ Matches ⊃ Proposals ⊃ Deals (sold)*.
- Pricing words: **PV** = Projected Views (a pricing estimate); **VG** = View
  Guarantee (the contractual floor). Don't invent CPM/"margin" language — TL
  says **Net revenue** / **TL profit**, and avoid "flight" / "hero channel".
- **Send date** = the expected publication date of a sponsored video.
- Two channel networks exist: **MSN** (the large ~11K opted-in Media Selling
  Network) and **TPP** (the small ~169 directly-managed VIP channels). Sourcing
  usually works over MSN; enrichment tasks ("get face on screen") are often
  assigned to MSN managers.

## The canonical acquisition funnel

A good default channel-acquisition workflow, with each stage's type and the
column the team acts on. Offer this, then let the user cut / rename / reorder.

| # | Stage | Type | What it means | Acted-on column |
|---|-------|------|---------------|-----------------|
| 1 | **Sourced** | query | The pool: look-alike channels for the brand's guide-brand winners (or a topic filter). | — |
| 2 | **Qualify** | list | Passed value-vs-price (and, if relevant, an authenticity check). | Projected views / price |
| 3 | **Get face on screen** | list | Assigned to MSN managers to fill in face-on-screen + enrich. | Face On Screen |
| 4 | **Reach out** | list | Has an outreach email; ready to contact. | Outreach email |
| 5 | **Contacted** | list | Outreach sent. | — |
| 6 | **Proposed** | list | A proposal is out. | — |

Notes:
- Stages 5–6 mirror the sponsorship sub-funnel (Match → Proposal → Deal); stop
  wherever the team's process stops. Don't add stages the team won't work.
- For a **brand-prospecting** workflow (report_type = brands) the shape rebases:
  *Prospects (query: brands in a category / competitors of a guide brand) →
  Qualified → Pitching → Won*.

## Sizing the pool (breadth)

There is no universal right number. A niche brand with a few dozen good
look-alikes is a complete answer; a broad consumer brand returning a few dozen
is probably too narrow. State your breadth judgement and offer to narrow/widen —
exactly the calibration `tl-keyword-research` does. The pool is the query stage;
everything downstream is a subset of it.
