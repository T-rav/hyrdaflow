---
id: 0094
topic: architecture
source_issue: 6348
source_phase: plan
created_at: 2026-04-10T06:49:24.638890+00:00
status: active
---

# Thin public wrappers replace private method access

When internal callers (e.g., `stale_issue_loop`, `sentry_loop`) access private methods on a façaded class (`_run_gh`, `_repo`), add thin public wrapper methods on the appropriate sub-client rather than exposing infrastructure. Example: add `list_open_issues_raw()` to `IssueClient` for `stale_issue_loop` to call instead of `_run_gh`. This maintains encapsulation boundaries while serving legitimate internal dependencies.
