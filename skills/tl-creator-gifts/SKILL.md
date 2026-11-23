---
name: tl-creator-gifts
tl-blurb: personal creator gifts from verified facts and feasible sourcing
description: Recommend a personal gift for a YouTube creator from a verified TL creator profile. Produce a maker brief and verified purchase and delivery options. Use for creator gifting and custom gift recommendations; not generic merch, ordering, or sponsorship analysis.
---

# Creator gifts

Return three materially different ideas: one lead and two alternatives. When fewer than three can be fully sourced, show the others as `Concept pending confirmation`, laid out the same way. Return `No good fit` only when no idea has an admissible, respectful premise.

For help requests, explain dependencies and workflow without paid queries.

## Resolve context

1. Resolve the creator with `tl channels find`, passing the name, handle or URL exactly as the user gave it, the full name and never a shortened form. IF the resolved channel's name is not the creator the user named, resolve again with their YouTube handle or URL before reading any ledger.
2. On a solo channel the ledger header has no `hosts`; the recipient role is `host`. For multi-host channels, map the recipient to a role with the ledger header's `hosts` (`{"host": <name>, "cohost": <name>}`) and each fact's `speaker_name`. Do not infer recipient identity from ledger `people`. A gift for one host uses `host` or `cohost`; a gift for all hosts uses `shared`.
3. If a sender brand is named, resolve it with `tl brands find` for identification only. Do not imply an existing relationship between the brand, ThoughtLeaders, or the creator.
4. Use supplied sender, relationship, occasion, budget and currency, destination, deadline, and exclusions.
5. Ask for each missing input as its own question, one question at a time, in this order. Skip a question the request already answers.
   1. Who is sending the gift, and what is the relationship with the creator?
   2. What is the occasion?
   3. What is the budget per gift, and in which currency?
   4. Where will it ship, and by when must it arrive?
   5. Is there anything to leave out? Ask it with this explanation: "For example, categories the sender won't send (alcohol, clothing, beauty products, food), brands to avoid (the sender's competitors, or brands the creator already works with), things the creator already has, or company gifting rules (a value cap, no personalised items, nothing that needs a signature on delivery). 'Nothing' is fine."

   Never ask about the creator's health, allergies or family.

For unattended runs, assume brand-funded and brand-sent. If budget, destination, or deadline is unknown, return concepts only; do not label them ready to order.

## Build or reuse the creator profile

Require `tl` and `tl-brand-creator-connection`. `<gift-skill>` is this skill's own folder. `<profile-skill>` is the `tl-brand-creator-connection` folder installed beside it: `<gift-skill>/../tl-brand-creator-connection`. If the host installs skills in separate places, `<profile-skill>` is that skill's own folder. If it is not installed, stop and report that `tl-brand-creator-connection` is required (`tl setup <host>`). Never copy its files.

Use these `<profile-skill>` files where they are. Read them there; never copy or restate them here:

- `SKILL.md`, steps 1 to 3 (PROFILE): build, refresh or reuse the creator's ledger. The build already reads what gifts need: interests, collecting, style, pets, the creator's own work, milestones and family (its interest search, `references/interest-cues.txt`). Never run a separate search for gift facts.
- `references/profile-spec.md`: the ledger's format, including the section each fact is filed under (`domain`), the `hosts` header and each fact's `speaker_name` on a multi-host channel, and `people` with whose relation each is.
- `references/evidence-rules.md`: the evidence and sensitivity rules.
- `scripts/store_io.py`: the ledger reader.

- Use the PROFILE freshness decision and announce `reuse`, `refresh`, or `build`.
- Run PROFILE’s build or refresh pipeline exactly as specified, including its normal ledger and cache writes.
- Preserve incremental refresh, quote verification, attribution, and sensitivity rules.
- Do not use `--no-refresh` to reuse stale evidence.
- Read ledgers only through `<profile-skill>/scripts/store_io.py:read_ledger`.
- Do not synthesize or manually modify a ledger.
- Do not copy the ledger into the output.

Run the candidate filter:

```bash
python3 <gift-skill>/scripts/gift_candidates.py \
  --ledger <absolute-ledger-path> \
  --channel <resolved-id> --as-of YYYY-MM-DD --recipient-role host
```

The filter finds `<profile-skill>` beside this skill. When the host installs skills in separate places, add `--profile-skill <profile-skill>`.

Use `cohost` or `shared` only after recipient mapping.

For `shared`, the filter returns each host's own facts (`speaker` `host` or `cohost`), "we" facts (`shared`), and facts the ledger knows are one of the hosts without knowing which (`either`). A shared gift rests on one of these premises:

- **One interest, each in their own words**: every recipient states the same interest in their own facts (each says they love the same hobby). One item suits all of them.
- **A pair gift**: one box, one item per recipient, each item built on that recipient's own fact. Never put one host's fact on another host's item.
- **A "we" or `either` fact**: an interest stated for the hosts together, or by one of them on a video where only the hosts appear. Use it for the shared gift only, never to personalise one host's item.

