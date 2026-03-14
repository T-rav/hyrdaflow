"""Tests for dashboard_routes.py — GitHub repo picker endpoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from repo_store import RepoRecord
from tests.helpers import find_endpoint, make_dashboard_router


class TestGitHubRepoEndpoints:
    """Tests for /api/github/repos and /api/github/clone routes."""

    # -----------------------------------------------------------------------
    # GET /api/github/repos
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_list_github_repos_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")
        assert endpoint is not None

        gh_output = json.dumps(
            [
                {
                    "name": "myrepo",
                    "owner": {"login": "alice"},
                    "url": "https://github.com/alice/myrepo",
                    "description": "A test repo",
                },
            ]
        ).encode()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(gh_output, b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query=None)
        data = json.loads(response.body)
        assert "repos" in data
        assert len(data["repos"]) == 1
        assert data["repos"][0]["name"] == "myrepo"

    @pytest.mark.asyncio
    async def test_list_github_repos_with_query_filter(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        gh_output = json.dumps(
            [
                {
                    "name": "foo",
                    "owner": {"login": "alice"},
                    "url": "",
                    "description": "",
                },
                {
                    "name": "bar",
                    "owner": {"login": "alice"},
                    "url": "",
                    "description": "",
                },
            ]
        ).encode()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(gh_output, b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query="foo")
        data = json.loads(response.body)
        assert len(data["repos"]) == 1
        assert data["repos"][0]["name"] == "foo"

    @pytest.mark.asyncio
    async def test_list_github_repos_with_null_owner(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Repos with owner: null must not crash the query filter."""
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        gh_output = json.dumps(
            [
                {
                    "name": "orphaned",
                    "owner": None,
                    "url": "",
                    "description": "",
                },
            ]
        ).encode()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(gh_output, b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query="orphaned")
        data = json.loads(response.body)
        assert data["repos"][0]["name"] == "orphaned"

    @pytest.mark.asyncio
    async def test_list_github_repos_gh_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("gh"),
        ):
            response = await endpoint(query=None)
        assert response.status_code == 503
        data = json.loads(response.body)
        assert "gh CLI not found" in data["error"]

    @pytest.mark.asyncio
    async def test_list_github_repos_timeout(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query=None)
        assert response.status_code == 504
        data = json.loads(response.body)
        assert "timed out" in data["error"]

    @pytest.mark.asyncio
    async def test_list_github_repos_auth_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"auth login required"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query=None)
        assert response.status_code == 401
        data = json.loads(response.body)
        assert "auth" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_list_github_repos_gh_failure(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"some error"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query=None)
        assert response.status_code == 502
        data = json.loads(response.body)
        assert "failed" in data["error"].lower()

    @pytest.mark.asyncio
    async def test_list_github_repos_bad_json(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"not json", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query=None)
        assert response.status_code == 502
        data = json.loads(response.body)
        assert "parse" in data["error"].lower()

    # -----------------------------------------------------------------------
    # POST /api/github/clone
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_clone_github_repo_success(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")
        assert endpoint is not None

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(req={"slug": "alice/myrepo"})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["slug"] == "alice-myrepo"
        assert "alice" in data["path"]
        assert "myrepo" in data["path"]

    @pytest.mark.asyncio
    async def test_clone_github_repo_already_cloned(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        # Pre-create the target directory with a .git dir
        clone_dir = tmp_path / "repos" / "alice" / "myrepo"
        clone_dir.mkdir(parents=True)
        (clone_dir / ".git").mkdir()

        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        # No subprocess should be called since already cloned
        response = await endpoint(req={"slug": "alice/myrepo"})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["already_cloned"] is True

    @pytest.mark.asyncio
    async def test_clone_github_repo_missing_slug(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        response = await endpoint(req={"slug": ""})
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "slug required" in data["error"]

    @pytest.mark.asyncio
    async def test_clone_github_repo_invalid_slug(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        response = await endpoint(req={"slug": "noslash"})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_clone_github_repo_no_body(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        response = await endpoint(req=None)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_clone_github_repo_gh_not_found(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("gh"),
        ):
            response = await endpoint(req={"slug": "alice/myrepo"})
        assert response.status_code == 503

    @pytest.mark.asyncio
    async def test_clone_github_repo_clone_failure(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(b"", b"repository not found"))
        mock_proc.returncode = 1

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(req={"slug": "alice/nonexistent"})
        assert response.status_code == 502
        data = json.loads(response.body)
        assert "Clone failed" in data["error"]

    @pytest.mark.asyncio
    async def test_clone_github_repo_timeout(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(side_effect=TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(req={"slug": "alice/myrepo"})
        assert response.status_code == 504

    @pytest.mark.asyncio
    async def test_clone_github_repo_with_register_cb(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        # Pre-create the target so clone is skipped
        clone_dir = tmp_path / "repos" / "alice" / "myrepo"
        clone_dir.mkdir(parents=True)
        (clone_dir / ".git").mkdir()

        record = RepoRecord(
            slug="alice-myrepo", repo="alice/myrepo", path=str(clone_dir)
        )
        mock_cfg = MagicMock()
        register_cb = AsyncMock(return_value=(record, mock_cfg))

        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=register_cb
        )
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        with patch("prep.ensure_labels", new_callable=AsyncMock) as mock_labels:
            response = await endpoint(req={"slug": "alice/myrepo"})
        data = json.loads(response.body)
        assert data["status"] == "ok"
        assert data["slug"] == "alice-myrepo"
        register_cb.assert_called_once()
        mock_labels.assert_called_once_with(mock_cfg)

    @pytest.mark.asyncio
    async def test_clone_github_repo_register_cb_value_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        clone_dir = tmp_path / "repos" / "alice" / "myrepo"
        clone_dir.mkdir(parents=True)
        (clone_dir / ".git").mkdir()

        register_cb = AsyncMock(side_effect=ValueError("duplicate"))
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=register_cb
        )
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        response = await endpoint(req={"slug": "alice/myrepo"})
        assert response.status_code == 400
        data = json.loads(response.body)
        assert "Invalid repository configuration" in data["error"]

    @pytest.mark.asyncio
    async def test_clone_github_repo_register_cb_generic_error(
        self, config, event_bus, state, tmp_path
    ) -> None:
        config.repos_workspace_dir = tmp_path / "repos"
        clone_dir = tmp_path / "repos" / "alice" / "myrepo"
        clone_dir.mkdir(parents=True)
        (clone_dir / ".git").mkdir()

        register_cb = AsyncMock(side_effect=RuntimeError("unexpected"))
        router, _ = make_dashboard_router(
            config, event_bus, state, tmp_path, register_repo_cb=register_cb
        )
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        response = await endpoint(req={"slug": "alice/myrepo"})
        assert response.status_code == 500

    @pytest.mark.asyncio
    async def test_clone_slug_with_empty_owner(
        self, config, event_bus, state, tmp_path
    ) -> None:
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        response = await endpoint(req={"slug": "/myrepo"})
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_clone_slug_path_traversal_rejected(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Slugs containing path traversal sequences must be rejected."""
        config.repos_workspace_dir = tmp_path / "repos"
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/clone", "POST")

        for malicious_slug in [
            "alice/../../etc",
            "../evil/repo",
            "alice/repo/../../secret",
        ]:
            response = await endpoint(req={"slug": malicious_slug})
            assert response.status_code == 400, (
                f"Expected 400 for slug={malicious_slug!r}"
            )

    @pytest.mark.asyncio
    async def test_list_github_repos_query_matches_owner(
        self, config, event_bus, state, tmp_path
    ) -> None:
        """Query should match against owner/name combined slug."""
        router, _ = make_dashboard_router(config, event_bus, state, tmp_path)
        endpoint = find_endpoint(router, "/api/github/repos", "GET")

        gh_output = json.dumps(
            [
                {
                    "name": "proj",
                    "owner": {"login": "acme"},
                    "url": "",
                    "description": "",
                },
                {
                    "name": "other",
                    "owner": {"login": "bob"},
                    "url": "",
                    "description": "",
                },
            ]
        ).encode()

        mock_proc = AsyncMock()
        mock_proc.communicate = AsyncMock(return_value=(gh_output, b""))
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            response = await endpoint(query="acme/proj")
        data = json.loads(response.body)
        assert len(data["repos"]) == 1
        assert data["repos"][0]["name"] == "proj"
