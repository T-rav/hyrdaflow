from __future__ import annotations

import pytest

from arch.models import (
    Allowlist,
    Fitness,
    ImportGraph,
    LayerMap,
    RuleModule,
    Violation,
)


def test_layer_map_values_must_be_uniform_type_ints() -> None:
    LayerMap({"src/a/**": 1, "src/b/**": 2})


def test_layer_map_values_must_be_uniform_type_strings() -> None:
    LayerMap({"src/a/**": "core", "src/b/**": "app"})


def test_layer_map_mixed_types_rejected() -> None:
    with pytest.raises(TypeError, match="uniform"):
        LayerMap({"src/a/**": 1, "src/b/**": "core"})


def test_allowlist_maps_source_to_allowed_targets() -> None:
    al = Allowlist({"src/plan_phase.py": {"src/planner.py"}})
    assert al.allowed("src/plan_phase.py", "src/planner.py") is True
    assert al.allowed("src/plan_phase.py", "src/worktree.py") is False
    assert al.allowed("src/other.py", "src/planner.py") is False


def test_fitness_max_lines_constructs() -> None:
    f = Fitness.max_lines("src/**/*_phase.py", 600)
    assert f.kind == "max_lines"
    assert f.target == "src/**/*_phase.py"
    assert f.value == 600


def test_fitness_forbidden_symbol_validates_outside_layer_membership() -> None:
    layers = LayerMap({"src/adapters/**": 4, "src/core/**": 1})
    Fitness.forbidden_symbol("subprocess.run", outside_layer=4).validate_against(layers)
    with pytest.raises(ValueError, match="outside_layer=99 not present"):
        Fitness.forbidden_symbol("x", outside_layer=99).validate_against(layers)


def test_import_graph_round_trips_edges() -> None:
    g = ImportGraph(module_unit="file")
    g.add_edge("src/a.py", "src/b.py")
    assert ("src/a.py", "src/b.py") in g.edges
    assert g.module_unit == "file"


def test_violation_is_hashable_and_equatable_by_tuple() -> None:
    v1 = Violation(source="src/a.py", target="src/b.py", rule="layer", detail="")
    v2 = Violation(source="src/a.py", target="src/b.py", rule="layer", detail="")
    assert v1 == v2
    assert {v1, v2} == {v1}


def test_rule_module_holds_all_four_fields() -> None:
    rm = RuleModule(
        extractor=lambda _: ImportGraph(module_unit="file"),
        layers=LayerMap({"src/a/**": 1}),
        allowlist=Allowlist({}),
        fitness=[],
    )
    assert rm.extractor is not None
