# Cooperative Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make HydraFlow a cooperative guest — merge assets alongside existing ones, never touch the primary checkout's branch, load config consistently, and create no GitHub side effects unless opted in.

**Architecture:** Six independent changes addressing seven integration issues. Tasks 1-5 are small, surgical edits. Task 6 is a new Python script replacing the destructive Makefile asset loop. Each task produces a working, testable commit.

**Tech Stack:** Python 3.11, Pydantic, Makefile, bash hooks, python-dotenv, pytest

**Spec:** `docs/superpowers/specs/2026-03-25-cooperative-integration-design.md`

**Beads:** ops-audit-fixes-tli, ops-audit-fixes-2am, ops-audit-fixes-kq3, ops-audit-fixes-nn8, ops-audit-fixes-4v9, ops-audit-fixes-e5e

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `src/workspace.py` | Modify (lines 189-278) | Remove force-checkout/reset from sanitize_repo |
| `tests/test_workspace_docker.py` | Modify (lines 557-620) | Update sanitizer tests |
| `Makefile` | Modify (lines 96-108, 298-322) | Conditional Docker, replace asset loop |
| `pyproject.toml` | Modify (line 16) | Add python-dotenv dependency |
| `src/server.py` | Modify (line 165) | Load .env at startup |
| `scripts/run_admin_task.py` | Modify (line 37) | Load .env for admin tasks |
| `src/config.py` | Modify (lines 144-173, ~970) | Add opt-in issue fields |
| `src/manifest_issue_syncer.py` | Modify (line 35) | Add opt-in guard |
| `src/metrics_manager.py` | Modify (line 65) | Add opt-in guard |
| `tests/test_config_env.py` | Verify (parametrized) | Auto-covers new bool overrides |
| `tests/test_manifest_issue_syncer.py` | Modify | Add disabled-guard test |
| `tests/test_metrics_manager.py` | Modify | Add disabled-guard test |
| `src/server.py` | Modify (line 61) | Add submodule auto-registration |
| `README.md` | Modify (after line 70) | Document dashboard startup |
| `scripts/merge_assets.py` | Create | Namespace-aware asset merge script |
| `tests/test_merge_assets.py` | Create | Tests for merge script |

---

### Task 1: Remove Force-Checkout from Sanitizer

**Bead:** ops-audit-fixes-tli (P0)
**Files:**
- Modify: `src/workspace.py:189-278`
- Modify: `tests/test_workspace_docker.py:557-620`

- [ ] **Step 1: Read the existing sanitizer tests**

Read `tests/test_workspace_docker.py` class `TestSanitizeRepo` to understand current test expectations.

- [ ] **Step 2: Update tests to match new behavior**

The sanitizer should no longer force-checkout or hard-reset. Update the existing tests:

```python
class TestSanitizeRepo:
    """Tests for WorkspaceManager.sanitize_repo."""

    @pytest.mark.asyncio
    async def test_sanitize_fetches_main_and_prunes_branches(self, config) -> None:
        manager = WorkspaceManager(config)

        commands_run: list[str] = []

        async def _fake_run(*args: str, **kw: object) -> str:
            cmd = " ".join(args)
            commands_run.append(cmd)
            if "branch --list" in cmd:
                return "  agent/issue-1\n  agent/issue-2\n"
            return ""

        with patch("workspace.run_subprocess", side_effect=_fake_run):
            await manager.sanitize_repo()

        # Should fetch origin
        assert any("fetch" in c for c in commands_run)
        # Should list agent branches
        assert any("branch --list agent/*" in c for c in commands_run)
        # Should delete orphan branches
        assert any("branch -D agent/issue-1" in c for c in commands_run)
        assert any("branch -D agent/issue-2" in c for c in commands_run)
        # Should NOT checkout or reset
        assert not any("checkout" in c for c in commands_run)
        assert not any("reset" in c for c in commands_run)

    @pytest.mark.asyncio
    async def test_sanitize_never_touches_primary_checkout_branch(self, config) -> None:
        """sanitize_repo must never switch the primary checkout's branch."""
        manager = WorkspaceManager(config)

        async def _fake_run(*args: str, **kw: object) -> str:
            cmd = " ".join(args)
            if "checkout" in cmd or "reset" in cmd:
                raise AssertionError(f"Sanitizer must not run: {cmd}")
            if "branch --list" in cmd:
                return ""
            return ""

        with patch("workspace.run_subprocess", side_effect=_fake_run):
            await manager.sanitize_repo()  # should not raise
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_workspace_docker.py::TestSanitizeRepo -v`
Expected: FAIL — current code still does checkout/reset.

