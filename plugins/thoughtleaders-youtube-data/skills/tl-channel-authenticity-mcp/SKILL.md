---
name: tl-channel-authenticity-mcp
description: Audit a YouTube channel for suspicious views, engagement, video integrity and comment patterns using connected ThoughtLeaders MCP tools and the complete shared authenticity scripts. Use for fake views, bot comments, channel vetting or sponsorship delivery audits. Requires Python, YouTube comment collection and two independent classifier passes. Do not use when the user explicitly requests the ThoughtLeaders CLI; use its authenticity skill instead.
---

# Full channel authenticity audit

Read the [canonical methodology](references/methodology.md) and
[MCP execution guide](references/mcp-runtime.md). The execution guide governs
canonical CLI examples and legacy agent names. All three evidence groups remain
mandatory: engagement/peers, view curves/video integrity, and comment content.
This is the same processing and scoring implementation distributed to CLI users.

Check Python, writable files, `yt-dlp`, working YouTube retrieval and independent
classifier calls before consuming data credits. If those cannot run, explain the
missing capability; do not substitute a metrics-only score. No TL CLI, database
credentials or user token is required by this package.

## Collect

Replace the directories below with absolute paths and choose a new session:

```sh
python3 SKILL_DIR/scripts/mcp_run.py run --session SESSION_DIR \
  SKILL_DIR/scripts/analyze_channel.py "CHANNEL_REFERENCE"
```

Follow the [request/receipt loop](references/mcp-runtime.md): call listed connected
tools, ingest complete responses, rerun the identical command, then read its
completed `output_path`. That output identifies `state_path` and `llm_batch_path`.
Preserve both files. If the channel is ambiguous, resolve it with the user and
restart with its numeric ID. Failed or partial comment collection is incomplete
evidence, never a successfully observed empty comment section.

## Classify twice

Read the complete batch and the
[canonical classifier prompt](references/agents/youtube-comment-classifier.md).
Run two independent host classifier calls on the same batch, each with the
channel niche and language. Save the strict responses to two different absolute
JSON paths. Verify expected indices and labels. Do not reuse the first answer as
the second pass. Only a successfully collected empty batch permits two `[]`
files. Missing classifier capability or invalid results block a complete score.

## Finalize and deliver

```sh
python3 SKILL_DIR/scripts/mcp_run.py run --session SESSION_DIR \
  SKILL_DIR/scripts/analyze_channel.py --finalize STATE_JSON PASS_ONE_JSON PASS_TWO_JSON
```

Read the completed output file and present the evidence-backed report. Use the
canonical [scoring](references/scoring.md) and [red flags](references/red-flags.md).
Label the score as an assessment of observed signals, retaining coverage and
uncertainty. Optional external audit logging requires a separately available
integration and user authorization; this package does not create Sheets or
change platform records.
