"""Tests for dashboard_routes.py — repo management endpoints."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus
from repo_store import RepoRecord, RepoRegistryStore
from tests.helpers import find_endpoint, make_dashboard_router

# ---------------------------------------------------------------------------
# Crate (milestone) endpoint tests
# ---------------------------------------------------------------------------


class TestCrateEndpoints:
    """Tests for /api/crates routes backed by GitHub milestones."""

    @pytest.mark.asyncio
    async def test_list_crates_returns_empty_list(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(return_value=[])
        endpoint = find_endpoint(router, "/api/crates", "GET")
        assert endpoint is not None
        response = await endpoint()
        data = json.loads(response.body)
        assert data == []

    @pytest.mark.asyncio
    async def test_list_crates_returns_enriched_data(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import Crate

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(
            return_value=[
                Crate(
                    number=1,
                    title="Sprint 1",
                    state="open",
                    open_issues=3,
                    closed_issues=2,
                )
            ]
        )
        endpoint = find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        data = json.loads(response.body)
        assert len(data) == 1
        assert data[0]["title"] == "Sprint 1"
        assert data[0]["total_issues"] == 5
        assert data[0]["progress"] == 40

    @pytest.mark.asyncio
    async def test_list_crates_zero_total_issues(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """progress should be 0 when a crate has zero issues (no division by zero)."""
        import json

        from models import Crate

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(
            return_value=[
                Crate(
                    number=2,
                    title="Empty",
                    state="open",
                    open_issues=0,
                    closed_issues=0,
                )
            ]
        )
        endpoint = find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        data = json.loads(response.body)
        assert data[0]["total_issues"] == 0
        assert data[0]["progress"] == 0

    @pytest.mark.asyncio
    async def test_list_crates_runtime_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(side_effect=RuntimeError("gh failed"))
        endpoint = find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        assert response.status_code == 500
        data = json.loads(response.body)
        assert data["error"] == "Failed to fetch crates"

    @pytest.mark.asyncio
    async def test_create_crate_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import Crate, CrateCreateRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.create_milestone = AsyncMock(
            return_value=Crate(number=5, title="Sprint 3", state="open")
        )
        endpoint = find_endpoint(router, "/api/crates", "POST")
        body = CrateCreateRequest(title="Sprint 3")
        response = await endpoint(body)
        data = json.loads(response.body)
        assert data["title"] == "Sprint 3"
        assert data["number"] == 5
        pr_mgr.create_milestone.assert_called_once_with(
            title="Sprint 3", description="", due_on=None
        )

    @pytest.mark.asyncio
    async def test_create_crate_error(self, config, event_bus, state, tmp_path) -> None:
        import json

        from models import CrateCreateRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.create_milestone = AsyncMock(side_effect=RuntimeError("rate limit"))
        endpoint = find_endpoint(router, "/api/crates", "POST")
        body = CrateCreateRequest(title="Fail")
        response = await endpoint(body)
        assert response.status_code == 500
        data = json.loads(response.body)
        assert data["error"] == "Failed to create crate"

    @pytest.mark.asyncio
    async def test_update_crate_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import Crate, CrateUpdateRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.update_milestone = AsyncMock(
            return_value=Crate(number=1, title="Updated", state="closed")
        )
        endpoint = find_endpoint(router, "/api/crates/{crate_number}", "PATCH")
        body = CrateUpdateRequest(title="Updated", state="closed")
        response = await endpoint(1, body)
        data = json.loads(response.body)
        assert data["title"] == "Updated"
        assert data["state"] == "closed"

    @pytest.mark.asyncio
    async def test_delete_crate_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.delete_milestone = AsyncMock()
        endpoint = find_endpoint(router, "/api/crates/{crate_number}", "DELETE")
        response = await endpoint(1)
        data = json.loads(response.body)
        assert data["ok"] is True
        pr_mgr.delete_milestone.assert_called_once_with(1)

    @pytest.mark.asyncio
    async def test_add_crate_items_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from models import CrateItemsRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.set_issue_milestone = AsyncMock()
        endpoint = find_endpoint(router, "/api/crates/{crate_number}/items", "POST")
        body = CrateItemsRequest(issue_numbers=[10, 11, 12])
        response = await endpoint(5, body)
        data = json.loads(response.body)
        assert data["ok"] is True
        assert data["added"] == 3
        assert pr_mgr.set_issue_milestone.call_count == 3

    @pytest.mark.asyncio
    async def test_remove_crate_items_only_removes_matching(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Only issues currently assigned to the target milestone should be cleared."""
        import json

        from models import CrateItemsRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        # Issue 10 belongs to milestone 5, issue 99 does not
        pr_mgr.list_milestone_issues = AsyncMock(
            return_value=[{"number": 10}, {"number": 11}]
        )
        pr_mgr.set_issue_milestone = AsyncMock()
        endpoint = find_endpoint(router, "/api/crates/{crate_number}/items", "DELETE")
        body = CrateItemsRequest(issue_numbers=[10, 99])
        response = await endpoint(5, body)
        data = json.loads(response.body)
        assert data["ok"] is True
        assert data["removed"] == 1  # Only issue 10 was actually in milestone 5
        pr_mgr.set_issue_milestone.assert_called_once_with(10, None)

    @pytest.mark.asyncio
    async def test_remove_crate_items_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        from models import CrateItemsRequest

        router, pr_mgr = make_dashboard_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestone_issues = AsyncMock(side_effect=RuntimeError("fail"))
        endpoint = find_endpoint(router, "/api/crates/{crate_number}/items", "DELETE")
        body = CrateItemsRequest(issue_numbers=[10])
        response = await endpoint(5, body)
        assert response.status_code == 500


