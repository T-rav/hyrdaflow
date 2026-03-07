# Test Adequacy Check

Assess whether changed production code has adequate test coverage. This is a read-only assessment — it does not modify files.

## When to Use

- After implementing changes, before committing
- To verify test coverage fills gaps left by removed TDD enforcement
- When reviewing a branch for test completeness

## Instructions

1. Get the diff of changes on the current branch:
   ```bash
   git diff origin/main...HEAD
   ```
   If that's empty, fall back to `git diff` (unstaged) or `git diff --cached` (staged).

2. Identify all changed or added production files (exclude test files).

3. For each changed production function/method/class, verify:

   - **Has a corresponding test** — at least one test exercises the new/changed code path
   - **Edge cases covered** — empty inputs, None values, boundary conditions, error paths
   - **Regression safety** — if existing behavior changed, tests verify the new behavior
   - **No test-only gaps** — new test utilities or fixtures are themselves tested if non-trivial

4. Produce structured output:

If coverage is adequate:
```
TEST_ADEQUACY_RESULT: OK
SUMMARY: All changed code has adequate test coverage
```

If gaps exist:
```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: <comma-separated list of gap categories>
GAPS:
- <production_file:function — what test is missing>
```

## Important

- Do NOT modify any files. This is a read-only assessment.
- Focus on whether production code is tested, not test code style.
- Ignore test file changes when assessing adequacy.
- Be pragmatic: simple getters/setters don't need dedicated tests. Focus on logic, branches, and error paths.
