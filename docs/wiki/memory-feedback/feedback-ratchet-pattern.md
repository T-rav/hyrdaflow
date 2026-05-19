---
source: feedback_ratchet_pattern.md
name: Ratchet pattern with grandfather YAML for retroactive convention enforcement
description: When you want to enforce a new convention but bulk-cleanup is too risky,
  ship a CI-failing detector + grandfather YAML allowlist that locks current state
  and fails on growth
status: issue-open
issue: 37
promoted_in: null
wontfix_reason: null
created: 2026-05-08
---

# Ratchet pattern with grandfather YAML for retroactive convention enforcement

For retroactive convention enforcement (e.g. "no `AsyncMock(Port)` without `spec=`"), use the **ratchet pattern**: ship a detector + sidecar grandfather YAML that lists existing violations. CI fails when the violation set EXCEEDS the grandfather list, but tolerates current state. List MAY shrink (cleanup welcome), MUST NOT grow.

**Why:** PR #8714 added `tests/test_mock_spec_discipline.py` + `tests/_mock_spec_grandfathered.yaml` for AsyncMock-spec discipline. The grandfather list shipped EMPTY because the codebase was already clean — turning the ratchet into a regression-prevention guard rather than a cleanup mandate. This converts "we should clean up X someday" (which never happens) into "X can't get worse, ever" (which sticks). The ratchet pattern was specifically designed for cases where bulk cleanup of 4000+ call sites would be impractical or risky.

**Pattern shape:**

1. **Pure detector** — AST walker / regex / etc. in `src/_<thing>_detector.py`. Returns a list of `Violation(path, lineno, reason)`.
2. **Meta-tests** — `tests/meta/test_<thing>_detector.py` with synthetic fixture files under `tests/meta/_<thing>_fixtures/`. Verifies detector logic on synthetic positive + negative cases.
3. **Grandfather YAML** — `tests/_<thing>_grandfathered.yaml`:
   ```yaml
   comment: <thing> ratchet. Generated <date>. MAY shrink. MUST NOT grow.
   entries:
     - path: tests/<file>.py
       line: 42
       reason: grandfathered at initial scan <date>
   ```
4. **Discipline test** — two assertions:
   - `test_no_new_<thing>_violations` — fails if `current - grandfathered` is non-empty
   - `test_grandfather_list_does_not_contain_false_positives` — fails if `grandfathered - current` is non-empty (stale entries that no longer violate, signaling cleanup happened — entry should be removed)

**How to apply:**

- Use this pattern for **convention violations the team agrees on but can't bulk-fix** (legacy code, spec drift, lint-rule rollouts).
- **DON'T use it for new code conventions** — those should fail outright with no grandfather mechanism. Ratchets are specifically for retroactive enforcement.
- Add fixture files to `pyproject.toml` `[tool.ruff.lint.per-file-ignores]` so ruff doesn't strip the intentional violations during `--fix`.
- Pyright already excludes `tests/` (per `[tool.pyright]`), so synthetic-fixture noise is silenced.
- **Edge cases the detector should silently skip rather than flag** when ambiguity exists — false negative > false positive for a ratchet (per Mock-spec spec §3 design).
