# Cooperative Integration Model

**Date:** 2026-03-25
**Status:** Draft
**Beads:** ops-audit-fixes-e5e, ops-audit-fixes-kq3, ops-audit-fixes-2am, ops-audit-fixes-tli, ops-audit-fixes-nn8, ops-audit-fixes-4v9

## Problem

HydraFlow assumes ownership of the target repo's tooling directories. When integrating into repos with existing `.claude/`, `.codex/`, `.pi/`, `.githooks/` configurations, `make setup` destroys them. The repo sanitizer force-switches the developer's branch. Config only works via Makefile-sourced env vars. Tracking issues are created without consent. This blocks adoption in established repos.

## Goal

Make HydraFlow a cooperative guest: it merges its assets alongside existing ones, never touches the primary checkout's branch, loads config consistently, and creates no GitHub side effects unless opted in.

---

## 1. Namespace-Aware Asset Merge

**Bead:** ops-audit-fixes-e5e (P0)
**Files:** `Makefile` (lines 298-322), new `scripts/merge_assets.py`

### Current Behavior

```makefile
rm -rf "$(TARGET_REPO_ROOT)/$$ASSET"
cp -R "$(PROJECT_ROOT)/$$ASSET" "$(TARGET_REPO_ROOT)/$$ASSET"
```

Wholesale replacement of `.claude/`, `.codex/`, `.pi/`, `.githooks/`.

### New Behavior

Replace the `rm -rf` + `cp -R` loop with a Python merge script (`scripts/merge_assets.py`) that:

