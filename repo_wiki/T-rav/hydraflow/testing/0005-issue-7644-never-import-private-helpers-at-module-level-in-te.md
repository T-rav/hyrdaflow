---
id: 0005
topic: testing
source_issue: 7644
source_phase: review
created_at: 2026-05-07T07:44:17.831320+00:00
status: active
corroborations: 1
---

# Never import private helpers at module level in test files

Import private or internal functions (`_foo`) inside the test function or a `pytest.fixture`, never at the top of the test module.

```python
# bad — kills entire file if symbol doesn't exist
from src.makefile_scaffold import _check_prereq_deps, _diff_targets

# good — failure is scoped to the test that needs it
def test_check_prereq():
    from src.makefile_scaffold import _check_prereq_deps
    ...
```

**Why:** A module-level `ImportError` prevents pytest from collecting the file, silently destroying all pre-existing passing tests in that module.
