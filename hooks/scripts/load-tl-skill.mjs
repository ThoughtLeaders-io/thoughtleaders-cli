#!/usr/bin/env node
// SessionStart hook: emit the tl skill into the session context so Claude
// has the CLI playbook loaded before the first user turn instead of
// triggering it lazily on the first matching prompt.
//
// stdout is captured by Claude Code and injected as additional session
// context. Any failure is swallowed silently — the hook must never block
// session start; the skill system will still pick the skill up lazily on
// demand if we don't load it here.

import fs from 'node:fs';
import path from 'node:path';

const root = process.env.CLAUDE_PLUGIN_ROOT;
if (!root) {
  process.exit(0);
}

const skillPath = path.join(root, 'skills', 'tl', 'SKILL.md');
try {
  const content = fs.readFileSync(skillPath, 'utf-8');
  process.stdout.write(content);
} catch {
  process.exit(0);
}
