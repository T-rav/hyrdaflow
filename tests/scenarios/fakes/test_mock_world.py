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


async def test_mock_world_accepts_iso_clock_start(tmp_path):
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path, clock_start="2025-06-15T12:00:00Z")
    assert world.clock.now() == 1_749_988_800.0


async def test_mock_world_accepts_unix_clock_start(tmp_path):
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path, clock_start=1_718_467_200.0)
    assert world.clock.now() == 1_718_467_200.0


async def test_mock_world_default_clock_start_uses_wall_time(tmp_path):
    import time

    from tests.scenarios.fakes.mock_world import MockWorld

    before = time.time()
    world = MockWorld(tmp_path)
    after = time.time()

    assert before <= world.clock.now() <= after + 1


async def test_mock_world_add_repo_registers_in_store(tmp_path):
    from repo_store import RepoRegistryStore
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.add_repo("acme/app", str(tmp_path / "acme-app"))

    store = RepoRegistryStore(tmp_path)
    records = store.list()
    assert any(r.slug == "acme/app" for r in records)


async def test_wire_targets_accepts_duck_typed_target(tmp_path):
    from unittest.mock import MagicMock

    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    fake_target = MagicMock()
    fake_target.prs = MagicMock()
    fake_target.triage_runner = MagicMock()
    fake_target.planners = MagicMock()
    fake_target.agents = MagicMock()
    fake_target.reviewers = MagicMock()
    fake_target.workspaces = MagicMock()

    # Capture expected bound methods before wiring (bound methods are not
    # identity-stable across repeated attribute accesses, so we snapshot them).
    expected_create_pr = world.github.create_pr
    expected_merge_pr = world.github.merge_pr
    expected_evaluate = world._llm.triage_runner.evaluate
    expected_workspace_create = world._workspace.create

    world._wire_targets(fake_target)

    # After wiring, PR methods must be FakeGitHub's bound methods
    assert fake_target.prs.create_pr == expected_create_pr
    assert fake_target.prs.merge_pr == expected_merge_pr
    assert fake_target.triage_runner.evaluate == expected_evaluate
    assert fake_target.workspaces.create == expected_workspace_create


async def test_start_dashboard_without_orchestrator_serves_root(tmp_path):
    import httpx

    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    url = await world.start_dashboard()
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url + "/")
        assert response.status_code == 200
        assert world.dashboard_url == url
    finally:
        await world.stop_dashboard()
    assert world.dashboard_url is None


async def test_start_dashboard_is_idempotent(tmp_path):
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    url_a = await world.start_dashboard()
    url_b = await world.start_dashboard()
    try:
        assert url_a == url_b
    finally:
        await world.stop_dashboard()


async def test_stop_dashboard_frees_port(tmp_path):
    import socket

    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    url = await world.start_dashboard()
    port = int(url.rsplit(":", 1)[1])

    await world.stop_dashboard()

    # After stop, the port must be reusable.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("127.0.0.1", port))
    finally:
        s.close()


async def test_start_dashboard_with_orchestrator_wires_fakes(tmp_path):
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    world.add_issue(1, "Test issue", "Body", labels=["hydraflow-find"])

    await world.start_dashboard(with_orchestrator=True)
    try:
        dashboard = world._dashboard
        orch = dashboard._orchestrator
        assert orch is not None
        # PR methods on the real service registry must point at FakeGitHub.
        # Use equality rather than identity because bound methods produce a
        # new object on each attribute access.
        assert orch._svc.prs.create_pr == world.github.create_pr
        # Triage runner (exposed as `triage` on ServiceRegistry — NOT
        # `triage_runner`) must point at FakeLLM.
        assert orch._svc.triage.evaluate == world._llm.triage_runner.evaluate
    finally:
        await world.stop_dashboard()


async def test_mockworld_wires_wiki_store_to_plan_phase(tmp_path) -> None:
    """MockWorld threads wiki_store through PipelineHarness to PlanPhase."""
    from repo_wiki import RepoWikiStore
    from tests.scenarios.fakes.mock_world import MockWorld

    wiki = RepoWikiStore(tmp_path / "wiki")
    world = MockWorld(tmp_path, wiki_store=wiki)

    plan_phase = world.harness.plan_phase
    # The attribute name on PlanPhase may be _wiki_store or wiki_store — verify
    stored = getattr(plan_phase, "_wiki_store", None)
    if stored is None:
        stored = getattr(plan_phase, "wiki_store", None)
    assert stored is wiki, f"PlanPhase did not receive wiki_store; saw {stored!r}"


async def test_mockworld_default_wiki_store_is_none(tmp_path) -> None:
    """Default (no wiki_store arg) leaves PlanPhase with no wiki wiring."""
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    plan_phase = world.harness.plan_phase
    stored = getattr(plan_phase, "_wiki_store", getattr(plan_phase, "wiki_store", None))
    assert stored is None


async def test_mockworld_wires_beads_manager_to_phases(tmp_path) -> None:
    """MockWorld threads beads_manager through PipelineHarness to plan + implement phases."""
    from tests.scenarios.fakes.fake_beads import FakeBeads
    from tests.scenarios.fakes.mock_world import MockWorld

    beads = FakeBeads()
    world = MockWorld(tmp_path, beads_manager=beads)

    assert world.harness.plan_phase._beads_manager is beads
    assert world.harness.implement_phase._beads_manager is beads


async def test_mockworld_default_beads_manager_is_none(tmp_path) -> None:
    from tests.scenarios.fakes.mock_world import MockWorld

    world = MockWorld(tmp_path)
    assert world.harness.plan_phase._beads_manager is None
    assert world.harness.implement_phase._beads_manager is None


async def test_mockworld_set_agents_preserves_beads_manager(tmp_path) -> None:
    """PipelineHarness.set_agents must not drop the beads_manager binding."""
    from tests.scenarios.fakes.fake_beads import FakeBeads
    from tests.scenarios.fakes.mock_world import MockWorld

    beads = FakeBeads()
    world = MockWorld(tmp_path, beads_manager=beads)
    # set_agents rebuilds ImplementPhase — make sure beads_manager survives
    sentinel = object()
    world.harness.set_agents(sentinel)  # type: ignore[arg-type]
    assert world.harness.implement_phase._beads_manager is beads