- [ ] **Step 4: Modify sanitize_repo**

In `src/workspace.py`, replace lines 189-278 with:

```python
async def sanitize_repo(self) -> None:
    """Fetch latest refs and clean up stale agent branches.

    The primary checkout's branch and working tree belong to the
    developer.  HydraFlow operates exclusively in worktrees and
    never force-switches the primary checkout.
    """
    repo = self._repo_root
    main = self._config.main_branch
    gh = self._config.gh_token

    # Fetch latest main for worktree creation
    await self._fetch_origin_with_retry(repo, main)

    # Delete orphan agent/* branches (HydraFlow's own branches)
    try:
        branches_output = await run_subprocess(
            "git",
            "branch",
            "--list",
            "agent/*",
            cwd=repo,
            gh_token=gh,
        )
        for line in branches_output.strip().splitlines():
            branch_name = line.strip().lstrip("* ")
            if branch_name:
                with contextlib.suppress(RuntimeError):
                    await run_subprocess(
                        "git",
                        "branch",
                        "-D",
                        branch_name,
                        cwd=repo,
                        gh_token=gh,
                    )
                    logger.info("Pruned orphan branch %s", branch_name)
    except RuntimeError:
        logger.debug("Could not list agent branches for cleanup", exc_info=True)

    logger.info("Repo sanitized — fetched %s, orphan branches pruned", main)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_workspace_docker.py::TestSanitizeRepo -v`
Expected: PASS

- [ ] **Step 6: Run full workspace test suite**

Run: `pytest tests/test_workspace_docker.py -x --tb=short -q`
Expected: All pass

- [ ] **Step 7: Lint and typecheck**

Run: `make lint && python -m pyright src/workspace.py`
Expected: Clean

- [ ] **Step 8: Commit**

```bash
bd update ops-audit-fixes-tli --status done
git add src/workspace.py tests/test_workspace_docker.py
git commit -m "Remove force-checkout and hard-reset from sanitize_repo

The primary checkout belongs to the developer. HydraFlow operates
exclusively in worktrees and never needs to switch the primary
checkout's branch. Keep fetch and orphan branch cleanup."
```

---

### Task 2: Conditional Docker Prerequisite

**Bead:** ops-audit-fixes-2am (P1)
**Files:**
- Modify: `Makefile:96-108`

- [ ] **Step 1: Edit the Makefile**

Add execution mode variable and gate `docker-ensure`:

Before the `docker-ensure` target (around line 96), add:

```makefile
EXECUTION_MODE ?= $(shell echo $${HYDRAFLOW_EXECUTION_MODE:-host})
```

Replace line 101:
```makefile
run: check-node-ui docker-ensure
```

With:
```makefile
ifeq ($(EXECUTION_MODE),docker)
run: check-node-ui docker-ensure
else
run: check-node-ui
endif
```

Keep the `run` target body (lines 102-108) unchanged.

- [ ] **Step 2: Verify syntax**

Run: `make -n run HYDRAFLOW_EXECUTION_MODE=host 2>&1 | head -5`
Expected: No mention of `docker-ensure` or `docker image inspect`.

Run: `make -n run HYDRAFLOW_EXECUTION_MODE=docker 2>&1 | head -5`
Expected: Includes `docker image inspect`.

- [ ] **Step 3: Commit**

```bash
bd update ops-audit-fixes-2am --status done
git add Makefile
git commit -m "Gate docker-ensure on HYDRAFLOW_EXECUTION_MODE

Host mode no longer triggers Docker image inspect/pull/build
when running make run."
```

---

### Task 3: Load .env via python-dotenv

