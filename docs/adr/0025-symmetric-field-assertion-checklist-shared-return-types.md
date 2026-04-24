# ADR-0025: Symmetric Field Assertion Checklist for Shared Return Types

**Status:** Accepted
**Enforced by:** (process)
**Date:** 2026-03-16

## Context

HydraFlow uses shared Pydantic models as return types across multiple methods.
For example, `ReviewResult` is returned by `ReviewRunner.review()`,
`ReviewRunner.fix_ci()`, and `ReviewRunner.fix_review_findings()`. When a new
field is added to such a model (e.g., `files_changed`), the implementation may
correctly populate it in all methods, but tests may only assert the field in one
method — silently masking regressions in the others.

This gap was discovered in issue #3182: `test_review_success_path_with_fixes`
had the mock for `_get_changed_files` but never asserted `result.files_changed`.
Meanwhile, `fix_ci()` and `fix_review_findings()` lacked both "populates" and
"empty when no changes" integration tests for `files_changed`.

## Decision

When a field exists on a shared return model and is set by multiple methods, the
test suite must include **all three legs** for **each method** that populates the
field:

1. **Happy-path success test** asserts the field value (both populated and empty
   cases).
2. **Dedicated "populates" integration test** verifies the field is set when the
   underlying operation produces changes.
3. **Dedicated "empty when no changes" integration test** verifies the field
   remains at its default when no changes occur.

Additionally, each method must have symmetric coverage for the standard
behavioral dimensions:

- Success path (basic + with fixes)
- Failure path
- Dry-run path
- Duration recording (success, dry-run, failure)
- Event publishing

## Consequences

- **Regressions caught earlier.** A mock that is wired up but never asserted
  will be flagged during the symmetry audit.
- **Slightly more tests.** Each new shared-model field requires `N x 3` test
  cases (where N = number of methods). This is an acceptable trade-off for the
  safety it provides.
- **Review checklist.** Reviewers can verify symmetry by searching for the field
  name across all test functions for the affected methods.

## Related

- Issue #3182 — original discovery of the missing assertion
- Issue #3183 — implementation of symmetric test coverage
- `src/reviewer.py:ReviewRunner` — the three methods sharing `ReviewResult`
- `src/models.py:ReviewResult` — the shared return type
- `tests/test_reviewer.py` — symmetric test cases
