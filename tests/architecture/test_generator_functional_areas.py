from arch._functional_areas_schema import FunctionalArea, FunctionalAreas
from arch._models import LoopInfo, PortInfo
from arch.generators.functional_areas import render_functional_areas


def test_renders_subgraph_per_area_with_members():
    fa = FunctionalAreas(
        areas={
            "orchestration": FunctionalArea(
                label="Orchestration",
                description="Plan-implement-review pipeline.",
                loops=["RunLoop"],
                ports=["AgentPort"],
                related_adrs=["ADR-0001"],
            ),
            "caretaking": FunctionalArea(
                label="Caretaking",
                description="Autonomous background work.",
                loops=["RepoWikiLoop"],
                related_adrs=["ADR-0029"],
            ),
        }
    )
    loops = [
        LoopInfo(name="RunLoop", module="src.run_loop", source_path="src/run_loop.py"),
        LoopInfo(
            name="RepoWikiLoop",
            module="src.repo_wiki_loop",
            source_path="src/repo_wiki_loop.py",
        ),
    ]
    ports = [
        PortInfo(
            name="AgentPort",
            module="src.ports",
            source_path="src/ports.py",
            methods=["start"],
        ),
    ]
    md = render_functional_areas(fa, loops=loops, ports=ports)

    assert "# Functional Area Map" in md
    assert "Orchestration" in md
    assert "Caretaking" in md
    assert "RunLoop" in md
    assert "RepoWikiLoop" in md
    assert "subgraph orchestration" in md
    assert "subgraph caretaking" in md
    assert "## Orchestration" in md
    assert "## Caretaking" in md
    assert "ADR-0001" in md
    assert "ADR-0029" in md


def test_mentions_unknown_member_in_warning_section():
    fa = FunctionalAreas(
        areas={
            "x": FunctionalArea(label="X", description="x", loops=["GhostLoop"]),
        }
    )
    md = render_functional_areas(fa, loops=[], ports=[])
    assert "GhostLoop" in md
    assert "⚠️" in md or "unknown" in md.lower()


def test_areas_render_in_yaml_insertion_order():
    fa = FunctionalAreas(
        areas={
            "z_area": FunctionalArea(
                label="Z", description="z", loops=["BLoop", "ALoop"]
            ),
            "a_area": FunctionalArea(
                label="A", description="a", loops=["DLoop", "CLoop"]
            ),
        }
    )
    loops = [
        LoopInfo(name=n, module="m", source_path="p")
        for n in ("ALoop", "BLoop", "CLoop", "DLoop")
    ]
    md = render_functional_areas(fa, loops=loops, ports=[])
    z_pos = md.index("subgraph z_area")
    a_pos = md.index("subgraph a_area")
    assert z_pos < a_pos  # YAML insertion order preserved
