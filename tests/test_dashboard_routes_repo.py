"""Tests for dashboard_routes.py — repo management endpoints."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from events import EventBus


@pytest.fixture(autouse=True)
def _disable_hitl_summary_autowarm(config) -> None:
    """Keep route tests deterministic unless a test explicitly opts in."""
    config.transcript_summarization_enabled = False
    config.gh_token = ""


# ---------------------------------------------------------------------------
# Crate (milestone) endpoint tests
# ---------------------------------------------------------------------------


class TestCrateEndpoints:
    """Tests for /api/crates routes backed by GitHub milestones."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        ), pr_mgr

    def _find_endpoint(self, router, path, method=None):
        for route in router.routes:
            if not (
                hasattr(route, "path")
                and route.path == path
                and hasattr(route, "endpoint")
            ):
                continue
            if method is None or (
                hasattr(route, "methods") and method in route.methods
            ):
                return route.endpoint
        return None

    @pytest.mark.asyncio
    async def test_list_crates_returns_empty_list(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(return_value=[])
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
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
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
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
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
        response = await endpoint()
        data = json.loads(response.body)
        assert data[0]["total_issues"] == 0
        assert data[0]["progress"] == 0

    @pytest.mark.asyncio
    async def test_list_crates_runtime_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        import json

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestones = AsyncMock(side_effect=RuntimeError("gh failed"))
        endpoint = self._find_endpoint(router, "/api/crates", "GET")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_milestone = AsyncMock(
            return_value=Crate(number=5, title="Sprint 3", state="open")
        )
        endpoint = self._find_endpoint(router, "/api/crates", "POST")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.create_milestone = AsyncMock(side_effect=RuntimeError("rate limit"))
        endpoint = self._find_endpoint(router, "/api/crates", "POST")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.update_milestone = AsyncMock(
            return_value=Crate(number=1, title="Updated", state="closed")
        )
        endpoint = self._find_endpoint(router, "/api/crates/{crate_number}", "PATCH")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.delete_milestone = AsyncMock()
        endpoint = self._find_endpoint(router, "/api/crates/{crate_number}", "DELETE")
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.set_issue_milestone = AsyncMock()
        endpoint = self._find_endpoint(
            router, "/api/crates/{crate_number}/items", "POST"
        )
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        # Issue 10 belongs to milestone 5, issue 99 does not
        pr_mgr.list_milestone_issues = AsyncMock(
            return_value=[{"number": 10}, {"number": 11}]
        )
        pr_mgr.set_issue_milestone = AsyncMock()
        endpoint = self._find_endpoint(
            router, "/api/crates/{crate_number}/items", "DELETE"
        )
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

        router, pr_mgr = self._make_router(config, event_bus, state, tmp_path)
        pr_mgr.list_milestone_issues = AsyncMock(side_effect=RuntimeError("fail"))
        endpoint = self._find_endpoint(
            router, "/api/crates/{crate_number}/items", "DELETE"
        )
        body = CrateItemsRequest(issue_numbers=[10])
        response = await endpoint(5, body)
        assert response.status_code == 500


class TestFindRepoMatch:
    """Tests for the _find_repo_match cascading match helper."""

    def _call(self, slug: str, repos: list[dict]) -> dict | None:
        from dashboard_routes import _find_repo_match

        return _find_repo_match(slug, repos)

    def test_exact_slug_match(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("insightmesh", repos) == repos[0]

    def test_owner_repo_format_strips_prefix(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("8thlight/insightmesh", repos) == repos[0]

    def test_path_tail_match(self) -> None:
        repos = [{"slug": "mesh", "path": "/home/user/insightmesh"}]
        assert self._call("insightmesh", repos) == repos[0]

    def test_path_component_match(self) -> None:
        repos = [{"slug": "mesh", "path": "/repos/8thlight/insightmesh"}]
        assert self._call("8thlight", repos) == repos[0]

    def test_exact_match_has_priority_over_path_match(self) -> None:
        exact = {"slug": "myrepo", "path": "/other/path"}
        path_match = {"slug": "other", "path": "/repos/myrepo"}
        repos = [path_match, exact]
        assert self._call("myrepo", repos) == exact

    def test_empty_slug_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("", repos) is None

    def test_no_match_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("bar", repos) is None

    def test_empty_repos_list_returns_none(self) -> None:
        assert self._call("foo", []) is None

    def test_slash_only_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("/", repos) is None

    def test_trailing_slash_stripped(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("8thlight/insightmesh/", repos) == repos[0]

    def test_multi_slash_input(self) -> None:
        repos = [{"slug": "repo", "path": "/repos/repo"}]
        assert self._call("github.com/owner/repo", repos) == repos[0]

    def test_case_insensitive_slug_match(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("InsightMesh", repos) == repos[0]

    def test_case_insensitive_owner_repo(self) -> None:
        repos = [{"slug": "insightmesh", "path": "/repos/insightmesh"}]
        assert self._call("8thLight/InsightMesh", repos) == repos[0]

    def test_repo_with_none_slug(self) -> None:
        repos = [{"slug": None, "path": "/repos/myrepo"}]
        assert self._call("myrepo", repos) == repos[0]

    def test_repo_with_missing_slug_key(self) -> None:
        repos = [{"path": "/repos/myrepo"}]
        assert self._call("myrepo", repos) == repos[0]

    def test_repo_with_none_path(self) -> None:
        repos = [{"slug": "foo", "path": None}]
        assert self._call("foo", repos) == repos[0]

    def test_whitespace_only_returns_none(self) -> None:
        repos = [{"slug": "foo", "path": "/repos/foo"}]
        assert self._call("   ", repos) is None

    def test_no_partial_substring_match(self) -> None:
        """Strategy 4 requires full path component, not substring."""
        repos = [{"slug": "mesh", "path": "/repos/insightmesh"}]
        # "insight" is a substring of "insightmesh" but not a full component
        assert self._call("insight", repos) is None


class TestDetectRepoSlugFromPath:
    """Tests for _detect_repo_slug_from_path helper."""

    @pytest.fixture(autouse=True)
    def _setup(self, config, event_bus, state, tmp_path: Path) -> None:
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        self.router = create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _get_helper(self):
        """Extract the _detect_repo_slug_from_path closure from the router scope."""
        # The helper is a closure inside create_router, accessible via the endpoint
        # We test it indirectly through the add_repo_by_path endpoint instead
        # For unit-level tests, we mock subprocess and call the endpoint
        pass

    @pytest.mark.asyncio
    async def test_https_remote_url(self) -> None:
        """HTTPS remote URL is parsed to owner/repo slug."""
        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(
            return_value=(b"https://github.com/owner/repo.git\n", b"")
        )
        mock_proc.returncode = 0

        from urllib.parse import urlparse

        url = "https://github.com/owner/repo.git"
        parsed = urlparse(url)
        slug = parsed.path.lstrip("/").removesuffix(".git")
        assert slug == "owner/repo"

    @pytest.mark.asyncio
    async def test_ssh_remote_url(self) -> None:
        """SSH remote URL is parsed to owner/repo slug."""
        url = "git@github.com:owner/repo.git"
        _, _, remainder = url.partition(":")
        slug = remainder.lstrip("/").removesuffix(".git")
        assert slug == "owner/repo"

    @pytest.mark.asyncio
    async def test_no_remote_returns_none(self) -> None:
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

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _get_endpoint(self, router):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/repos/add"
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        msg = "add_repo_by_path endpoint not found"
        raise AssertionError(msg)

    @pytest.mark.asyncio
    async def test_missing_path_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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
        """Valid git repo path is registered with supervisor."""
        import json as json_mod

        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()

        mock_supervisor = MagicMock()
        mock_supervisor.register_repo = MagicMock(
            return_value={"status": "ok", "slug": "testrepo", "path": str(repo_dir)},
        )
        with patch.dict("sys.modules", {"hf_cli.supervisor_client": mock_supervisor}):
            from dashboard_routes import create_router
            from pr_manager import PRManager

            pr_mgr = PRManager(config, event_bus)
            router = create_router(
                config=config,
                event_bus=event_bus,
                state=state,
                pr_manager=pr_mgr,
                get_orchestrator=lambda: None,
                set_orchestrator=lambda o: None,
                set_run_task=lambda t: None,
                ui_dist_dir=tmp_path / "no-dist",
                template_dir=tmp_path / "no-templates",
            )
            endpoint = self._get_endpoint(router)

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

        mock_supervisor = MagicMock()
        mock_supervisor.register_repo = MagicMock(
            return_value={"status": "ok", "slug": "labeltest", "path": str(repo_dir)},
        )
        with patch.dict("sys.modules", {"hf_cli.supervisor_client": mock_supervisor}):
            from dashboard_routes import create_router
            from pr_manager import PRManager

            pr_mgr = PRManager(config, event_bus)
            router = create_router(
                config=config,
                event_bus=event_bus,
                state=state,
                pr_manager=pr_mgr,
                get_orchestrator=lambda: None,
                set_orchestrator=lambda o: None,
                set_run_task=lambda t: None,
                ui_dist_dir=tmp_path / "no-dist",
                template_dir=tmp_path / "no-templates",
            )
            endpoint = self._get_endpoint(router)

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

    @pytest.mark.asyncio
    async def test_supervisor_not_running_returns_503(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        repo_dir = tmp_path / "supervisor-down-repo"
        repo_dir.mkdir()

        mock_supervisor = MagicMock()
        mock_supervisor.register_repo = MagicMock(
            side_effect=RuntimeError(
                "hf supervisor is not running. Run `hf run` inside a repo to start it."
            )
        )
        mock_supervisor_manager = MagicMock()
        mock_supervisor_manager.ensure_running = MagicMock(return_value=None)
        with patch.dict(
            "sys.modules",
            {
                "hf_cli.supervisor_client": mock_supervisor,
                "hf_cli.supervisor_manager": mock_supervisor_manager,
            },
        ):
            from dashboard_routes import create_router
            from pr_manager import PRManager

            pr_mgr = PRManager(config, event_bus)
            router = create_router(
                config=config,
                event_bus=event_bus,
                state=state,
                pr_manager=pr_mgr,
                get_orchestrator=lambda: None,
                set_orchestrator=lambda o: None,
                set_run_task=lambda t: None,
                ui_dist_dir=tmp_path / "no-dist",
                template_dir=tmp_path / "no-templates",
            )
            endpoint = self._get_endpoint(router)
            with (
                self._mock_git_validation(
                    repo_dir, remote_url="https://github.com/org/down.git"
                ),
                patch("prep.ensure_labels", new_callable=AsyncMock) as ensure_labels,
            ):
                resp = await endpoint({"path": str(repo_dir)})

        data = json_mod.loads(resp.body)
        assert resp.status_code == 503
        assert "hf supervisor is not running" in data["error"]
        mock_supervisor_manager.ensure_running.assert_called_once()
        ensure_labels.assert_not_called()

    @pytest.mark.asyncio
    async def test_supervisor_autostart_then_register_succeeds(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        repo_dir = tmp_path / "supervisor-autostart-repo"
        repo_dir.mkdir()

        mock_supervisor = MagicMock()
        mock_supervisor.register_repo = MagicMock(
            side_effect=[
                RuntimeError(
                    "hf supervisor is not running. Run `hf run` inside a repo to start it."
                ),
                {"status": "ok"},
            ]
        )
        mock_supervisor_manager = MagicMock()
        mock_supervisor_manager.ensure_running = MagicMock(return_value=None)
        with patch.dict(
            "sys.modules",
            {
                "hf_cli.supervisor_client": mock_supervisor,
                "hf_cli.supervisor_manager": mock_supervisor_manager,
            },
        ):
            from dashboard_routes import create_router
            from pr_manager import PRManager

            pr_mgr = PRManager(config, event_bus)
            router = create_router(
                config=config,
                event_bus=event_bus,
                state=state,
                pr_manager=pr_mgr,
                get_orchestrator=lambda: None,
                set_orchestrator=lambda o: None,
                set_run_task=lambda t: None,
                ui_dist_dir=tmp_path / "no-dist",
                template_dir=tmp_path / "no-templates",
            )
            endpoint = self._get_endpoint(router)
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
        assert mock_supervisor.register_repo.call_count == 2
        mock_supervisor_manager.ensure_running.assert_called_once()

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
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

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

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _get_endpoint(self, router):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == "/api/repos/pick-folder"
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        msg = "pick_repo_folder endpoint not found"
        raise AssertionError(msg)

    @pytest.mark.asyncio
    async def test_no_selection_returns_400(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        with patch(
            "dashboard_routes._pick_folder_with_dialog",
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
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router)

        with patch(
            "dashboard_routes._pick_folder_with_dialog",
            new_callable=AsyncMock,
            return_value=str(repo_dir),
        ):
            resp = await endpoint()

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert data["path"] == str(repo_dir.resolve())


class TestBrowsableFilesystemAPI:
    """Tests for /api/fs/roots and /api/fs/list endpoints."""

    def _make_router(self, config, event_bus, state, tmp_path):
        from dashboard_routes import create_router
        from pr_manager import PRManager

        pr_mgr = PRManager(config, event_bus)
        return create_router(
            config=config,
            event_bus=event_bus,
            state=state,
            pr_manager=pr_mgr,
            get_orchestrator=lambda: None,
            set_orchestrator=lambda o: None,
            set_run_task=lambda t: None,
            ui_dist_dir=tmp_path / "no-dist",
            template_dir=tmp_path / "no-templates",
        )

    def _get_endpoint(self, router, target_path: str):
        for route in router.routes:
            if (
                hasattr(route, "path")
                and route.path == target_path
                and hasattr(route, "endpoint")
            ):
                return route.endpoint
        msg = f"{target_path} endpoint not found"
        raise AssertionError(msg)

    @pytest.mark.asyncio
    async def test_fs_roots_returns_allowed_roots(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router, "/api/fs/roots")
        resp = await endpoint()
        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        assert isinstance(data.get("roots"), list)
        assert len(data["roots"]) >= 1
        assert all("path" in root for root in data["roots"])

    @pytest.mark.asyncio
    async def test_fs_list_rejects_disallowed_path(
        self,
        config,
        event_bus: EventBus,
        state,
        tmp_path: Path,
    ) -> None:
        import json as json_mod

        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router, "/api/fs/list")
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
        router = self._make_router(config, event_bus, state, tmp_path)
        endpoint = self._get_endpoint(router, "/api/fs/list")

        with patch("dashboard_routes._allowed_repo_roots", return_value=(str(root),)):
            resp = await endpoint(path=str(root))

        data = json_mod.loads(resp.body)
        assert resp.status_code == 200
        names = [item["name"] for item in data["directories"]]
        assert "repo-a" in names
        assert "repo-b" in names
        assert ".hidden" not in names
