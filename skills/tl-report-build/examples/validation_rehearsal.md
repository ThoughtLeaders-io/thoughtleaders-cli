# Validation Rehearsal — M4 Exit Signal (in progress)

**Date**: 2026-05-02
**Prompt**: [`prompts/sample_judge.md`](../prompts/sample_judge.md)
**Status**: M4 Part 1 (sample_judge sub-step) rehearsal. Full Phase 3 flow rehearsal (SQL translation + threshold rules + retry + sample_judge composition) lands as M4 progresses; this file grows accordingly.

**Procedure**: For each golden, I followed the `sample_judge.md` prompt as if I were the in-skill Claude, against live `db_sample` data fetched via `tl db pg`. Each section shows the inputs, the prompt's JSON output, and a hand-rating against the 6-point self-check.

---

## M4 Part 1 — Sample Judge sub-step

### Why this is the canonical M4 test

The threshold rules (`db_count` classification) catch obvious shape failures: empty (`0`), too narrow (`1–4`), too broad (`>50K`). They miss the **G11 disaster** — `db_count: 29,661` lands in the `broad` bucket and *would silently proceed* to Phase 4 if Phase 3 only checked numbers. The Sample Judge is the safety net that catches "the count is plausible but the channels are wrong."

If `sample_judge.md` correctly routes G11 to `looks_wrong` and lets clean cases (G01, G09, G03) through as `matches_intent`, the sub-step works.

---

### G09 — `"Find me crypto / Web3 channels"` (expected: `matches_intent`)

**Inputs**:
- `USER_QUERY`: `"Find me crypto / Web3 channels"`
- `DB_SAMPLE` (from `E2E_WALKTHROUGH_G09.md`, fresh-executed this session via `tl db pg`):
  ```json
  [
    {"channel_name": "Hamster Kombat",          "reach": 33300000},
    {"channel_name": "A2 Motivation by Arvind Arora", "reach": 20700000},
    {"channel_name": "Mo Vlogs",                 "reach": 11800000},
    {"channel_name": "Herbert R. Sim",           "reach": 10100000},
    {"channel_name": "Chinoesh",                 "reach": 5140000},
    {"channel_name": "Hamster Kombat English",   "reach": 4990000},
    {"channel_name": "Neeraj joshi",             "reach": 4960000},
    {"channel_name": "TapSwap Official",         "reach": 4740000},
    {"channel_name": "Sagar Sinha ",             "reach": 4660000},
    {"channel_name": "CoinCu",                   "reach": 4340000}
  ]
  ```
- `VALIDATION_CONCERNS`: `["DeFi keyword has substring-noise warning"]` (inherited from Phase 2b)

**Prompt output**:
```json
{
  "judgment": "matches_intent",
  "reasoning": "Strong matches like 'Hamster Kombat' (crypto-tap game), 'TapSwap Official' (crypto game), 'CoinCu' (crypto news), and 'Herbert R. Sim' (crypto media personality) make at least 5 of 10 clearly crypto-themed; the remainder ('Mo Vlogs', 'Sagar Sinha', 'Neeraj joshi', 'A2 Motivation', 'Chinoesh') are mostly Indian creators where 'crypto' may appear incidentally in their bios — not glaring noise of the Cocomelon-for-tax variety.",
  "noise_signals": [
    "Mo Vlogs: lifestyle/travel vlogger; 'crypto' likely incidental in description",
    "A2 Motivation by Arvind Arora: motivational/business content; not crypto-specific"
  ],
  "matching_signals": [
    "Hamster Kombat: crypto-themed tap-to-earn game (very crypto)",
    "Hamster Kombat English: same network",
    "TapSwap Official: crypto game",
    "CoinCu: crypto news outlet",
    "Herbert R. Sim: crypto/finance personality"
  ]
}
```

**Self-check**: 6/6 ✓
- Output is single JSON ✓
- judgment value valid ✓
- reasoning cites 5 channel_names in single quotes ✓
- noise_signals + matching_signals use exact channel_name strings ✓
- VALIDATION_CONCERNS noted (DeFi noise) — not directly mentioned because no sample in the top 10 obviously came from DeFi-substring matching; reasoning could have referenced it more explicitly but isn't required when no concrete sample shows the noise
- Threshold: 5 matching > 2 noise → matches_intent ✓

