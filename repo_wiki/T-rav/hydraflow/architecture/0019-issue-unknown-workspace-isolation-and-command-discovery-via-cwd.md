---
id: 0019
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849589+00:00
status: active
---

# Workspace Isolation and Command Discovery via CWD

Claude Code discovers commands from subprocess cwd's .claude/commands/, not from invoking process. Commands must be installed into every workspace, not just source repo. Pre-flight validation (before subprocess launch) catches stale commands due to external state changes. Defense-in-depth prevents agent commits to target repos: combine .gitignore hf.*.md entries + hf.* prefix namespace isolation. Built-in hf.* patterns always take priority over extra patterns in deduplication. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. Path traversal guard required for extra_tool_dirs to verify they don't escape repo boundary. See also: Dynamic Discovery for convention patterns.
