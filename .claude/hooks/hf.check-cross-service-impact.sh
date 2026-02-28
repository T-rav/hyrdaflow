#!/bin/bash
# Hook: Warn when editing shared/ files about downstream service impact.
# Fires on PreToolUse for Edit tool.
# Warns ONCE per session (4-hour window), does not block.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

# Only check files in shared/
if ! echo "$FILE_PATH" | grep -qE '/shared/'; then
  exit 0
fi

# Skip test files and __init__.py
if echo "$FILE_PATH" | grep -qE '(test_|_test\.py|conftest\.py|/tests/|__init__\.py)'; then
  exit 0
fi

# Only check Python files
if ! echo "$FILE_PATH" | grep -qE '\.py$'; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"

# Check if already warned this session (within last 4 hours) — before mkdir
WARNED_MARKER="$MARKER_DIR/warned-cross-service"
if [ -f "$WARNED_MARKER" ] && [ -n "$(find "$WARNED_MARKER" -mmin -240 2>/dev/null)" ]; then
  exit 0
fi

mkdir -p "$MARKER_DIR"

# Find which services import from shared/
SHARED_MODULE=$(echo "$FILE_PATH" | sed -n 's|.*/shared/\(.*\)\.py$|\1|p' | tr '/' '.')
SERVICES=""

# Auto-discover directories that import from shared/
for svc_dir in "$PROJECT_DIR"/*/; do
  [ -d "$svc_dir" ] || continue
  svc=$(basename "$svc_dir")
  # Skip shared itself, hidden dirs, and non-service directories
  case "$svc" in
    shared|venv|node_modules|__pycache__|.git|.claude|.hydra|.github|ui|docs) continue ;;
  esac
  if grep -rql "from shared\." "$svc_dir" --include="*.py" 2>/dev/null | head -1 > /dev/null 2>&1; then
    SERVICES="${SERVICES}  - ${svc}\n"
  fi
done

if [ -n "$SERVICES" ]; then
  echo "CROSS-SERVICE IMPACT WARNING:" >&2
  echo "  You are editing: $FILE_PATH" >&2
  echo "  This shared module is imported by:" >&2
  echo -e "$SERVICES" >&2
  echo "Consider:" >&2
  echo "  - Run tests for affected services: make test-service SERVICE=<name>" >&2
  echo "  - Check for breaking changes to function signatures or return types" >&2
  echo "  - Verify type compatibility across all consumers" >&2
  touch "$WARNED_MARKER"
fi

exit 0
