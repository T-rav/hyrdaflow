#!/bin/bash
# Hook: Track that a task plan has been created in this session.
# Fires on PostToolUse for TaskCreate tool.
# Touches a marker file so the edit guard can verify planning happened.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | (md5sum 2>/dev/null || md5) | cut -d' ' -f1)"
[ -d "$MARKER_DIR" ] || mkdir -p "$MARKER_DIR"
touch "$MARKER_DIR/planned"
