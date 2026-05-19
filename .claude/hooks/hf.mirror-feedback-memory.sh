#!/bin/bash
# Hook: Auto-mirror Claude session-memory feedback files into the in-repo backlog.
# Fires on PostToolUse for Write tool when the target path is a `feedback_*.md`
# under `~/.claude/projects/*/memory/`.
#
# Closes the honor-system gap from ADR-0057: previously, `Write(feedback_*.md)`
# required a separate manual mirror commit. Now the mirror lands automatically
# in `<repo-root>/docs/wiki/memory-feedback/<slug>.md` as an unstaged file;
# Claude stages + commits it on the next commit.
#
# Bead: hydraflow-edn7. Failure-tolerant: never blocks the originating Write.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only act on feedback memory files in Claude's session-memory directory.
if ! echo "$FILE_PATH" | grep -qE '\.claude/projects/.+/memory/feedback_.+\.md$'; then
  exit 0
fi

# File must exist (might have been a failed write).
if [ ! -f "$FILE_PATH" ]; then
  exit 0
fi

SCRIPT="$CLAUDE_PROJECT_DIR/scripts/mirror_feedback_memory.py"
if [ ! -f "$SCRIPT" ]; then
  echo "MIRROR: skipping — $SCRIPT not found" >&2
  exit 0
fi

# Run from the project dir so the script's `git rev-parse --show-toplevel`
# resolves the right repo root.
cd "$CLAUDE_PROJECT_DIR"
if ! uv run python "$SCRIPT" "$FILE_PATH" 2>&1; then
  echo "MIRROR: failed to mirror $FILE_PATH (non-blocking)" >&2
fi

# Always succeed — never block the Write.
exit 0