1. Reads the existing asset manifest at `TARGET_REPO_ROOT/.hydraflow/assets.json` (if present).
2. Removes only files listed in the previous manifest (HydraFlow's own files from last install).
3. Copies new HydraFlow files into the target directories.
4. Writes an updated manifest listing every file HydraFlow installed.

### Merge Script: `scripts/merge_assets.py`

**Input:** `--source PROJECT_ROOT --target TARGET_REPO_ROOT`
**Output:** Updated `TARGET_REPO_ROOT/.hydraflow/assets.json`

```python
"""Merge HydraFlow assets into a target repo without destroying existing files."""

def merge_assets(source: Path, target: Path) -> None:
    manifest_path = target / ".hydraflow" / "assets.json"
    old_manifest = load_manifest(manifest_path)  # {"files": [...]}

    # Remove previously-installed HydraFlow files
    for rel_path in old_manifest.get("files", []):
        full = target / rel_path
        if full.is_file():
            full.unlink()

    # Copy new HydraFlow files (only hf.* namespaced files + settings merge)
    new_files = []
    for asset_dir in [".claude", ".codex", ".pi"]:
        new_files += copy_namespaced_files(source / asset_dir, target / asset_dir)

    # Handle .githooks separately (chaining)
    new_files += chain_hooks(source / ".githooks", target / ".githooks")

    # Deep-merge settings.json
    merge_settings(source / ".claude" / "settings.json",
                   target / ".claude" / "settings.json")
    new_files.append(".claude/settings.json")  # track as managed

    # Deep-merge settings.local.json
    merge_settings(source / ".claude" / "settings.local.json",
                   target / ".claude" / "settings.local.json")
    new_files.append(".claude/settings.local.json")

    # Write updated manifest
    save_manifest(manifest_path, new_files)
```

### Copy Rules by Directory

| Source Path | Target Path | Rule |
|---|---|---|
| `.claude/commands/hf.*.md` | `.claude/commands/hf.*.md` | Copy. User commands untouched. |
| `.claude/hooks/hf.*.sh` | `.claude/hooks/hf.*.sh` | Copy. User hooks untouched. |
| `.claude/agents/hf.*.md` | `.claude/agents/hf.*.md` | Copy. User agents untouched. |
| `.claude/settings.json` | `.claude/settings.json` | Deep-merge (see below). |
| `.claude/settings.local.json` | `.claude/settings.local.json` | Deep-merge (see below). |
| `.codex/skills/hf.*/` | `.codex/skills/hf.*/` | Copy dirs. User skills untouched. |
| `.pi/skills/hf-*.md` | `.pi/skills/hf-*.md` | Copy. User skills untouched. |
| `.githooks/pre-commit` | `.githooks/hf-pre-commit` | Rename + chain (see below). |
| `.githooks/pre-push` | `.githooks/hf-pre-push` | Rename + chain (see below). |

### `settings.json` Deep-Merge

Structure:
```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "...", "hooks": [...]}],
    "PostToolUse": [...],
    "Stop": [...]
  },
  "permissions": {"allow": [...], "deny": [...]}
}
```

Merge strategy:
- For each hook category (`PreToolUse`, `PostToolUse`, `Stop`): append HydraFlow entries that don't already exist. Match by the hook command path (e.g., `.claude/hooks/hf.block-destructive-git.sh`).
- For `permissions.allow` / `permissions.deny`: append HydraFlow patterns not already present.
- Preserve all existing user entries unchanged.
- Tag injected entries with a `"_hydraflow": true` key for future identification and cleanup.

### Hook Chaining for `.githooks/`

HydraFlow's hooks install as `hf-pre-commit` and `hf-pre-push` (renamed).

**If no existing hook:** Create `pre-commit` that calls `hf-pre-commit`.

**If existing hook:** Append a dispatcher block to the end of the existing file:

```bash
# --- HydraFlow hook chain (do not edit) ---
if [ -x "$(dirname "$0")/hf-pre-commit" ]; then
  "$(dirname "$0")/hf-pre-commit" || exit $?
fi
# --- End HydraFlow hook chain ---
```

Bounded by markers so `make clean-assets` can remove them.

### Cleanup: `make clean-assets`

New Makefile target that:
1. Reads `.hydraflow/assets.json`.
2. Removes all listed files.
3. Removes HydraFlow entries from `settings.json` (entries with `"_hydraflow": true`).
4. Removes hook chain blocks from `.githooks/pre-commit` and `.githooks/pre-push`.
5. Deletes `.hydraflow/assets.json`.

### Makefile Changes

Replace the asset loop (lines 298-305) with:

```makefile
@echo "$(BLUE)Merging agent assets into target repo...$(RESET)"
@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/merge_assets.py \
    --source "$(PROJECT_ROOT)" --target "$(TARGET_REPO_ROOT)"
```

Replace the hook copy block (lines 306-322) with the merge script's hook chaining (handled inside `merge_assets.py`).

---

## 2. Consistent `.env` Loading

**Bead:** ops-audit-fixes-kq3 (P1)
**Files:** `pyproject.toml`, `src/server.py`, `scripts/run_admin_task.py`

### Change

Add `python-dotenv` dependency. Call `load_dotenv()` before config resolution.

### `pyproject.toml`

Add to `[project.dependencies]`:
```toml
"python-dotenv>=1.0",
```

### `src/server.py` (in `main()`, before `load_runtime_config()`)

```python
from dotenv import load_dotenv
load_dotenv()  # loads repo-root .env into os.environ
```

### `scripts/run_admin_task.py` (at top of `main()`)

```python
from dotenv import load_dotenv
load_dotenv()
```

### Behavior

All 150+ `HYDRAFLOW_*` config keys in `.env` now work regardless of entry point (Makefile, direct Python, admin scripts). The existing `_dotenv_lookup` fallback for GH token and git identity stays as-is for backward compatibility.

---

## 3. Conditional Docker Prerequisite

**Bead:** ops-audit-fixes-2am (P1)
**Files:** `Makefile`

### Change

Gate `docker-ensure` on execution mode:

```makefile
EXECUTION_MODE ?= $(shell echo $${HYDRAFLOW_EXECUTION_MODE:-host})

ifeq ($(EXECUTION_MODE),docker)
run: check-node-ui docker-ensure
else
run: check-node-ui
endif
```

The rest of the `run` target body stays identical. Host mode skips the Docker image inspect/pull/build entirely.

---

## 4. Sanitizer Scope Reduction

**Bead:** ops-audit-fixes-tli (P0)
**Files:** `src/workspace.py` (lines 189-278)

### Current Behavior

`sanitize_repo()` on the primary checkout:
1. `git fetch origin {main_branch}`
2. `git checkout -f {main_branch}` if HEAD is on a different branch
3. `git reset --hard origin/{main_branch}`
4. Delete orphan `agent/*` branches

Steps 2-3 destroy uncommitted work and hijack the developer's branch.

### New Behavior

Remove steps 2 and 3. Keep steps 1 and 4.

```python
async def sanitize_repo(self) -> None:
    """Fetch latest refs and clean up stale agent branches.

    The primary checkout's branch and working tree belong to the
    developer.  HydraFlow operates exclusively in worktrees and
    never force-switches the primary checkout.
    """
    # Fetch latest main for worktree creation
    await self._fetch_main()

    # Clean up orphan agent/* branches (HydraFlow's own branches)
    await self._delete_orphan_agent_branches()
```

The force-checkout block (lines 202-239) and hard-reset block (lines 241-250) are deleted entirely.

### Why This Is Safe

HydraFlow creates isolated workspaces via `git clone --local` in `workspace.py:create()`. The workspace gets its own branch from `origin/{main_branch}`. The primary checkout's state is irrelevant to agent execution.

---

## 5. Opt-In GitHub Issue Creation

**Bead:** ops-audit-fixes-nn8 (P1)
**Files:** `src/config.py`, `src/manifest_issue_syncer.py`, `src/metrics_manager.py`

### Config Fields

```python
manifest_issue_enabled: bool = Field(
    default=False,
    description="Create a GitHub issue to persist manifest snapshots",
)
metrics_issue_enabled: bool = Field(
    default=False,
    description="Create a GitHub issue to persist metrics snapshots",
)
```

Add to `_ENV_BOOL_OVERRIDES`:
```python
("manifest_issue_enabled", "HYDRAFLOW_MANIFEST_ISSUE_ENABLED", False),
("metrics_issue_enabled", "HYDRAFLOW_METRICS_ISSUE_ENABLED", False),
```

### Guards

**`manifest_issue_syncer.py:sync()`** — add at top:
```python
if not self._config.manifest_issue_enabled:
    return
```

**`metrics_manager.py:sync()`** — add at top:
```python
if not self._config.metrics_issue_enabled:
    return
```

Local file storage (`.hydraflow/metrics/`, `.hydraflow/manifest/`) continues unconditionally. Only the GitHub issue creation is gated.

Label creation via `ensure_labels()` is unchanged — pipeline labels are required for HydraFlow to function.

---

## 6. Submodule Auto-Registration and Documentation

**Bead:** ops-audit-fixes-4v9 (P1)
**Files:** `src/server.py`, `README.md`

### Auto-Registration

In `server.py:_run_with_dashboard()`, after restoring persisted repos:

```python
# Auto-register parent repo when running as a git submodule
hydraflow_root = Path(__file__).resolve().parent.parent
parent_repo = hydraflow_root.parent
if (parent_repo / ".git").exists() and (hydraflow_root / ".git").is_file():
    # .git is a file (not dir) = submodule layout
    slug = await _detect_slug(parent_repo)
    if slug and not registry.get(slug):
        await _register_repo(parent_repo, slug)
        logger.info("Auto-registered parent repo %s (submodule detected)", slug)
```

Detection criteria:
- `hydraflow_root / ".git"` is a **file** (submodule marker), not a directory.
- `parent_repo / ".git"` exists (parent is a git repo).
- Parent isn't already registered.

### README Addition

Add after the existing Quick Start section:

```markdown
### Dashboard Mode (multi-repo)

Set `HYDRAFLOW_DASHBOARD_ENABLED=true` in `.env`, then:

    make run

The dashboard opens at http://localhost:5556. When running as a git
submodule, the parent repo is auto-registered on startup.

To manually register additional repos:

    curl -X POST "http://localhost:5556/api/repos/add?path=/path/to/repo"
    curl -X POST "http://localhost:5556/api/runtimes/{slug}/start"
```

---

## Implementation Order

| Step | Bead | Risk | Dependencies |
|------|------|------|-------------|
| 1 | ops-audit-fixes-tli — Sanitizer scope | Low (deletion only) | None |
| 2 | ops-audit-fixes-2am — Docker gate | Low (3 Makefile lines) | None |
| 3 | ops-audit-fixes-kq3 — .env loading | Low (additive) | None |
| 4 | ops-audit-fixes-nn8 — Opt-in issues | Low (guard additions) | None |
| 5 | ops-audit-fixes-4v9 — Auto-registration | Low (additive) | None |
| 6 | ops-audit-fixes-e5e — Asset merge | Medium (largest change) | None, but test last |

Steps 1-5 are independent and can be parallelized. Step 6 is the largest and should be implemented and tested last.

## Testing Strategy

- **Asset merge:** Unit tests for `merge_assets.py` — merge into empty dir, merge alongside existing files, cleanup, settings deep-merge, hook chaining with existing hooks, idempotency (running setup twice produces same result).
- **`.env` loading:** Integration test that sets `HYDRAFLOW_MAIN_BRANCH=staging` in `.env` and verifies config resolution.
- **Docker gate:** Manual — `HYDRAFLOW_EXECUTION_MODE=host make run` should not invoke Docker.
- **Sanitizer:** Existing workspace tests + new test confirming primary checkout branch is never switched.
- **Opt-in issues:** Unit tests for manifest and metrics syncers confirming early return when disabled.
- **Auto-registration:** Unit test mocking submodule detection.
