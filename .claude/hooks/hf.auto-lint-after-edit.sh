#!/bin/bash
# Hook: Auto-fix lint issues on Python files immediately after edits.
# Fires on PostToolUse for Edit and Write tools.
# Runs ruff check --fix on the specific file changed (fast, targeted).
# Does NOT block — silently fixes lint issues to prevent accumulation.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only lint Python files
if ! echo "$FILE_PATH" | grep -qE '\.py$'; then
  exit 0
fi

# Skip .claude/ config files
if echo "$FILE_PATH" | grep -qE '\.claude/'; then
  exit 0
fi

# File must exist (might have been a failed write)
if [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

# Auto-fix lint issues on this file only (fast, ~200ms)
if command -v ruff &>/dev/null; then
  ISSUES=$(ruff check "$FILE_PATH" 2>/dev/null || true)
  if [ -n "$ISSUES" ]; then
    ruff check --fix --unsafe-fixes "$FILE_PATH" > /dev/null 2>&1 || true
    ruff format "$FILE_PATH" > /dev/null 2>&1 || true
    REMAINING=$(ruff check "$FILE_PATH" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      echo "LINT: Auto-fixed some issues in $(basename "$FILE_PATH"), but these remain:" >&2
      echo "$REMAINING" | head -5 >&2
      echo "Fix these manually before committing." >&2
    fi
  fi
elif command -v uv &>/dev/null; then
  ISSUES=$(uv run ruff check "$FILE_PATH" 2>/dev/null || true)
  if [ -n "$ISSUES" ]; then
    uv run ruff check --fix --unsafe-fixes "$FILE_PATH" > /dev/null 2>&1 || true
    uv run ruff format "$FILE_PATH" > /dev/null 2>&1 || true
    REMAINING=$(uv run ruff check "$FILE_PATH" 2>/dev/null || true)
    if [ -n "$REMAINING" ]; then
      echo "LINT: Auto-fixed some issues in $(basename "$FILE_PATH"), but these remain:" >&2
      echo "$REMAINING" | head -5 >&2
      echo "Fix these manually before committing." >&2
    fi
  fi
fi

exit 0
