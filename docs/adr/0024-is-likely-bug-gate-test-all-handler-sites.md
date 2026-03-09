# ADR-0024: Test All `is_likely_bug` Handler Sites Per Module

**Status:** Proposed
**Date:** 2026-03-09

## Context

HydraFlow applies the `is_likely_bug()` gate pattern across many modules to
classify exceptions as probable bugs (re-raise) versus expected operational
errors (log and continue). A single module often contains multiple handler
sites — for example, `adr_reviewer.py` uses `is_likely_bug()` in three
separate `except` blocks (lines 490, 594, 1009), and `reviewer.py` uses it in
three methods (`review()`, `fix_ci()`, `fix_review_findings()`).

During review of PRs that apply exception-handling patterns across a module
(see memory issue #2469), a recurring gap was identified: tests would cover
only the most prominent handler site (e.g., `_route_to_triage` in
`adr_reviewer.py`) while leaving other sites in the same module untested. This
created a false sense of coverage — the module appeared tested, but individual
handler sites could silently regress if their surrounding control flow changed.

The problem is amplified by the cross-cutting nature of the pattern. When
`is_likely_bug()` is added to N locations within a module, a single
"representative" test exercises only one code path. The remaining N−1 paths
have no regression protection, and refactoring that breaks one path (e.g.,
changing variable names, reordering try/except blocks, or modifying the
exception type) will not be caught.

Current state of the codebase:

- **`adr_reviewer.py`** — 3 handler sites
- **`reviewer.py`** — 3 handler sites (`review`, `fix_ci`, `fix_review_findings`)
- **`merge_conflict_resolver.py`** — 2 handler sites
- **`triage.py`** — 2 handler sites
- **`verification_judge.py`** — 2 handler sites
- **`orchestrator.py`** — 3 handler sites
- **`planner.py`**, **`hitl_runner.py`** — 1 handler site each

Tests in `tests/test_exception_chaining.py` and `tests/test_reviewer.py` now
cover per-site assertions for most modules, but the convention was not
documented as a durable decision until this ADR.

## Decision

Require one test per `is_likely_bug()` handler site when applying the
exception-handling pattern to a module. PRs that add or modify `is_likely_bug`
guards must include a test for **each** handler site — not just one
representative test for the module.

### Concrete rules

1. **One test per handler site.** If a module has N `is_likely_bug()` calls,
   the corresponding test file must have at least N tests that individually
   trigger each handler's `except` block and verify the re-raise / log
   behavior.

2. **Test naming convention.** Tests should identify the method under test in
   their name (e.g., `test_is_likely_bug_reraise_fix_ci`,
   `test_is_likely_bug_reraise_review`), making it easy to map tests to
   handler sites during review.

3. **PR review enforcement.** Reviewers must count `is_likely_bug` call sites
   in the diff and verify a matching number of tests. This is a lightweight
   check that does not require tooling.

4. **Scope.** This policy applies to the `is_likely_bug()` gate specifically
   and, by extension, to any cross-cutting exception-classification pattern
   applied to multiple locations within a single module.

### Scope boundaries

- Applies to **all modules** in `src/` that use `is_likely_bug()`.
- Does not mandate retroactive test backfill for modules that already have
  adequate per-site coverage (e.g., `test_exception_chaining.py` and
  `test_reviewer.py` already follow this pattern).
- Does not prescribe test file organization — per-site tests may live in the
  module's existing test file or in a dedicated exception-chaining test file.

### Operational impact on HydraFlow workers

- **Review agent** (`reviewer.py`): The review prompt should verify that PRs
  touching `is_likely_bug` handler sites include per-site tests. The agent can
  count occurrences of `is_likely_bug` in the diff and compare against test
  method count.
- **Implement agent** (`agent.py`): When adding `is_likely_bug()` to multiple
  methods, the agent must generate a test for each call site rather than a
  single representative test.
- **Triage / Plan / HITL phases**: No impact.

## Consequences

**Positive**

- Eliminates coverage gaps where only one of N handler sites is tested,
  preventing silent regressions in the remaining sites.
- Makes the testing expectation explicit and discoverable for both human
  reviewers and automated agents.
- Aligns with the existing test structure in `test_exception_chaining.py` and
  `test_reviewer.py`, formalizing a pattern that was already emerging.

**Negative / Trade-offs**

- Increases test count proportionally to the number of handler sites, adding
  maintenance cost when the `is_likely_bug()` classification logic changes.
- May produce tests that appear repetitive, since each test follows a similar
  mock-inject-assert pattern. This duplication is intentional — each test
  exercises a distinct code path.
- Reviewers must manually count handler sites; no automated CI check is
  introduced at this stage.

## Alternatives considered

1. **Single representative test per module** — rejected because it leaves N−1
   handler sites unprotected and creates a false sense of coverage.
2. **Parametrized test over all handler sites** — considered viable for modules
   where handler sites share identical setup, but rejected as a hard
   requirement because handler sites often have different mock setups and
   control flow. Parametrization is acceptable as an optimization where it
   fits naturally.
3. **Automated CI check counting handler sites vs tests** — deferred. The
   review checklist is sufficient given the current frequency of changes. Can
   be revisited if the pattern is repeatedly missed during review.

## Related

- Source memory: [#2469 — is_likely_bug gate — test all handler sites in the same module](https://github.com/T-rav/hydra/issues/2469)
- Implementing issue: [#2478](https://github.com/T-rav/hydra/issues/2478)
- Test coverage: `tests/test_exception_chaining.py`, `tests/test_reviewer.py`
