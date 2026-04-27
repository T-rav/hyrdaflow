from arch._models import FakeInfo, MockWorldMap
from arch.generators.mockworld_map import render_mockworld_map


def test_emits_table_and_mermaid():
    m = MockWorldMap(
        fakes=[
            FakeInfo(
                name="FakeWidget",
                module="mockworld.fakes.fake_widget",
                source_path="src/mockworld/fakes/fake_widget.py",
                implements_port="WidgetPort",
                used_in_scenarios=["tests/scenarios/test_widget.py"],
            ),
        ]
    )
    md = render_mockworld_map(m)
    assert "FakeWidget" in md
    assert "WidgetPort" in md
    assert "test_widget" in md
    assert "```mermaid" in md


def test_handles_empty_map():
    md = render_mockworld_map(MockWorldMap())
    assert "no fakes" in md.lower()
