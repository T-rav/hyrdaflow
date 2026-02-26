#!/bin/bash
# Hook: Generate a concise per-session retro from tool observations.
# Fires on Stop and writes artifacts under .claude/state/self-improve/.

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
STATE_DIR="${PROJECT_DIR}/.claude/state/self-improve"
OBS_FILE="${STATE_DIR}/observations.jsonl"
RETRO_DIR="${STATE_DIR}/session-retros"
MEMORY_CANDIDATES="${STATE_DIR}/memory-candidates.md"

if [ ! -f "${OBS_FILE}" ]; then
  exit 0
fi

mkdir -p "${RETRO_DIR}"

session_id="${CLAUDE_SESSION_ID:-unknown}"
if [ "${session_id}" = "unknown" ]; then
  session_id=$(tail -n 200 "${OBS_FILE}" | jq -r 'select(.session_id != null and .session_id != "") | .session_id' | tail -n 1)
  if [ -z "${session_id}" ]; then
    session_id="unknown"
  fi
fi

SESSION_EVENTS_FILE=$(mktemp)
tail -n 400 "${OBS_FILE}" | jq -c --arg sid "${session_id}" 'select(.session_id == $sid)' > "${SESSION_EVENTS_FILE}" || true

event_count=$(wc -l < "${SESSION_EVENTS_FILE}" | tr -d ' ')
if [ "${event_count}" -eq 0 ]; then
  rm -f "${SESSION_EVENTS_FILE}"
  exit 0
fi

write_count=$(jq -s '[.[] | select(.tool == "Write")] | length' "${SESSION_EVENTS_FILE}")
edit_count=$(jq -s '[.[] | select(.tool == "Edit")] | length' "${SESSION_EVENTS_FILE}")
read_count=$(jq -s '[.[] | select(.tool == "Read")] | length' "${SESSION_EVENTS_FILE}")
bash_count=$(jq -s '[.[] | select(.tool == "Bash")] | length' "${SESSION_EVENTS_FILE}")
task_count=$(jq -s '[.[] | select(.tool == "TaskCreate")] | length' "${SESSION_EVENTS_FILE}")

unique_files=$(jq -s '[.[] | select(.file_path != "") | .file_path] | unique | length' "${SESSION_EVENTS_FILE}")
top_bash_verbs=$(jq -r 'select(.bash_verb != "n/a") | .bash_verb' "${SESSION_EVENTS_FILE}" | sort | uniq -c | sort -nr | head -n 5 || true)

ts_slug=$(date -u +"%Y%m%dT%H%M%SZ")
retro_file="${RETRO_DIR}/${ts_slug}-${session_id}.md"

{
  echo "# Session Retro (${ts_slug})"
  echo
  echo "- Session ID: \`${session_id}\`"
  echo "- Events captured: ${event_count}"
  echo "- Tool counts: Write=${write_count}, Edit=${edit_count}, Read=${read_count}, Bash=${bash_count}, TaskCreate=${task_count}"
  echo "- Unique files touched: ${unique_files}"
  echo
  echo "## Top Bash Verbs"
  if [ -n "${top_bash_verbs}" ]; then
    echo '```text'
    echo "${top_bash_verbs}"
    echo '```'
  else
    echo "_No bash commands captured._"
  fi
  echo
  echo "## Suggested Improvements"

  if [ "${read_count}" -lt 2 ] && [ $((write_count + edit_count)) -ge 3 ]; then
    echo "- Add more explicit exploration before edits (reinforce \`hf.enforce-plan-and-explore\`)."
  fi

  if [ "${bash_count}" -gt 0 ] && ! echo "${top_bash_verbs}" | grep -Eq 'pytest|make|uv|ruff|pyright'; then
    echo "- Run a verification pass before commit (\`verification-loop\` skill)."
  fi

  if [ "${event_count}" -ge 50 ]; then
    echo "- Session was long; use strategic compaction checkpoints (\`strategic-compact\` skill)."
  fi

  if [ "${task_count}" -eq 0 ] && [ $((write_count + edit_count)) -gt 0 ]; then
    echo "- Create a concrete task plan earlier in the session for stronger traceability."
  fi

  echo
  echo "## Memory Candidate"
  echo "- Durable learning to consider via \`/hf.memory\`: "
  echo "  - _Fill in the key workflow preference or root-cause insight from this retro._"
} > "${retro_file}"

if [ ! -f "${MEMORY_CANDIDATES}" ]; then
  {
    echo "# Memory Candidates"
    echo
    echo "Auto-generated session insights to promote with \`/hf.memory\`."
    echo
  } > "${MEMORY_CANDIDATES}"
fi

{
  echo "## ${ts_slug} (${session_id})"
  echo "- Retro: ${retro_file}"
  echo "- Events: ${event_count}; Write/Edit: $((write_count + edit_count)); Read: ${read_count}; Bash: ${bash_count}"
  echo
} >> "${MEMORY_CANDIDATES}"

echo "[hf.session-retro] Wrote ${retro_file}" >&2
rm -f "${SESSION_EVENTS_FILE}"
exit 0
