---
name: tl-creator-gifts
tl-blurb: personal creator gifts with verified facts and practical sourcing
description: Suggest a personal gift for a YouTube creator using their existing verified TL creator profile, with a maker-ready customization brief and checked purchase and delivery options. Use for creator gifting or custom gift recommendations, not generic merch design, ordering, or sponsorship performance analysis.
---

# Creator gifts

Give the buyer one strong choice and at most two genuinely different alternatives.
A personal gift must have a useful place in the recipient's life; a logo on generic
swag or a single hobby mention is not enough. No good fit is a useful result.
For help requests explain the workflow and dependencies without paid queries.

## Start with what changes the choice

Resolve the creator with `tl channels find`. For a multi-host channel identify the
actual recipient and map their name to host/cohost from source evidence; never
infer that mapping from the ledger's `people` field. A shared gift needs an
explicitly shared premise. Resolve a named sender brand with `tl brands find`,
without claiming a client relationship or a booking.

Use supplied context first: who funds and sends the gift, relationship, occasion,
budget and currency (including delivery/tax), destination country, arrival date,
and exclusions. Ask once for only missing details that change the recommendation.
In an unattended run propose brand-funded and brand-sent, mark this assumption,
and continue with unconstrained concepts if budget, destination or deadline is
unknown. Do not present those concepts as ready to order.

## Reuse the profile

Requires the `tl` and `tl-brand-creator-connection` skills. Locate them using the
host's skill discovery; read the latter's PROFILE instructions, profile-spec and
evidence-rules. Use its absolute directory as `<profile-skill>` below. If absent,
report the missing dependency and the normal `tl setup <host>` install route;
do not hunt another user's files or copy extraction code.

Use PROFILE's `start_run.py` and existing freshness decision, announcing reuse,
refresh or build. Preserve incremental refresh, quote verification and attribution.
Do not force `--no-refresh` to bypass stale evidence. Keep the gift workflow
read-only on TL: on `cast_sheet.py apply`, omit optional `--context-full`; on
`ledger_meta.py write`, omit optional `--context`. These options enable PROFILE's
optional metadata cache writes. Still use the full context for cast rendering,
attribution and extraction, and pass the writer's channel/format/lanes arguments.
Skip optional completion telemetry. If the installed PROFILE version cannot
build without remote writes, report that dependency; never synthesize a ledger.

Light web research is ON by default for gifts, including when PROFILE reuses a
transcripts-only ledger. Keep it separate from the canonical ledger: at most three
creator search queries and six source-page opens. Prefer the creator's linked
site, own social posts and first-person interviews. Record quote/excerpt, URL,
publication date when available, access date and identity evidence. A third-party
claim or a current access date alone does not confirm a current personal fact.
Use this supplement to corroborate, update or veto a gift premise; it cannot
replace a missing verified PROFILE. Do not expand into PROFILE's uncapped social
research unless separately requested. Respect explicit web-off requests and
explain any resulting evidence gap.

Read the ledger only through its existing `store_io.read_ledger`. The optional
helper below loads that reader from an explicit installed location and rejects
ineligible facts. It is a candidate filter, not a source verifier or gift ranker:

```bash
python3 <gift-skill>/scripts/gift_candidates.py \
  --profile-skill <profile-skill> --ledger <absolute-ledger-path> \
  --channel <resolved-id> --as-of YYYY-MM-DD --recipient-role host
```

Use `cohost` or `shared` only after the recipient mapping above. Missing/legacy
headers or old profiles require PROFILE; no eligible facts means no good fit.
The helper never returns rejected details. Do not copy the full ledger into the
gift output. Published ledgers strip verification bookkeeping: a valid header is
not proof of source truth. Reopen every proposed premise's source/corpus context
before using it and record the exact support. Failed source access leaves the
premise unverified; omit it from the shortlist.

## Select and source together

Judge each premise for current personal meaning, utility, originality, respect
and feasibility. A recurring preference is stronger than a passing mention;
ask whether they already own the item. Separate facts from the inference that
they might enjoy this gift. Unresolved contradictions veto all affected ideas.

Exclude unconfirmed, ended, superseded, staged-only and hook-only premises.
For gifting, also exclude clinical, children and precise-location details,
intimate relationships, finances, bereavement, and third-party personal details,
even if publicly disclosed. Public does not automatically mean appropriate.
Respect the creator's stated no-gift policy and boundaries around private life;
public professional work may be the only appropriate basis for a concept.
Do not encode rejected details in a design, example, note, filename or explanation;
explain exclusions only by category. Lifestyle facts still need contextual review.
Do not print a spouse's name, home location or private milestone onto a gift.

For every promising idea immediately find a way to make and ship it. Cap supplier
research at six search queries and twelve source-page opens per run. Stop when
verified feasible options are sufficient; if caps prevent verification report the
gap rather than inventing a vendor or expanding silently. Source revisits count
toward these caps; local corpus reads do not.

Prefer a direct single-item maker/retailer with customization and a clear delivery
route over opening a merch store. Compare an appropriate engraved/handmade maker,
print-on-demand/custom dropshipper (including Fourthwall when relevant), and an
ordinary retail option. No default partner affiliation. Verify the exact variant,
quantity-one availability, permitted artwork/text, proof approval, current price
and currency, production window, destination-specific transit, customs/tax,
packaging and recipient/order link. Separate advertised estimates from guarantees.
Never substitute a platform-wide claim for an item's country eligibility.

Unknown shipping charge, customization surcharge or taxes must be stated as
unknown, not zero. A base-price-only listing is a concept pending a landed quote
when the buyer has a hard total budget. Calculate production plus transit plus
reasonable buffer in business days, including weekends/holidays. If arrival or
destination cannot be verified, or stock is unavailable, drop or swap the idea;
do not rank it as a feasible recommendation. A checkout-dependent quote may be
left as a clearly labelled concept. Never use checkout to submit an order.

Public country information can guide research, never a home address. The buyer
ships only to an address the creator/manager supplies, an authorized manager or
confirmed PO box. Confirm carrier acceptance of PO boxes. A move, customs or
cross-border restriction can change the vendor and invalidate the timing.

## Deliver

Use [output-and-evaluation.md](references/output-and-evaluation.md) for the
shortlist, maker brief, examples and optional later evaluation design. Save in
the user's output folder outside the skill and source repository; return absolute
paths. Keep profile data and buyer-specific outputs out of version control.

Report creator and supplier query/page counts, elapsed research time, actual TL
credits from usage receipts, and model/search monetary cost if exposed. Mark an
unavailable monetary cost as unreported; never call it free or infer it from gift
prices. Profile build cost and gift cost are separate. No purchases, messages,
partner terms, release or automatic checkout are implied by a recommendation.
