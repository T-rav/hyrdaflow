"""Tests for the BeadsManager — bd CLI wrapper and integration points."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from beads_manager import BeadsManager, BeadTask
from task_graph import TaskGraphPhase


@pytest.fixture()
def _enabled_config():
    """Return a mock config with beads_enabled=True."""
    cfg = AsyncMock()
    cfg.beads_enabled = True
    return cfg


@pytest.fixture()
def _disabled_config():
    """Return a mock config with beads_enabled=False."""
    cfg = AsyncMock()
    cfg.beads_enabled = False
    return cfg


@pytest.fixture()
def manager(_enabled_config):
    return BeadsManager(_enabled_config)


@pytest.fixture()
def disabled_manager(_disabled_config):
    return BeadsManager(_disabled_config)


# ---------------------------------------------------------------------------
# No-op when disabled
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_disabled_is_available(disabled_manager):
    assert await disabled_manager.is_available() is False


@pytest.mark.asyncio()
async def test_disabled_init(disabled_manager):
    assert await disabled_manager.init(Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_create_task(disabled_manager):
    assert await disabled_manager.create_task("title", "0", Path("/tmp")) is None


@pytest.mark.asyncio()
async def test_disabled_add_dependency(disabled_manager):
    assert await disabled_manager.add_dependency("x-a1", "x-b2", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_claim(disabled_manager):
    assert await disabled_manager.claim("x-a1", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_close(disabled_manager):
    assert await disabled_manager.close("x-a1", "done", Path("/tmp")) is False


@pytest.mark.asyncio()
async def test_disabled_list_ready(disabled_manager):
    assert await disabled_manager.list_ready(Path("/tmp")) == []


@pytest.mark.asyncio()
async def test_disabled_show(disabled_manager):
    assert await disabled_manager.show("x-a1", Path("/tmp")) is None


@pytest.mark.asyncio()
async def test_disabled_create_from_phases(disabled_manager):
    phases = [
        TaskGraphPhase(id="P1", name="P1 — Setup", files=[], tests=[], depends_on=[])
    ]
    assert await disabled_manager.create_from_phases(phases, 42, Path("/tmp")) == {}


# ---------------------------------------------------------------------------
# is_available — uses `bd status` as a liveness check
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_is_available_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = ""
        assert await manager.is_available() is True
        mock_run.assert_called_once_with("bd", "status", timeout=10.0)


@pytest.mark.asyncio()
async def test_is_available_not_installed(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FileNotFoundError("bd not found")
        assert await manager.is_available() is False


@pytest.mark.asyncio()
async def test_is_available_runtime_error(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("command failed")
        assert await manager.is_available() is False


# ---------------------------------------------------------------------------
# init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_init_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Initialized"
        assert await manager.init(Path("/repo")) is True
        mock_run.assert_called_once_with("bd", "init", cwd=Path("/repo"), timeout=30.0)


@pytest.mark.asyncio()
async def test_init_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.init(Path("/repo")) is False


# ---------------------------------------------------------------------------
# create_task — uses `bd create "title" -p <priority> --silent`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_task_silent_output(manager):
    """bd create --silent outputs only the bead ID."""
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
async def test_create_task_empty_output(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "  \n"
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result is None


@pytest.mark.asyncio()
async def test_create_task_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        result = await manager.create_task("My task", "0", Path("/repo"))
        assert result is None


# ---------------------------------------------------------------------------
# add_dependency — `bd dep add <child> <parent>`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_add_dependency_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Added dependency"
        assert (
            await manager.add_dependency("repo-z2o", "repo-4yu", Path("/repo")) is True
        )
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
async def test_add_dependency_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert (
            await manager.add_dependency("repo-z2o", "repo-4yu", Path("/repo")) is False
        )


# ---------------------------------------------------------------------------
# claim — `bd update <id> --claim`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_claim_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Updated"
        assert await manager.claim("repo-4yu", Path("/repo")) is True
        mock_run.assert_called_once_with(
            "bd",
            "update",
            "repo-4yu",
            "--claim",
            cwd=Path("/repo"),
            timeout=30.0,
        )


@pytest.mark.asyncio()
async def test_claim_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = OSError("disk error")
        assert await manager.claim("repo-4yu", Path("/repo")) is False


# ---------------------------------------------------------------------------
# close — `bd close <id> --reason "message"`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_close_success(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "Closed"
        assert await manager.close("repo-4yu", "Phase complete", Path("/repo")) is True
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
async def test_close_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.close("repo-4yu", "done", Path("/repo")) is False


# ---------------------------------------------------------------------------
# list_ready — `bd ready --json`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_list_ready_json(manager):
    """Parses actual bd ready --json output format."""
    json_output = json.dumps(
        [
            {
                "id": "repo-4yu",
                "title": "Issue #42 — P1 — Data Model",
                "status": "open",
                "priority": 0,
                "issue_type": "task",
                "dependency_count": 0,
            },
            {
                "id": "repo-z2o",
                "title": "Issue #42 — P2 — API Layer",
                "status": "open",
                "priority": 1,
                "dependencies": [
                    {
                        "issue_id": "repo-z2o",
                        "depends_on_id": "repo-4yu",
                        "type": "blocks",
                    }
                ],
                "dependency_count": 1,
            },
        ]
    )
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = json_output
        result = await manager.list_ready(Path("/repo"))

    assert len(result) == 2
    assert result[0].id == "repo-4yu"
    assert result[0].title == "Issue #42 — P1 — Data Model"
    assert result[0].status == "open"
    assert result[0].priority == 0
    assert result[0].depends_on == []
    assert result[1].id == "repo-z2o"
    assert result[1].depends_on == ["repo-4yu"]
    mock_run.assert_called_once_with(
        "bd",
        "ready",
        "--json",
        cwd=Path("/repo"),
        timeout=30.0,
    )


@pytest.mark.asyncio()
async def test_list_ready_empty_json(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "[]"
        assert await manager.list_ready(Path("/repo")) == []


@pytest.mark.asyncio()
async def test_list_ready_invalid_json(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "not json"
        assert await manager.list_ready(Path("/repo")) == []


@pytest.mark.asyncio()
async def test_list_ready_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = RuntimeError("failed")
        assert await manager.list_ready(Path("/repo")) == []


# ---------------------------------------------------------------------------
# show — `bd show <id> --json`
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_show_json(manager):
    """Parses actual bd show --json output format."""
    json_output = json.dumps(
        {
            "id": "repo-4yu",
            "title": "Issue #42 — P1 — Data Model",
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

    assert result is not None
    assert result.id == "repo-4yu"
    assert result.title == "Issue #42 — P1 — Data Model"
    assert result.status == "in_progress"
    assert result.priority == 0
    assert result.depends_on == ["repo-abc"]
    mock_run.assert_called_once_with(
        "bd",
        "show",
        "repo-4yu",
        "--json",
        cwd=Path("/repo"),
        timeout=30.0,
    )


@pytest.mark.asyncio()
async def test_show_json_list_format(manager):
    """bd show --json may return a list with one item."""
    json_output = json.dumps(
        [
            {
                "id": "repo-4yu",
                "title": "My task",
                "status": "open",
                "priority": 2,
            }
        ]
    )
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = json_output
        result = await manager.show("repo-4yu", Path("/repo"))

    assert result is not None
    assert result.id == "repo-4yu"


@pytest.mark.asyncio()
async def test_show_invalid_json(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.return_value = "not json"
        assert await manager.show("repo-4yu", Path("/repo")) is None


@pytest.mark.asyncio()
async def test_show_failure(manager):
    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run:
        mock_run.side_effect = FileNotFoundError("not found")
        assert await manager.show("repo-4yu", Path("/repo")) is None


# ---------------------------------------------------------------------------
# create_from_phases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio()
async def test_create_from_phases(manager):
    phases = [
        TaskGraphPhase(
            id="P1",
            name="P1 — Data Model",
            files=["src/model.py"],
            tests=["test model creation"],
            depends_on=[],
        ),
        TaskGraphPhase(
            id="P2",
            name="P2 — API Layer",
            files=["src/api.py"],
            tests=["test api endpoint"],
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
        if "dep" in cmd_args:
            return "Added dependency"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    assert "P1" in mapping
    assert "P2" in mapping
    assert len(mapping) == 2
    # Verify priority: P1 no deps → "0", P2 has deps → "1"
    create_calls = [c for c in mock_run_fn.call_args_list if "create" in list(c.args)]
    assert create_calls[0].args[4] == "0"  # -p 0 for P1
    assert create_calls[1].args[4] == "1"  # -p 1 for P2
    # Verify --silent flag is used
    assert create_calls[0].args[5] == "--silent"


@pytest.mark.asyncio()
async def test_create_from_phases_partial_failure(manager):
    """Partial failures during bead creation are handled gracefully."""
    phases = [
        TaskGraphPhase(id="P1", name="P1 — Model", files=[], tests=[], depends_on=[]),
        TaskGraphPhase(id="P2", name="P2 — API", files=[], tests=[], depends_on=["P1"]),
    ]

    async def mock_run(*args, **_kwargs):
        cmd_args = list(args)
        if "create" in cmd_args and "P2" in str(cmd_args):
            raise RuntimeError("failed")
        if "create" in cmd_args:
            return "repo-ok1"
        return ""

    with patch("beads_manager.run_subprocess", new_callable=AsyncMock) as mock_run_fn:
        mock_run_fn.side_effect = mock_run
        mapping = await manager.create_from_phases(phases, 42, Path("/repo"))

    assert "P1" in mapping
    assert "P2" not in mapping


# ---------------------------------------------------------------------------
# _parse_ready_json
# ---------------------------------------------------------------------------


def test_parse_ready_json_empty():
    assert BeadsManager._parse_ready_json("[]") == []


def test_parse_ready_json_invalid():
    assert BeadsManager._parse_ready_json("not json") == []


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


# ---------------------------------------------------------------------------
# _parse_show_json
# ---------------------------------------------------------------------------


def test_parse_show_json_single():
    data = json.dumps(
        {"id": "r-a1", "title": "Task", "status": "closed", "priority": 0}
    )
    task = BeadsManager._parse_show_json(data)
    assert task is not None
    assert task.id == "r-a1"
    assert task.status == "closed"


def test_parse_show_json_empty_list():
    assert BeadsManager._parse_show_json("[]") is None


def test_parse_show_json_invalid():
    assert BeadsManager._parse_show_json("garbage") is None


# ---------------------------------------------------------------------------
# State roundtrip
# ---------------------------------------------------------------------------


def test_bead_mapping_state_roundtrip(tmp_path):
    """Verify bead mappings survive a state save/load cycle."""
    from state import StateTracker

    state_file = tmp_path / "state.json"
    tracker = StateTracker(state_file)

    mapping = {"P1": "repo-4yu", "P2": "repo-z2o", "P3": "repo-qq9"}
    tracker.set_bead_mapping(42, mapping)

    assert tracker.get_bead_mapping(42) == mapping
    assert tracker.get_bead_mapping(999) == {}

    tracker2 = StateTracker(state_file)
    assert tracker2.get_bead_mapping(42) == mapping


# ===========================================================================
# Integration tests — plan_phase._create_beads_from_plan
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
    """Tests for beads creation during the plan phase."""

    @pytest.mark.asyncio()
    async def test_creates_beads_when_enabled(self, config) -> None:
        """After a successful plan with Task Graph, beads are created and mapping posted."""
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)

        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        mock_beads.create_from_phases = AsyncMock(
            return_value={"P1": "repo-4yu", "P2": "repo-z2o"}
        )
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        plan_result = PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        planners.plan = AsyncMock(return_value=plan_result)
        store.get_plannable = supply_once([issue])

        await phase.plan_issues()

        mock_beads.init.assert_awaited_once()
        mock_beads.create_from_phases.assert_awaited_once()
        assert state.get_bead_mapping(42) == {"P1": "repo-4yu", "P2": "repo-z2o"}

        bead_comments = [
            c for c in prs.post_comment.call_args_list if "Bead Task Mapping" in str(c)
        ]
        assert len(bead_comments) == 1
        body = bead_comments[0].args[1]
        assert "| P1 | #repo-4yu |" in body
        assert "| P2 | #repo-z2o |" in body

    @pytest.mark.asyncio()
    async def test_skips_beads_when_disabled(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, _prs, store, _stop = make_plan_phase(config)
        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        )
        store.get_plannable = supply_once([issue])
        await phase.plan_issues()
        assert state.get_bead_mapping(42) == {}

    @pytest.mark.asyncio()
    async def test_skips_when_no_task_graph(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, _prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
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
    async def test_empty_mapping_not_saved(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        mock_beads.create_from_phases = AsyncMock(return_value={})
        phase._beads_manager = mock_beads

        issue = TaskFactory.create(id=42)
        planners.plan = AsyncMock(
            return_value=PlanResultFactory.create(success=True, plan=_TASK_GRAPH_PLAN)
        )
        store.get_plannable = supply_once([issue])
        await phase.plan_issues()

        assert state.get_bead_mapping(42) == {}
        assert not any(
            "Bead Task Mapping" in str(c) for c in prs.post_comment.call_args_list
        )

    @pytest.mark.asyncio()
    async def test_comment_post_failure_does_not_crash(self, config) -> None:
        from tests.conftest import PlanResultFactory, TaskFactory
        from tests.helpers import make_plan_phase, supply_once

        phase, state, planners, prs, store, _stop = make_plan_phase(config)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
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
    def test_bead_mapping_injects_claim_and_close(self, config, event_bus) -> None:
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
        assert "**Bead:** #repo-z2o" in prompt
        assert "bd update repo-4yu --claim" in prompt
        assert "bd update repo-z2o --claim" in prompt
        assert 'bd close repo-4yu --reason "Phase complete"' in prompt
        assert 'bd close repo-z2o --reason "Phase complete"' in prompt

    def test_no_bead_mapping_no_commands(self, config, event_bus) -> None:
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
        assert "**Bead:**" not in prompt

    def test_partial_bead_mapping(self, config, event_bus) -> None:
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
        assert "bd update repo-4yu --claim" in prompt
        assert "repo-z2o" not in prompt


# ===========================================================================
# Integration tests — implement_phase bead mapping passthrough
# ===========================================================================


class TestImplementPhaseBeadsIntegration:
    @pytest.mark.asyncio()
    async def test_passes_mapping_when_enabled(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)

        mock_beads = AsyncMock()
        mock_beads.enabled = True
        mock_beads.init = AsyncMock(return_value=True)
        phase._beads_manager = mock_beads
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu"})

        await phase.run_batch()

        assert captured[0]["bead_mapping"] == {"P1": "repo-4yu"}
        mock_beads.init.assert_awaited_once()

    @pytest.mark.asyncio()
    async def test_no_mapping_when_disabled(self, config) -> None:
        from tests.conftest import TaskFactory
        from tests.helpers import make_implement_phase

        captured: list[dict] = []

        async def agent(issue, wt_path, branch, **kwargs):
            from tests.conftest import WorkerResultFactory

            captured.append(kwargs)
            return WorkerResultFactory.create(
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
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
                issue_number=issue.id,
                success=True,
                worktree_path=str(wt_path),
            )

        issue = TaskFactory.create(id=42)
        phase, _wt, _prs = make_implement_phase(config, [issue], agent_run=agent)
        phase._store.enrich_with_comments = AsyncMock(return_value=issue)
        mock_beads = AsyncMock()
        mock_beads.enabled = True
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

        bead_tasks = [
            {
                "id": "repo-4yu",
                "phase": "P1",
                "status": "closed",
                "files": "src/models.py",
                "tests": "Widget persists",
            },
        ]
        prompt, _ = runner._build_review_prompt_with_stats(
            pr, issue, diff, bead_tasks=bead_tasks
        )

        assert "## Per-Bead Review" in prompt
        assert "Bead #repo-4yu" in prompt
        assert "Files listed are present in the diff" in prompt

    def test_no_section_without_tasks(self, config, event_bus) -> None:
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        pr = PRInfo(number=101, branch="agent/issue-42", issue_number=42)
        issue = Task(id=42, title="Fix", body="body")
        diff = "diff --git a/x b/x\n+y\n"

        prompt, _ = runner._build_review_prompt_with_stats(
            pr, issue, diff, bead_tasks=None
        )
        assert "## Per-Bead Review" not in prompt

    def test_no_section_with_empty_list(self, config, event_bus) -> None:
        from models import PRInfo, Task
        from reviewer import ReviewRunner

        runner = ReviewRunner(config, event_bus)
        pr = PRInfo(number=101, branch="agent/issue-42", issue_number=42)
        issue = Task(id=42, title="Fix", body="body")
        diff = "diff --git a/x b/x\n+y\n"

        prompt, _ = runner._build_review_prompt_with_stats(
            pr, issue, diff, bead_tasks=[]
        )
        assert "## Per-Bead Review" not in prompt


# ===========================================================================
# Integration tests — review_phase bead context builder
# ===========================================================================


class TestReviewPhaseBeadContext:
    def test_builds_context_from_mapping_and_comments(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._config = config.model_copy(update={"beads_enabled": True})
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu", "P2": "repo-z2o"})

        issue = Task(id=42, title="Widget", body="body", comments=[_TASK_GRAPH_PLAN])
        result = phase._build_bead_review_context(issue)

        assert result is not None
        assert len(result) == 2
        p1 = next(b for b in result if b["phase"] == "P1")
        assert p1["id"] == "repo-4yu"
        assert "src/models.py" in str(p1["files"])

    def test_none_when_disabled(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        assert (
            phase._build_bead_review_context(Task(id=42, title="T", body="b")) is None
        )

    def test_none_when_no_mapping(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._config = config.model_copy(update={"beads_enabled": True})
        assert (
            phase._build_bead_review_context(Task(id=999, title="T", body="b")) is None
        )

    def test_n_a_without_comments(self, config) -> None:
        from models import Task
        from tests.helpers import make_review_phase

        phase = make_review_phase(config)
        phase._config = config.model_copy(update={"beads_enabled": True})
        phase._state.set_bead_mapping(42, {"P1": "repo-4yu"})

        result = phase._build_bead_review_context(
            Task(id=42, title="T", body="b", comments=[])
        )
        assert result is not None
        assert result[0]["files"] == "N/A"
        assert result[0]["tests"] == "N/A"
