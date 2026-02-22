"""Tests for the project manifest detection and persistence system."""

from __future__ import annotations

import json
from pathlib import Path

from manifest import (
    ProjectManifestManager,
    build_manifest_markdown,
    detect_build_systems,
    detect_ci_systems,
    detect_key_docs,
    detect_languages,
    detect_sub_projects,
    detect_test_frameworks,
    load_project_manifest,
)
from state import StateTracker
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# detect_languages
# ---------------------------------------------------------------------------


class TestDetectLanguages:
    """Tests for manifest.detect_languages."""

    def test_detect_languages__python(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        assert detect_languages(tmp_path) == ["python"]

    def test_detect_languages__javascript(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert detect_languages(tmp_path) == ["javascript"]

    def test_detect_languages__rust(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert detect_languages(tmp_path) == ["rust"]

    def test_detect_languages__go(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example")
        assert detect_languages(tmp_path) == ["go"]

    def test_detect_languages__java(self, tmp_path: Path) -> None:
        (tmp_path / "pom.xml").write_text("<project/>")
        assert detect_languages(tmp_path) == ["java"]

    def test_detect_languages__mixed(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        (tmp_path / "package.json").write_text("{}")
        result = detect_languages(tmp_path)
        assert "python" in result
        assert "javascript" in result

    def test_detect_languages__empty_repo(self, tmp_path: Path) -> None:
        assert detect_languages(tmp_path) == []

    def test_detect_languages__setup_py(self, tmp_path: Path) -> None:
        (tmp_path / "setup.py").write_text("from setuptools import setup")
        assert detect_languages(tmp_path) == ["python"]

    def test_detect_languages__requirements_txt(self, tmp_path: Path) -> None:
        (tmp_path / "requirements.txt").write_text("flask")
        assert detect_languages(tmp_path) == ["python"]

    def test_detect_languages__tsconfig(self, tmp_path: Path) -> None:
        (tmp_path / "tsconfig.json").write_text("{}")
        assert detect_languages(tmp_path) == ["javascript"]


# ---------------------------------------------------------------------------
# detect_build_systems
# ---------------------------------------------------------------------------


class TestDetectBuildSystems:
    """Tests for manifest.detect_build_systems."""

    def test_detect_build_systems__makefile(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("all:\n\techo hi")
        assert "make" in detect_build_systems(tmp_path)

    def test_detect_build_systems__cmake(self, tmp_path: Path) -> None:
        (tmp_path / "CMakeLists.txt").write_text("project(test)")
        assert "cmake" in detect_build_systems(tmp_path)

    def test_detect_build_systems__npm(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text("{}")
        assert "npm" in detect_build_systems(tmp_path)

    def test_detect_build_systems__none(self, tmp_path: Path) -> None:
        assert detect_build_systems(tmp_path) == []

    def test_detect_build_systems__multiple(self, tmp_path: Path) -> None:
        (tmp_path / "Makefile").write_text("all:")
        (tmp_path / "pyproject.toml").write_text("[project]")
        result = detect_build_systems(tmp_path)
        assert "make" in result
        assert "pip" in result


# ---------------------------------------------------------------------------
# detect_test_frameworks
# ---------------------------------------------------------------------------


class TestDetectTestFrameworks:
    """Tests for manifest.detect_test_frameworks."""

    def test_detect_test_frameworks__pytest_ini(self, tmp_path: Path) -> None:
        (tmp_path / "pytest.ini").write_text("[pytest]")
        assert "pytest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__conftest(self, tmp_path: Path) -> None:
        (tmp_path / "conftest.py").write_text("import pytest")
        assert "pytest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__pyproject_pytest(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]")
        assert "pytest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__tests_dir_with_python(
        self, tmp_path: Path
    ) -> None:
        (tmp_path / "tests").mkdir()
        (tmp_path / "pyproject.toml").write_text("[project]")
        assert "pytest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__vitest(self, tmp_path: Path) -> None:
        (tmp_path / "vitest.config.ts").write_text("export default {}")
        assert "vitest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__jest_config(self, tmp_path: Path) -> None:
        (tmp_path / "jest.config.js").write_text("module.exports = {}")
        assert "jest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__jest_in_package_json(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(json.dumps({"jest": {}}))
        assert "jest" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__cargo_test(self, tmp_path: Path) -> None:
        (tmp_path / "Cargo.toml").write_text("[package]")
        assert "cargo-test" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__go_test(self, tmp_path: Path) -> None:
        (tmp_path / "go.mod").write_text("module example")
        assert "go-test" in detect_test_frameworks(tmp_path)

    def test_detect_test_frameworks__empty_repo(self, tmp_path: Path) -> None:
        assert detect_test_frameworks(tmp_path) == []

    def test_detect_test_frameworks__vitest_over_jest(self, tmp_path: Path) -> None:
        """When vitest is present, jest should not be detected even if markers exist."""
        (tmp_path / "vitest.config.ts").write_text("export default {}")
        (tmp_path / "jest.config.js").write_text("module.exports = {}")
        frameworks = detect_test_frameworks(tmp_path)
        assert "vitest" in frameworks
        assert "jest" not in frameworks


# ---------------------------------------------------------------------------
# detect_ci_systems
# ---------------------------------------------------------------------------


class TestDetectCiSystems:
    """Tests for manifest.detect_ci_systems."""

    def test_detect_ci_systems__github_actions(self, tmp_path: Path) -> None:
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        assert "github-actions" in detect_ci_systems(tmp_path)

    def test_detect_ci_systems__gitlab(self, tmp_path: Path) -> None:
        (tmp_path / ".gitlab-ci.yml").write_text("stages: []")
        assert "gitlab-ci" in detect_ci_systems(tmp_path)

    def test_detect_ci_systems__none(self, tmp_path: Path) -> None:
        assert detect_ci_systems(tmp_path) == []


# ---------------------------------------------------------------------------
# detect_sub_projects
# ---------------------------------------------------------------------------


class TestDetectSubProjects:
    """Tests for manifest.detect_sub_projects."""

    def test_detect_sub_projects__npm_workspaces_list(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"workspaces": ["packages/*", "apps/*"]})
        )
        result = detect_sub_projects(tmp_path)
        assert len(result) == 2
        assert result[0]["name"] == "packages/*"

    def test_detect_sub_projects__npm_workspaces_dict(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"workspaces": {"packages": ["lib/*"]}})
        )
        result = detect_sub_projects(tmp_path)
        assert len(result) == 1
        assert result[0]["name"] == "lib/*"

    def test_detect_sub_projects__cargo_workspace(self, tmp_path: Path) -> None:
        cargo_content = '[workspace]\nmembers = [\n    "crate-a",\n    "crate-b",\n]\n'
        (tmp_path / "Cargo.toml").write_text(cargo_content)
        result = detect_sub_projects(tmp_path)
        names = [sp["name"] for sp in result]
        assert "crate-a" in names
        assert "crate-b" in names

    def test_detect_sub_projects__python_namespace(self, tmp_path: Path) -> None:
        sub = tmp_path / "my_subpackage"
        sub.mkdir()
        (sub / "pyproject.toml").write_text("[project]")
        result = detect_sub_projects(tmp_path)
        assert any(sp["name"] == "my_subpackage" for sp in result)

    def test_detect_sub_projects__ignores_dotdirs(self, tmp_path: Path) -> None:
        hidden = tmp_path / ".hidden"
        hidden.mkdir()
        (hidden / "pyproject.toml").write_text("[project]")
        result = detect_sub_projects(tmp_path)
        assert not any(sp["name"] == ".hidden" for sp in result)

    def test_detect_sub_projects__ignores_venv(self, tmp_path: Path) -> None:
        venv = tmp_path / "venv"
        venv.mkdir()
        (venv / "pyproject.toml").write_text("[project]")
        result = detect_sub_projects(tmp_path)
        assert not any(sp["name"] == "venv" for sp in result)

    def test_detect_sub_projects__empty_repo(self, tmp_path: Path) -> None:
        assert detect_sub_projects(tmp_path) == []


# ---------------------------------------------------------------------------
# detect_key_docs
# ---------------------------------------------------------------------------


class TestDetectKeyDocs:
    """Tests for manifest.detect_key_docs."""

    def test_detect_key_docs__readme(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello")
        assert "README.md" in detect_key_docs(tmp_path)

    def test_detect_key_docs__multiple(self, tmp_path: Path) -> None:
        (tmp_path / "README.md").write_text("# Hello")
        (tmp_path / "LICENSE").write_text("MIT")
        (tmp_path / "CLAUDE.md").write_text("# Claude instructions")
        docs = detect_key_docs(tmp_path)
        assert "README.md" in docs
        assert "LICENSE" in docs
        assert "CLAUDE.md" in docs

    def test_detect_key_docs__none(self, tmp_path: Path) -> None:
        assert detect_key_docs(tmp_path) == []


# ---------------------------------------------------------------------------
# build_manifest_markdown
# ---------------------------------------------------------------------------


class TestBuildManifestMarkdown:
    """Tests for manifest.build_manifest_markdown."""

    def test_build_manifest_markdown__python_project(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]")
        (tmp_path / "Makefile").write_text("all:")
        (tmp_path / "README.md").write_text("# Project")
        (tmp_path / ".github" / "workflows").mkdir(parents=True)

        md = build_manifest_markdown(tmp_path)

        assert "## Project Manifest" in md
        assert "python" in md
        assert "make" in md
        assert "pytest" in md
        assert "github-actions" in md
        assert "README.md" in md

    def test_build_manifest_markdown__empty_repo(self, tmp_path: Path) -> None:
        md = build_manifest_markdown(tmp_path)
        assert "## Project Manifest" in md
        assert "unknown" in md

    def test_build_manifest_markdown__with_sub_projects(self, tmp_path: Path) -> None:
        (tmp_path / "package.json").write_text(
            json.dumps({"workspaces": ["packages/a"]})
        )
        md = build_manifest_markdown(tmp_path)
        assert "### Sub-projects" in md
        assert "packages/a" in md


# ---------------------------------------------------------------------------
# ProjectManifestManager
# ---------------------------------------------------------------------------


class TestProjectManifestManager:
    """Tests for the ProjectManifestManager class."""

    def test_manifest_manager__scan(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        content = manager.scan()
        assert "python" in content

    def test_manifest_manager__write_and_read(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        content = "## Test Manifest\npython, make"
        digest_hash = manager.write(content)
        assert len(digest_hash) == 16
        assert manager.manifest_path.read_text() == content

    def test_manifest_manager__needs_refresh_no_file(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        assert manager.needs_refresh("abc") is True

    def test_manifest_manager__needs_refresh_hash_mismatch(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        content = "old content"
        manager.write(content)
        assert manager.needs_refresh("wrong_hash") is True

    def test_manifest_manager__needs_refresh_hash_match(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        content = "stable content"
        digest_hash = manager.write(content)
        assert manager.needs_refresh(digest_hash) is False

    def test_manifest_manager__refresh(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("[project]")
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        content, digest_hash = manager.refresh()
        assert "python" in content
        assert len(digest_hash) == 16
        assert manager.manifest_path.read_text() == content

    def test_manifest_manager__manifest_path(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manager = ProjectManifestManager(config)
        expected = tmp_path / ".hydraflow" / "memory" / "manifest.md"
        assert manager.manifest_path == expected


# ---------------------------------------------------------------------------
# load_project_manifest
# ---------------------------------------------------------------------------


class TestLoadProjectManifest:
    """Tests for the load_project_manifest prompt injection helper."""

    def test_load_project_manifest__missing_file(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        assert load_project_manifest(config) == ""

    def test_load_project_manifest__empty_file(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manifest_path = tmp_path / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("   \n  ")
        assert load_project_manifest(config) == ""

    def test_load_project_manifest__valid_content(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        manifest_path = tmp_path / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("## Project Manifest\npython, make")
        result = load_project_manifest(config)
        assert "python" in result

    def test_load_project_manifest__truncation(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path, max_manifest_prompt_chars=200)
        manifest_path = tmp_path / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True)
        manifest_path.write_text("x" * 500)
        result = load_project_manifest(config)
        assert len(result) < 500
        assert "...(truncated)" in result


# ---------------------------------------------------------------------------
# State tracking integration
# ---------------------------------------------------------------------------


class TestManifestStateTracking:
    """Tests for manifest state tracking in StateTracker."""

    def test_state__update_and_get_manifest_state(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        state.update_manifest_state("abc123")
        manifest_hash, last_updated = state.get_manifest_state()
        assert manifest_hash == "abc123"
        assert last_updated is not None

    def test_state__default_manifest_state(self, tmp_path: Path) -> None:
        state = StateTracker(tmp_path / "state.json")
        manifest_hash, last_updated = state.get_manifest_state()
        assert manifest_hash == ""
        assert last_updated is None

    def test_state__manifest_state_persists(self, tmp_path: Path) -> None:
        state_file = tmp_path / "state.json"
        state = StateTracker(state_file)
        state.update_manifest_state("hash456")

        # Reload from disk
        state2 = StateTracker(state_file)
        manifest_hash, last_updated = state2.get_manifest_state()
        assert manifest_hash == "hash456"
        assert last_updated is not None


# ---------------------------------------------------------------------------
# Config fields
# ---------------------------------------------------------------------------


class TestManifestConfig:
    """Tests for manifest-related config fields."""

    def test_config__manifest_refresh_interval_default(self) -> None:
        config = ConfigFactory.create()
        assert config.manifest_refresh_interval == 3600

    def test_config__max_manifest_prompt_chars_default(self) -> None:
        config = ConfigFactory.create()
        assert config.max_manifest_prompt_chars == 2000

    def test_config__manifest_refresh_interval_custom(self) -> None:
        config = ConfigFactory.create(manifest_refresh_interval=600)
        assert config.manifest_refresh_interval == 600

    def test_config__max_manifest_prompt_chars_custom(self) -> None:
        config = ConfigFactory.create(max_manifest_prompt_chars=5000)
        assert config.max_manifest_prompt_chars == 5000


# ---------------------------------------------------------------------------
# Prompt injection in agent runners
# ---------------------------------------------------------------------------


class TestManifestInjectionInRunners:
    """Verify that all agent runners inject ## Project Context when manifest exists."""

    def test_agent_runner__injects_manifest(self, tmp_path: Path) -> None:
        """AgentRunner._build_prompt includes ## Project Context from manifest."""
        from agent import AgentRunner
        from events import EventBus

        config = ConfigFactory.create(repo_root=tmp_path)
        config.repo_root.mkdir(parents=True, exist_ok=True)
        manifest_path = config.repo_root / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("## Project Manifest\npython, make")

        runner = AgentRunner(config, EventBus())
        from models import GitHubIssue

        issue = GitHubIssue(
            number=1,
            title="Test",
            body="body",
            labels=[],
            comments=[],
        )
        prompt = runner._build_prompt(issue)
        assert "## Project Context" in prompt
        assert "python, make" in prompt

    def test_hitl_runner__injects_manifest(self, tmp_path: Path) -> None:
        """HITLRunner._build_prompt includes ## Project Context from manifest."""
        from events import EventBus
        from hitl_runner import HITLRunner

        config = ConfigFactory.create(repo_root=tmp_path)
        config.repo_root.mkdir(parents=True, exist_ok=True)
        manifest_path = config.repo_root / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("## Project Manifest\nrust, cargo")

        runner = HITLRunner(config, EventBus())
        from models import GitHubIssue

        issue = GitHubIssue(
            number=1,
            title="Test",
            body="body",
            labels=[],
            comments=[],
        )
        prompt = runner._build_prompt(issue, "fix it", "CI failed")
        assert "## Project Context" in prompt
        assert "rust, cargo" in prompt

    def test_conflict_prompt__injects_manifest_with_config(
        self, tmp_path: Path
    ) -> None:
        """build_conflict_prompt includes ## Project Context when config is given."""
        from conflict_prompt import build_conflict_prompt

        config = ConfigFactory.create(repo_root=tmp_path)
        config.repo_root.mkdir(parents=True, exist_ok=True)
        manifest_path = config.repo_root / ".hydraflow" / "memory" / "manifest.md"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("## Project Manifest\ngo, make")

        prompt = build_conflict_prompt(
            "https://github.com/org/repo/issues/1",
            "https://github.com/org/repo/pull/2",
            None,
            1,
            config=config,
        )
        assert "## Project Context" in prompt
        assert "go, make" in prompt

    def test_conflict_prompt__omits_manifest_without_config(self) -> None:
        """build_conflict_prompt omits ## Project Context without config."""
        from conflict_prompt import build_conflict_prompt

        prompt = build_conflict_prompt(
            "https://github.com/org/repo/issues/1",
            "https://github.com/org/repo/pull/2",
            None,
            1,
        )
        assert "## Project Context" not in prompt


# ---------------------------------------------------------------------------
# Marker consolidation verification
# ---------------------------------------------------------------------------


class TestMarkerConsolidation:
    """Verify that scaffold modules import markers from manifest.py."""

    def test_ci_scaffold__uses_manifest_markers(self) -> None:
        from ci_scaffold import _JS_MARKERS, _PYTHON_MARKERS
        from manifest import JS_MARKERS, PYTHON_MARKERS

        assert tuple(_PYTHON_MARKERS) == tuple(PYTHON_MARKERS)
        assert tuple(_JS_MARKERS) == tuple(JS_MARKERS)

    def test_lint_scaffold__uses_manifest_markers(self) -> None:
        from lint_scaffold import _JS_MARKERS, _PYTHON_MARKERS
        from manifest import JS_MARKERS, PYTHON_MARKERS

        assert set(_PYTHON_MARKERS) == set(PYTHON_MARKERS)
        assert set(_JS_MARKERS) == set(JS_MARKERS)

    def test_makefile_scaffold__uses_manifest_markers(self) -> None:
        from makefile_scaffold import _JS_MARKERS, _PYTHON_MARKERS
        from manifest import JS_MARKERS, PYTHON_MARKERS

        assert tuple(_PYTHON_MARKERS) == tuple(PYTHON_MARKERS)
        assert tuple(_JS_MARKERS) == tuple(JS_MARKERS)

    def test_prep_hooks__uses_manifest_markers(self) -> None:
        from manifest import PYTHON_MARKERS
        from prep_hooks import _PYTHON_MARKERS

        assert tuple(_PYTHON_MARKERS) == tuple(PYTHON_MARKERS)
