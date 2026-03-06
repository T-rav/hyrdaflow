# ADR-0011: Epic Release Creation Architecture

**Status:** Accepted
**Date:** 2026-03-01

## Context

HydraFlow needed a mechanism to automatically create GitHub Releases when an epic
completes (all child issues resolved). Several integration points were candidates:

- **`PostMergeHandler`** — runs after each PR merge. Knows which issue just closed
  but has no visibility into the parent epic's completion state.
- **`EpicCompletionChecker`** — already checks whether all sub-issues are resolved
  and closes the epic. Has full context: epic title, sub-issue list, and completion
  status.
- **`EpicManager._try_auto_close()`** — the top-level entry point that fires when
  any child completes (`on_child_completed()`). Delegates to
  `EpicCompletionChecker` for the actual close-and-release workflow.

The release feature must extract a version from the epic title, create a git tag,
create a GitHub Release with a changelog, and persist release state for
crash-recovery and dashboard reporting.

## Decision

Hook release creation into the **`EpicCompletionChecker._try_close_epic()`** path,
invoked from **`EpicManager._try_auto_close()`**. Do **not** place release logic in
`PostMergeHandler` or any other per-PR handler.

The call chain is:

```
PostMergeHandler.handle_approved()
  └─ EpicManager.on_child_completed(epic, child)
       └─ EpicManager._try_auto_close(epic)
            └─ EpicCompletionChecker.check_and_close_epics(child)
                 └─ _try_close_epic(epic, title, body, sub_issues)
                      ├─ _create_release_for_epic()
                      │    ├─ extract_version_from_title(epic_title)
                      │    ├─ PRManager.create_tag(tag)
                      │    ├─ PRManager.create_release(tag, title, changelog)
                      │    └─ StateTracker.upsert_release(release)
                      ├─ post close comment (with release URL if created)
                      └─ close_issue(epic)
```

Key implementation details:

1. **Tag and release are separate operations.** `PRManager.create_tag()` creates
   and pushes a git tag; `PRManager.create_release()` creates the GitHub Release
   referencing that tag. This two-step approach allows partial-failure handling
   (tag created but release failed).

2. **Version extraction from epic title.** The `extract_version_from_title()`
   utility parses a semver-like version from the epic's title. If no version is
   found, release creation is silently skipped. The `release_version_source` config
   field exists for future alternative sources but currently only `epic_title` is
   implemented.

3. **Release state persisted in `StateData.releases`.** The `Release` model is
   stored in a `dict[str, Release]` keyed by epic number (as string). This
   enables crash-recovery (re-check release existence before retrying) and
   dashboard reporting.

4. **Gated by `config.release_on_epic_close`.** The feature is opt-in; when
   disabled, the epic closes normally without any tag/release side-effects.

5. **Dry-run support.** Both `create_tag()` and `create_release()` in `PRManager`
   respect the global `dry_run` flag, logging intent without executing.

## Consequences

**Positive:**
- Release creation fires exactly once, at the moment all sub-issues are confirmed
  complete — no risk of premature releases from partial merges.
- `PostMergeHandler` remains focused on single-PR lifecycle; epic-level concerns
  stay in the epic subsystem.
- State persistence enables idempotent retries and dashboard visibility.
- The two-step tag/release flow allows fine-grained error handling and logging.

**Trade-offs:**
- Release creation depends on version being parseable from the epic title; epics
  without a version string produce no release (by design, but could surprise users).
- If `EpicCompletionChecker` fails, the fallback direct-close path in
  `_try_auto_close()` does **not** attempt release creation — only the primary
  path creates releases.
- Two separate `gh` calls (tag + release) instead of a single atomic operation
  means a tag could exist without a corresponding release on transient failure.

## Alternatives considered

1. **Hook into `PostMergeHandler` directly.**
   Rejected: would require each merge handler to track epic-level state and detect
   "last child" completion — duplicating logic already in `EpicCompletionChecker`.

2. **Use `gh release create --target main` for atomic tag+release.**
   Not adopted: keeping tag creation separate (`git tag` + `git push`) gives
   explicit control over the tag ref and clearer error attribution. The `gh release
   create` command can still reference an existing tag.

3. **Dedicated `ReleaseManager` service.**
   Not adopted at this stage: the release logic is compact enough to live in
   `EpicCompletionChecker`. A separate service can be extracted if release
   workflows grow more complex (e.g., artifact uploads, multi-repo coordination).

## Related

- Source memory: Issue #1682 — *[Memory] Epic release creation architecture*
- `src/epic.py` — `EpicManager._try_auto_close()`, `EpicCompletionChecker._create_release_for_epic()`
- `src/pr_manager.py` — `PRManager.create_tag()`, `PRManager.create_release()`
- `src/models.py` — `Release` model, `StateData.releases`
- PR #1690 — *feat: create GitHub Release with changelog when epic closes*
