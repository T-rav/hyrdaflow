# Quality Gates

**Always run lint and tests before declaring work complete or committing.** Do not present implementation as "done" until quality checks pass.

## Sequence before committing

1. After each significant code change: `make lint` (auto-fixes formatting and imports)
2. Before committing: `make quality` (lint + typecheck + security + tests + layer-check in parallel)
3. If lint auto-fixes files, re-check for type errors introduced by removed imports
4. Track your edits across files — avoid creating duplicate helpers or inconsistent naming when refactoring multiple test files
5. Merge consecutive identical if-conditions so the shared guard is evaluated once. When you see redundant chains like `if A and B: ... elif A and not B: ...`, restructure them as `if A: if B: ... else: ...` to keep the shared condition centralized and avoid logic drift.

The `/hf.quality-gate` slash command runs a structured quality check sequence. Use it before presenting work as complete.

## Quick validation loop

```bash
# After small changes
make lint && make test

# Before committing
make quality
```

## Code review before merge

**After creating a PR, always self-review it for gaps, bugs, and test coverage before declaring it done.** Use `/superpowers:requesting-code-review` to run a structured review that checks:

- **Gaps** — Missing edge cases, unhandled error paths, callers not updated for API changes
- **Bugs** — Logic errors, off-by-one, race conditions, injection risks
- **Test coverage** — Missing boundary tests, untested code paths, missing negative cases

Do not present a PR as ready until the review passes and any findings are addressed.

## Reasoning triggers

For analysis-heavy tasks (architecture decisions, debugging, code review), use explicit reasoning prompts to trigger deeper analysis:

- "Think through the tradeoffs of this approach before implementing"
- "Consider what could go wrong and what edge cases exist"
- "Explain your reasoning before making changes"

Simple mechanical tasks (rename, format, move) don't need these — just do them.

## Related

- [`testing.md`](testing.md) — test requirements
- [`avoided-patterns.md`](avoided-patterns.md) — mistakes that commonly slip through quality gates
- [`commands.md`](commands.md) — full `make` target reference
