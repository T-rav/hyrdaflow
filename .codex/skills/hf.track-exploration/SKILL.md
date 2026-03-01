---
name: hf.track-exploration
description: hf.track-exploration
---

# hf.track-exploration

```bash
#!/bin/bash
# Hook: Track that code exploration (Read/Grep) has occurred in this session.
# Fires on PostToolUse for Read and Grep tools.
# Touches a marker file so the edit guard can verify exploration happened.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
MARKER_DIR="/tmp/claude-code-markers/$(echo -n "$PROJECT_DIR" | md5)"
mkdir -p "$MARKER_DIR"
touch "$MARKER_DIR/explored"
```