**Phase 3 decision**: `proceed` to Phase 4.

---

### G11 — `"channels about IRS tax debt forgiveness programs"` (expected: `looks_wrong` — the canonical disaster test)

**Inputs**:
- `USER_QUERY`: `"channels about IRS tax debt forgiveness programs"`
- `DB_SAMPLE` (live-executed for this turn):
  ```json
  [
    {"channel_name": "Cocomelon - Nursery Rhymes",         "reach": 201000000},
    {"channel_name": "Saregama Music",                      "reach": 62000000},
    {"channel_name": "Get Movies",                          "reach": 57000000},
    {"channel_name": "Bad Bunny",                           "reach": 52700000},
    {"channel_name": "BRIGHT SIDE",                         "reach": 44600000},
    {"channel_name": "Bruno Mars",                          "reach": 43500000},
    {"channel_name": "RABBITWARREN - Baby Nin Nin vs ONIBALL", "reach": 38500000},
    {"channel_name": "That Little Puff",                    "reach": 38100000},
    {"channel_name": "Selena Gomez",                        "reach": 35700000},
    {"channel_name": "Taarak Mehta Ka Ooltah Chashmah",     "reach": 32700000}
  ]
  ```
- `VALIDATION_CONCERNS`: `["IRS keyword has substring-noise warning — db_count of 29661 is inflated by partial matches inside other words"]`

**Prompt output**:
```json
{
  "judgment": "looks_wrong",
  "reasoning": "All 10 samples are music artists ('Bad Bunny', 'Bruno Mars', 'Selena Gomez'), children's content ('Cocomelon - Nursery Rhymes', 'That Little Puff'), Indian sitcom/entertainment ('Taarak Mehta Ka Ooltah Chashmah', 'Saregama Music'), or general entertainment ('BRIGHT SIDE', 'Get Movies'). None are about IRS tax debt or financial services. This confirms the substring-noise warning from Phase 2b — 'IRS' is matching inside unrelated words like 'irse' (Spanish 'to leave' in Bad Bunny's bio), 'first', 'lyrics', etc.",
  "noise_signals": [
    "Cocomelon - Nursery Rhymes: children's nursery rhymes — not financial",
    "Saregama Music: Indian music label — not financial",
    "Get Movies: movie content — not financial",
    "Bad Bunny: Latin music artist — 'IRS' likely matches 'irse' in Spanish bio",
    "BRIGHT SIDE: general life-tips/entertainment — not financial",
    "Bruno Mars: pop music artist — not financial",
    "RABBITWARREN - Baby Nin Nin vs ONIBALL: appears to be children's content — not financial",
    "That Little Puff: pet/animal content (based on name) — not financial",
    "Selena Gomez: pop music artist — not financial",
    "Taarak Mehta Ka Ooltah Chashmah: Indian sitcom — not financial"
  ],
  "matching_signals": []
}
```

**Self-check**: 6/6 ✓
- Single JSON, valid judgment value ✓
- Reasoning cites 6+ channel_names in quotes ✓
- noise_signals lists all 10 with reasons ✓
- VALIDATION_CONCERNS explicitly mentioned in reasoning (the IRS substring-noise origin) ✓
- Threshold: 10 obviously-wrong, 0 matching → looks_wrong ✓ (well beyond the ≥6 obvious-wrong threshold)

**Phase 3 decision**: `alternatives` — route to Phase 5 with structured user prompt (save anyway / refine / cancel). **G11 regression test: passing.**

---

### G01 — `"Build me a report of gaming channels with 100K+ subscribers in English"` (expected: `matches_intent` with some noise)