**Bead:** ops-audit-fixes-kq3 (P1)
**Files:**
- Modify: `pyproject.toml:16`
- Modify: `src/server.py:165`
- Modify: `scripts/run_admin_task.py:37`
- Test: `tests/test_server.py` (if exists) or `tests/test_config_env.py`

- [ ] **Step 1: Add python-dotenv dependency**

In `pyproject.toml`, add to the `dependencies` list:

```toml
"python-dotenv>=1.0",
```

- [ ] **Step 2: Install the dependency**

Run: `uv sync`

- [ ] **Step 3: Add load_dotenv to server.py**

In `src/server.py`, modify `main()` (line 165). Add before the `verbose` variable:

```python
def main() -> None:
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    verbose = os.environ.get("HYDRAFLOW_VERBOSE_LOGS", "").strip() not in {
```

- [ ] **Step 4: Add load_dotenv to run_admin_task.py**

In `scripts/run_admin_task.py`, modify `main()` (line 37). Add at the top of the function:

```python
async def main() -> None:
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    if len(sys.argv) < 2 or sys.argv[1] not in _TASKS:
```

- [ ] **Step 5: Write a test**

Add to `tests/test_config_env.py`:

```python
class TestDotenvLoading:
    """Verify .env loading at server startup."""

    def test_dotenv_loads_hydraflow_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """python-dotenv should load HYDRAFLOW_ vars from .env."""
        env_file = tmp_path / ".env"
        env_file.write_text("HYDRAFLOW_MAIN_BRANCH=staging\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("HYDRAFLOW_MAIN_BRANCH", raising=False)

        from dotenv import load_dotenv
        load_dotenv(dotenv_path=env_file)

        assert os.environ.get("HYDRAFLOW_MAIN_BRANCH") == "staging"
```

- [ ] **Step 6: Run test**

Run: `pytest tests/test_config_env.py::TestDotenvLoading -v`
Expected: PASS

- [ ] **Step 7: Lint**

Run: `make lint`

- [ ] **Step 8: Commit**

```bash
bd update ops-audit-fixes-kq3 --status done
git add pyproject.toml src/server.py scripts/run_admin_task.py tests/test_config_env.py uv.lock
git commit -m "Load .env at startup via python-dotenv

All HYDRAFLOW_* config keys in .env now work regardless of entry
point (Makefile, direct Python, admin scripts)."
```

---

### Task 4: Opt-In Manifest and Metrics Issues

**Bead:** ops-audit-fixes-nn8 (P1)
**Files:**
- Modify: `src/config.py:144-173` (bool overrides table), `src/config.py:~970` (field definition)
- Modify: `src/manifest_issue_syncer.py:35`
- Modify: `src/metrics_manager.py:65`
- Modify: `tests/test_manifest_issue_syncer.py`
- Modify: `tests/test_metrics_manager.py`

- [ ] **Step 1: Write failing tests**

In `tests/test_manifest_issue_syncer.py`, add:

```python
class TestManifestIssueOptIn:
    """Manifest issue creation should be opt-in."""

    @pytest.mark.asyncio
    async def test_sync_returns_early_when_disabled(self, tmp_path: Path) -> None:
        """sync() should do nothing when manifest_issue_enabled is False."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            manifest_issue_enabled=False,
        )
        # Build a syncer with mock deps
        from manifest_issue_syncer import ManifestIssueSyncer
        state = MagicMock()
        prs = MagicMock()
        syncer = ManifestIssueSyncer(config, state, prs)

        await syncer.sync("# Manifest", "abc123")

        # Should not call any PR methods
        prs.create_issue.assert_not_called()
        prs.post_comment.assert_not_called()
```

In `tests/test_metrics_manager.py`, add:

```python
class TestMetricsIssueOptIn:
    """Metrics issue creation should be opt-in."""

    @pytest.mark.asyncio
    async def test_sync_skips_issue_when_disabled(self, tmp_path: Path) -> None:
        """sync() should only write local cache when metrics_issue_enabled is False."""
        config = ConfigFactory.create(
            repo_root=tmp_path,
            metrics_issue_enabled=False,
        )
        # ... build MetricsManager with mocks, call sync()
        # Assert: _ensure_metrics_issue never called, local cache still written
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_manifest_issue_syncer.py::TestManifestIssueOptIn -v`
Expected: FAIL — field doesn't exist yet.

