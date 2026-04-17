"""Verify WorkspaceManager wires base-branch operations through config.base_branch()."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

from tests.helpers import ConfigFactory


def _cfg(tmp_path: Path, *, staging_enabled: bool):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )
    cfg.staging_enabled = staging_enabled
    return cfg


class TestWorkspaceBaseBranchFetch:
    async def test_reset_uses_staging_when_enabled(self, tmp_path: Path) -> None:
        """reset_to_main should fetch+reset to origin/staging when staging_enabled."""
        from workspace import WorkspaceManager

        cfg = _cfg(tmp_path, staging_enabled=True)
        ws = WorkspaceManager(cfg)
        with patch("workspace.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ""
            await ws.reset_to_main(tmp_path)
        all_cmds = [call.args for call in mock_run.call_args_list]
        joined = [" ".join(map(str, cmd)) for cmd in all_cmds]
        assert any("origin/staging" in s for s in joined), (
            f"expected an 'origin/staging' invocation; got: {joined}"
        )
        assert not any("origin/main" in s for s in joined), (
            f"unexpected 'origin/main' when staging_enabled=True; got: {joined}"
        )

    async def test_reset_uses_main_when_disabled(self, tmp_path: Path) -> None:
        """reset_to_main should fetch+reset to origin/main when staging disabled."""
        from workspace import WorkspaceManager

        cfg = _cfg(tmp_path, staging_enabled=False)
        ws = WorkspaceManager(cfg)
        with patch("workspace.run_subprocess", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = ""
            await ws.reset_to_main(tmp_path)
        all_cmds = [call.args for call in mock_run.call_args_list]
        joined = [" ".join(map(str, cmd)) for cmd in all_cmds]
        assert any("origin/main" in s for s in joined), (
            f"expected an 'origin/main' invocation; got: {joined}"
        )


class TestBaseBranchHelperReturnsCorrect:
    """Guard rail: verify HydraFlowConfig.base_branch() actually does what we think."""

    def test_base_branch_staging(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path, staging_enabled=True)
        assert cfg.base_branch() == "staging"

    def test_base_branch_main(self, tmp_path: Path) -> None:
        cfg = _cfg(tmp_path, staging_enabled=False)
        assert cfg.base_branch() == "main"
