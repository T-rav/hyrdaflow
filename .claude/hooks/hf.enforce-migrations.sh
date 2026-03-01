#!/bin/bash
# Hook: Block direct database schema changes outside of migration files.
# Fires on PreToolUse for Edit and Write tools.
# Blocks if SQL DDL or Alembic operations are written in non-migration files.

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# Only check Python files
if ! echo "$FILE_PATH" | grep -qE '\.py$'; then
  exit 0
fi

# Allow migration files (they're SUPPOSED to have DDL)
if echo "$FILE_PATH" | grep -qE '/migrations/|/migrations_data/'; then
  exit 0
fi

# Allow test files (they may use DDL for in-memory test DBs)
if echo "$FILE_PATH" | grep -qE '(test_|_test\.py|conftest\.py|/tests/)'; then
  exit 0
fi

# Check the content being written/edited for DDL patterns
# For Edit: check new_string; for Write: check content
NEW_CONTENT=$(echo "$INPUT" | jq -r '.tool_input.new_string // .tool_input.content // empty')

if [ -z "$NEW_CONTENT" ]; then
  exit 0
fi

# Check for raw SQL DDL statements
if echo "$NEW_CONTENT" | grep -qiE '(CREATE\s+TABLE|ALTER\s+TABLE|DROP\s+TABLE|ADD\s+COLUMN|DROP\s+COLUMN|RENAME\s+TABLE|MODIFY\s+COLUMN|CREATE\s+INDEX|DROP\s+INDEX)'; then
  echo "BLOCKED: Direct SQL DDL detected outside of migration files." >&2
  echo "" >&2
  echo "  File: $FILE_PATH" >&2
  echo "" >&2
  echo "Database schema changes MUST go through Alembic migrations:" >&2
  echo "  - <module>/migrations/versions/" >&2
  echo "" >&2
  echo "Create a new migration:" >&2
  echo "  cd <module> && alembic revision -m 'description_of_change'" >&2
  exit 2
fi

# Check for SQLAlchemy Alembic operations (op.create_table, op.add_column, etc.)
if echo "$NEW_CONTENT" | grep -qE 'op\.(create_table|drop_table|add_column|drop_column|alter_column|create_index|drop_index|rename_table|create_foreign_key|drop_constraint)'; then
  echo "BLOCKED: Alembic operations (op.*) detected outside of migration files." >&2
  echo "" >&2
  echo "  File: $FILE_PATH" >&2
  echo "" >&2
  echo "Alembic operations belong in migration files only:" >&2
  echo "  - <module>/migrations/versions/" >&2
  exit 2
fi
