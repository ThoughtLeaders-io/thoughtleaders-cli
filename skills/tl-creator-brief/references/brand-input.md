# Brand input

## Ask, never assume

The skill must ask how to understand the brand, and offer all three options. It
never picks one on its own, and it never quietly scrapes.

The reason is that a brand gets to choose which version of itself is being
presented. A product can be one thing across its entire sponsorship history and
then launch something new, and whoever is running a campaign on the new thing
wants the old ad reads and the website ignored in favour of their own brief.
Only they know that. So it is a question, every run.

| Option | What runs |
|---|---|
| **Past sponsorships** | `scripts/brand_reads.py`, below. What creators have actually said about the product on camera. |
| **The brand's website** | One fetch of the brand's own site, from the `website` field on the brand record. What the product does, in the brand's own words. |
| **Their own talking points or brief** | Use exactly what was pasted in. Do not go looking for past reads or the site to check it, and do not flag disagreements with them. Their brief wins by definition. |

More than one may be picked. If so, label which claim came from which source,
because they can disagree and the reader needs to see that rather than a
blended average.

## Past sponsorships

```bash
cd <this skill>/scripts && python3 brand_reads.py --brand <brand_id> --max 10
```

Pass every brand ID from the resolve step, including former names after a
rebrand, with a repeated `--brand`.

**Two sources, always both.** The script runs both and labels each read:

- **`deal`**: a sponsorship brokered through the platform. Unambiguous.
- **`mention`**: a sponsorship the platform detected out on YouTube, whoever
  brokered it. Essential, because this skill has to work for a brand that has
  never bought through us at all.

**Never read zero brokered deals as "never sponsored anything."** Observed: one
brand returns zero brokered deals and roughly ten thousand detected mention
videos. The two counts measure completely different things and the output must
label them separately.

**What the script deliberately does not return:** any price, cost, rate card or
performance figure. None of that tells you what the product is, which is the
only reason this step exists, and none of it may reach the output.

## Verifying a read before you believe it

Detected mentions group affiliate reads in with paid ones. An affiliate read is
not the brand's own pitch and can describe the product wrong, so it cannot be
treated as evidence of what the brand offers.

The script cannot make this call, so it returns each read's actual words with
`needs_verification: true`. Read the words. A genuine sponsorship read names the
product and makes the brand's own claims about it; an affiliate mention drops a
link and moves on.

**The floor is three verified reads.** Below three, the picture is too thin to
trust: one or two reads can be one affiliate's misreading or one creator's odd
take. When fewer than three survive verification, say so, and ask for the
website or their own brief instead of extrapolating.

## What this file does not cover, on purpose

- **Competitor and guide brand reads.** Another brand's material is not this
  brand's, and the skill has one brand per run. Out.
- **Performance.** Which past read did well is a different question from what
  the product is. The skill does not rank, filter or report on it.
- **LinkedIn and any other off-platform source.** Out.
