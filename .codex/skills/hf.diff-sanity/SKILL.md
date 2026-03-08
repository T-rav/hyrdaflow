---
name: hf.diff-sanity
description: "Review branch diff for accidental deletions, debug code, missing imports, scope creep, and logic errors."
---

# Diff Sanity Check

Review the current branch diff for common implementation mistakes before committing. This is a read-only check — it does not modify files.

## When to Use

- After implementing changes, before committing
- As a pre-review sanity pass
- When you want a quick check for accidental mistakes

## Instructions

1. Get the diff of changes on the current branch:
   ```bash
   git diff origin/main...HEAD
   ```
   If that's empty, fall back to `git diff` (unstaged) or `git diff --cached` (staged).

2. Review the diff for these problems:

   - **Accidental deletions** — unrelated code removed that should not have been
   - **Leftover debug code** — `print()`, `console.log()`, `debugger`, `breakpoint()`, commented-out code
   - **Missing imports** — new symbols referenced but not imported; removed code with stale imports
   - **Scope creep** — files changed that are unrelated to the issue
   - **Hardcoded secrets or credentials** — API keys, tokens, passwords in the diff
   - **Broken string literals** — unclosed quotes, malformed f-strings
   - **Obvious logic errors** — inverted conditions, off-by-one, unreachable code after return

3. For each problem found, note the file path, line, and description.

4. Produce structured output:

If all checks pass:
```
DIFF_SANITY_RESULT: OK
SUMMARY: No issues found
```

If problems are found:
```
DIFF_SANITY_RESULT: RETRY
SUMMARY: <comma-separated list of problem categories found>
FINDINGS:
- <file:line — description>
```

## Important

- Do NOT modify any files. This is a read-only review.
- Focus on objective mistakes, not style preferences.
- If the diff is too large (>15,000 chars), summarize by file and focus on the riskiest changes.
