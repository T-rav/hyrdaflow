from arch._models import ModuleEdge, ModuleGraph, ModuleNode
from arch.generators.module_graph import render_module_graph


def test_renders_mermaid_with_weighted_edges():
    g = ModuleGraph(
        nodes=[ModuleNode(name="src.foo"), ModuleNode(name="src.bar")],
        edges=[ModuleEdge(from_module="src.foo", to_module="src.bar", weight=3)],
    )
    md = render_module_graph(g)
    assert "graph LR" in md
    # Node IDs are sanitized via _safe_id (`.` → `_`); weights are quoted.
    assert 'src_foo -- "3" --> src_bar' in md
    assert 'src_foo["src.foo"]' in md  # node label preserves the dotted name
    assert 'src_bar["src.bar"]' in md


def test_handles_empty_graph():
    md = render_module_graph(ModuleGraph())
    assert "no modules" in md.lower()
