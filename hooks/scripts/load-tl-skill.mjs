#!/usr/bin/env node
// SessionStart hook: tell the model, before the first user turn, that the tl
// skill exists and must be loaded before any `tl` command.
//
// It used to print the whole skills/tl/SKILL.md (~70 KB). Claude Code caps
// hook output well below that and swaps anything larger for a ~2 KB
// "output too large" preview plus a file path, so the skill never actually
// loaded this way; the model only saw its first lines. A short pointer stays
// under the cap and the Skill tool loads the full playbook on demand.
// tests/test_session_start_hook.py keeps this output under 1.5 KB.
//
// stdout is captured by Claude Code and injected as session context. Any
// failure is swallowed silently: the hook must never block session start.

import fs from 'node:fs';
import path from 'node:path';

const MESSAGE = `The tl-cli plugin is installed. Before running any \`tl\` command, or answering a question about YouTube sponsorships, channels, brands, uploads, deals, pipeline or revenue in ThoughtLeaders data, load the tl skill with the Skill tool (tl-cli:tl). It is the CLI playbook: commands and their syntax, which data source answers what (Postgres, Elasticsearch, Firebolt), field glossary, credit costs and guardrails. Do not guess tl syntax without it. The plugin's more specific skills (keyword research, views guarantee, channel authenticity, save report and others) are in the skill list; use one when its description matches the request.
`;

try {
  const root = process.env.CLAUDE_PLUGIN_ROOT;
  // Only point at the skill if it is actually there.
  if (root && fs.existsSync(path.join(root, 'skills', 'tl', 'SKILL.md'))) {
    process.stdout.write(MESSAGE);
  }
} catch {
  // never block session start
}
process.exit(0);