- [ ] **Step 3: Add config fields**

In `src/config.py`, add the field definitions near the other tracking fields (around line 970):

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

Add to `_ENV_BOOL_OVERRIDES` (after line 172):

```python
("manifest_issue_enabled", "HYDRAFLOW_MANIFEST_ISSUE_ENABLED", False),
("metrics_issue_enabled", "HYDRAFLOW_METRICS_ISSUE_ENABLED", False),
```

- [ ] **Step 4: Add guard to manifest_issue_syncer.py**

In `src/manifest_issue_syncer.py`, at the top of `sync()` (line 42), add before the existing label check:

```python
if not self._config.manifest_issue_enabled:
    return
```

- [ ] **Step 5: Add guard to metrics_manager.py**

In `src/metrics_manager.py`, in `sync()` (line 65), add after the snapshot build but before the hash compare — actually, we want local cache to still work. Add the guard right before `_ensure_metrics_issue()` call (line 96):

```python
if not self._config.metrics_issue_enabled:
    self._state.update_metrics_state(snapshot_hash)
    return {
        "status": "cached_locally",
        "reason": "metrics_issue_disabled",
        "snapshot_hash": snapshot_hash,
        "timestamp": snapshot.timestamp,
    }
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_manifest_issue_syncer.py tests/test_metrics_manager.py tests/test_config_env.py -x --tb=short -q`
Expected: All pass (parametrized env tests auto-cover the new fields).

- [ ] **Step 7: Lint and typecheck**

Run: `make lint && python -m pyright src/config.py src/manifest_issue_syncer.py src/metrics_manager.py`

- [ ] **Step 8: Commit**

```bash
bd update ops-audit-fixes-nn8 --status done
git add src/config.py src/manifest_issue_syncer.py src/metrics_manager.py tests/test_manifest_issue_syncer.py tests/test_metrics_manager.py
git commit -m "Make manifest and metrics GitHub issues opt-in

Default to disabled. Local file storage continues unconditionally.
Set HYDRAFLOW_MANIFEST_ISSUE_ENABLED=true or
HYDRAFLOW_METRICS_ISSUE_ENABLED=true to enable."
```

---

### Task 5: Submodule Auto-Registration and README

**Bead:** ops-audit-fixes-4v9 (P1)
**Files:**
- Modify: `src/server.py:61`
- Modify: `README.md:~70`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test**

Find or create `tests/test_server.py`. Add:

```python
class TestSubmoduleAutoRegistration:
    """Auto-register parent repo when running as a git submodule."""

    @pytest.mark.asyncio
    async def test_detects_submodule_and_registers_parent(self, tmp_path: Path) -> None:
        """When .git is a file (submodule), auto-register parent."""
        # Set up: parent_repo/.git (dir), parent_repo/hydraflow/.git (file)
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".git").mkdir()  # real git repo

        hydraflow = parent / "hydraflow"
        hydraflow.mkdir()
        (hydraflow / ".git").write_text("gitdir: ../.git/modules/hydraflow\n")  # submodule marker

        # detect_submodule_parent should return parent
        from server import _detect_submodule_parent
        result = _detect_submodule_parent(hydraflow)
        assert result == parent
```

- [ ] **Step 2: Extract detection helper in server.py**

In `src/server.py`, add a helper function:

```python
def _detect_submodule_parent(hydraflow_root: Path) -> Path | None:
    """Return the parent repo path if HydraFlow is a git submodule, else None."""
    git_path = hydraflow_root / ".git"
    if not git_path.is_file():
        return None  # .git is a directory — standalone repo, not a submodule
    parent = hydraflow_root.parent
    if (parent / ".git").exists():
        return parent
    return None
```

- [ ] **Step 3: Add auto-registration in _run_with_dashboard**

In `src/server.py`, after the repo restoration loop (after line 61), add:

```python
    # Auto-register parent repo when running as a git submodule
    hydraflow_root = Path(__file__).resolve().parent.parent
    submodule_parent = _detect_submodule_parent(hydraflow_root)
    if submodule_parent is not None:
        try:
            parent_slug = await _detect_remote_slug(submodule_parent)
            if parent_slug and parent_slug not in registry:
                _, _ = await _register_repo(submodule_parent, parent_slug)
                logger.info(
                    "Auto-registered parent repo %s (submodule detected)", parent_slug
                )
        except Exception:
            logger.debug("Submodule auto-registration failed", exc_info=True)
```

Note: `_detect_remote_slug` may need to be extracted from the dashboard routes or written as a small helper that runs `git remote get-url origin`.

- [ ] **Step 4: Add README section**

In `README.md`, after the Quick Start code block (after `make run` line ~70), add:

```markdown
### Dashboard Mode (multi-repo)

Set `HYDRAFLOW_DASHBOARD_ENABLED=true` in `.env`, then:

```bash
make run
```

The dashboard opens at http://localhost:5556. When running as a git
submodule, the parent repo is auto-registered on startup.

To manually register additional repos:

```bash
curl -X POST "http://localhost:5556/api/repos/add?path=/path/to/repo"
curl -X POST "http://localhost:5556/api/runtimes/{slug}/start"
```
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_server.py -x --tb=short -v`
Expected: PASS

- [ ] **Step 6: Lint**

Run: `make lint`

- [ ] **Step 7: Commit**

```bash
bd update ops-audit-fixes-4v9 --status done
git add src/server.py README.md tests/test_server.py
git commit -m "Auto-register parent repo in submodule mode and document dashboard startup"
```

---

### Task 6: Namespace-Aware Asset Merge

**Bead:** ops-audit-fixes-e5e (P0)
**Files:**
- Create: `scripts/merge_assets.py`
- Create: `tests/test_merge_assets.py`
- Modify: `Makefile:298-322`

This is the largest task. Break into sub-steps.

- [ ] **Step 1: Write core merge tests**

Create `tests/test_merge_assets.py`:

