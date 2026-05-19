---
source: feedback_ruff_strips_unused_imports_during_tdd.md
name: ruff strips unused imports during TDD cycles
description: HydraFlow's post-tool-use formatter hook runs ruff, which removes imports
  that aren't yet referenced — breaks the standard "add import, write failing test,
  add impl" sequence
status: issue-open
issue: 39
promoted_in: null
wontfix_reason: null
created: '2026-04-21'
---

HydraFlow's pre-commit/post-edit hook runs `ruff --fix` which removes unused imports. During a TDD cycle this creates a race: if you add `from mymodule import new_symbol` before the test body that references it (or before the impl that defines it), ruff strips the import the moment the file is saved, and the subsequent write fails with `NameError: name 'new_symbol' is not defined`.

**Why:** Ripped into this repeatedly during sub-project 1 of the prompt audit (PR #8376). Spent several cycles fighting the formatter before spotting the pattern.

**How to apply:**

1. **In impl files**: write the implementation block BEFORE touching the imports at the top. Then add the needed import at the top once the symbol exists and is referenced.
2. **In test files**: write the test function body (which uses the new symbol) BEFORE adding the new symbol to the `from X import (...)` block at the top. If you add the import first, ruff strips it during save.
3. **Alternative for test files**: do the import inside the test function (not at module level). Ruff doesn't strip locally-scoped imports.
4. **When you see "name X is not defined" after a save**: first check whether ruff stripped the import rather than debugging the code.

This isn't a code bug — it's the interaction between TDD's "failing test first" discipline and auto-fixing linters. The fix is ordering, not configuration.
