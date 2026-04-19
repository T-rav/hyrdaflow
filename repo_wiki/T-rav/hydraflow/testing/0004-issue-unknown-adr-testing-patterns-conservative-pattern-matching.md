---
id: 0004
topic: testing
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T14:53:08.908957+00:00
status: active
---

# ADR Testing Patterns: Conservative Pattern Matching and Validation

Extract only high-confidence invariant patterns (4 baseline: uniqueness, usage, negative, coverage) from ADR Decision sections. Generate all tests with `@pytest.mark.skip(reason="skeleton: requires human review")` by default, deferring validation to humans. This prevents over-matching ambiguous language while supporting future pattern refinement.

ADR validation: ADRs must pass `tests/test_adr_pre_validator.py` which enforces required sections (Status, Context, Decision, Consequences), valid status values, and correct markdown formatting. Validate that each ADR's status is one of: Proposed, Accepted, Deprecated, Superseded. Markdown formatting must follow the standard ADR template.
