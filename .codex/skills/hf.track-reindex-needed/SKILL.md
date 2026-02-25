---
name: hf.track-reindex-needed
description: hf.track-reindex-needed
---

# hf.track-reindex-needed

```bash
#!/bin/bash
# Hook: Mark that claude-context reindexing may be needed after git operations
# that bring in new or different code.
# Fires on PostToolUse for Bash.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Detect git operations that change the working tree
if echo "$COMMAND" | grep -qE 'git\s+(pull|merge|checkout|switch|rebase|cherry-pick|stash\s+pop|stash\s+apply)'; then
  PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
  MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | md5)"
  mkdir -p "$MARKER_DIR"
  touch "$MARKER_DIR/needs-reindex"
fi
```
