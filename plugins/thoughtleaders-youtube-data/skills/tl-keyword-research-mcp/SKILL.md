---
name: tl-keyword-research-mcp
description: Build and validate YouTube topic keyword filters, measure matching content, and find channels by topic intensity using connected ThoughtLeaders MCP tools and packaged processing scripts. Use for topics, niches, concepts, validated keyword groups, trend videos, or channel targets. Do not use when the user explicitly requests the ThoughtLeaders CLI; use its keyword research skill instead.
---

# Validated YouTube keyword research

Use the shared [canonical workflow](references/methodology.md) and
[MCP execution guide](references/mcp-runtime.md). Read both before running.
This package contains the complete canonical scripts, search reference and
classifier prompts; it requires Python and writable files, but no TL CLI.
The execution guide governs how all canonical command examples are run here.

For help questions, read [help](references/help.md) and answer without queries.
For research, honor the user's intent, quick/deep path and trend/channel/both
choice. Follow every applicable canonical stage: expansion, probing, validation,
refinement, intensity triage, materialization and delivery. Deep research retains
at least three refinement rounds. Neither a synonym list nor raw matches are a
validated result.

Run the packaged script through the resumable MCP adapter, for example:

```sh
python3 SKILL_DIR/scripts/mcp_run.py run --session SESSION_DIR \
  SKILL_DIR/scripts/probe.py --level topic "sustainable fashion" "repair clothing"
```

Replace both directories with absolute paths. Follow `needs_tools` requests,
ingest complete JSON tool responses, and repeat the same invocation. Read the
completed `output_path`; use it as the next stage's `--input` where needed.
The [execution guide](references/mcp-runtime.md) gives the exact receipt and
pipeline handling. Never execute `tl` commands shown in the canonical reference.

Read [search semantics](references/elasticsearch-content-search.md) before
constructing filters. Use live `tl_schema_es` for current access and schema.
Use the bundled [entity resolver](references/agents/keyword-entity-resolver.md),
[keyword validator](references/agents/keyword-relevance-validator.md), and
[context classifier](references/agents/keyword-context-classifier.md) when the
canonical stages call for them. Use host-supported agent execution; verify every
returned batch against the sent IDs.

Deliver the validated filter groups, expression, inline report link, and chosen
videos/channels with scope, evidence, intensity and validation status. Preserve
failed candidates and retrieval limits. `build_report.py` creates the inline link
without a platform write. Named report creation is not supported by this package.
