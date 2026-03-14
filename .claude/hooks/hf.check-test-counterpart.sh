#!/bin/bash
# Hook: Nudge when editing or creating Python source files without a test counterpart.
# Fires on PreToolUse for Write and Edit tools.
# Does NOT block (exit 0) - only shows a reminder.
# For edits: warns once per file per session (4-hour window).
# For new files: always warns.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only check Python source files
if ! echo "$FILE_PATH" | grep -qE '\.py$'; then
  exit 0
fi

# Skip test files, configs, __init__, migrations, scripts
if echo "$FILE_PATH" | grep -qE '(test_|_test\.py|conftest\.py|/tests/|__init__\.py|migrations?/|setup\.py|manage\.py|/scripts/)'; then
  exit 0
fi

FILENAME=$(basename "$FILE_PATH" .py)

# Look for existing test counterpart in common locations
DIR=$(dirname "$FILE_PATH")
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"

for test_path in \
  "${DIR}/tests/test_${FILENAME}.py" \
  "${DIR}/test_${FILENAME}.py" \
  "${DIR}/../tests/test_${FILENAME}.py" \
  "${PROJECT_ROOT}/tests/test_${FILENAME}.py"; do
  if [ -f "$test_path" ]; then
    exit 0  # Test file already exists
  fi
done

# For existing files (edits), only warn once per file per session
if [ -f "$FILE_PATH" ]; then
  MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_ROOT" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
  [ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"
  WARNED_MARKER="$MARKER_DIR/warned-test-$(echo -n "$FILE_PATH" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
  if [ -f "$WARNED_MARKER" ] && [ -n "$(find "$WARNED_MARKER" -mmin -240 2>/dev/null)" ]; then
    exit 0
  fi
  touch "$WARNED_MARKER"
  echo "Reminder: Editing source file without a test counterpart." >&2
else
  echo "Reminder: New source file being created without a test counterpart." >&2
fi

echo "  Source: $FILE_PATH" >&2
echo "  Expected: test_${FILENAME}.py" >&2
echo "  Per CLAUDE.md: Every new function/class/feature MUST include tests." >&2

exit 0
