# Quality Gate

Run a comprehensive quality check before declaring work complete or committing. This catches lint errors, type issues, and test failures BEFORE they accumulate.

## When to Use

- After finishing implementation, before committing
- Anytime you want to verify the codebase is clean
- Before presenting work as "done" to the user

## Instructions

Run these checks **sequentially** (each depends on the prior passing):

### Step 1: Lint (auto-fix)

```bash
make lint
```

If ruff fixes anything, report which files were modified. Re-stage those files if they were already staged.

### Step 2: Type Check

```bash
make typecheck
```

If pyright reports errors, fix them immediately. Common issues:
- Missing imports after ruff auto-removed unused ones
- Type narrowing needed after refactoring
- New function missing return type annotation

### Step 3: Security Scan

```bash
make security
```

Fix any Medium+ findings from bandit.

### Step 4: Tests

```bash
make test-fast
```

If tests fail:
1. Read the failure output carefully
2. Determine if it's a test bug or implementation bug
3. Fix the root cause (not the symptom)
4. Re-run only the failing test file to verify the fix
5. Run the full suite again

### Step 5: Report

Produce a summary:

```
QUALITY GATE: PASS/FAIL
- Lint: ✓/✗ (N files auto-fixed)
- Types: ✓/✗ (N errors)
- Security: ✓/✗ (N findings)
- Tests: ✓/✗ (N passed, N failed)
```

If any step fails and you cannot auto-fix it, stop and report the issue clearly.

## Important

- Do NOT skip steps or declare early success
- Do NOT use `--no-verify` to work around failures
- If lint auto-fixes create type errors, fix the type errors too
- This is the minimum bar — run `make quality` for the full parallel check
