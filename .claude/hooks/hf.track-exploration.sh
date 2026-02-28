#!/bin/bash
# Hook: Track that code exploration (Read/Grep/Glob) has occurred in this session.
# Fires on PostToolUse for Read, Grep, Glob, claude-context, and cclsp tools.
# Touches a marker file so the edit guard can verify exploration happened.
# Filters out non-code files to avoid false "explored" markers.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

# If a file path is present, only count code files as exploration
if [ -n "$FILE_PATH" ]; then
  if ! echo "$FILE_PATH" | grep -qE '\.(py|ts|tsx|js|jsx|rs|go|java|rb|sh|yml|yaml)$'; then
    exit 0
  fi
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
[ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"
touch "$MARKER_DIR/explored"
