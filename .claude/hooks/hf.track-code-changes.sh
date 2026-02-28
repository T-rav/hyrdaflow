#!/bin/bash
# Hook: Set a marker when source code is modified during a session.
# Fires on PostToolUse for Edit and Write.
# Stop agent hooks check this marker to skip review when no code changed.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only track source files
if ! echo "$FILE_PATH" | grep -qE '\.(py|ts|tsx|js|jsx|html|css|yml|yaml|md)$'; then
  # Also check for Dockerfiles
  if ! echo "$FILE_PATH" | grep -qiE 'Dockerfile'; then
    exit 0
  fi
fi

# Skip .claude/ config files — editing hooks/settings isn't "code"
if echo "$FILE_PATH" | grep -qE '\.claude/'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
[ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"
touch "$MARKER_DIR/code-changed"

exit 0