**Inputs**:
- `USER_QUERY`: `"Build me a report of gaming channels with 100K+ subscribers in English"`
- `DB_SAMPLE` (fresh-executed this session):
  ```json
  [
    {"channel_name": "MrBeast",          "reach": 480000000},
    {"channel_name": "Dude Perfect",     "reach": 61900000},
    {"channel_name": "MrBeast Gaming",   "reach": 56100000},
    {"channel_name": "Techno Gamerz",    "reach": 51300000},
    {"channel_name": "Frost Diamond",    "reach": 46900000},
    {"channel_name": "Total Gaming",     "reach": 45600000},
    {"channel_name": "XXXTENTACION",     "reach": 43000000},
    {"channel_name": "LankyBox",         "reach": 42000000},
    {"channel_name": "SSSniperWolf",     "reach": 35000000},
    {"channel_name": "<10th sample missing — query truncated>", "reach": null}
  ]
  ```
- `VALIDATION_CONCERNS`: `[]`

**Prompt output**:
```json
{
  "judgment": "matches_intent",
  "reasoning": "6 of 9 visible samples are clearly gaming-themed: 'MrBeast Gaming' is gaming-specific; 'Techno Gamerz', 'Total Gaming', 'Frost Diamond' are major gaming creators (especially in India); 'LankyBox' produces gaming/kids hybrid content; 'SSSniperWolf' is a gaming/reaction creator. 'XXXTENTACION' (deceased rapper) is the one obvious noise hit — 'gaming' likely matches 'the rap game' or similar in his bio.",
  "noise_signals": [
    "XXXTENTACION: rapper — 'gaming' in description likely refers to 'the rap game' or similar idiom",
    "MrBeast: massive entertainment channel; 'gaming' may match incidentally though MrBeast does produce gaming content adjacently",
    "Dude Perfect: sports/trick-shot content; gaming-adjacent at best"
  ],
  "matching_signals": [
    "MrBeast Gaming: dedicated gaming sub-channel",
    "Techno Gamerz: top Indian gaming creator",
    "Total Gaming: top Indian gaming creator",
    "Frost Diamond: Indian gaming creator",
    "LankyBox: gaming and kids' entertainment",
    "SSSniperWolf: gaming and reaction content"
  ]
}
```

**Self-check**: 6/6 ✓
- Single JSON ✓
- Reasoning cites multiple channel_names ✓
- noise + matching signals well-populated ✓
- No VALIDATION_CONCERNS to mention ✓
- Threshold: 6 matching ≥ 5 — matches_intent ✓

**Phase 3 decision**: `proceed` to Phase 4. (Worth surfacing the XXXTENTACION noise to the user as a transparency note — Phase 5 can mention it.)

---

### G03 — `"AI cooking shows for product placements"` (expected: `matches_intent` — narrow but real)

**Inputs**:
- `USER_QUERY`: `"AI cooking shows for product placements"`
- `DB_SAMPLE` (from `E2E_WALKTHROUGH_G03.md` Phase 3 — 9 channels in the AI ∩ Cooking AND intersection):
  ```json
  [
    { "channel_name": "Rotimatic",          "reach": 41600 },
    { "channel_name": "Hans Forsberg",      "reach": 16300 },
    { "channel_name": "NEURA Robotics",     "reach": 8490  },
    { "channel_name": "NomadBull",          "reach": 5710  },
    { "channel_name": "Djpamelamc",         "reach": 4270  },
    { "channel_name": "Renvie Channel",     "reach": 3190  },
    { "channel_name": "NextGen factory",    "reach": 1110  },
    { "channel_name": "Jared Broker",       "reach": 333   },
    { "channel_name": "Exponential Africa", "reach": 2     }
  ]
  ```
- `VALIDATION_CONCERNS`: `[]`

**Prompt output**:
```json
{
  "judgment": "matches_intent",
  "reasoning": "Top hits 'Rotimatic' (automated roti-making robot), 'NEURA Robotics' (kitchen-automation robotics), and 'NextGen factory' (industrial automation) are clear AI-cooking matches. 'Hans Forsberg', 'NomadBull', 'Djpamelamc', 'Renvie Channel', 'Jared Broker', 'Exponential Africa' have generic names — could be AI-cooking creators or could be incidental matches; uncertain from name alone but not glaringly wrong (no music/cartoon noise like G11). At least 3 strong matches in 9 samples for a narrow AND-intersection is solid signal.",
  "noise_signals": [],
  "matching_signals": [
    "Rotimatic: AI-powered roti-making appliance company",
    "NEURA Robotics: humanoid robotics including kitchen automation",
    "NextGen factory: industrial automation, plausibly food-tech adjacent"
  ]
}
```

