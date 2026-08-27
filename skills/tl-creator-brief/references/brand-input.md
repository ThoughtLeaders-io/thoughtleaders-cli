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

### How the channels are pulled, both paths

Neither path filters, ranks or orders by performance. **There is no winners
filter, and no minimum number of reads.** Both paths take the most recent reads
and stop, because a product changes and the current description of it is the one
being sold. Recency is the only ordering.

**Path 1, brokered, Postgres.** `thoughtleaders_adlink` is the deal. The brand
hangs off the advertiser's profile, and the channel off the ad spot, so the join
runs adlink to profile to profile_brands for the brand and adlink to adspot to
channel for the creator:

```
thoughtleaders_adlink a
  JOIN thoughtleaders_profile p          ON a.advertiser_profile_id = p.id
  JOIN thoughtleaders_profile_brands pb  ON p.id = pb.profile_id
  JOIN thoughtleaders_adspot s           ON a.ad_spot_id = s.id
  JOIN thoughtleaders_channel ch         ON s.channel_id = ch.id
WHERE pb.brand_id IN (<ids>) AND a.publish_status = 3
  AND a.publish_date IS NOT NULL
ORDER BY a.publish_date DESC
```

`publish_status = 3` is published, so the read actually aired. No price or cost
column is selected. A `LIMIT` is not optional: Postgres reads through the CLI are
row-capped and a missing limit truncates silently.

**Path 2, detected, Elasticsearch.** Two queries against the upload index, both
sorted `publication_date desc`:

- `{"term": {"sponsored_brand_mentions": "<brand_id>"}}` lists the videos that
  carry a sponsored mention. One `should` clause per brand ID after a rebrand.
- a `nested` query on `brand_mentions`, matching `brand_mentions.id` and
  `brand_mentions.type: "sponsored"`, returns the snippet, the entity as the
  captions heard it, and the timestamps.

Keep only mentions whose `field` is `transcript`. A `description` hit is the
affiliate link in the video description, not anything anyone said out loud.

## Reading them

The only thing this step is for is learning what the product is, so any read
that describes the product does the job. One creator saying "a mobile app for
quick one minute mind sport duels against real people" tells you more than a
count of reads ever could. There is no sample size to satisfy.

Detected mentions do group affiliate reads in with paid ones, but that matters
less than it sounds here. An affiliate read that describes the product still
describes the product. An affiliate read that only drops a link describes
nothing, and that is visible from the absence of words rather than needing a
verdict.

Where several reads disagree about what the product is, say so and prefer the
most recent, because a product can change and only the current version is the
one being sold.

If no read has any words in it, use the brand's website or their own brief
instead.

## What this file does not cover, on purpose

- **Competitor and guide brand reads.** Another brand's material is not this
  brand's, and the skill has one brand per run. Out.
- **Performance.** Which past read did well is a different question from what
  the product is. The skill does not rank, filter or report on it.
- **LinkedIn and any other off-platform source.** Out.