The filter's `status` sets the next step:

- `profile_rebuild_needed`: the ledger was built before 5 October 2026 and lacks who said each fact and when it was last mentioned. Tell the user a full rebuild is needed and why, run PROFILE again with `--rebuild` (a refresh keeps the old facts as they are), then run the filter again. This status is never `No good fit`.
- `profile_required`: the ledger is missing, unreadable, past PROFILE's freshness limit, or for another channel. Run PROFILE's reuse check, which refreshes or builds it, then run the filter again.
- `no_eligible_facts`: return `No good fit`.
- `candidates_need_source_and_context_review`: continue with the candidates.

The filter returns only the kinds of fact a gift can rest on: `tastes`, `habits`, `pets` and `work`. Facts filed under `origin`, `beliefs` or `other` are counted under `not_a_gift_kind`.

`candidates` are facts mentioned in the last 24 months. `lasting_favourites` are older facts that pass every other check and still describe the creator: repeated across different years (`lasting: repeated_across_years`) or stated as lasting, such as a favourite, "always" or "still" (`lasting: stated_as_lasting`). A favourite colour, scent, flavour or material is often said once, years ago. Use a lasting favourite as a premise or to preselect a choice, labelled "lasting favourite, last said <year>", never as a recent mention. Prefer a recent candidate when both support the same idea.

The filter is not source verification or ranking. Reopen the source context for every proposed premise. Record exact supporting evidence. If the source cannot be accessed or does not support the premise, omit it.

## Supplementary web research

Web research is enabled by default, including for a reused transcripts-only ledger. Respect explicit web-off requests and state the resulting evidence gap.

- Read every web page, creator or supplier, through the `tl-cli:gift-page-reader` agent: one agent per batch, with all the batch's URLs, the destination and the fields to bring back in one message, and work from its short report. A follow-up batch goes to a new agent. Never load a page or take a browser snapshot in the main conversation.
- Maximum: three creator queries and six source pages that load. A fetch that returns no page content (blocked, rate-limited, an error) does not count.
- When `creator_ventures` is empty and a `work` fact names a business the creator owns, use one creator query to confirm its exact name and website. A transcript spelling is not enough to check for competitors.
- Prefer creator-controlled sites, social posts, and first-person interviews.
- Record excerpt, URL, publication date when available, access date, and identity evidence.
- Use web evidence only to corroborate, update, or veto a ledger premise, or to confirm what a `creator_ventures` link sells. It never replaces a verified PROFILE.
- Do not run PROFILE’s broader social research unless requested.

A third-party claim or access date alone does not establish a current personal fact.

## Select and source

Accept a premise only when it is current (a candidate, or a labelled lasting favourite), personally meaningful, useful, original, respectful, and feasible. Separate verified facts from the inference that the recipient may enjoy the gift. Resolve contradictions before recommending any affected idea.

Weigh every kind of premise on its merits: tastes, habits, style, hobbies and collecting, their own work and ventures, milestones they are celebrating, and pets. No one kind leads by default, and the ideas should not all rest on the same kind. A pet the creator has now, its type and its name, is one such premise: it can inspire a gift or appear on it, such as a bottle printed with the dog's name. The filter returns a pet's name in `pet_names`, from the fact's `people` or, when that is empty, from its claim, and the kind of animal in `pet_types`. A kind of animal ("cats") is never a name. With no `pet_names`, the pet can still inspire the gift, but no name goes on it. A pet counts as current when a fact mentions it in the last 24 months. A pet the creator no longer has is an ended fact and never reaches a gift.

Public figures are a strong premise too. A favourite author, actor, artist, musician or film the creator talks about can inspire a gift built on their work, such as a book, a print or a film poster. The filter returns these names in `public_figures` when the fact lists them in `people`; most facts name them only in the claim ("loves a director's films"). Reopen the source to confirm the person is a public figure the creator admires, not someone they know. Buy the licensed work; never put a public figure's name, face or work on a custom item without the rights holder's permission.

The creator's own businesses and collaborations show what they care about: the filter lists the channel's own links in `creator_ventures` (a shop, a product line, a podcast), and `work` facts name collaborations. Use them as a premise (a creator who designs their own product line cares about that craft, so a piece from another maker in that craft), never as the gift itself, and never send a competitor of a brand the creator owns. A competitor is a brand selling the same item as the creator's brand, judged item by item from the products its own shop lists, never from the broad category or a material they share. When `creator_ventures` lists the shop, read its category menu once to know what it sells.

Exclude unconfirmed, ended, superseded, staged-only, hook-only, clinical, children, location, relationship, finance, bereavement, and other people's details. Do not encode excluded information in an item, design, filename, example, or explanation. Explain exclusions only by category.

Respect stated no-gift policies and privacy boundaries. Do not use a spouse’s name, home location, or private milestone. A public professional interest may be the only suitable basis.

