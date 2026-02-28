#!/bin/bash
# Hook: Clean up the code-changed marker after Stop review agents finish.
# Fires on Stop (command type) — should be last in the Stop hooks array.
# Prevents stale markers from triggering reviews in the next session.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
rm -f "$MARKER_DIR/code-changed"

exit 0
