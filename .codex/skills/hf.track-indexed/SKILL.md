---
name: hf.track-indexed
description: hf.track-indexed
---

# hf.track-indexed

```bash
#!/bin/bash
# Hook: Track that claude-context was used (clears reindex reminder).
# Fires on PostToolUse for claude-context.
# Touches "last-indexed" marker and removes "needs-reindex" if present.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | md5)"
mkdir -p "$MARKER_DIR"

touch "$MARKER_DIR/last-indexed"
rm -f "$MARKER_DIR/needs-reindex"
```
