# ADR-0027: Duplicate Class Definitions — Merge-Artifact Pattern

**Status:** Proposed
**Date:** 2026-03-18

## Context

HydraFlow uses Pydantic models and dataclasses extensively across its codebase. The
shared `models.py` module serves as the canonical location for data models used across
multiple phases, while feature-specific modules (e.g., `adr_pre_validator.py`) may
define local types scoped to a single concern.

A recurring merge-artifact pattern has been observed: when a PR introduces a new model
class, the class sometimes appears in both a feature module and in `models.py` with
slightly different field names or types. This happens when two branches independently
add the same concept — one in the feature module (where it is actually used) and one
in `models.py` (where it was speculatively placed for reuse). After merge, both
definitions survive because there is no compile-time or lint-time check that flags
duplicate class names across modules.

The `models.py` copy tends to become dead code: nothing imports it, but it creates a
silent naming collision. If a future contributor imports from `models.py` instead of
the feature module (or vice versa), they get a subtly incompatible type — fields may
be missing, renamed, or have different defaults. This leads to runtime errors or
silently dropped data that are difficult to trace.

This pattern was identified through memory issue #2380 and confirmed by review of
merge histories where duplicate class names coexisted undetected across modules.

## Decision

Adopt the following rules to prevent and detect merge-artifact duplicate class
definitions in HydraFlow:

### 1. Single-definition rule

Every model class (Pydantic `BaseModel` subclass, dataclass, or `TypedDict`) must
have exactly one definition across the entire `src/` tree. If a type is used by
multiple modules, it belongs in `models.py`. If it is used by a single feature module,
it belongs in that module only — not also in `models.py`.

### 2. PR review: grep for class name uniqueness

During code review of any PR that adds or renames a model class, reviewers must grep
all source files (`src/**/*.py`) for the class name. If the name appears in more than
one module (excluding imports and type annotations), the duplicate must be resolved
before merge.

### 3. Conflict resolution strategy

When a duplicate is found:

- **Determine the canonical location** — whichever module actually imports and uses
  the class at runtime is canonical. The other copy is dead code.
- **Delete the dead copy** and update any stale imports.
- **Reconcile field differences** — if the two definitions have different fields,
  merge them into the canonical version and verify all call sites.

### 4. Scope boundaries

This decision applies to all Python class definitions in `src/` that represent data
models (Pydantic, dataclass, TypedDict). It does not apply to:

- Test helper classes in `tests/` (test doubles may intentionally shadow production
  types).
- Protocol or ABC classes that define interfaces (these are not data models).
- Identically-named classes in unrelated namespaces where the duplication is
  intentional and documented.

### 5. Automation triggers

The manual review check in Rule 2 is a stopgap. Switch to automated enforcement
when **any** of the following conditions is met:

- **Trigger A — Duplicate slips through review:** A duplicate class definition
  reaches `main` despite the manual grep check. The post-mortem for that incident
  must include adding an automated lint rule (custom Ruff rule or a CI script) as
  a corrective action.
- **Trigger B — Third occurrence in memory/issue history:** If HydraFlow's memory
  or issue tracker records three or more incidents of duplicate class definitions
  (including the original #2380), automation becomes mandatory regardless of
  whether the duplicates were caught in review.
- **Trigger C — Calendar deadline:** If neither Trigger A nor B fires by
  2026-06-01, a tracking issue must be opened to implement the automated check
  within the next sprint. The manual process must not run indefinitely.

Once any trigger fires, the automated rule replaces Rule 2 entirely — the manual
grep step is removed from the review checklist.

### 6. One-time codebase audit

Before this ADR moves to Accepted, a time-boxed audit must be completed:

- **Scope:** All Python class definitions in `src/` that subclass `BaseModel`,
  use `@dataclass`, or extend `TypedDict`.
- **Method:** Run `grep -rn "^class " src/ | awk -F: '{print $NF, $1}' | sort` and
  group by class name. Flag any name that appears in more than one module
  (excluding `tests/`).
- **Time box:** The audit must be completed within one calendar week of this ADR
  being accepted. Open a tracking issue for the audit before acceptance.
- **Output:** Each confirmed duplicate is resolved per Rule 3 (conflict resolution
  strategy) in a dedicated PR. The tracking issue is closed when all duplicates
  are resolved or explicitly documented as intentional exceptions under Rule 4.

### Operational impact on HydraFlow workers

- **Review agent** (`src/reviewer.py:ReviewRunner`): Must flag duplicate class
  names as a review finding. A grep-based check during the review phase catches
  this pattern until an automated lint rule replaces it (see Rule 5 automation
  triggers).
- **Implementation agent** (`src/agent.py:AgentRunner`): When adding new model
  classes, the agent must search for existing classes with the same name before
  creating a new definition.
- No runtime behaviour changes — this is a development and review discipline.

## Consequences

**Positive**

- Eliminates a class of silent bugs where two definitions of the same type coexist
  with incompatible fields, leading to runtime data loss or `ValidationError`
  exceptions.
- Makes the canonical location of each type unambiguous, reducing confusion for
  contributors navigating the codebase.
- The review-time grep check is lightweight and requires no new tooling — it can be
  performed with standard CLI tools or IDE search.

**Negative / Trade-offs**

- Adds a manual review step that relies on reviewer discipline until automation is
  triggered (see Rule 5). The automation triggers ensure this manual phase has a
  hard deadline of 2026-06-01 at the latest.
- Strictly enforcing single-definition may occasionally force a type into `models.py`
  earlier than desired (when a second consumer appears), creating a small refactoring
  cost.
- The one-time codebase audit (Rule 6) must be completed within one week of
  acceptance. This is a bounded effort but requires dedicated time.

## Alternatives considered

1. **Automated lint rule (e.g., custom Ruff or Pyright plugin)** — desirable but
   deferred with explicit activation triggers (Rule 5). The manual review check is
   practical today and will be replaced by automation no later than 2026-06-01 or
   upon the next duplicate slipping through review, whichever comes first.
2. **Namespace-scoped uniqueness only (allow duplicates across packages)** — rejected
   because HydraFlow's `src/` tree is a single flat package; cross-module imports are
   common and namespace boundaries do not provide meaningful isolation.
3. **Re-export pattern (feature module re-exports from models.py)** — rejected because
   it does not prevent the root cause (two independent definitions) and adds an
   indirection layer that obscures where the type is actually defined.

## Related

- Source memory: [#2380 — Duplicate class definitions across modules — merge-artifact pattern](https://github.com/T-rav/hydra/issues/2380)
- Implementing issue: [#2382](https://github.com/T-rav/hydra/issues/2382)
- Related learning: [#2381 — Duplicate class definitions](https://github.com/T-rav/hydra/issues/2381)
- Council review: [#3244 — ADR council requested changes](https://github.com/T-rav/hydraflow/issues/3244)
