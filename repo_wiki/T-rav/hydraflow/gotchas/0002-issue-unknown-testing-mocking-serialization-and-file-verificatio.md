---
id: 0002
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674453+00:00
status: active
---

# Testing — Mocking, Serialization, and File Verification

Always patch functions at their definition site (e.g., `hindsight.retain_safe`), not import site. Deferred imports break module-level mocks. Never attach methods dynamically to mock objects; use unittest.mock.patch() at definition site to validate actual function signatures and catch keyword argument typos.

Files referenced in issues may not exist (e.g., shared_prompt_prefix.py). Always verify file existence before planning changes using git history and grep.

For serialization testing, validate both model_dump_json()→model_validate_json() (serialization fidelity) and save/load cycles (full integration). JSON tests catch serialization bugs; integration tests catch type coercion and persistence issues.

Use explicit assertions on structured markers rather than narrative content to ensure test stability across agent output format changes. ID generation must have test coverage verifying consistency across lookups—ensure plans_dir keys and filename extractions use the same ID logic. Join factory metrics by issue_number, not pr_number.

When removing test imports/files referencing deleted code, run tests to surface incomplete cleanup. Always run `make test` and `make quality-lite` before declaring work complete—test failures naturally surface incomplete cleanup and hidden dependencies.

See also: Code Quality — type-checking applies to validators and imports; ID Generation — ID extraction and generation must be consistent; Infrastructure — parser assertions validate against realistic multi-paragraph output.
