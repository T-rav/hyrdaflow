"""Smoke tests for arch._models.

These tests verify the shared model dataclasses can be instantiated and
round-trip through JSON. Future extractor/generator tasks will exercise
these models through richer scenarios.
"""

from __future__ import annotations

from arch._models import (
    ADRRef,
    ADRRefIndex,
    EventBusTopology,
    EventEdge,
    FakeInfo,
    LabelStateMachine,
    LabelTransition,
    LoopInfo,
    MockWorldMap,
    ModuleEdge,
    ModuleGraph,
    ModuleNode,
    PortAdapterInfo,
    PortInfo,
)


class TestLoopInfo:
    def test_minimal_construction(self):
        loop = LoopInfo(
            name="DiagramLoop",
            module="src.diagram_loop",
            source_path="src/diagram_loop.py",
        )
        assert loop.name == "DiagramLoop"
        assert loop.tick_interval_seconds is None
        assert loop.event_subscriptions == []
        assert loop.kill_switch_var is None
        assert loop.adr_refs == []

    def test_full_construction(self):
        loop = LoopInfo(
            name="DiagramLoop",
            module="src.diagram_loop",
            source_path="src/diagram_loop.py",
            tick_interval_seconds=60,
            event_subscriptions=["PR_OPENED"],
            kill_switch_var="HYDRAFLOW_DISABLE_DIAGRAM_LOOP",
            adr_refs=["ADR-0029", "ADR-0049"],
        )
        assert loop.tick_interval_seconds == 60
        assert loop.event_subscriptions == ["PR_OPENED"]
        assert loop.kill_switch_var == "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"
        assert loop.adr_refs == ["ADR-0029", "ADR-0049"]

    def test_json_round_trip(self):
        loop = LoopInfo(
            name="DiagramLoop",
            module="src.diagram_loop",
            source_path="src/diagram_loop.py",
            tick_interval_seconds=60,
        )
        data = loop.model_dump()
        rehydrated = LoopInfo.model_validate(data)
        assert rehydrated == loop


class TestPortInfo:
    def test_port_with_adapters_and_fake(self):
        adapter = PortAdapterInfo(
            name="GitHubPRAdapter",
            module="src.adapters.github_pr",
            source_path="src/adapters/github_pr.py",
        )
        fake = PortAdapterInfo(
            name="FakePR",
            module="tests.fakes.fake_pr",
            source_path="tests/fakes/fake_pr.py",
            is_fake=True,
        )
        port = PortInfo(
            name="PRPort",
            module="src.ports.pr_port",
            source_path="src/ports/pr_port.py",
            methods=["create_pr", "merge_pr"],
            adapters=[adapter],
            fake=fake,
        )
        assert port.fake is not None
        assert port.fake.is_fake is True
        assert len(port.adapters) == 1


class TestLabelStateMachine:
    def test_default_construction(self):
        sm = LabelStateMachine()
        assert sm.states == []
        assert sm.transitions == []

    def test_with_transitions(self):
        sm = LabelStateMachine(
            states=["hydraflow-ready", "hydraflow-in-progress"],
            transitions=[
                LabelTransition(
                    from_state="hydraflow-ready",
                    to_state="hydraflow-in-progress",
                    trigger="orchestrator picks up issue",
                ),
            ],
        )
        assert len(sm.transitions) == 1
        assert sm.transitions[0].from_state == "hydraflow-ready"


class TestModuleGraph:
    def test_default_construction(self):
        graph = ModuleGraph()
        assert graph.nodes == []
        assert graph.edges == []

    def test_with_edges(self):
        graph = ModuleGraph(
            nodes=[ModuleNode(name="src.adapters"), ModuleNode(name="src.ports")],
            edges=[
                ModuleEdge(from_module="src.adapters", to_module="src.ports", weight=3),
            ],
        )
        assert graph.edges[0].weight == 3


class TestEventBusTopology:
    def test_default_construction(self):
        topo = EventBusTopology()
        assert topo.events == []

    def test_with_events(self):
        topo = EventBusTopology(
            events=[
                EventEdge(
                    event="PR_OPENED",
                    publishers=["src.orchestrator:open_pr"],
                    subscribers=["src.review_loop:on_pr_opened"],
                ),
            ],
        )
        assert topo.events[0].event == "PR_OPENED"


class TestADRRefIndex:
    def test_default_construction(self):
        idx = ADRRefIndex()
        assert idx.adr_to_modules == []

    def test_with_refs(self):
        idx = ADRRefIndex(
            adr_to_modules=[
                ADRRef(adr_id="ADR-0029", cited_modules=["src.diagram_loop"]),
            ],
        )
        assert idx.adr_to_modules[0].adr_id == "ADR-0029"


class TestMockWorldMap:
    def test_default_construction(self):
        m = MockWorldMap()
        assert m.fakes == []

    def test_with_fakes(self):
        m = MockWorldMap(
            fakes=[
                FakeInfo(
                    name="FakeGitHub",
                    module="tests.scenarios.fakes.fake_github",
                    source_path="tests/scenarios/fakes/fake_github.py",
                    implements_port="GitHubPort",
                    used_in_scenarios=["scenario_pr_lifecycle"],
                ),
            ],
        )
        assert m.fakes[0].name == "FakeGitHub"
        assert m.fakes[0].implements_port == "GitHubPort"
