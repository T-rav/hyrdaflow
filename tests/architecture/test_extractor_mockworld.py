from arch.extractors.mockworld import extract_mockworld_map

# Fixture Fake bodies must include the ``_is_fake_adapter = True`` marker —
# the extractor filters by it to exclude nested-record dataclasses
# (FakeIssue, FakePR, FakeIssueRecord, FakeIssueSummary) that live
# alongside Fake adapters in the real codebase.

_FAKE_WIDGET_BODY = (
    "class FakeWidget:\n    _is_fake_adapter = True\n    def make(self): ..."
)
_FAKE_REAL_BODY = "class FakeReal:\n    _is_fake_adapter = True"


def test_indexes_fakes_and_scenario_uses(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/mockworld/__init__.py": "",
            "src/mockworld/fakes/__init__.py": "",
            "src/mockworld/fakes/fake_widget.py": _FAKE_WIDGET_BODY,
            "tests/scenarios/test_widget_scenario.py": """
            from mockworld.fakes.fake_widget import FakeWidget
            def test_thing(): pass
        """,
            "tests/scenarios/test_unrelated.py": "def test_other(): pass",
        }
    )
    m = extract_mockworld_map(
        fakes_dir=root / "src/mockworld/fakes",
        scenarios_dir=root / "tests/scenarios",
    )
    assert len(m.fakes) == 1
    f = m.fakes[0]
    assert f.name == "FakeWidget"
    assert any("test_widget_scenario" in s for s in f.used_in_scenarios)
    assert not any("test_unrelated" in s for s in f.used_in_scenarios)


def test_skips_test_files_and_dunder(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/mockworld/__init__.py": "",
            "src/mockworld/fakes/__init__.py": "",
            "src/mockworld/fakes/fake_real.py": _FAKE_REAL_BODY,
            "src/mockworld/fakes/test_fake_real.py": (
                "class FakeBogus:\n    _is_fake_adapter = True"
            ),
        }
    )
    m = extract_mockworld_map(
        fakes_dir=root / "src/mockworld/fakes",
        scenarios_dir=root / "tests/scenarios",
    )
    assert [f.name for f in m.fakes] == ["FakeReal"]


def test_skips_classes_without_marker(fixture_src_tree):
    """Nested-record dataclasses without the marker are excluded.

    Mirrors the real-codebase pattern: FakeIssue / FakePR live in
    ``fake_github.py`` next to FakeGitHub but aren't Fake adapters.
    """
    root = fixture_src_tree(
        {
            "src/mockworld/__init__.py": "",
            "src/mockworld/fakes/__init__.py": "",
            "src/mockworld/fakes/fake_thing.py": (
                "from dataclasses import dataclass\n"
                "@dataclass\n"
                "class FakeRecord:\n"  # no marker → must be excluded
                "    number: int\n"
                "class FakeThing:\n"
                "    _is_fake_adapter = True\n"
            ),
        }
    )
    m = extract_mockworld_map(
        fakes_dir=root / "src/mockworld/fakes",
        scenarios_dir=root / "tests/scenarios",
    )
    assert [f.name for f in m.fakes] == ["FakeThing"]


def test_classvar_marker_recognised(fixture_src_tree):
    """ClassVar-annotated marker (used on @dataclass fakes) is detected."""
    root = fixture_src_tree(
        {
            "src/mockworld/__init__.py": "",
            "src/mockworld/fakes/__init__.py": "",
            "src/mockworld/fakes/fake_data.py": (
                "from dataclasses import dataclass\n"
                "from typing import ClassVar\n"
                "@dataclass\n"
                "class FakeData:\n"
                "    _is_fake_adapter: ClassVar[bool] = True\n"
                "    value: int = 0\n"
            ),
        }
    )
    m = extract_mockworld_map(
        fakes_dir=root / "src/mockworld/fakes",
        scenarios_dir=root / "tests/scenarios",
    )
    assert [f.name for f in m.fakes] == ["FakeData"]
