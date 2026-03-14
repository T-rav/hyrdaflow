# ADR-0024: caplog Logger Name Must Match Production getLogger() Exactly

**Status:** Proposed
**Date:** 2026-03-14

## Context

HydraFlow's test suite uses `pytest`'s `caplog` fixture to assert that error-path
logging occurs correctly in production code. The standard pattern is:

```python
with caplog.at_level(logging.ERROR, logger="hydraflow.some_module"):
    await code_under_test()
assert "expected message" in caplog.text
```

The `logger=` argument to `caplog.at_level()` must exactly match the string passed
to `logging.getLogger()` in the production module. For example, if the production
file contains `logger = logging.getLogger("hydraflow.adr_reviewer")`, the test must
use `logger="hydraflow.adr_reviewer"` — not `logger="adr_reviewer"`, not
`logger="hydraflow"`, and not the module's `__name__`.

A mismatch causes `caplog` to attach its handler to a different logger in Python's
logger hierarchy. The production logger's messages are never captured, so
`caplog.text` is empty and the assertion fails. The failure mode is silent at the
point of misconfiguration — there is no warning that the logger name is wrong — and
manifests only as a test assertion failure at runtime. This makes the root cause
non-obvious, especially when the test was recently written and the developer assumes
the production code is not emitting the expected log line.

This pattern was discovered during review of caplog-based assertions added for
error-path coverage (see memory issue #2673). The mismatch was between a shortened
logger name in the test and the fully-qualified name used in production code.

### Current tooling gaps

- **Pyright / mypy**: Cannot statically verify that a string argument to
  `caplog.at_level()` matches a `getLogger()` call in another file.
- **Ruff**: No rule exists to cross-reference logger name strings across files.
- **pytest**: Reports the assertion failure but gives no hint that the logger name
  is the cause.

## Decision

Adopt a convention and review-time check requiring that every `caplog.at_level()`
call in the test suite uses a logger name that is verified against the production
source before the test is written.

### Convention

1. **Grep before wiring**: Before adding a `caplog.at_level()` assertion, grep the
   production file for `getLogger` to find the exact logger name string. Copy it
   verbatim into the test.
2. **Use fully-qualified names**: Production modules must use fully-qualified logger
   names (e.g., `logging.getLogger("hydraflow.module_name")`), not `__name__` or
   shortened forms, so the string is stable and greppable across the codebase.
3. **One logger per module**: Each production module should define at most one
   module-level logger. If a module needs multiple loggers, each must have a
   distinct, documented name.

### Review checklist addition

During code review of test files that use `caplog`:

1. Every `caplog.at_level(..., logger="X")` call must have a matching
   `logging.getLogger("X")` in the production module under test.
2. If the production module changes its logger name, all test files referencing the
   old name must be updated in the same commit.

### Scope boundaries

- This policy applies to **test files** (`tests/test_*.py`) that use `caplog`.
- Production logger naming is a supporting convention, not a strict enforcement
  target — existing modules using `__name__` are acceptable as long as tests
  reference the resolved name correctly.
- No automated CI check is required at this stage. If logger name mismatches recur
  despite the review convention, a follow-up task should introduce a custom lint
  rule or pytest plugin.

### Operational impact on HydraFlow workers

- **Review agent** (`reviewer.py`): The review prompt can include a heuristic —
  when a diff adds `caplog.at_level`, verify the `logger=` argument appears as a
  `getLogger()` argument in the corresponding production file. This is a
  string-level check that fits within the existing review agent's diff-analysis
  pass.
- **Implement agent** (`agent.py`): When generating tests that assert on logging,
  the agent should grep the production file for `getLogger` and use the exact
  string. This avoids a common source of test failures in generated code.
- **Triage / Plan / HITL phases**: No impact.

## Consequences

**Positive**

- Eliminates a class of silent test misconfiguration where caplog assertions pass
  vacuously (empty `caplog.text` compared against a substring that happens not to
  be there) or fail with a misleading error.
- Makes logger name strings greppable and consistent across production and test
  code.
- Low adoption cost — the convention is a single grep command before writing the
  test.

**Negative / Trade-offs**

- Adds a manual verification step that cannot currently be enforced statically,
  relying on developer discipline and review-time checks.
- Requiring fully-qualified logger names in production code is a soft convention;
  modules using `__name__` will continue to work but require tests to resolve the
  module path to its string equivalent.
- If a production module renames its logger, tests will break — but this is the
  desired behavior, as it surfaces the change explicitly rather than silently
  decoupling test and production logging.

## Alternatives considered

1. **Use `__name__` everywhere and derive in tests** — rejected because `__name__`
   resolves differently depending on how the module is imported (e.g., `__main__`
   vs package path), making it fragile for test assertions.
2. **Capture all loggers with `caplog.at_level(logging.ERROR)`** (no logger
   argument) — rejected because this captures logs from all modules, making
   assertions non-specific and prone to false positives from unrelated log lines.
3. **Write a pytest plugin to auto-detect mismatches** — deferred as
   over-engineering for the current frequency of this issue. Can be revisited if
   the pattern recurs despite the review convention.

## Related

- Source memory: [#2673 — caplog logger name must match production getLogger() exactly](https://github.com/T-rav/hydraflow/issues/2673)
- Implementing issue: [#2683](https://github.com/T-rav/hydraflow/issues/2683)
