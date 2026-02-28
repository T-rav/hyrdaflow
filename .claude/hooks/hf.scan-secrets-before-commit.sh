#!/bin/bash
# Hook: Scan staged files for potential secrets before allowing commit.
# Fires on PreToolUse for Bash commands matching git commit.
# Blocks commit if API keys, tokens, or hardcoded passwords are found in staged diffs.

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')
[ -z "$CWD" ] && CWD="$(pwd)"

# Only intercept git commit commands
if ! echo "$COMMAND" | grep -qE '(^|\s|&&\s*|;\s*)git commit'; then
  exit 0
fi

cd "$CWD"

# Get staged files
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)

if [ -z "$STAGED_FILES" ]; then
  exit 0
fi

# Get only the added lines from the staged diff (ignore removed lines)
ADDED_LINES=$(git diff --cached -U0 2>/dev/null | grep -E '^\+[^+]' || true)

if [ -z "$ADDED_LINES" ]; then
  exit 0
fi

# Define secret patterns (high-confidence, low false-positive)
PATTERNS=(
  'xoxb-[0-9]'                          # Slack bot tokens
  'xapp-[0-9]'                          # Slack app tokens
  'xoxp-[0-9]'                          # Slack user tokens
  'sk-[a-zA-Z0-9]{20,}'                 # OpenAI / Stripe keys
  'AKIA[0-9A-Z]{16}'                    # AWS access key IDs
  'ghp_[a-zA-Z0-9]{36}'                 # GitHub personal access tokens
  'ghs_[a-zA-Z0-9]{36}'                 # GitHub server tokens
  'glpat-[a-zA-Z0-9\-]{20}'             # GitLab personal access tokens
  'AIza[0-9A-Za-z\-_]{35}'              # Google API keys
)

# Build combined regex
COMBINED_PATTERN=$(printf '%s|' "${PATTERNS[@]}")
COMBINED_PATTERN="${COMBINED_PATTERN%|}"  # Remove trailing pipe

# Scan added lines for secrets
MATCHES=$(echo "$ADDED_LINES" | grep -oEn "$COMBINED_PATTERN" 2>/dev/null || true)

if [ -n "$MATCHES" ]; then
  echo "BLOCKED: Potential secrets detected in staged changes:" >&2
  echo "" >&2
  # Single-pass: parse file headers from the full staged diff to attribute matches
  FULL_DIFF=$(git diff --cached -U0 2>/dev/null || true)
  AFFECTED_FILES=$(echo "$FULL_DIFF" | awk -v pat="$COMBINED_PATTERN" '
    /^diff --git/ { file = $NF; sub(/^b\//, "", file) }
    /^\+[^+]/ && match($0, pat) { files[file] = 1 }
    END { for (f in files) print f }
  ' 2>/dev/null || true)
  if [ -n "$AFFECTED_FILES" ]; then
    echo "$AFFECTED_FILES" | sed 's/^/  - /' >&2
  fi
  echo "" >&2
  echo "Remove secrets and use environment variables instead." >&2
  echo "If this is a false positive (e.g., test fixtures), ask the user to confirm." >&2
  exit 2
fi