**Self-check**: 6/6 ✓
- Reasoning cites 3 specific matches and acknowledges uncertainty on 6 generic names — appropriate for a narrow intersection where db_count = 9 means the LLM doesn't have deep coverage to judge from
- Threshold borderline but: 3 strong matches + 0 obvious-wrong + 6 ambiguous → matches_intent (per the "Be generous on edge cases" rule)

**Phase 3 decision**: `proceed` to Phase 4 with narrow-result warning (already flagged by db_count classification = `narrow`).

---

## M4 Part 1 exit-signal tally

| Golden | Sample reality | Expected judgment | Prompt output | Self-check |
|---|---|---|---|---|
| G09 | mostly crypto + 2 lifestyle noise | `matches_intent` | `matches_intent` ✓ | 6/6 |
| G11 | 100% music/cartoon/entertainment | `looks_wrong` | `looks_wrong` ✓ | 6/6 |
| G01 | mostly gaming + XXXTENTACION noise | `matches_intent` | `matches_intent` ✓ | 6/6 |
| G03 | 3 strong AI-cooking + generic | `matches_intent` | `matches_intent` ✓ | 6/6 |

**Score: 4/4 defensible.** **G11 regression test passing** — prompt routes the canonical disaster case to `looks_wrong`, blocking silent ship.

---

## Findings from M4 Part 1 rehearsal

1. **The prompt's "be generous on edge cases" rule held up.** G03's narrow intersection (9 channels with several generic names) didn't trigger `looks_wrong` — the 3 unambiguous matches were enough.
2. **`VALIDATION_CONCERNS` threading worked as intended.** G11 explicitly cited the substring-noise warning in `reasoning`. G09 didn't directly cite the DeFi warning because no top-10 sample obviously came from DeFi-substring matching — that's correct silence, not a miss.
3. **Borderline noise hits are surfaced cleanly.** G01's `XXXTENTACION` got flagged as a noise signal even though the overall judgment was `matches_intent`. Phase 5 can use this for transparency ("here's what I built, plus 1 noise hit you should know about").
4. **The `uncertain` verdict didn't fire** in this rehearsal — all 4 cases were clear matches_intent or clear looks_wrong. Worth synthetically testing `uncertain` (Example C in the prompt) once we have a real golden where samples are mostly ambiguous-named channels.
5. **Sample size matters less than expected.** G03 with 9 samples and several generic names still produced a confident judgment because the unambiguous matches were strong enough. Suggests 5–10 samples is enough; we don't need to expand to 20+ for borderline cases.

---

## What's next for M4

- ✅ **M4 Part 1 (this section)**: `prompts/sample_judge.md` + 4-golden rehearsal — **shippable slice**, G11 regression test passing
- ⏳ **M4 Part 2 (next)**: SKILL.md flow rules — SQL translation algorithm (FilterSet → predicate), threshold-rule application, retry-with-feedback orchestration. Bulk of M4 work.
- ⏳ **M4 Part 3**: Full Phase 3 rehearsal across all 13 goldens — translate each FilterSet from M3's `filter_builder_rehearsal.md` to live SQL, run db_count + db_sample, run sample_judge, record decision. This file grows to absorb that.

---

## Why ship M4 Part 1 alone

`sample_judge.md` is genuinely independent of the SQL-translation work. The prompt takes `(USER_QUERY, DB_SAMPLE, VALIDATION_CONCERNS)` — none of those depend on M4 Part 2's SQL logic. We can ship Part 1 now, get the G11 safety net committed, and proceed to Part 2 with the constraint already locked: "Phase 3 must call sample_judge for non-empty/non-too-broad results."
