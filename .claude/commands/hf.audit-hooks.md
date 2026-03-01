# Hooks & Workflow Audit

Audit all Claude Code hooks (`.claude/settings.json` and `.claude/hooks/*.sh`) for correctness, efficiency, and gating opportunities. Launch a single agent that reads everything and reports findings.

## Instructions

1. Launch the agent below using `Task` with `subagent_type: "general-purpose"`.
2. Present the findings to the user.

## Agent Prompt

```
You are a hooks and workflow auditor for this project.

## Steps

1. Read `.claude/settings.json` to understand the full hook configuration (PreToolUse, PostToolUse, Stop)
2. Read ALL `.sh` files in `.claude/hooks/` (use Glob for `**/*.sh`)
3. For each hook script, analyze against the checklist below
4. For the settings.json hook wiring, analyze against the wiring checklist below
5. Return a structured report of findings

## Hook Script Checklist

For each .sh file:

**Fast-exit gating:**
- Does it exit early when the tool input is irrelevant? (e.g., non-Python file for a Python-only check)
- Does it avoid expensive operations (git, grep, make) before confirming relevance?
- Are marker/warned checks done BEFORE filesystem scans or subprocess calls?
- Does it use session markers with TTL to avoid repeating warnings?

**Correctness:**
- Does `set -euo pipefail` behave correctly? (unmatched grep with pipefail can cause unexpected exits — should use `|| true`)
- Does it read tool_input correctly via jq? (Edit uses `file_path` + `old_string` + `new_string`; Write uses `file_path` + `content`)
- Are exit codes correct? (0 = allow, 2 = block for PreToolUse; 0 = ok for PostToolUse)
- Does it handle missing/empty jq fields gracefully?

**Efficiency:**
- Are there redundant subprocess calls? (multiple git invocations that could be combined)
- Are there filesystem operations that run unconditionally but could be gated?
- Could marker files be checked before mkdir -p?
- Are there grep/find calls that scan large directory trees unnecessarily?

**Robustness:**
- Does it work when CLAUDE_PROJECT_DIR is unset? (fallback to pwd)
- Does it handle filenames with spaces?
- Does it work on both macOS and Linux? (md5 vs md5sum, find syntax)
- Are /tmp marker directories cleaned up or TTL-gated?

## Settings.json Wiring Checklist

**Matcher coverage:**
- Are all relevant tools covered? (e.g., if a check applies to both Edit and Write, is it on both matchers?)
- Are there matchers that should exist but don't?
- Are there hooks on matchers where they'll never trigger? (wasted registration)

**Hook ordering:**
- Are fast/cheap hooks listed before slow/expensive ones in each matcher's array?
- For Stop hooks: are agent hooks gated by a marker or fast check before doing LLM work?
- Is the cleanup command hook last in the Stop array?

**Consistency:**
- Do all PreToolUse blocking hooks use exit 2?
- Do all PostToolUse tracking hooks use exit 0?
- Are timeout values reasonable? (tracking: 5s, checks: 10-15s, tests: 120s)
- Do all hooks that should have statusMessage have one?

**Gaps:**
- Are there tools or workflows not covered by any hook?
- Are there hooks that overlap or duplicate each other's checks?
- Could any PreToolUse hooks be replaced by cheaper PostToolUse tracking + Stop review?

## Report Format

Group findings by severity:

### Critical (broken or blocking incorrectly)
- [hook:line] description

### High (wasted execution or missing gate)
- [hook:line] description and recommended fix

### Medium (improvement opportunity)
- [hook:line] description

### Low (style/micro-optimization)
- [hook:line] description

### Summary
- Total hooks: X scripts, Y settings entries
- Gating score: X/Y hooks have proper fast-exit paths
- Portability: any macOS-only concerns
- Recommended next actions (top 3)
```
