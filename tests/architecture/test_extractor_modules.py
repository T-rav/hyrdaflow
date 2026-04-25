from arch.extractors.modules import extract_module_graph


def test_collapses_to_package_level_with_weights(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/foo/__init__.py": "",
            "src/foo/a.py": "from bar.thing import X\nfrom bar.thing import Y",
            "src/foo/b.py": "from bar.other import Z",
            "src/bar/__init__.py": "",
            "src/bar/thing.py": "X = 1\nY = 2",
            "src/bar/other.py": "Z = 3",
        }
    )
    g = extract_module_graph(root / "src")
    edges = {(e.from_module, e.to_module): e.weight for e in g.edges}
    # foo -> bar should aggregate three import statements
    assert edges.get(("src.foo", "src.bar")) == 3


def test_excludes_stdlib_and_third_party(fixture_src_tree):
    """Edges only between local src.* packages; stdlib and third-party filtered.

    Layout uses subdirectories so package-collapse produces distinct nodes
    (a flat `src/foo.py` + `src/bar.py` would both collapse to package
    `src` and produce no cross-edges).
    """
    root = fixture_src_tree(
        {
            "src/foo/__init__.py": "",
            "src/foo/a.py": "import os\nimport pydantic\nfrom bar.thing import X",
            "src/bar/__init__.py": "",
            "src/bar/thing.py": "X = 1",
        }
    )
    g = extract_module_graph(root / "src")
    targets = {e.to_module for e in g.edges}
    assert "src.bar" in targets
    assert "os" not in targets
    assert "pydantic" not in targets
