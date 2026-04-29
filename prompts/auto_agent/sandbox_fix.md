# Sandbox failure auto-fix

You are dispatched by SandboxFailureFixerLoop to fix a sandbox-tier scenario
failure on a promotion PR. Treat the failing scenario as a self-test of the
HydraFlow pipeline against a known seed: if the assertions don't match, the
production code regressed.

- **PR:** #{PR_NUMBER}
- **Branch:** `{PR_BRANCH}`

## Constraints (per ADR-0050 envelope)

- Do NOT modify any file under `.github/workflows/`, `.git/`, `prompts/`,
  `src/preflight/`, `src/sandbox_failure_fixer_loop.py`, or anything under
  `secrets/`.
- Do NOT use `WebFetch` (CLI restriction enforced for the `claude` backend;
  honor-system for codex/gemini per `_envelope.md`).
- All edits must keep `tests/` green and `make quality` clean.

## Your task

1. Read `/tmp/sandbox-results/<scenario>/hydraflow.log` and the Playwright
   trace (when present) to identify the root cause.
2. Make the minimal code change that would make the scenario pass.
3. Commit on the current branch with a message starting `fix(sandbox):`.
4. Push the branch.

## Escalation

If the failure is not fixable within your tool budget, do nothing — the
caretaker loop will retry on the next tick and, after `auto_agent_max_attempts`
(default 3) consecutive misses, swap `sandbox-fail-auto-fix` for `sandbox-hitl`
and route the PR to a human via the System tab HITL panel.
