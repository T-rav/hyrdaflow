# Self-Improving Harness

This branch imports selected assets from `affaan-m/everything-claude-code` and wires them into HydraFlow's existing hook discipline.

## Imported Skills

Installed under `.codex/skills/`:

- `continuous-learning-v2`
- `eval-harness`
- `verification-loop`
- `strategic-compact`
- `skill-stocktake`

## Runtime Loop

HydraFlow now runs two additional hooks:

- `PostToolUse` -> `.claude/hooks/hf.observe-session.sh`
  - Captures minimal tool metadata (tool, file path, bash verb, session ID)
  - Writes JSONL to `.claude/state/self-improve/observations.jsonl`
- `Stop` -> `.claude/hooks/hf.session-retro.sh`
  - Generates per-session retros in `.claude/state/self-improve/session-retros/`
  - Appends index entries to `.claude/state/self-improve/memory-candidates.md`
  - Emits actionable suggestions tied to imported skills

Runtime artifacts are ignored via `.gitignore` (`.claude/state/`).

## Why This Is "Harnessed"

- No autonomous mutation of prompts/skills in-repo.
- Observation data is lightweight and local to the project.
- Retros produce explicit artifacts for human review.
- Promotion into durable memory still goes through `/hf.memory` and HITL.

## Usage

1. Use HydraFlow normally.
2. At session end, inspect latest retro:
   - `.claude/state/self-improve/session-retros/<timestamp>-<session>.md`
3. Promote durable learnings using:
   - `/hf.memory`
4. Run structured quality checks when suggested:
   - `verification-loop` skill
   - `eval-harness` skill
