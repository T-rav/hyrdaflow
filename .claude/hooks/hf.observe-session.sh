#!/bin/bash
# Hook: Capture lightweight tool-use observations for self-improvement analysis.
# Fires on PostToolUse for high-signal tools (Read/Write/Edit/Bash/TaskCreate).

set -euo pipefail

INPUT=$(cat)
if [ -z "${INPUT}" ]; then
  exit 0
fi

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
STATE_DIR="${PROJECT_DIR}/.claude/state/self-improve"
ARCHIVE_DIR="${STATE_DIR}/archive"
OBS_FILE="${STATE_DIR}/observations.jsonl"
MAX_BYTES=$((5 * 1024 * 1024))

[ -d "${ARCHIVE_DIR}" ] || mkdir -p "${STATE_DIR}" "${ARCHIVE_DIR}"

tool_name=$(echo "${INPUT}" | jq -r '.tool_name // .tool // "unknown"')
session_id=$(echo "${INPUT}" | jq -r '.session_id // empty')
if [ -z "${session_id}" ]; then
  session_id="${CLAUDE_SESSION_ID:-unknown}"
fi

file_path=$(echo "${INPUT}" | jq -r '.tool_input.file_path // empty')
bash_command=$(echo "${INPUT}" | jq -r '.tool_input.command // empty')
bash_verb="${bash_command%% *}"
if [ -z "${bash_verb}" ]; then
  bash_verb="n/a"
fi

# Rotate log only when file exists and exceeds threshold
if [ -f "${OBS_FILE}" ]; then
  current_size=$(wc -c < "${OBS_FILE}" | tr -d ' ')
  if [ "${current_size}" -ge "${MAX_BYTES}" ]; then
    mv "${OBS_FILE}" "${ARCHIVE_DIR}/observations-$(date -u +%Y%m%dT%H%M%SZ).jsonl"
  fi
fi

timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
jq -nc \
  --arg timestamp "${timestamp}" \
  --arg session_id "${session_id}" \
  --arg tool "${tool_name}" \
  --arg file_path "${file_path}" \
  --arg bash_verb "${bash_verb}" \
  '{
    timestamp: $timestamp,
    session_id: $session_id,
    tool: $tool,
    file_path: $file_path,
    bash_verb: $bash_verb
  }' >> "${OBS_FILE}"

exit 0
