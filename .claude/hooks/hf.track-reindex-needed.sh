#!/bin/bash
# Hook: Mark that claude-context reindexing may be needed after git operations
# that bring in new or different code.
# Fires on PostToolUse for Bash.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Detect git operations that change the working tree
if echo "$COMMAND" | grep -qE 'git\s+(pull|merge|checkout|switch|rebase|cherry-pick|stash\s+pop|stash\s+apply)'; then
  PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
  MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
  [ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"
  touch "$MARKER_DIR/needs-reindex"
fi
