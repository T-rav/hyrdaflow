#!/bin/bash
# Hook: Warn if editing source code without prior exploration or planning.
# Fires on PreToolUse for Edit and Write tools.
# Warns ONCE per session (4-hour window), does not block.
# Only checks Python source files (skips tests, configs, __init__).

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check Python source files
if ! echo "$FILE_PATH" | grep -qE '\.py$'; then
  exit 0
fi

# Skip test files, configs, __init__, migrations, scripts
if echo "$FILE_PATH" | grep -qE '(test_|_test\.py|conftest\.py|/tests/|__init__\.py|migrations?/|setup\.py|/scripts/)'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"

# Check if already warned this session (within last 4 hours) — before mkdir
WARNED_MARKER="$MARKER_DIR/warned"
if [ -f "$WARNED_MARKER" ] && [ -n "$(find "$WARNED_MARKER" -mmin -240 2>/dev/null)" ]; then
  exit 0
fi

mkdir -p "$MARKER_DIR"

WARNINGS=""

# Check for exploration (Read/Grep marker within last 4 hours)
EXPLORE_MARKER="$MARKER_DIR/explored"
if [ ! -f "$EXPLORE_MARKER" ] || [ -z "$(find "$EXPLORE_MARKER" -mmin -240 2>/dev/null)" ]; then
  WARNINGS="${WARNINGS}- No code exploration detected. Before making changes:\n"
  WARNINGS="${WARNINGS}    * Read relevant source files to understand existing code\n"
  WARNINGS="${WARNINGS}    * Use claude-context MCP to semantically search the codebase\n"
  WARNINGS="${WARNINGS}    * Use cclsp MCP for go-to-definition and find-references across services\n"
  WARNINGS="${WARNINGS}    * Check claude-context memory for past architectural decisions\n"
fi

# Check for plan (TaskCreate marker within last 4 hours)
PLAN_MARKER="$MARKER_DIR/planned"
if [ ! -f "$PLAN_MARKER" ] || [ -z "$(find "$PLAN_MARKER" -mmin -240 2>/dev/null)" ]; then
  WARNINGS="${WARNINGS}- No task plan detected. Before implementing:\n"
  WARNINGS="${WARNINGS}    * Use TaskCreate to outline your approach\n"
  WARNINGS="${WARNINGS}    * Store key decisions in claude-context memory for future reference\n"
fi

if [ -n "$WARNINGS" ]; then
  echo "SESSION REMINDER:" >&2
  echo -e "$WARNINGS" >&2
  echo "Explore the code and create a plan before making changes to ensure quality." >&2
  touch "$WARNED_MARKER"
fi

exit 0