```python
"""Tests for the namespace-aware asset merge script."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from merge_assets import (
    chain_hooks,
    clean_assets,
    copy_namespaced_files,
    load_manifest,
    merge_assets,
    merge_settings_file,
    save_manifest,
)


class TestLoadSaveManifest:
    def test_load_returns_empty_when_missing(self, tmp_path: Path) -> None:
        result = load_manifest(tmp_path / "missing.json")
        assert result == {"files": []}

    def test_round_trip(self, tmp_path: Path) -> None:
        path = tmp_path / ".hydraflow" / "assets.json"
        files = [".claude/hooks/hf.block.sh", ".codex/skills/hf.adr/SKILL.md"]
        save_manifest(path, files)
        loaded = load_manifest(path)
        assert loaded["files"] == files


class TestCopyNamespacedFiles:
    def test_copies_only_hf_prefixed_files(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / ".claude" / "commands"
        source.mkdir(parents=True)
        (source / "hf.adr.md").write_text("# ADR")
        (source / "hf.issue.md").write_text("# Issue")
        (source / "user-custom.md").write_text("# User")

        target = tmp_path / "target" / ".claude" / "commands"
        target.mkdir(parents=True)
        (target / "my-command.md").write_text("# Mine")

        copied = copy_namespaced_files(
            source.parent, target.parent, subdir="commands", prefix="hf."
        )

        assert (target / "hf.adr.md").read_text() == "# ADR"
        assert (target / "hf.issue.md").read_text() == "# Issue"
        assert (target / "my-command.md").read_text() == "# Mine"  # untouched
        assert not (target / "user-custom.md").exists()  # not copied
        assert len(copied) == 2

    def test_preserves_existing_user_files(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / ".claude" / "hooks"
        source.mkdir(parents=True)
        (source / "hf.lint.sh").write_text("#!/bin/bash\nlint")

        target = tmp_path / "target" / ".claude" / "hooks"
        target.mkdir(parents=True)
        (target / "my-hook.sh").write_text("#!/bin/bash\nmine")

        copy_namespaced_files(source.parent, target.parent, subdir="hooks", prefix="hf.")

        assert (target / "my-hook.sh").read_text() == "#!/bin/bash\nmine"


class TestChainHooks:
    def test_creates_dispatcher_when_no_existing_hook(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / ".githooks"
        source.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\nlint-check")

        target = tmp_path / "target" / ".githooks"
        target.mkdir(parents=True)

        chain_hooks(source, target)

        assert (target / "hf-pre-commit").exists()
        dispatcher = (target / "pre-commit").read_text()
        assert "hf-pre-commit" in dispatcher

    def test_appends_chain_to_existing_hook(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / ".githooks"
        source.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\nlint-check")

        target = tmp_path / "target" / ".githooks"
        target.mkdir(parents=True)
        (target / "pre-commit").write_text("#!/bin/bash\neslint .\nvitest run\n")

        chain_hooks(source, target)

        content = (target / "pre-commit").read_text()
        assert content.startswith("#!/bin/bash\neslint .")  # original preserved
        assert "hf-pre-commit" in content
        assert "--- HydraFlow hook chain" in content

    def test_idempotent_chain(self, tmp_path: Path) -> None:
        source = tmp_path / "source" / ".githooks"
        source.mkdir(parents=True)
        (source / "pre-commit").write_text("#!/bin/bash\nlint")

        target = tmp_path / "target" / ".githooks"
        target.mkdir(parents=True)
        (target / "pre-commit").write_text("#!/bin/bash\nuser-hook\n")

        chain_hooks(source, target)
        first = (target / "pre-commit").read_text()
        chain_hooks(source, target)
        second = (target / "pre-commit").read_text()
        assert first == second  # no double-append


class TestMergeSettingsFile:
    def test_merges_hooks_into_existing_settings(self, tmp_path: Path) -> None:
        source_settings = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "hf.block.sh", "_hydraflow": True}]}
                ]
            }
        }
        existing_settings = {
            "hooks": {
                "PreToolUse": [
                    {"matcher": "Bash", "hooks": [{"type": "command", "command": "user-hook.sh"}]}
                ]
            }
        }
        source_path = tmp_path / "source.json"
        target_path = tmp_path / "target.json"
        source_path.write_text(json.dumps(source_settings))
        target_path.write_text(json.dumps(existing_settings))

        merge_settings_file(source_path, target_path)

        result = json.loads(target_path.read_text())
        pre_tool = result["hooks"]["PreToolUse"]
        # Both user and HydraFlow hooks should be present
        all_commands = []
        for entry in pre_tool:
            for hook in entry.get("hooks", []):
                all_commands.append(hook.get("command"))
        assert "user-hook.sh" in all_commands
        assert "hf.block.sh" in all_commands

    def test_creates_settings_when_target_missing(self, tmp_path: Path) -> None:
        source_path = tmp_path / "source.json"
        target_path = tmp_path / "target.json"
        source_path.write_text('{"hooks": {"Stop": []}}')

        merge_settings_file(source_path, target_path)

        assert target_path.exists()


class TestMergeAssets:
    def test_full_merge_into_empty_target(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"
        target.mkdir()

        # Set up minimal source structure
        (source / ".claude" / "commands").mkdir(parents=True)
        (source / ".claude" / "commands" / "hf.adr.md").write_text("# ADR")
        (source / ".claude" / "hooks").mkdir(parents=True)
        (source / ".claude" / "hooks" / "hf.block.sh").write_text("#!/bin/bash")
        (source / ".claude" / "settings.json").write_text('{"hooks": {}}')
        (source / ".githooks").mkdir()
        (source / ".githooks" / "pre-commit").write_text("#!/bin/bash\nlint")

        merge_assets(source, target)

        manifest = load_manifest(target / ".hydraflow" / "assets.json")
        assert len(manifest["files"]) > 0
        assert (target / ".claude" / "commands" / "hf.adr.md").exists()
        assert (target / ".githooks" / "hf-pre-commit").exists()

    def test_merge_preserves_user_files(self, tmp_path: Path) -> None:
        source = tmp_path / "source"
        target = tmp_path / "target"

        # User has existing claude commands
        (target / ".claude" / "commands").mkdir(parents=True)
        (target / ".claude" / "commands" / "my-deploy.md").write_text("# Deploy")

        # HydraFlow source
        (source / ".claude" / "commands").mkdir(parents=True)
        (source / ".claude" / "commands" / "hf.adr.md").write_text("# ADR")
        (source / ".claude" / "settings.json").write_text('{"hooks": {}}')

        merge_assets(source, target)

        assert (target / ".claude" / "commands" / "my-deploy.md").read_text() == "# Deploy"
        assert (target / ".claude" / "commands" / "hf.adr.md").exists()


class TestCleanAssets:
    def test_removes_only_managed_files(self, tmp_path: Path) -> None:
        target = tmp_path / "target"
        (target / ".claude" / "commands").mkdir(parents=True)
        (target / ".claude" / "commands" / "hf.adr.md").write_text("# ADR")
        (target / ".claude" / "commands" / "user.md").write_text("# User")

        manifest_path = target / ".hydraflow" / "assets.json"
        save_manifest(manifest_path, [".claude/commands/hf.adr.md"])

        clean_assets(target)

        assert not (target / ".claude" / "commands" / "hf.adr.md").exists()
        assert (target / ".claude" / "commands" / "user.md").exists()
        assert not manifest_path.exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_merge_assets.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement merge_assets.py**

Create `scripts/merge_assets.py` implementing:
- `load_manifest(path)` / `save_manifest(path, files)`
- `copy_namespaced_files(source_dir, target_dir, subdir, prefix)` — copies `prefix*` files from `source_dir/subdir/` to `target_dir/subdir/`, returns list of relative paths
- `chain_hooks(source_hooks_dir, target_hooks_dir)` — renames HydraFlow hooks with `hf-` prefix, appends chain block to existing hooks or creates dispatcher
- `merge_settings_file(source_path, target_path)` — deep-merges settings JSON, tags HydraFlow entries with `"_hydraflow": true`
- `merge_assets(source, target)` — orchestrates the full merge
- `clean_assets(target)` — reads manifest, removes managed files, strips hook chains
- `if __name__ == "__main__":` CLI with `--source`, `--target`, `--clean` args

Key implementation details:
- Hook chain markers: `# --- HydraFlow hook chain (do not edit) ---` and `# --- End HydraFlow hook chain ---`
- Settings merge: for each hook category, collect all HydraFlow-tagged entries from source, append to target if not already present (match by command path)
- Namespaced copy for `.codex/skills/`: copy directories matching `hf.*/`
- Namespaced copy for `.pi/skills/`: copy files matching `hf-*.md`

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_merge_assets.py -v`
Expected: All pass.

- [ ] **Step 5: Update Makefile**

Replace the asset loop in `Makefile` (lines 298-314) with:

```makefile
@echo "$(BLUE)Merging agent assets into target repo...$(RESET)"
@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/merge_assets.py \
    --source "$(PROJECT_ROOT)" --target "$(TARGET_REPO_ROOT)"
