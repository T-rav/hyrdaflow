---
id: 0011
topic: gotchas
source_issue: 7644
source_phase: review
created_at: 2026-05-07T07:44:17.831282+00:00
status: active
corroborations: 1
---

# Verify implementation files are modified before merging a feature PR

A PR that closes an issue must touch the implementation file, not only docs and tests. Before merging, confirm with `git diff --name-only origin/main` that the target source file appears in the diff.

- PR closes #7644 but `src/makefile_scaffold.py` shows 0 changes
- Only docs and tests were committed; `merge_makefile()` remained 146 lines untouched

**Why:** Tests can pass against stubs or old code; a green CI with no implementation change ships dead-end work.
