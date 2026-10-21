# Choose a research tool

Use the connected tool whose name ends with the name below; host prefixes vary.
Read its current input definition before calling it. This guide does not require
shell commands or installing the CLI. If a named tool is unavailable, report that
limitation and use only available tools; do not invent a replacement call.

| Question | Tool |
| --- | --- |
| Who am I, what access do I have? | `tl_whoami` |
| Current credits, rates, or usage? | `tl_balance`, `tl_describe`, `tl_pricing`, `tl_usage_history`, `tl_credits_history` |
| Resolve a channel or brand? | `tl_channels_find`, `tl_brands_find` |
| Broad channels like a seed? | `tl_channels_similar` |
| Sponsorable audience/topic look-alikes? | `tl_channels_lookalike` |
| Brands like a brand? | `tl_brands_similar` |
| Discover available topic tags? | `tl_recommender_tags` |
| Strong channels or brands for a tag? | `tl_recommender_top_channels`, `tl_recommender_top_brands` |
| Understand a channel or brand's recommendation signals? | `tl_recommender_inspect_channel`, `tl_recommender_inspect_brand` |
| Channels a particular brand should sponsor? | `tl_recommender_channels_for_brand` |
| Channels for a known profile ID? | `tl_recommender_similar_to_profile` |
| Brands suitable for a channel? | `tl_recommender_similar_brands_to_channel` |
| Structured records, relationships, counts? | `tl_schema_pg`, then `tl_db_pg` |
| Video content, brand mentions, transcript evidence? | `tl_schema_es`, then `tl_db_es` |
| Historical metric snapshots? | `tl_schema_fb`, then `tl_db_fb` |

Similarity tools have different score scales and language defaults. Do not compare
scores across methods or transfer optional arguments between tools. Use the
requested language explicitly when supported. Recommendations are candidates to
validate, not proof of fit or a commitment to buy.

For a broad topic, try available recommender tags first. For a precise concept or
transcript phrase, use ES to test candidate terms and inspect actual matches.
Refine ambiguous terms and include plausible variants where samples show missed
coverage. Keep dates, content fields, terms and sample limits reproducible; do not
claim an exhaustive sponsorship footprint from a few keyword hits.

## Transcript excerpts

With `tl_db_es`, `query` is a JSON object, not a serialized string. Set
`include_highlight: true` as a **tool argument outside `query`**. Within `query`,
add this highlight configuration to a bounded search built from the live schema:

```json
{
  "highlight": {
    "fields": {
      "transcript": {"fragment_size": 200, "number_of_fragments": 3}
    }
  }
}
```

Use a small result `size` and select identifying `_source` fields rather than the
full transcript. Read actual `highlight.transcript` excerpts. A matched video
without a returned excerpt supports a match claim, not a quotation. Caption XML
or a fragment may omit the timing needed to locate the words: quote only returned
text and attach timestamps only when the returned evidence associates them with
that exact passage. Never borrow a timestamp from a neighboring cue.

For a costly expansion, consult current pricing or the query tool's `pricing`
estimate option if exposed. A pricing estimate is not executed research evidence.
Stop on access/credit limits; explain the limitation and any returned reset time.
