# Testing Is Mandatory

**ALWAYS write unit tests for code changes before committing.** Every new function, class, or feature modification MUST include comprehensive tests.

- Tests live in `tests/` following the pattern `tests/test_<module>.py`
- New features: Write tests BEFORE committing
- Bug fixes: Add regression tests that reproduce the bug
- Refactoring: Ensure existing tests pass, add tests for new paths
- Never commit untested code
- Coverage threshold: **70%**

## ADR testing rules

- **Never write tests for ADR markdown content.** ADRs are documentation, not code. Do not create `test_adr_NNNN_*.py` files that assert on markdown headings, status fields, or prose content — these break whenever the document is edited and provide no value. Only test ADR-related *code* (e.g., `test_adr_reviewer.py` tests the reviewer logic).
- **Never include line numbers in ADR source citations.** Throughout ADR documents (Related, Context, Decision, Consequences sections), cite source files by function or class name only (e.g., `src/config.py:_resolve_base_paths`). Do NOT add `(line 42)` or similar anywhere — line numbers drift as the source file is edited and council reviews will flag them as stale.

## Related

- [`avoided-patterns.md`](avoided-patterns.md) — recurring test-side mistakes (top-level imports of optional deps, wrong-level mocks, falsy optional checks)
- [`quality-gates.md`](quality-gates.md) — the full quality sequence to run before committing
- [`docs/adr/0022-integration-test-architecture-cross-phase.md`](../adr/0022-integration-test-architecture-cross-phase.md) — integration test architecture
- [`docs/adr/0035-tests-must-match-toggle-state-they-assert.md`](../adr/0035-tests-must-match-toggle-state-they-assert.md) — toggle/test alignment
