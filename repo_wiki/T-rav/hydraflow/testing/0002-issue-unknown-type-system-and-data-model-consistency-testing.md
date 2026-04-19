---
id: 0002
topic: testing
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T14:53:08.908950+00:00
status: active
---

# Type System and Data Model Consistency Testing

Schema evolution and field synchronization: Global singletons like `_event_counter` are shared across all instances. Tests must never assert on absolute ID values—only on relative ordering and uniqueness within a single test. This prevents test pollution and ensures event ordering is the actual concern. Before property-based tests exercise a transition graph, add structural tests: every target is a valid stage, every stage has a transition entry, no dangling references. Test constants (`ALL_PIPELINE_LABELS`, `VALID_STAGES`, `VALID_TRANSITIONS`) serve as both test oracles and executable documentation—keep them synchronized. Direct-swap labels (hitl-active, hitl-autofix, fixed, verify) are set via `swap_pipeline_labels()` calls, not transitions. STAGE_ORDER gates full lifecycle tests; new stages require STAGE_ORDER updates. Test both EVENT_TYPE_TO_STAGE and SOURCE_TO_STAGE paths independently. When related data structures must stay in sync, add dedicated sync tests asserting set equality via dynamic field extraction. Use `len(LABELS) == 13` instead of hardcoding. Validate explicitly that each label field is present in `all_pipeline_labels`.

Model and TypedDict field changes: Adding fields to Pydantic models or TypedDict structures breaks tests with exact field sets or exact equality assertions. Required updates: model definition, test factory defaults, field assertions in all_fields tests, state assertions, serialization/deserialization round-trips. Grep the test suite for each model name before committing. For TypedDict fields marked `NotRequired`, update exact-match assertions but not missing-key assertions. When changing internal dict key types (e.g., `int` → `str`), test both old format and new format loading without crashes. When narrowing field types with validators, accept empty strings explicitly to preserve backward compatibility. When adding Literal constraints to Pydantic fields, test both valid and invalid values. Use `total=False` Pydantic models to conditionally include fields like `verdict` and `duration` only when provided (non-None), not as None values.

Type annotation changes: TypedDicts are dicts at runtime, so existing test assertions work identically. Migrating from dict[str, Any] to TypedDict returns requires no test changes—the value is purely in static type validation. When narrowing function parameter types from `Any` to specific types, callers passing `Any`-typed values will still type-check successfully. `Any` is compatible with all types in pyright, enabling safe gradual type annotation migrations. Type annotation changes without runtime behavior modifications can be verified entirely through existing test suites and type checkers; new test additions are unnecessary. Verify via `make quality-lite` and `make test`.

Feature toggle implementation: Feature toggles require both a config field definition in `src/config.py` AND an `_ENV_INT_OVERRIDES` entry to support environment-variable override. Both are necessary for the toggle to be runtime-configurable. Each toggle field must be tested for both default value and environment-variable override behavior.

See also: Core Testing Strategy and Design for Testability — mock return values must match TypedDict structure.
