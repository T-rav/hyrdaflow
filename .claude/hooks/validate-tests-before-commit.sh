#!/bin/bash
# Hook: Validate tests exist for staged changes and pass before allowing commit.
# Fires on PreToolUse for Bash commands matching git commit.
# Blocks commit if:
#   1. --no-verify or --no-hooks flags are used
#   2. Python source files are staged without corresponding test files
#   3. Tests for affected services fail

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
CWD=$(echo "$INPUT" | jq -r '.cwd // empty')

# Only intercept git commit commands
if ! echo "$COMMAND" | grep -qE '(^|\s|&&\s*|;\s*)git commit'; then
  exit 0
fi

# Block --no-verify / --no-hooks (forbidden per CLAUDE.md)
if echo "$COMMAND" | grep -qE '\-\-no-verify|\-\-no-hooks'; then
  echo "BLOCKED: --no-verify and --no-hooks are forbidden per CLAUDE.md." >&2
  echo "Fix code issues first, then commit cleanly." >&2
  exit 2
fi

# Resolve project root from git toplevel (CWD may be a subdirectory)
PROJECT_ROOT=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")
cd "$PROJECT_ROOT"

# Get staged files early — skip expensive checks for non-source commits
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null || true)

if [ -z "$STAGED_FILES" ]; then
  exit 0  # Nothing staged, let git handle it
fi

# Fast exit: if no source code is staged, skip lint and tests entirely
HAS_SOURCE=$(echo "$STAGED_FILES" | grep -E '\.(py|ts|tsx|js|jsx)$' || true)
if [ -z "$HAS_SOURCE" ]; then
  exit 0  # Config/docs/YAML/Dockerfile-only commit, no lint or test needed
fi

# Require uv for running Python
if ! command -v uv &>/dev/null; then
  echo "BLOCKED: uv is not installed. Install it: curl -LsSf https://astral.sh/uv/install.sh | sh" >&2
  exit 2
fi

# Run lint checks (only reached for commits with source code)
echo "Running lint checks..." >&2
if ! make -C "$PROJECT_ROOT" lint-check > /dev/null 2>&1; then
  echo "BLOCKED: Lint check failed." >&2
  echo "Run 'make lint' to auto-fix formatting and import issues, then re-stage." >&2
  exit 2
fi
echo "Lint checks passed." >&2

# Get staged Python source files (excluding tests, configs, migrations, __init__)
SOURCE_FILES=$(echo "$STAGED_FILES" | grep '\.py$' \
  | grep -vE '(test_|_test\.py|conftest\.py|/tests/|__init__\.py|migrations?/|setup\.py|manage\.py)' \
  || true)

# Get staged test files
TEST_FILES=$(echo "$STAGED_FILES" | grep -E '(test_[^/]*\.py$|_test\.py$)' || true)

# If there are source changes but no test files staged, block the commit
if [ -n "$SOURCE_FILES" ] && [ -z "$TEST_FILES" ]; then
  echo "BLOCKED: Python source files staged without corresponding test files." >&2
  echo "" >&2
  echo "Source files staged:" >&2
  echo "$SOURCE_FILES" | sed 's/^/  - /' >&2
  echo "" >&2
  echo "Per CLAUDE.md: Every new function/class/feature MUST include tests." >&2
  echo "Write tests for your changes and stage them before committing." >&2
  exit 2
fi

# Determine which services are affected and run their tests
SERVICES_TO_TEST=""

# Auto-discover affected top-level directories from staged files
TOP_DIRS=$(echo "$STAGED_FILES" | sed -n 's|^\([^/]*\)/.*|\1|p' | sort -u)
for dir in $TOP_DIRS; do
  # Skip non-testable directories
  case "$dir" in
    .github|.claude|.hydraflow|docs|ui|venv|node_modules) continue ;;
  esac
  if [ -d "$PROJECT_ROOT/$dir/tests" ]; then
    SERVICES_TO_TEST="$SERVICES_TO_TEST $dir"
  fi
done

# Also check root-level test directory
if echo "$STAGED_FILES" | grep -q "^tests/"; then
  SERVICES_TO_TEST="$SERVICES_TO_TEST root"
fi

if [ -z "$SERVICES_TO_TEST" ]; then
  exit 0  # No testable service changes (docs, configs, etc.)
fi

# Run tests for each affected service
FAILED_SERVICES=""

for service in $SERVICES_TO_TEST; do
  if [ "$service" = "root" ]; then
    TEST_DIR="$PROJECT_ROOT"
    TEST_PATH="tests/"
  else
    TEST_DIR="$PROJECT_ROOT/$service"
    TEST_PATH="tests/"
  fi

  if [ -d "$TEST_DIR/$TEST_PATH" ]; then
    echo "Running tests for $service..." >&2
    if ! (cd "$TEST_DIR" && PYTHONPATH=. VIRTUAL_ENV="$PROJECT_ROOT/venv" uv run --active pytest -m "not integration and not system_flow and not smoke" -q "$TEST_PATH" 2>&1); then
      FAILED_SERVICES="$FAILED_SERVICES $service"
    fi
  fi
done

if [ -n "$FAILED_SERVICES" ]; then
  echo "" >&2
  echo "BLOCKED: Tests failed for:$FAILED_SERVICES" >&2
  echo "Fix failing tests before committing." >&2
  exit 2
fi

echo "All tests passed for affected services." >&2
exit 0