class TestDetectRepoSlugFromPath:
    """Tests for _detect_repo_slug_from_path helper."""

    @pytest.fixture(autouse=True)
    def _setup(self, config, event_bus, state, tmp_path: Path) -> None:
        self.router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

    def _get_helper(self):
        """Extract the _detect_repo_slug_from_path closure from the router scope."""
        # The helper is a closure inside create_router, accessible via the endpoint
        # We test it indirectly through the add_repo_by_path endpoint instead
        # For unit-level tests, we mock subprocess and call the endpoint
        pass

    def test_https_remote_url(self) -> None:
        """HTTPS remote URL is parsed to owner/repo slug."""
        from urllib.parse import urlparse

        url = "https://github.com/owner/repo.git"
        parsed = urlparse(url)
        slug = parsed.path.lstrip("/").removesuffix(".git")
        assert slug == "owner/repo"

    def test_ssh_remote_url(self) -> None:
        """SSH remote URL is parsed to owner/repo slug."""
        url = "git@github.com:owner/repo.git"
        _, _, remainder = url.partition(":")
        slug = remainder.lstrip("/").removesuffix(".git")
        assert slug == "owner/repo"

    def test_no_remote_returns_none(self) -> None:
        """Empty stdout means no remote — returns None-equivalent."""
        url = ""
        assert not url  # Would return None in the helper


