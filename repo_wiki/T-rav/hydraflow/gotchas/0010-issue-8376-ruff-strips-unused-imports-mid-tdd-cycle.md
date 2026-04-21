---
id: 0010
topic: gotchas
source_issue: 8376
source_phase: synthesis
created_at: 2026-04-21T00:00:00+00:00
status: active
---

# Ruff Strips Unused Imports Mid-TDD Cycle

HydraFlow's pre-commit and post-edit hooks run `ruff --fix`, which removes imports that aren't yet referenced in the file. During a standard TDD cycle (add import → write failing test → add implementation) this creates a race: if a new symbol is imported before the test body or implementation that uses it is saved to disk, ruff strips the import during the first save and the subsequent save fails with `NameError: name '<symbol>' is not defined`.

**Where it bites:** Any file being iteratively built — new test modules, new utility scripts, extensions to existing test files. Spotted repeatedly during sub-project 1 of the prompt audit (PR #8376), where each new rubric-rule task added `from scripts.audit_prompts import score_<rule>` to `tests/test_audit_prompts.py` — the import was stripped before the test body referencing it was appended.

**Pattern that works — impl-first ordering:**

1. For impl files (`scripts/foo.py`, `src/bar.py`): write the implementation block first, then add the needed top-level imports after the symbol exists *and* is referenced.
2. For test files: write the test function body (which uses the new symbol) first, then add the new symbol to the `from X import (...)` block. If you add the import in isolation, it will be stripped.
3. Alternative for test files: use a function-local import inside the test body. Ruff does not strip locally-scoped imports. Slightly uglier but race-free.

**Diagnostic signal:** "name `X` is not defined" immediately after a file save — first check whether ruff stripped the import rather than debugging the code. Look at the head of the file; the import line is often gone.

**Not a bug — an interaction:** TDD's "failing test first" discipline and auto-fixing linters have incompatible premises (intermediate states should be incomplete vs. intermediate states should be clean). The fix is sequencing, not configuration.

See also:
- Feedback memory: `feedback_ruff_strips_unused_imports_during_tdd.md` (user-level)
- `pyproject.toml` `[tool.ruff.lint]` — `F401` (unused-import) is in the enabled lint set via `F`.
