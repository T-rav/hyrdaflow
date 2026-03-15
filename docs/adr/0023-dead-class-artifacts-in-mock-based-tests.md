# ADR-0023: Require Instantiation Verification for Test-Local Classes

**Status:** Accepted
**Date:** 2026-03-08

## Context

HydraFlow's test suite uses `unittest.mock.patch` extensively to simulate failures
in phase runners, git operations, and file-system calls. A recurring pattern emerged
where a developer writes a helper class inside a test body (e.g., `ExplodingStr` to
raise on `__fspath__`) targeting an earlier implementation, then refactors the
production code so the failure is injected via `patch` side effects instead. The
helper class remains in the test file but is never instantiated.

These dead class artifacts are invisible at runtime — Python happily defines a class
that nobody constructs — so they survive linting (`ruff`), type checking (`pyright`),
and the test run itself. They only surface during manual code review, and even then
they are easy to overlook because they sit next to the mock setup that *does* run.

The pattern was identified during review of mock-based failure injection tests that
patched `os.fdopen` (see memory issue #2362). The leftover `ExplodingStr` class
added confusion for reviewers and set a precedent for accumulating dead test code
across the repository.

Current tooling gaps:

- **Ruff** does not flag unused class definitions inside function bodies; its
  unused-variable rules only cover simple name bindings.
- **Pyright** reports no error for a class that is defined but never referenced.
- **pytest** naturally ignores class definitions that are not `Test*`-prefixed.
- **Coverage** shows 0% for the dead class body, but coverage reports are not
  enforced at the per-class granularity needed to catch this.

## Decision

Adopt a review-time and CI-enforced policy that every class defined inside a test
function body must be instantiated or explicitly referenced within that test.

### Review checklist addition

During code review of test files, reviewers must verify:

1. Every `class` statement inside a `def test_*` or `async def test_*` body is
   followed by at least one instantiation (`ClassName(...)`) or direct reference
   (e.g., passed as a `side_effect`, `return_value`, or `new` argument to `patch`).
2. If a helper class is shared across multiple tests, it should be promoted to
   module-level scope so its visibility is explicit and it can be referenced by name
   from any test in the file.
3. When refactoring a test to use `patch` side effects instead of a custom class,
   the developer must delete the now-unused class in the same commit.

### Scope boundaries

- This policy applies to **test files only** (`tests/test_*.py`). Production code
  already benefits from import-time detection of unused symbols.
- The policy covers classes defined inside test function bodies. Module-level test
  helper classes are outside scope because they are visible to linters and easier
  to audit.
- No custom lint rule or AST-walking CI check is required at this stage; the
  review checklist is sufficient given the low frequency of the pattern. If dead
  class artifacts recur despite the checklist, a follow-up task should introduce
  an automated check.

### Operational impact on HydraFlow workers

- **Review agent** (`reviewer.py`): The review prompt can be augmented with a
  heuristic check — scan `class` definitions inside test functions and verify each
  class name appears at least once more in the same function body. This is a
  string-level check that does not require AST parsing and fits within the existing
  review agent's diff-analysis pass.
- **Implement agent** (`agent.py`): No change required. Implementation agents
  generate test code but are not responsible for detecting dead artifacts in
  existing tests.
- **Triage / Plan / HITL phases**: No impact.

## Consequences

**Positive**

- Eliminates a class of silent test debt that accumulates during mock refactoring.
- Reduces reviewer confusion when reading failure-injection tests, because every
  class in the test body has a clear purpose.
- Establishes a lightweight convention that can later be automated if the pattern
  recurs at higher frequency.

**Negative / Trade-offs**

- Adds one more item to the review checklist, increasing reviewer cognitive load
  marginally.
- String-level heuristic in the review agent may produce false positives for classes
  used via metaprogramming (e.g., `locals()` or `globals()` lookups), though this
  pattern is extremely rare in HydraFlow tests.
- Does not catch dead classes at module scope — those require separate tooling
  (e.g., `vulture`) which is out of scope for this decision.

## Alternatives considered

1. **Add a `vulture` or custom AST check to CI** — rejected for now because the
   frequency of this pattern does not justify the maintenance cost of a new CI
   step. Can be revisited if the review checklist proves insufficient.
2. **Ignore the problem** — rejected because dead helper classes actively mislead
   reviewers into thinking the class is part of the test's failure-injection
   mechanism, increasing review time and risk of copy-paste propagation.
3. **Ban helper classes inside test bodies entirely** — rejected as overly
   restrictive; inline helper classes are a valid pattern for mock `new` arguments
   and custom exception types scoped to a single test.

## Related

- Source memory: [#2362 — Dead class artifacts in tests using mock-based failure injection](https://github.com/T-rav/hydra/issues/2362)
- Implementing issue: [#2373](https://github.com/T-rav/hydra/issues/2373)
## Council Amendment Notes

The following amendments were generated from council feedback:

- Architect: The ADR captures a genuine architectural scoping decision — a
- Pragmatist: The scope is defensible given this project's established ADR
- Editor: The document is well-written and complete, and ADR-0022 establishes

These notes are intended to be incorporated before final acceptance.
