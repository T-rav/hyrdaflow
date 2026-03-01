---
name: hf.block-destructive-git
description: hf.block-destructive-git
---

# hf.block-destructive-git

```bash
#!/bin/bash
# Hook: Block destructive git commands that are hard to reverse.
# Fires on PreToolUse for all Bash commands.
# Blocks: push --force, reset --hard, checkout ., restore ., clean -f, branch -D

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

if [ -z "$COMMAND" ]; then
  exit 0
fi

# Block destructive git commands
if echo "$COMMAND" | grep -qE 'git\s+(push\s+.*--force|push\s+-f\b|reset\s+--hard|checkout\s+\.|restore\s+\.|clean\s+-f|branch\s+-D)'; then
  echo "BLOCKED: Destructive git command detected." >&2
  echo "" >&2
  echo "The following are forbidden without explicit user approval:" >&2
  echo "  - git push --force / -f  (overwrites remote history)" >&2
  echo "  - git reset --hard       (discards uncommitted changes)" >&2
  echo "  - git checkout .         (discards all working tree changes)" >&2
  echo "  - git restore .          (discards all working tree changes)" >&2
  echo "  - git clean -f           (deletes untracked files)" >&2
  echo "  - git branch -D          (force-deletes branch)" >&2
  echo "" >&2
  echo "Ask the user for explicit approval before running destructive commands." >&2
  exit 2
fi
```
