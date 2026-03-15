"""Tests for the BeadsManager — bd CLI wrapper and integration points."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from beads_manager import BeadsManager, BeadsNotInstalledError, BeadTask
from task_graph import TaskGraphPhase


@pytest.fixture()
def manager():
    return BeadsManager()


# ---------------------------------------------------------------------------
# check_available — raises if bd not installed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_ensure_installed_already_available(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = ""
        await manager.ensure_installed()
        mock_run.assert_called_once_with("bd", "status", timeout=10.0)


@pytest.mark.asyncio()
async def test_ensure_installed_auto_installs(manager):
    call_count = 0

    async def mock_run(*args, **_kwargs):
        nonlocal call_count
        call_count += 1
        cmd = list(args)
        if cmd[0] == "bd" and call_count == 1:
            raise FileNotFoundError("bd not found")
        if cmd[0] == "npm":
            return "installed"
        return ""  # second bd status call succeeds

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        await manager.ensure_installed()

    # Should have called: bd status (fail), npm install, bd status (success)
    assert call_count == 3


@pytest.mark.asyncio()
async def test_ensure_installed_no_npm_raises(manager):
    async def mock_run(*args, **_kwargs):
        cmd = list(args)
        if cmd[0] == "bd":
            raise FileNotFoundError("bd not found")
        if cmd[0] == "npm":
            raise FileNotFoundError("npm not found")
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        with pytest.raises(BeadsNotInstalledError, match="npm is not installed"):
            await manager.ensure_installed()


@pytest.mark.asyncio()
async def test_ensure_installed_npm_fails_to_install(manager):
    call_count = 0

    async def mock_run(*args, **_kwargs):
        nonlocal call_count
        call_count += 1
        cmd = list(args)
        if cmd[0] == "bd":
            raise FileNotFoundError("bd not found")
        if cmd[0] == "npm":
            return "installed"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        with pytest.raises(BeadsNotInstalledError):
            await manager.ensure_installed()


# ---------------------------------------------------------------------------
# init — raises on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Initialized"
        await manager.init(Path("/repo"))
        mock_run.assert_called_once_with("bd", "init", cwd=Path("/repo"), timeout=30.0)


@pytest.mark.asyncio()
async def test_init_not_installed(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FileNotFoundError("bd not found")
        with pytest.raises(BeadsNotInstalledError):
            await manager.init(Path("/repo"))


@pytest.mark.asyncio()
async def test_init_runtime_error(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("dolt error")
        with pytest.raises(RuntimeError, match="dolt error"):
            await manager.init(Path("/repo"))


# ---------------------------------------------------------------------------
# create_task — `bd create "title" -p <priority> --silent`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_task_returns_id(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "myrepo-4yu"
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result == "myrepo-4yu"
        mock_run.assert_called_once_with(
            "bd",
            "create",
            "My task",
            "-p",
            "0",
            "--silent",
            cwd=Path("/repo"),
            timeout=30.0,
        )


@pytest.mark.asyncio()
async def test_create_task_empty_output_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "  \n"
        with pytest.raises(RuntimeError, match="empty output"):
            await manager.create_task("My task", "0", Path("/repo"))


@pytest.mark.asyncio()
async def test_create_task_failure_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        with pytest.raises(RuntimeError):
            await manager.create_task("My task", "0", Path("/repo"))


# ---------------------------------------------------------------------------
# add_dependency — `bd dep add <child> <parent>`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_add_dependency_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Added dependency"
        await manager.add_dependency("repo-z2o", "repo-4yu", Path("/repo"))
        mock_run.assert_called_once_with(
            "bd",
            "dep",
            "add",
            "repo-z2o",
            "repo-4yu",
            cwd=Path("/repo"),
            timeout=30.0,
        )


@pytest.mark.asyncio()
async def test_add_dependency_failure_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        with pytest.raises(RuntimeError):
            await manager.add_dependency("repo-z2o", "repo-4yu", Path("/repo"))


# ---------------------------------------------------------------------------
# claim — `bd update <id> --claim`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_claim_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Updated"
        await manager.claim("repo-4yu", Path("/repo"))
        mock_run.assert_called_once_with(
            "bd",
            "update",
            "repo-4yu",
            "--claim",
            cwd=Path("/repo"),
            timeout=30.0,
        )


@pytest.mark.asyncio()
async def test_claim_failure_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = OSError("disk error")
        with pytest.raises(OSError):
            await manager.claim("repo-4yu", Path("/repo"))


# ---------------------------------------------------------------------------
# close — `bd close <id> --reason "message"`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_close_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Closed"
        await manager.close("repo-4yu", "Phase complete", Path("/repo"))
        mock_run.assert_called_once_with(
            "bd",
            "close",
            "repo-4yu",
            "--reason",
            "Phase complete",
            cwd=Path("/repo"),
            timeout=30.0,
        )


@pytest.mark.asyncio()
async def test_close_failure_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        with pytest.raises(RuntimeError):
            await manager.close("repo-4yu", "done", Path("/repo"))


# ---------------------------------------------------------------------------
# list_ready — `bd ready --json`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_ready_json(manager):
    json_output = json.dumps(
        [
            {
                "id": "repo-4yu",
                "title": "P1 — Data Model",
                "status": "open",
                "priority": 0,
                "dependency_count": 0,
            },
            {
                "id": "repo-z2o",
                "title": "P2 — API Layer",
                "status": "open",
                "priority": 1,
                "dependencies": [
                    {
                        "issue_id": "repo-z2o",
                        "depends_on_id": "repo-4yu",
                        "type": "blocks",
                    }
                ],
            },
        ]
    )
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = json_output
        result = await manager.list_ready(Path("/repo"))

    assert len(result) == 2
    assert result[0].id == "repo-4yu"
    assert result[0].priority == 0
    assert result[0].depends_on == []
    assert result[1].id == "repo-z2o"
    assert result[1].depends_on == ["repo-4yu"]


@pytest.mark.asyncio()
async def test_list_ready_empty(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "[]"
        assert await manager.list_ready(Path("/repo")) == []


@pytest.mark.asyncio()
async def test_list_ready_invalid_json_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "not json"
        with pytest.raises(json.JSONDecodeError):
            await manager.list_ready(Path("/repo"))


# ---------------------------------------------------------------------------
# show — `bd show <id> --json`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_show_json(manager):
    json_output = json.dumps(
        {
            "id": "repo-4yu",
            "title": "P1 — Data Model",
            "status": "in_progress",
            "priority": 0,
            "dependencies": [
                {"issue_id": "repo-4yu", "depends_on_id": "repo-abc", "type": "blocks"}
            ],
        }
    )
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = json_output
        result = await manager.show("repo-4yu", Path("/repo"))

    assert result.id == "repo-4yu"
    assert result.status == "in_progress"
    assert result.depends_on == ["repo-abc"]


@pytest.mark.asyncio()
async def test_show_list_format(manager):
    json_output = json.dumps(
        [{"id": "repo-4yu", "title": "My task", "status": "open", "priority": 2}]
    )
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = json_output
        result = await manager.show("repo-4yu", Path("/repo"))
    assert result.id == "repo-4yu"


@pytest.mark.asyncio()
async def test_show_empty_list_raises(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "[]"
        with pytest.raises(RuntimeError, match="unparseable"):
            await manager.show("repo-4yu", Path("/repo"))


# ---------------------------------------------------------------------------
# create_from_phases — creates tasks + wires deps, raises on failure
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_from_phases(manager):
    phases = [
        TaskGraphPhase(
            id="P1",
            name="P1 — Data Model",
            files=["src/model.py"],
            tests=["test model"],
            depends_on=[],
        ),
        TaskGraphPhase(
            id="P2",
            name="P2 — API",
            files=["src/api.py"],
            tests=["test api"],
            depends_on=["P1"],
        ),
    ]

    call_count = 0

    async def mock_run(*args, **_kwargs):
        nonlocal call_count
        call_count += 1
        cmd_args = list(args)
        if "create" in cmd_args:
            return f"repo-id{call_count}"
        return "ok"

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    assert mapping == {"P1": "repo-id1", "P2": "repo-id2"}
    create_calls = [c for c in mock_run_fn.call_args_list if "create" in list(c.args)]
    assert create_calls[0].args[4] == "0"  # P1 no deps → priority 0
    assert create_calls[1].args[4] == "1"  # P2 has deps → priority 1
    assert create_calls[0].args[5] == "--silent"


@pytest.mark.asyncio()
async def test_create_from_phases_failure_raises(manager):
    phases = [
        TaskGraphPhase(id="P1", name="P1", files=[], tests=[], depends_on=[]),
    ]
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("bd not running")
        with pytest.raises(RuntimeError):
            await manager.create_from_phases(phases, 42, Path("/repo"))


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


def test_parse_ready_json_with_deps():
    data = json.dumps(
        [
            {"id": "r-a1", "title": "Task A", "status": "open", "priority": 0},
            {
                "id": "r-b2",
                "title": "Task B",
                "status": "open",
                "priority": 1,
                "dependencies": [{"depends_on_id": "r-a1", "type": "blocks"}],
            },
        ]
    )
    tasks = BeadsManager._parse_ready_json(data)
    assert len(tasks) == 2
    assert tasks[0] == BeadTask(id="r-a1", title="Task A", status="open", priority=0)
    assert tasks[1].depends_on == ["r-a1"]


def test_parse_show_json_single():
    data = json.dumps(
        {"id": "r-a1", "title": "Task", "status": "closed", "priority": 0}
    )
    task = BeadsManager._parse_show_json(data)
    assert task is not None
    assert task.id == "r-a1"


def test_parse_show_json_empty_list():
    assert BeadsManager._parse_show_json("[]") is None


# ---------------------------------------------------------------------------
# State roundtrip
# ---------------------------------------------------------------------------


def test_bead_mapping_state_roundtrip(tmp_path):
    from state import StateTracker

    state_file = tmp_path / "state.json"
    tracker = StateTracker(state_file)

    mapping = {"P1": "repo-4yu", "P2": "repo-z2o"}
    tracker.set_bead_mapping(42, mapping)
    assert tracker.get_bead_mapping(42) == mapping
    assert tracker.get_bead_mapping(999) == {}

    tracker2 = StateTracker(state_file)
    assert tracker2.get_bead_mapping(42) == mapping


# ===========================================================================
# Integration tests — plan_phase creates beads after planning
# ===========================================================================

_TASK_GRAPH_PLAN = (
    "## Task Graph\n\n"
    "### P1 \u2014 Model\n"
    "**Files:** src/models.py\n"
    "**Tests:**\n- Widget persists\n"
    "**Depends on:** (none)\n\n"
    "### P2 \u2014 API\n"
    "**Files:** src/api.py\n"
    "**Tests:**\n- GET returns list\n"
    "**Depends on:** P1\n"
)


class TestPlanPhaseBeadsIntegration:
    @pytest.mark.asyncio()
    async def test_creates_beads_and_posts_mapping(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.create_from_phases = AsyncMock(
            return_value={"P1": "repo-4yu", "P2": "repo-z2o"}
        )
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        )
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        mock_beads.init.assert_awaited_once()
        mock_beads.create_from_phases.assert_awaited_once()
        assert state.get_bead_mapping(42) == {"P1": "repo-4yu", "P2": "repo-z2o"}

        bead_comments = [
            c for c in prs.post_comment.call_args_list if "Bead Task Mapping" in str(c)
        ]
        assert len(bead_comments) == 1
        assert "| P1 | #repo-4yu |" in bead_comments[0].args[1]

    @pytest.mark.asyncio()
    async def test_no_beads_without_manager(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, _prs, store, _stop = make_plan_phase(config)
        # beads_manager is None by default in make_plan_phase
        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        )
        store.get_plannable = supply_once([issue])
        await phase.plan_issues()
        assert state.get_bead_mapping(42) == {}

    @pytest.mark.asyncio()
    async def test_no_beads_without_task_graph(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, _prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(
                success=True, plan="## Plan\n\n1. Do the thing\n"
            )
        )
        store.get_plannable = supply_once([issue])
        await phase.plan_issues()

        mock_beads.init.assert_not_awaited()
        assert state.get_bead_mapping(42) == {}

    @pytest.mark.asyncio()
    async def test_comment_failure_does_not_crash(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.create_from_phases = AsyncMock(return_value={"P1": "repo-4yu"})
        phase._beads_manager = mock_beads

        original_post = prs.post_comment

        async def selective_fail(issue_id, body, *args, **kwargs):
            if "Bead Task Mapping" in body:
                raise RuntimeError("GitHub API error")
            return await original_post(issue_id, body, *args, **kwargs)

        prs.post_comment = AsyncMock(side_effect=selective_fail)
        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        )
        store.get_plannable = supply_once([issue])

        results = await phase.plan_issues()
        assert state.get_bead_mapping(42) == {"P1": "repo-4yu"}
        assert len(results) == 1


# ===========================================================================
# Integration tests — agent prompt with bead_mapping
# ===========================================================================


class TestAgentBeadPromptIntegration:
    def test_injects_claim_and_close(self, config, event_bus) -> None:
        from agent import AgentRunner
        from models import Task

        issue = Task(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(
            issue, bead_mapping={"P1": "repo-4yu", "P2": "repo-z2o"}
        )

        assert "**Bead:** #repo-4yu" in prompt
        assert "bd update repo-4yu --claim" in prompt
        assert 'bd close repo-4yu --reason "Phase complete"' in prompt
        assert "bd update repo-z2o --claim" in prompt

    def test_no_commands_without_mapping(self, config, event_bus) -> None:
        from agent import AgentRunner
        from models import Task

        issue = Task(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(issue, bead_mapping=None)

        assert "bd update" not in prompt
        assert "bd close" not in prompt

    def test_partial_mapping(self, config, event_bus) -> None:
        from agent import AgentRunner
        from models import Task

        issue = Task(
            id=10,
            title="Add widget",
            body="Need widgets",
            comments=["## Implementation Plan\n\n" + _TASK_GRAPH_PLAN],
        )
        runner = AgentRunner(config, event_bus)
        prompt, _ = runner._build_prompt_with_stats(
            issue, bead_mapping={"P1": "repo-4yu"}
        )

        assert "**Bead:** #repo-4yu" in prompt
        assert "repo-z2o" not in prompt


# ===========================================================================
# Integration tests — implement_phase bead mapping passthrough
# ===========================================================================


class TestImplementPhaseBeadsIntegration:
    @pytest.mark.asyncio()
    async def test_passes_mapping_to_agent(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, worktree_path=str(wt_path)
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)

        mock_beads = AsyncMock()
        phase._beads_manager = mock_beads
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu"})

        await phase.run_batch()

        assert captured[0]["bead_mapping"] == {"P1": "repo-4yu"}
        mock_beads.init.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_no_mapping_without_manager(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, worktree_path=str(wt_path)
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        await phase.run_batch()
        assert "bead_mapping" not in captured[0]

    @pytest.mark.asyncio()
    async def test_no_mapping_when_state_empty(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id, success=True, worktree_path=str(wt_path)
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)
        mock_beads = AsyncMock()
        phase._beads_manager = mock_beads

        await phase.run_batch()
        assert "bead_mapping" not in captured[0]
        mock_beads.init.assert_not_awaited()


# ===========================================================================
# Integration tests — reviewer per-bead review section
# ===========================================================================


class TestReviewerBeadPromptIntegration:
    def test_adds_per_bead_section(self, config, event_bus) -> None:
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        pr = PRInfo(number=101, branch="agent/issue-42", issue_number=42)
        issue = Task(id=42, title="Add widget", body="Need widgets")
        diff = "diff --git a/src/models.py b/src/models.py\n+class Widget:\n"

        prompt, _ = runner._build_review_prompt_with_stats(
            pr,
            issue,
            diff,
            bead_tasks=[
                {
                    "id": "repo-4yu",
                    "phase": "P1",
                    "status": "closed",
                    "files": "src/models.py",
                    "tests": "Widget persists",
                }
            ],
        )
        assert "## Per-Bead Review" in prompt
        assert "Bead #repo-4yu" in prompt

    def test_no_section_without_tasks(self, config, event_bus) -> None:
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        prompt, _ = runner._build_review_prompt_with_stats(
            PRInfo(number=101, branch="x", issue_number=42),
            Task(id=42, title="Fix", body="b"),
            "diff --git a/x b/x\n+y\n",
            bead_tasks=None,
        )
        assert "## Per-Bead Review" not in prompt


# ===========================================================================
# Integration tests — review_phase bead context builder
# ===========================================================================


class TestReviewPhaseBeadContext:
    def test_builds_context_from_mapping(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu", "P2": "repo-z2o"})

        issue = Task(id=42, title="Widget", body="body", comments=[_TASK_GRAPH_PLAN])
        result = phase._build_bead_review_context(issue)

        assert result is not None
        assert len(result) == 2
        p1 = next(b for b in result if b["phase"] == "P1")
        assert p1["id"] == "repo-4yu"
        assert "src/models.py" in str(p1["files"])

    def test_none_when_no_mapping(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        assert (
            phase._build_bead_review_context(Task(id=999, title="T", body="b")) is None
        )

    def test_n_a_without_plan_comments(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu"})

        result = phase._build_bead_review_context(
            Task(id=42, title="T", body="b", comments=[])
        )
        assert result is not None
        assert result[0]["files"] == "N/A"
        assert result[0]["tests"] == "N/A"
