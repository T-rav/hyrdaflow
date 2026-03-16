# ADR-0023: Duplicate Class Definitions — Merge-Artifact Pattern

**Status:** Accepted
**Date:** 2026-03-08

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

### Operational impact on HydraFlow workers

- **Review agent** (`reviewer.py`): Should be configured to flag duplicate class names
  as a review finding. A grep-based check during the review phase can catch this
  pattern automatically.
- **Implementation agent** (`agent.py`): When adding new model classes, the agent
  should search for existing classes with the same name before creating a new
  definition.
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

- Adds a manual review step that relies on reviewer discipline. Until an automated
  lint rule is implemented, duplicates can still slip through if reviewers skip the
  check.
- Strictly enforcing single-definition may occasionally force a type into `models.py`
  earlier than desired (when a second consumer appears), creating a small refactoring
  cost.
- Resolving existing duplicates requires an audit of the current codebase, which is
  a one-time effort.

## Alternatives considered

1. **Automated lint rule (e.g., custom Ruff or Pyright plugin)** — desirable but
   deferred. Writing a reliable cross-module duplicate-class detector is non-trivial;
   the manual review check is practical today and can be replaced by automation later.
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
