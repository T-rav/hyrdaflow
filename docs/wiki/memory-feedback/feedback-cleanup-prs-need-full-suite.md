---
source: feedback_cleanup_prs_need_full_suite.md
name: Cleanup PRs need full-suite verification (not file-targeted subsets)
description: When deleting defensive guards or "redundant" code, run pytest tests/ -x not just tests/test_<related_file>.py — over-pruning often surfaces in unrelated test files
status: pending
issue: null
promoted_in: null
wontfix_reason: null
created: '2026-05-02'
---

When implementing code-cleanup PRs that remove defensive guards (`getattr(self, "_X", None)` → `self._X`, `if x is None: raise` deletions, dead-code removal), **always verify with the full test suite** before merging — not just file-targeted subsets like `pytest tests/test_<related_file>.py`.

**Why:** PR #8460 (cleanup-trust-types) removed `getattr(self, "_X", None)` checks where `_X` turned out to be set CONDITIONALLY in subclasses or scaffolding code (test fixtures bypassing `__init__` via `cls.__new__(cls)`), not unconditionally. The implementer ran `pytest tests/test_base_runner.py tests/test_repo_wiki_loop.py tests/test_events.py` (211 tests, all green) and shipped — but `tests/test_audit_prompts.py` and `tests/test_repo_wiki_loop_pr.py` (which weren't in that subset) had 7 `AttributeError` failures. PR #8463 was a hotfix.

**How to apply:**
- Cleanup PRs: run `make quality` (full suite) before pushing, even if it takes 7+ minutes.
- If full quality is too slow during iteration, at minimum run `pytest tests/ -x --timeout=60 -q` (full collection, fail-fast).
- Don't trust file-targeted subsets — `getattr` removals look local but break wherever a different code path bypassed `__init__`.
- Remediation pattern: set the attr unconditionally in `__init__` as `Optional[X] = None`. Preserves cleanup intent (no defensive `getattr` at read sites) AND makes attr statically visible.
