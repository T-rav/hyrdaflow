#!/bin/bash
# Hook: Warn if claude-context index may be stale before using it.
# Fires on PreToolUse for claude-context.
# Checks for a "needs-reindex" marker set after git pull/merge/checkout,
# and also warns if no indexing has happened recently (8-hour window).

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"

REINDEX_MARKER="$MARKER_DIR/needs-reindex"
INDEXED_MARKER="$MARKER_DIR/last-indexed"
WARNED_MARKER="$MARKER_DIR/reindex-warned"

# Don't warn more than once per hour (fast exit before mkdir)
if [ -f "$WARNED_MARKER" ] && [ -n "$(find "$WARNED_MARKER" -mmin -60 2>/dev/null)" ]; then
  exit 0
fi

mkdir -p "$MARKER_DIR"

SHOULD_WARN=false
REASON=""

# Check if git operation triggered a reindex need
if [ -f "$REINDEX_MARKER" ]; then
  SHOULD_WARN=true
  REASON="Code changed via git (pull/merge/checkout/rebase) since last index."
# Check if index is stale (no indexing in 8 hours)
elif [ ! -f "$INDEXED_MARKER" ] || [ -z "$(find "$INDEXED_MARKER" -mmin -480 2>/dev/null)" ]; then
  SHOULD_WARN=true
  REASON="Claude-context index may be stale (no indexing detected in 8+ hours)."
fi

if [ "$SHOULD_WARN" = true ]; then
  echo "REINDEX REMINDER: $REASON" >&2
  echo "Run: Reindex the codebase with claude-context to get accurate semantic search results." >&2
  touch "$WARNED_MARKER"
fi