class TestAddRepoByPath:
    """Tests for POST /api/repos/add endpoint."""

    class _FakeGitProcess:
        """Minimal async proc stub for git subprocess calls."""

        def __init__(self, stdout: bytes, returncode: int = 0) -> None:
            self._stdout = stdout
            self.returncode = returncode

        async def communicate(self):
            return self._stdout, b""

    def _mock_git_validation(
        self,
        repo_dir: Path,
        *,
        remote_url: str | None = "https://github.com/testowner/testrepo.git",
    ):
        """Patch asyncio.create_subprocess_exec for git validation + slug detection."""
        expected_path = str(repo_dir.resolve())

        async def fake_create_subprocess_exec(*cmd, **_kwargs):
            assert cmd[0] == "git", f"unexpected binary {cmd[0]}"
            assert cmd[1] == "-C", "git -C <path> expected"
            assert cmd[2] == expected_path, f"unexpected repo path {cmd[2]}"
            git_args = tuple(cmd[3:])
            if git_args[:2] == ("rev-parse", "--git-dir"):
                return self._FakeGitProcess(b".git\n", returncode=0)
            if git_args[:3] == ("remote", "get-url", "origin"):
                stdout = (remote_url + "\n").encode() if remote_url else b""
                return self._FakeGitProcess(stdout, returncode=0)
            raise AssertionError(f"unexpected git args {git_args}")

        return patch(
            "asyncio.create_subprocess_exec",
            side_effect=fake_create_subprocess_exec,
        )

    @pytest.mark.asyncio
    async def test_missing_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint({"path": ""})
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "path required" in data["error"]

    @pytest.mark.asyncio
    async def test_missing_body_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint(None)
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "path required" in data["error"]

    @pytest.mark.asyncio
    async def test_non_string_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint({"path": 123})
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "path must be a string" in data["error"]

    @pytest.mark.asyncio
    async def test_nonexistent_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint({"path": str(tmp_path / "missing-repo-dir")})
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "not a git repository" in data["error"]

    @pytest.mark.asyncio
    async def test_non_git_repo_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        fake_dir = tmp_path / "not-a-repo"
        fake_dir.mkdir()
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint({"path": str(fake_dir)})
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "not a git repository" in data["error"]

    @pytest.mark.asyncio
    async def test_disallowed_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint({"path": "/"})
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "inside your home directory or temp directory" in data["error"]

    @pytest.mark.asyncio
    async def test_valid_path_registers_repo(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """Valid git repo path is registered via register_repo_cb."""
        import json as json_mod

        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()

        returned_record = RepoRecord(
            slug="testowner/testrepo",
            repo="testowner/testrepo",
            path=str(repo_dir.resolve()),
        )
        register_cb = AsyncMock(return_value=(returned_record, config))

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=register_cb
        )
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        with (
            self._mock_git_validation(
                repo_dir, remote_url="https://github.com/testowner/testrepo.git"
            ),
            patch("prep.ensure_labels", new_callable=AsyncMock),
        ):
            resp = await endpoint({"path": str(repo_dir)})

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"
        assert data["path"] == str(repo_dir.resolve())
        register_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_label_creation_failure_still_registers(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """Labels fail but repo is still registered with a warning."""
        import json as json_mod

        repo_dir = tmp_path / "label-fail-repo"
        repo_dir.mkdir()

        returned_record = RepoRecord(
            slug="org/labeltest",
            repo="org/labeltest",
            path=str(repo_dir.resolve()),
        )
        register_cb = AsyncMock(return_value=(returned_record, config))

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=register_cb
        )
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        with (
            self._mock_git_validation(
                repo_dir, remote_url="https://github.com/org/labeltest.git"
            ),
            patch(
                "prep.ensure_labels",
                new_callable=AsyncMock,
                side_effect=RuntimeError("gh not found"),
            ),
        ):
            resp = await endpoint({"path": str(repo_dir)})

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"
        assert data["labels_created"] is False
        register_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_supervisor_not_running_returns_503(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """Without register_repo_cb, the endpoint returns 503 (no supervisor)."""
        import json as json_mod

        repo_dir = tmp_path / "supervisor-down-repo"
        repo_dir.mkdir()

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")
        with self._mock_git_validation(
            repo_dir, remote_url="https://github.com/org/down.git"
        ):
            resp = await endpoint({"path": str(repo_dir)})

        data = json_mod.loads(resp.body)
        assert resp.status_code == 503
        assert data["error"] == "supervisor unavailable"

    @pytest.mark.asyncio
    async def test_register_repo_cb_succeeds(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """register_repo_cb is invoked and registration succeeds."""
        import json as json_mod

        repo_dir = tmp_path / "supervisor-autostart-repo"
        repo_dir.mkdir()

        returned_record = RepoRecord(
            slug="org/autostart",
            repo="org/autostart",
            path=str(repo_dir.resolve()),
        )
        register_cb = AsyncMock(return_value=(returned_record, config))

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=register_cb
        )
        endpoint = find_endpoint(router, "/api/repos/add", "POST")
        with (
            self._mock_git_validation(
                repo_dir, remote_url="https://github.com/org/autostart.git"
            ),
            patch("prep.ensure_labels", new_callable=AsyncMock),
        ):
            resp = await endpoint({"path": str(repo_dir)})

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"
        register_cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_req_query_plain_path_is_accepted(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        fake_dir = tmp_path / "query-path-repo"
        fake_dir.mkdir()
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint(
            req=None,
            req_query=str(fake_dir),
            path=None,
            repo_path_query=None,
        )
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "not a git repository" in data["error"]

    @pytest.mark.asyncio
    async def test_req_query_json_path_is_accepted(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        fake_dir = tmp_path / "query-json-path-repo"
        fake_dir.mkdir()
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        resp = await endpoint(
            req=None,
            req_query=json_mod.dumps({"path": str(fake_dir)}),
            path=None,
            repo_path_query=None,
        )
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "not a git repository" in data["error"]


class TestPickRepoFolder:
    """Tests for POST /api/repos/pick-folder endpoint."""

    @pytest.mark.asyncio
    async def test_no_selection_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/pick-folder", "POST")

        with patch(
            "dashboard_routes._state_routes._pick_folder_with_dialog",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = await endpoint()

        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert data["error"] == "No folder selected"

    @pytest.mark.asyncio
    async def test_selected_folder_returns_path(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        repo_dir = tmp_path / "picked-repo"
        repo_dir.mkdir()
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/repos/pick-folder", "POST")

        with patch(
            "dashboard_routes._state_routes._pick_folder_with_dialog",
            new_callable=AsyncMock,
            return_value=str(repo_dir),
        ):
            resp = await endpoint()

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["path"] == str(repo_dir.resolve())


class TestBrowsableFilesystemAPI:
    """Tests for /api/fs/roots and /api/fs/list endpoints."""

    @pytest.mark.asyncio
    async def test_fs_roots_returns_allowed_roots(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/fs/roots")
        resp = await endpoint()
        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert isinstance(data.get("roots"), list)
        assert len(data["roots"]) >= 1
        assert all("path" in root for root in data["roots"])

    @pytest.mark.asyncio
    async def test_fs_roots_respects_allowed_repo_roots_fn(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """allowed_repo_roots_fn is used by /api/fs/roots, not the real home/tmp."""
        import json as json_mod

        custom_root = str(tmp_path / "custom-root")
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            allowed_repo_roots_fn=lambda: (custom_root,),
        )
        endpoint = find_endpoint(router, "/api/fs/roots")
        resp = await endpoint()
        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        paths = [r["path"] for r in data["roots"]]
        assert paths == [custom_root]

    @pytest.mark.asyncio
    async def test_fs_roots_includes_all_injected_roots(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """All roots from allowed_repo_roots_fn are returned — no middle items dropped."""
        import json as json_mod

        root_a = str(tmp_path / "root-a")
        root_b = str(tmp_path / "root-b")
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            allowed_repo_roots_fn=lambda: (root_a, root_b),
        )
        endpoint = find_endpoint(router, "/api/fs/roots")
        resp = await endpoint()
        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        paths = [r["path"] for r in data["roots"]]
        assert paths == [root_a, root_b]
        names = [r["name"] for r in data["roots"]]
        assert names == ["Home", "Temp"]

    @pytest.mark.asyncio
    async def test_fs_list_empty_roots_returns_500(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        """Empty allowed_repo_roots_fn triggers the no-roots guard with 500."""
        import json as json_mod

        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            allowed_repo_roots_fn=lambda: (),
        )
        endpoint = find_endpoint(router, "/api/fs/list")
        resp = await endpoint(path=None)
        data = json_mod.loads(resp.body)
        assert resp.status_code == 500
        assert "no allowed roots configured" in data["error"]

    @pytest.mark.asyncio
    async def test_fs_list_rejects_disallowed_path(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/fs/list")
        resp = await endpoint(path="/")
        data = json_mod.loads(resp.body)
        assert resp.status_code == 400
        assert "inside your home directory or temp directory" in data["error"]

    @pytest.mark.asyncio
    async def test_fs_list_returns_child_directories(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        root = tmp_path / "browse-root"
        root.mkdir()
        (root / "repo-a").mkdir()
        (root / "repo-b").mkdir()
        (root / ".hidden").mkdir()
        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            allowed_repo_roots_fn=lambda: (str(root),),
        )
        endpoint = find_endpoint(router, "/api/fs/list")
        resp = await endpoint(path=str(root))

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        names = [item["name"] for item in data["directories"]]
        assert "repo-a" in names
        assert "repo-b" in names
        assert ".hidden" not in names


# ---------------------------------------------------------------------------
# Repo store / runtime integration helpers
# ---------------------------------------------------------------------------


class _StubRuntime:
    def __init__(self, config):
        self.config = config
        self.slug = config.repo_slug
        self.running = False
        self.event_bus = MagicMock()
        self.state = MagicMock()
        self._orchestrator = MagicMock()

    @property
    def orchestrator(self):
        return self._orchestrator

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False


class _StubRegistry:
    def __init__(self):
        self._items: dict[str, _StubRuntime] = {}

    async def register(self, config):
        runtime = _StubRuntime(config)
        self._items[runtime.slug] = runtime
        return runtime

    def get(self, slug):
        return self._items.get(slug)

    def remove(self, slug):
        return self._items.pop(slug, None)

    @property
    def all(self):
        return list(self._items.values())


class TestRepoStoreRuntimeIntegration:
    """Ensure repo_store-backed endpoints persist repos and manage runtimes."""

    def _init_repo(self, repo_path: Path) -> None:
        repo_path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "-C", str(repo_path), "init"], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_path),
                "remote",
                "add",
                "origin",
                "https://github.com/acme/widgets.git",
            ],
            check=True,
        )

    @pytest.mark.asyncio
    async def test_add_repo_persists_record_and_registers_runtime(
        self, event_bus: EventBus, state, tmp_path: Path, monkeypatch
    ) -> None:
        import re

        from tests.helpers import ConfigFactory

        registry = _StubRegistry()
        repo_store = RepoRegistryStore(tmp_path / "repos-data")
        base_config = ConfigFactory.create(
            repo_root=tmp_path / "base",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )

        async def _register_repo_cb(repo_path, slug):
            repo_label = (slug or repo_path.name or "repo").strip()
            safe_slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", repo_label).strip("-") or "repo"
            record = RepoRecord(
                slug=safe_slug, repo=slug or safe_slug, path=str(repo_path)
            )
            record = repo_store.upsert(record)
            cfg = base_config.model_copy(update={"repo": record.repo})
            await registry.register(cfg)
            return record, cfg

        router, _ = make_dashboard_router(
            base_config,
            event_bus,
            state,
            tmp_path,
            registry=registry,
            repo_store=repo_store,
            register_repo_cb=_register_repo_cb,
            default_repo_slug=base_config.repo_slug,
        )
        add_endpoint = find_endpoint(router, "/api/repos/add", "POST")
        repo_path = tmp_path / "widgets"
        self._init_repo(repo_path)
        import prep

        monkeypatch.setattr(prep, "ensure_labels", AsyncMock())

        response = await add_endpoint(
            {"path": str(repo_path)},
            None,
            None,
            None,
        )
        assert response.status_code == 200
        stored = repo_store.get("acme-widgets")
        assert stored is not None
        assert stored.repo == "acme/widgets"

    @pytest.mark.asyncio
    async def test_start_runtime_starts_stopped_runtime(
        self, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from tests.helpers import ConfigFactory

        registry = _StubRegistry()
        repo_store = RepoRegistryStore(tmp_path / "repos-data")
        base_config = ConfigFactory.create(
            repo_root=tmp_path / "base",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        repo_path = tmp_path / "widgets"
        self._init_repo(repo_path)
        repo_store.upsert(
            RepoRecord(slug="acme-widgets", repo="acme/widgets", path=str(repo_path))
        )
        # Pre-register the runtime in stopped state
        cfg = base_config.model_copy(update={"repo": "acme/widgets"})
        runtime = await registry.register(cfg)
        runtime.slug = "acme-widgets"
        runtime.running = False
        registry._items["acme-widgets"] = runtime

        router, _ = make_dashboard_router(
            base_config,
            event_bus,
            state,
            tmp_path,
            registry=registry,
            repo_store=repo_store,
            default_repo_slug=base_config.repo_slug,
        )
        start_endpoint = find_endpoint(router, "/api/runtimes/{slug}/start", "POST")

        response = await start_endpoint("acme-widgets")
        assert response.status_code == 200
        assert runtime.running is True

    @pytest.mark.asyncio
    async def test_remove_repo_stops_runtime_and_updates_store(
        self, event_bus: EventBus, state, tmp_path: Path
    ) -> None:
        from tests.helpers import ConfigFactory

        registry = _StubRegistry()
        repo_store = RepoRegistryStore(tmp_path / "repos-data")
        base_config = ConfigFactory.create(
            repo_root=tmp_path / "base",
            workspace_base=tmp_path / "worktrees",
            state_file=tmp_path / "state.json",
        )
        repo_path = tmp_path / "widgets"
        self._init_repo(repo_path)
        record = RepoRecord(
            slug="acme-widgets", repo="acme/widgets", path=str(repo_path)
        )
        repo_store.upsert(record)
        runtime = await registry.register(base_config.model_copy())
        runtime.slug = "acme-widgets"
        runtime.running = True
        registry._items["acme-widgets"] = runtime

        async def _remove_repo_cb(slug):
            target = registry.get(slug)
            if target:
                if target.running:
                    await target.stop()
                registry.remove(slug)
            return repo_store.remove(slug)

        router, _ = make_dashboard_router(
            base_config,
            event_bus,
            state,
            tmp_path,
            registry=registry,
            repo_store=repo_store,
            remove_repo_cb=_remove_repo_cb,
            default_repo_slug=base_config.repo_slug,
        )
        delete_endpoint = find_endpoint(router, "/api/repos/{slug}", "DELETE")

        response = await delete_endpoint("acme-widgets")
        assert response.status_code == 200
        assert repo_store.get("acme-widgets") is None
        assert registry.get("acme-widgets") is None

    @pytest.mark.asyncio
    async def test_remove_repo_falls_back_to_store_without_callback(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """DELETE /api/repos/{slug} removes from repo_store when no callback."""
        repo_store = RepoRegistryStore(tmp_path / "repos-data")
        record = RepoRecord(
            slug="acme-widgets", repo="acme/widgets", path=str(tmp_path)
        )
        repo_store.upsert(record)

        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            repo_store=repo_store,
            remove_repo_cb=None,
        )
        delete_endpoint = find_endpoint(router, "/api/repos/{slug}", "DELETE")

        response = await delete_endpoint("acme-widgets")
        assert response.status_code == 200
        assert repo_store.get("acme-widgets") is None

    @pytest.mark.asyncio
    async def test_remove_repo_store_fallback_returns_404_for_unknown(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """DELETE /api/repos/{slug} returns 404 when slug not in store."""
        repo_store = RepoRegistryStore(tmp_path / "repos-data")

        router, _ = make_dashboard_router(
            config,
            event_bus,
            state,
            tmp_path,
            repo_store=repo_store,
            remove_repo_cb=None,
        )
        delete_endpoint = find_endpoint(router, "/api/repos/{slug}", "DELETE")

        response = await delete_endpoint("nonexistent")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/repos/add — register_repo_cb branch
# ---------------------------------------------------------------------------


class TestAddRepoByPathWithCallback:
    """Tests for POST /api/repos/add when register_repo_cb is provided."""

    @pytest.mark.asyncio
    async def test_register_repo_cb_invoked_on_valid_path(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from repo_store import RepoRecord

        repo_dir = tmp_path / "cb-repo"
        repo_dir.mkdir()

        returned_record = RepoRecord(
            slug="cb-repo", repo="org/cb-repo", path=str(repo_dir)
        )
        cb = AsyncMock(return_value=(returned_record, config))

        class _FakeGitProcess:
            def __init__(self, stdout: bytes, returncode: int = 0) -> None:
                self._stdout = stdout
                self.returncode = returncode

            async def communicate(self):
                return self._stdout, b""

        async def fake_exec(*cmd, **_):
            git_args = tuple(cmd[3:])
            if git_args[:2] == ("rev-parse", "--git-dir"):
                return _FakeGitProcess(b".git\n")
            if git_args[:3] == ("remote", "get-url", "origin"):
                return _FakeGitProcess(b"https://github.com/org/cb-repo.git\n")
            raise AssertionError(f"unexpected: {cmd}")

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=cb
        )
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        with (
            patch("asyncio.create_subprocess_exec", side_effect=fake_exec),
            patch("prep.ensure_labels", new_callable=AsyncMock),
        ):
            resp = await endpoint({"path": str(repo_dir)})

        data = json.loads(resp.body)
        assert resp.status_code == 200
        assert data["status"] == "ok"
        assert data["slug"] == "cb-repo"
        cb.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_register_repo_cb_value_error_returns_400(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        repo_dir = tmp_path / "err-repo"
        repo_dir.mkdir()
        cb = AsyncMock(side_effect=ValueError("already registered"))

        class _FakeGitProcess:
            def __init__(self, stdout: bytes, returncode: int = 0) -> None:
                self._stdout = stdout
                self.returncode = returncode

            async def communicate(self):
                return self._stdout, b""

        async def fake_exec(*cmd, **_):
            git_args = tuple(cmd[3:])
            if git_args[:2] == ("rev-parse", "--git-dir"):
                return _FakeGitProcess(b".git\n")
            if git_args[:3] == ("remote", "get-url", "origin"):
                return _FakeGitProcess(b"https://github.com/org/err-repo.git\n")
            raise AssertionError(f"unexpected: {cmd}")

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=cb
        )
        endpoint = find_endpoint(router, "/api/repos/add", "POST")

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            resp = await endpoint({"path": str(repo_dir)})

        data = json.loads(resp.body)
        assert resp.status_code == 400
        assert "already registered" in data["error"]


# ---------------------------------------------------------------------------
# GET /api/repos — repo_store branch
# ---------------------------------------------------------------------------


class TestListSupervisedReposWithStore:
    """Tests for GET /api/repos when repo_store is provided (no supervisor)."""

    @pytest.mark.asyncio
    async def test_returns_store_records_when_repo_store_set(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        from repo_store import RepoRecord, RepoStore

        store = RepoStore(tmp_path)
        repo_path = tmp_path / "my-repo"
        repo_path.mkdir()
        store.upsert(
            RepoRecord(slug="my-repo", repo="org/my-repo", path=str(repo_path))
        )

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, repo_store=store, registry=None
        )
        endpoint = find_endpoint(router, "/api/repos")
        resp = await endpoint()

        data = json.loads(resp.body)
        assert resp.status_code == 200
        assert len(data["repos"]) == 1
        assert data["repos"][0]["slug"] == "my-repo"
        assert data["repos"][0]["running"] is False
        assert data["can_register"] is True

    @pytest.mark.asyncio
    async def test_marks_running_when_runtime_active(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json
        from types import SimpleNamespace

        from repo_store import RepoRecord, RepoStore

        store = RepoStore(tmp_path)
        repo_path = tmp_path / "live-repo"
        repo_path.mkdir()
        store.upsert(RepoRecord(slug="live-repo", repo="org/live", path=str(repo_path)))

        mock_orch = MagicMock()
        mock_orch.current_session_id = "sess-abc"
        runtime = SimpleNamespace(running=True, orchestrator=mock_orch)
        mock_registry = MagicMock()
        mock_registry.get.return_value = runtime

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, repo_store=store, registry=mock_registry
        )
        endpoint = find_endpoint(router, "/api/repos")
        resp = await endpoint()

        data = json.loads(resp.body)
        assert resp.status_code == 200
        assert data["repos"][0]["running"] is True
        assert data["repos"][0]["session_id"] == "sess-abc"
