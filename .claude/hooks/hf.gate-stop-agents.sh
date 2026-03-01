#!/bin/bash
# Hook: Gate Stop agent hooks — block if no code was changed this session.
# Runs as a command hook BEFORE the agent hooks in the Stop array.
# If no code-changed marker exists, exits non-zero to skip subsequent hooks.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"

if [ ! -f "$MARKER_DIR/code-changed" ]; then
  exit 2
fi

echo "Code changes detected — running reviews" >&2

exit 0
