# Training the cue-phrase weights

`references/cue-phrases.txt` carries a weight per phrase that is both the ES boost and
the window's rank score. Commit b7147f7 measured the hand-tuned ladder flat — 3.0 windows
yielded 0.47 gems, 2.0 yielded 0.45, 1.0 yielded 0.50 — so the weights were a knob tuned
to nothing. `scripts/train_cues.py` fits them to labeled windows instead.

**Status (2026-09-15): the first training run did NOT beat the hand-tuned file on both
held-out channels. The weights in `cue-phrases.txt` are still the hand-tuned ones.** Read
"What the first run found" before rerunning, and do not ship a trained file on a single
channel's improvement.

## How to rerun

1. **Fetch uncapped corpora**, one channel at a time (nothing else from the skill runs —
   no extractors, no merge, no assembler):

       python3 scripts/fetch_cues.py --channel <id> --out <corpus> \
         --host-terms "<first name>,<surname>" \
         --min-score 0 --min-windows 100000 --max-windows 100000 \
         --per-video-cap 8 --generic-floor 100000

   `--generic-floor 100000` is what forces the fallback pass: the pass runs whenever
   `len(kept) < floor` and the floor was set explicitly, so a huge floor always runs it.
   No code change is needed to get both retrieval populations. Each channel takes about
   30 seconds and returns 2,000-8,000 kept windows.

2. **Build the labeling input** from `<corpus>/<channel>/batches/*.json` — those are the
   kept, *widened* windows, the text the extractor would actually see. One JSONL line per
   window: `{"id": "<channel>:<video>:<start>", "channel", "text", "format_hint",
   "channel_format", "host_named_in_third_person", "host_names_self"}`. Never include
   `cues_fired` or `rank_score`: those are the features being fitted.

3. **Label with bulk-classify**, never with per-window Claude agents:

       ~/.claude/bin/bulk-classify --in windows.jsonl --out labels.jsonl \
         --prompt "$(cat label-prompt.txt)" --model deepseek/deepseek-v3.2 --concurrency 32

   It is resumable — rerun the same command after any interruption. Shuffle the input
   first, so a partial run covers every channel evenly. Cost is about $0.01 per 100
   windows. Calibrate the labeler against your own labels on a stratified sample of 100
   BEFORE spending: label them by hand from `extractor-rubric.md` + the "What counts as
   self-disclosure" section of `evidence-rules.md`, then compare.

4. **Fit, mine and evaluate**:

       python3 scripts/train_cues.py --labels labels.jsonl --windows <corpus> \
         --eval-channels <held-out ids> --extra-phrases mined.txt \
         --out references/cue-phrases.txt --report fit.json

   Fit channels default to every channel in the corpus except `--eval-channels`. A phrase
   is dropped when its coefficient is <= 0 or it fired in fewer than `--min-support`
   windows (8). Surviving positive coefficients are rescaled by quantile into the file's
   own 0.5 / 1 / 2 / 3 bands, so the file keeps its shape and the runtime does not change.

## The label prompt

The prompt is the rubric's gem test plus the voice rule, asking for
`{"gem": true|false, "count": n, "why": "<=15 words"}`. The version that calibrated best
is in `part1-data/label-prompt-v2.txt` of the training run. Two things mattered:

- **Carrying the deterministic voice flags** (`host_named_in_third_person`,
  `channel_format`, `format_hint`) into the item and spelling out that a guest's,
  co-host's or interviewee's first-person line is NOT the creator's. Without that, the
  labeler scored guest life stories as gems and agreement was 0.69.
- Naming the categories that are NOT disclosure: in-game and on-screen worlds, prank
  premises, channel-as-work-product talk, the sponsored claim itself, momentary states.

## What the first run found (2026-09-15, 10 channels, DeepSeek labels)

- **Calibration never cleared the bar.** Hand labels vs DeepSeek: 0.690 on the first
  prompt, **0.790** with the voice-hardened prompt (Cohen kappa 0.58), 0.760 when the
  premise-implied rule was sharpened further. Claude Sonnet 4.5 on the same sample scored
  0.793 at ~30x the cost with 8% unparseable answers. The two models agreed with each
  other only **0.761** — less than either agreed with the human — so the ceiling is the
  rubric's own ambiguity, not the labeler. The unstable cases are premise-implied opinions
  (a cooking host's verdict on a dish), interview and collab voice, and channel-meta talk.
- **First-person density beats phrase identity.** In the fit, `generic_density` carried a
  coefficient of ~2.7 while no individual phrase exceeded ~0.7. Which cue fired says far
  less about a gem than how much first-person speech the window carries — the same result
  b7147f7 saw from the other side.
- **Most phrases cannot be judged from one corpus.** With ~3k fit windows, 170 of 193
  phrases fired in fewer than 8 windows and were dropped on support alone, not on
  evidence. Any production retrain needs enough labeled windows that support, not the
  floor, decides.
- **Mining helped one channel and hurt the other.** Adding ten hand-checked mined phrases
  (`my body`, `my back`, `my training`, `i've been doing`, `i usually`, `i started`,
  `i decided`, `i tried`, `i have a`, `i'm pretty`) took Matt D'Avella's top-150 from 78
  to 106 gems, while Colin and Samir fell from 50 to 45. Gem yield did not rise
  monotonically with rank score under either weight set, on either channel.

The honest conclusion from run one: **the weight ladder is not where the retrieval quality
lives.** The next experiment worth running is not a better fit of the same 193 phrases —
it is scoring windows on first-person density and voice flags directly, with the phrase
list reduced to a retrieval filter rather than a ranker.
