#!/bin/bash
# Hook: Soft warning when creating a new file (prefer editing existing).
# Fires on PostToolUse for Write tool.
# Does not block. Warns once per file.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Skip test files, configs, and known new-file scenarios
if echo "$FILE_PATH" | grep -qE '(test_|conftest\.py|__init__\.py|\.md$|migrations/versions/)'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Check if this file is tracked by git (i.e., existed before)
if git -C "$PROJECT_DIR" ls-files --error-unmatch "$FILE_PATH" > /dev/null 2>&1; then
  # File already tracked — this is an overwrite of an existing file, not a new file
  exit 0
fi

# File is new (untracked) — soft warning
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
[ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"
WARNED_MARKER="$MARKER_DIR/warned-newfile-$(echo -n "$FILE_PATH" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"

if [ -f "$WARNED_MARKER" ]; then
  exit 0
fi

echo "NOTE: New file created: $FILE_PATH" >&2
echo "  Prefer editing existing files when possible to avoid file bloat." >&2
echo "  If this file is necessary, ensure it has:" >&2
echo "  - Corresponding test file (if source code)" >&2
echo "  - Proper imports and integration with existing modules" >&2
touch "$WARNED_MARKER"

exit 0
