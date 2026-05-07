"""Surface scenarios — exercise phase-2 fakes (Docker, Git, FS, HTTP)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.scenario


# ----- Docker (FakeDocker) -----


class TestSD1DockerStreamHappyPath:
    async def test_scripted_event_stream_replays_in_order(self, mock_world):
        mock_world.docker.script_run(
            [
                {"type": "tool_use", "name": "edit"},
                {"type": "result", "success": True, "exit_code": 0},
            ]
        )
        events = [e async for e in await mock_world.docker.run_agent(command=["agent"])]
        assert [e["type"] for e in events] == ["tool_use", "result"]


class TestSD2DockerMalformedResult:
    async def test_nonzero_exit_is_observable(self, mock_world):
        mock_world.docker.script_run(
            [
                {"type": "result", "success": False, "exit_code": 137},  # OOM-ish
            ]
        )
        events = [e async for e in await mock_world.docker.run_agent(command=["agent"])]
        assert events[-1]["exit_code"] == 137


class TestSD3DockerRecordsInvocation:
    async def test_invocation_captures_command_and_env(self, mock_world):
        async for _ in await mock_world.docker.run_agent(
            command=["agent", "--issue", "42"], env={"TOKEN": "redacted"}
        ):
            pass
        inv = mock_world.docker.invocations[0]
        assert inv.command == ["agent", "--issue", "42"]
        assert inv.env == {"TOKEN": "redacted"}


# ----- Git (FakeGit) -----


class TestSG1GitCoreWorktreeCorruption:
    async def test_corrupted_config_detected_and_repaired(self, mock_world, tmp_path):
        mock_world.git.script_set_corrupted_config(
            tmp_path, key="core.worktree", value="/workspace"
        )
        assert (
            await mock_world.git.config_get(tmp_path, "core.worktree") == "/workspace"
        )
        await mock_world.git.config_unset(tmp_path, "core.worktree")
        assert await mock_world.git.config_get(tmp_path, "core.worktree") is None


class TestSG2GitPushRejected:
    async def test_scripted_rejection_raises(self, mock_world, tmp_path):
        mock_world.git.reject_next_push()
        with pytest.raises(RuntimeError, match="non-fast-forward"):
            await mock_world.git.push(tmp_path, "origin", "main")


class TestSG3GitWorktreeLifecycle:
    async def test_add_remove_clears_tracking(self, mock_world, tmp_path):
        wt = tmp_path / "wt"
        await mock_world.git.worktree_add(wt, "feature/x", new_branch=True)
        assert wt in mock_world.git.active_worktrees()
        await mock_world.git.worktree_remove(wt)
        assert wt not in mock_world.git.active_worktrees()


# ----- FS (FakeFS) -----


class TestSF1FSWriteRead:
    async def test_write_then_read_roundtrips(self, mock_world):
        path = Path("/.hydraflow/plans/issue-1.md")
        mock_world.fs.write(path, "plan body")
        assert mock_world.fs.read(path) == "plan body"


class TestSF2FSLockContention:
    async def test_second_lock_raises(self, mock_world):
        path = Path("/.hydraflow/metrics/cache.lock")
        lock1 = mock_world.fs.lock(path)
        with lock1:
            lock2 = mock_world.fs.lock(path)
            with pytest.raises(RuntimeError, match="already held"):
                lock2.__enter__()


# ----- HTTP (FakeHTTP) -----


class TestSH1HTTPRoutedResponse:
    async def test_routed_response_returns_scripted_body(self, mock_world):
        mock_world.http.when("POST", "https://api.github.com/gists").respond(
            status_code=201, json={"html_url": "https://gist.example/x"}
        )
        resp = await mock_world.http.request(
            "POST", "https://api.github.com/gists", json={}
        )
        assert resp.status_code == 201


class TestSH2HTTPUnroutedRaises:
    async def test_unrouted_request_raises_lookup(self, mock_world):
        with pytest.raises(LookupError, match="no route"):
            await mock_world.http.request("GET", "https://example.com/nope")
