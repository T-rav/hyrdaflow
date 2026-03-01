#!/bin/bash
# Hook: Nudge when creating new Python source files without a test counterpart.
# Fires on PreToolUse for Write tool.
# Does NOT block (exit 0) - only shows a reminder.

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

# Only warn for NEW files (not edits to existing files)
if [ -f "$FILE_PATH" ]; then
  exit 0
fi

FILENAME=$(basename "$FILE_PATH" .py)

# Look for existing test counterpart in common locations
DIR=$(dirname "$FILE_PATH")
for test_path in \
  "${DIR}/tests/test_${FILENAME}.py" \
  "${DIR}/test_${FILENAME}.py" \
  "${DIR}/../tests/test_${FILENAME}.py"; do
  if [ -f "$test_path" ]; then
    exit 0  # Test file already exists
  fi
done

echo "Reminder: New source file being created without a test counterpart." >&2
echo "  Source: $FILE_PATH" >&2
echo "  Expected: test_${FILENAME}.py" >&2
echo "  Per CLAUDE.md: Every new function/class MUST include tests." >&2

exit 0
