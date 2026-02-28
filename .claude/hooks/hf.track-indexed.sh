#!/bin/bash
# Hook: Track that claude-context was used (clears reindex reminder).
# Fires on PostToolUse for claude-context.
# Touches "last-indexed" marker and removes "needs-reindex" if present.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
[ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"

touch "$MARKER_DIR/last-indexed"
rm -f "$MARKER_DIR/needs-reindex"
