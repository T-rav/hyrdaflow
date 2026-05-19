---
source: feedback_make_quality_pipe_exit_code.md
name: Piping make to tail masks the make exit code
description: "`make quality | tail -200` returns 0 even when make fails — the run-in-background notification was misleading; check tail content for actual failures"
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: 2026-05-08
---

# Piping make to tail masks the make exit code

When running `make quality 2>&1 | tail -N` (background or otherwise), the **pipe's exit code is `tail`'s, not make's**. So an exit-0 notification can hide a real failure. This burned a real moment in the 2026-05-08 PR #8714 work — the bash notification said "exit code 0" but `make quality` had 3 test failures buried in the tail output.

**Why:** Bash pipelines return the exit status of the last command in the pipeline by default. `tail` always returns 0 (it has no failure mode for normal stdin reads). So `make quality | tail` masks make's failure status.

**How to apply:**

- **Check tail content even on exit-0** — read the last few lines for "FAILED" or "Error" markers when running long pipelines.
- **Better: `set -o pipefail` at the top of the bash command**:
  ```bash
  set -o pipefail; make quality 2>&1 | tail -200
  ```
  Now the exit code reflects make's status, not tail's.
- **Best for run_in_background bash**: capture full output to a file, then tail the file separately:
  ```bash
  make quality 2>&1 > /tmp/quality.log; echo "EXIT=$?"; tail -5 /tmp/quality.log
  ```
  Now you see both the actual exit code AND the tail without ambiguity. This is the pattern that worked on the second run of PR #8714's quality gate.

**Generalizes to:** any pipeline ending in `tail`, `head`, `cat`, `tee`, `grep` (with --quiet), or anything else that doesn't propagate upstream failures.
