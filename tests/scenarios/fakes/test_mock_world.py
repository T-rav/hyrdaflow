"""Tests for MockWorld orchestrating fixture."""

from __future__ import annotations

import pytest

from tests.conftest import WorkerResultFactory
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario


class TestMockWorldSingleIssue:
    async def test_single_issue_happy_path(self, tmp_path):
        world = MockWorld(tmp_path)
        world.add_issue(1, "Fix login bug", "The login is broken", ["hydraflow-find"])
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.final_stage == "done"

    async def test_fluent_chaining(self, tmp_path):
        world = (
            MockWorld(tmp_path)
            .add_issue(1, "Bug A", "body", ["hydraflow-find"])
            .add_issue(2, "Bug B", "body", ["hydraflow-find"])
        )
        assert len(world._issues) == 2


class TestMockWorldScriptedFailure:
    async def test_implement_failure_with_scripted_result(self, tmp_path):
        world = MockWorld(tmp_path)
        world.add_issue(1, "Fix bug", "body", ["hydraflow-find"])
        fail_result = WorkerResultFactory.create(
            issue_number=1, success=False, error="compile error"
        )
        world.set_phase_result("implement", 1, fail_result)
        result = await world.run_pipeline()

        outcome = result.issue(1)
        assert outcome.worker_result is not None
        assert outcome.worker_result.success is False


class TestMockWorldServiceFailure:
    async def test_fail_and_heal_service(self, tmp_path):
        world = MockWorld(tmp_path)
        world.fail_service("hindsight")
        assert world.hindsight.is_failing is True
        world.heal_service("hindsight")
        assert world.hindsight.is_failing is False


class TestMockWorldLoopCatalog:
    async def test_run_with_loops_uses_catalog(self, tmp_path):
        """MockWorld.run_with_loops routes through LoopCatalog, not _make_loop."""
        world = MockWorld(tmp_path)
        stats = await world.run_with_loops(["ci_monitor"], cycles=1)
        assert "ci_monitor" in stats


class TestMockWorldRealAgentRunner:
    async def test_use_real_agent_runner_wires_real_runner(self, tmp_path) -> None:
        from agent import AgentRunner
        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path, use_real_agent_runner=True)
        # Assert both the surface attribute AND the ImplementPhase binding.
        # The latter is what ImplementPhase._run_single_issue actually calls.
        assert isinstance(world.harness.agents, AgentRunner)
        assert isinstance(world.harness.implement_phase._agents, AgentRunner)

    async def test_default_mockworld_still_uses_scripted_agent(self, tmp_path) -> None:
        import inspect

        from tests.scenarios.fakes.mock_world import MockWorld

        world = MockWorld(tmp_path)
        # Scripted path: harness.agents.run is the bound method of _FakeAgentRunner
        # patched onto the harness's AsyncMock.
        agents_run = world.harness.agents.run
        assert inspect.ismethod(agents_run)
        # implement_phase still holds the original AsyncMock harness.agents (the
        # .run attribute on that mock was swapped, but the mock identity is preserved).
        assert world.harness.implement_phase._agents is world.harness.agents


async def test_fail_service_docker_arms_exit_nonzero(tmp_path) -> None:
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.fail_service("docker")
    events = [e async for e in await world.docker.run_agent(command=["x"])]
    assert events[-1]["success"] is False


async def test_fail_service_github_arms_rate_limit(tmp_path) -> None:
    import pytest

    from tests.scenarios.fakes.fake_github import RateLimitError
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.github.add_issue(1, "t", "b", labels=[])
    world.fail_service("github")
    with pytest.raises(RateLimitError):
        await world.github.add_labels(1, ["x"])


async def test_heal_service_github_clears_rate_limit(tmp_path) -> None:
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.github.add_issue(1, "t", "b", labels=[])
    world.fail_service("github")
    world.heal_service("github")
    await world.github.add_labels(1, ["x"])  # no raise
    assert "x" in world.github.issue(1).labels


async def test_heal_service_docker_clears_pending_fault(tmp_path) -> None:
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.fail_service("docker")
    world.heal_service("docker")
    events = [e async for e in await world.docker.run_agent(command=["x"])]
    # After healing the pending fault, next run_agent returns the default success
    assert events[-1]["success"] is True


async def test_fail_service_unknown_raises(tmp_path) -> None:
    import pytest

    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    with pytest.raises(ValueError, match="unknown service"):
        world.fail_service("bogus-service")


async def test_pipeline_harness_set_agents_rebuilds_implement_phase(tmp_path) -> None:
    """set_agents must propagate the new runner into ImplementPhase._agents."""
    from tests.helpers import PipelineHarness

    harness = PipelineHarness(tmp_path)
    sentinel = object()
    harness.set_agents(sentinel)  # type: ignore[arg-type]
    assert harness.agents is sentinel
    assert harness.implement_phase._agents is sentinel


async def test_run_pipeline_is_single_shot(tmp_path) -> None:
    """Calling run_pipeline twice must raise — state would otherwise be stale."""
    import pytest

    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    await world.run_pipeline()

    with pytest.raises(RuntimeError, match="single-shot"):
        await world.run_pipeline()