```

Add a `clean-assets` target:

```makefile
clean-assets:
	@echo "$(BLUE)Removing HydraFlow assets from target repo...$(RESET)"
	@cd $(HYDRAFLOW_DIR) && PYTHONPATH=src $(UV) python scripts/merge_assets.py \
	    --target "$(TARGET_REPO_ROOT)" --clean
```

- [ ] **Step 6: Run full test suite**

Run: `make quality`
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
bd update ops-audit-fixes-e5e --status done
git add scripts/merge_assets.py tests/test_merge_assets.py Makefile
git commit -m "Replace rm-rf asset sync with namespace-aware merge

HydraFlow now merges its hf.* namespaced assets alongside existing
files instead of destroying them. Tracks installed files in
.hydraflow/assets.json. Git hooks are chained, not replaced.
Settings are deep-merged. make clean-assets removes only HydraFlow
files."
```

---

## Verification

After all tasks are committed:

- [ ] Run `make quality` — full lint + typecheck + security + tests
- [ ] Run `bd list` — all 6 beads should be closed
- [ ] Manual: `make setup TARGET_REPO_ROOT=/tmp/test-repo` on a repo with existing `.claude/` — verify files are preserved
- [ ] Manual: `HYDRAFLOW_EXECUTION_MODE=host make run` — verify no Docker build
