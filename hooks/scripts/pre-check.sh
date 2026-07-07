#!/usr/bin/env bash
# PreToolUse hook: validate auth and check credits before tl commands.
# Only runs when the Bash command starts with "tl ".

COMMAND="${TOOL_INPUT_command:-}"

# Only act on tl commands
if [[ ! "$COMMAND" =~ ^tl[[:space:]] ]]; then
  exit 0
fi

# Skip for system commands that don't need auth
if [[ "$COMMAND" =~ ^tl[[:space:]]+(auth|doctor|--help|--version|describe) ]]; then
  exit 0
fi

# Check auth
if ! tl auth status --quiet 2>/dev/null; then
  echo "WARN: Not authenticated. Run 'tl auth login' first." >&2
  exit 0  # Don't block, just warn
fi

# NOTE: no "add a limit" hint here. List commands are server-limited by
# default and typically cost far below the warning-worthy range, so the
# hint was pure noise for agents (it fired on every unlimited list call
# regardless of cost).

exit 0
