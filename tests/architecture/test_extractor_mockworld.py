from arch.extractors.mockworld import extract_mockworld_map


def test_indexes_fakes_and_scenario_uses(fixture_src_tree):
    root = fixture_src_tree(
        {
            "tests/scenarios/fakes/__init__.py": "",
            "tests/scenarios/fakes/fake_widget.py": "class FakeWidget:\n    def make(self): ...",
            "tests/scenarios/test_widget_scenario.py": """
            from tests.scenarios.fakes.fake_widget import FakeWidget
            def test_thing(): pass
        """,
            "tests/scenarios/test_unrelated.py": "def test_other(): pass",
        }
    )
    m = extract_mockworld_map(
        fakes_dir=root / "tests/scenarios/fakes",
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
            "tests/scenarios/fakes/fake_real.py": "class FakeReal: pass",
            "tests/scenarios/fakes/test_fake_real.py": "class FakeBogus: pass",
            "tests/scenarios/fakes/__init__.py": "",
        }
    )
    m = extract_mockworld_map(
        fakes_dir=root / "tests/scenarios/fakes",
        scenarios_dir=root / "tests/scenarios",
    )
    assert [f.name for f in m.fakes] == ["FakeReal"]
