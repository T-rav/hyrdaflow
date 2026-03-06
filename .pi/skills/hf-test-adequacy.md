# Test Adequacy Check

Assess whether changed production code has adequate test coverage. Read-only — do not modify files.

## Steps

1. Run `git diff origin/main...HEAD` to get the branch diff.
2. Identify changed production files (exclude test files).
3. For each changed function/method/class, verify:
   - At least one test exercises the new/changed path
   - Edge cases covered (empty inputs, None, boundary conditions, error paths)
   - Regression safety (changed behavior has updated tests)
4. Report gaps with production file:function and what test is missing.

## Output

Adequate coverage:
```
TEST_ADEQUACY_RESULT: OK
SUMMARY: All changed code has adequate test coverage
```

Gaps found:
```
TEST_ADEQUACY_RESULT: RETRY
SUMMARY: <gap categories>
GAPS:
- <production_file:function — what test is missing>
```