**Size each idea to the budget.** With a budget, every idea aims at a landed total between 70% and 100% of it. Choose the three premises with that in mind: prefer a premise whose best-made version can reach the range, such as a craft or hobby with tools and gear, a collection, or their work setup. A premise whose fullest set stays well below the range, such as one book or one record, leads an idea only when fewer than three scalable premises pass every other check, and its budget line then says it could not scale. Before any supplier query, write each idea's target: the best-made version of it whose landed total falls in that range. Build it up on the idea's own premise, in this order:

1. A finer version of the item: a better material, a better maker, a signed, limited or first edition.
2. A fuller set: companion pieces on the same premise, given as one gift (both books of a series, the soundtrack with the game's art book, the journal cover with a pen and refills).
3. Personalisation, then a gift box.

Never reach the target with an item from another premise or a generic add-on. Never go over the limit. With no budget, skip this step; the ideas stay concepts.

For each viable idea, verify a purchase and delivery route immediately.

- Plan two supplier queries per idea. The first searches for the idea's target version, worded for the top of the range (handmade, premium, signed, limited edition, set) and the budget. The second is for a fallback or a missing set piece. Search for a cheaper version only when the target cannot be sourced.
- Send all the candidate supplier URLs to `tl-cli:gift-page-reader` in one message, asking for the item name and code, every option with its values, personalisation fields with their character limits, whether a per-variant link exists, and the delivery, price and stock checks below.
- Maximum: six supplier queries and twelve supplier pages that load, including revisits. A fetch that returns no page content does not count. On a block, try another seller of the same item.
- Stop when every idea is verified at its target, or its step-ups are exhausted.
- Prefer a direct single-item maker or retailer with customization and a clear delivery route.
- Compare alternatives only when they could materially improve quality, personalization, price, or delivery feasibility.
- Verify the exact variant, quantity-one availability, customization limits, proof approval, current price and currency, production, destination-specific transit, taxes/customs, packaging, and order route.
- Do not treat platform-wide shipping statements as item-level eligibility.
- Mark unknown shipping, customization charges, and taxes as unknown.
- The budget is a hard limit on the landed total: item, personalisation, shipping, taxes and duty.
- Use the budget for quality, not the cheapest version that checks out. Say in one line what the price buys. A listing whose landed total is unknown remains a concept until a landed quote is available.
- Before writing an idea up, check its budget use: the landed total, or the item total plus "shipping unknown", as a share of the budget. Below 70%, take the next step-up from the target list and source it. When none can be sourced, the idea's budget line says so and names the step-up searches run and what each found. A blocked or failed search is not evidence that no better version exists: try another seller first.
- Convert production and transit business-day ranges to an arrival estimate that accounts for weekends and holidays.
- If availability, destination, or timing cannot be verified, drop the idea or mark it `Concept pending confirmation`.
- Do not submit checkout or place an order.

## Preselect every choice

The buyer should open one link and find the gift already set up for this creator. For each sourced idea, decide every choice the order page asks for before writing it up.

1. List the page's choices: colour, size, scent, flavour, finish, personalisation text, font, thread or engraving colour, placement, gift note, from the page reader's full option list, not only the default view.
2. Decide each choice from a creator fact when one applies, from `candidates` or `lasting_favourites`: a favourite colour, scent, flavour or material, or a style statement such as "never wears colour". Cite the fact ID. When the fact points to the option without naming it, label the choice as inference. When no fact applies, choose the most neutral option and say so.
3. Choose only options the page offers, and check the chosen variant can be ordered for the destination. When the creator's preference is not offered, take the closest offered option and say why, or try another supplier within the limits.
4. When the page has a personalisation field, suggest exact text within the page's limits: the creator's initials or the public name they use, a current pet's name from `pet_names`, or a short public phrase from their own words. Give one suggestion and one alternative. The exclusions above apply to every character. When the page has no personalisation field, the order card says "Personalisation: none on this page" and gives no text.
5. When a choice would decide the gift and the ledger has no fact for it, such as a favourite scent for a candle, one of the creator web queries may look for it under the same evidence rules.
6. Build a preloaded link that opens with the chosen variant selected, when the shop supports one: a Shopify `?variant=<id>` (ids from the product's `.js` data), the variant's own Amazon `/dp/<ASIN>`, a WooCommerce `?attribute_pa_<name>=<value>`, or the shop's own per-variant URL. Open the link and confirm the page shows the chosen option before calling it preloaded. This check does not count toward the supplier page limit. If no link can select it, say the link opens on the default.
7. Personalisation text rarely survives a link. Give it in the order card, in the page's own field order and labels, ready to copy.

Use public country information only for research. Ship only to an address supplied by the recipient, authorized manager, or confirmed PO box. Verify carrier PO-box support.

## Deliver

Follow [output-and-evaluation.md](references/output-and-evaluation.md).

Save outputs outside the skill and source repository. Return absolute paths. Do not commit profile data or buyer-specific outputs.

Report creator and supplier query/page counts, elapsed research time, actual TL credits from receipts, and exposed model/search cost. Report unavailable monetary cost as `unreported`. Keep profile-build and gift-research costs separate.

Recommendations do not authorize purchases, messages, partner terms, releases, or checkout.
