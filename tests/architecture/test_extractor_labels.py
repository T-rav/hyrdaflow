from arch.extractors.labels import extract_labels


def test_extracts_explicit_transitions_constant(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/labels.py": """
            TRANSITIONS = [
                ("hydraflow-ready", "hydraflow-implementing", "agent_started"),
                ("hydraflow-implementing", "hydraflow-reviewing", "pr_opened"),
                ("hydraflow-reviewing", "hydraflow-merged", "pr_merged"),
            ]
        """,
        }
    )
    sm = extract_labels(root / "src")
    assert sorted(sm.states) == [
        "hydraflow-implementing",
        "hydraflow-merged",
        "hydraflow-ready",
        "hydraflow-reviewing",
    ]
    assert len(sm.transitions) == 3
    edge = next(t for t in sm.transitions if t.from_state == "hydraflow-ready")
    assert edge.to_state == "hydraflow-implementing"
    assert edge.trigger == "agent_started"


def test_returns_empty_when_no_transitions_found(fixture_src_tree):
    root = fixture_src_tree({"src/foo.py": "x = 1"})
    sm = extract_labels(root / "src")
    assert sm.states == []
    assert sm.transitions == []
