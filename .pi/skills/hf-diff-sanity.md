# Diff Sanity Check

Review the current branch diff for common implementation mistakes. Read-only — do not modify files.

## Steps

1. Run `git diff origin/main...HEAD` to get the branch diff.
2. Check for:
   - Accidental deletions of unrelated code
   - Leftover debug code (print, console.log, breakpoint, commented-out code)
   - Missing or stale imports
   - Scope creep (unrelated files changed)
   - Hardcoded secrets or credentials
   - Broken string literals
   - Obvious logic errors (inverted conditions, off-by-one, unreachable code)
3. Report findings with file path and line references.

## Output

All clear:
```
DIFF_SANITY_RESULT: OK
SUMMARY: No issues found
```

Problems found:
```
DIFF_SANITY_RESULT: RETRY
SUMMARY: <problem categories>
FINDINGS:
- <file:line — description>
```
