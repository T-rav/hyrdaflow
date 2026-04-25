from arch._models import PortAdapterInfo, PortInfo
from arch.generators.port_map import render_port_map


def test_renders_port_with_adapter_and_fake():
    ports = [
        PortInfo(
            name="WidgetPort",
            module="src.ports",
            source_path="src/ports.py",
            methods=["make", "break_"],
            adapters=[
                PortAdapterInfo(
                    name="WidgetAdapter",
                    module="src.widget_adapter",
                    source_path="src/widget_adapter.py",
                )
            ],
            fake=PortAdapterInfo(
                name="FakeWidget",
                module="tests.scenarios.fakes.fake_widget",
                source_path="tests/scenarios/fakes/fake_widget.py",
                is_fake=True,
            ),
        )
    ]
    md = render_port_map(ports)
    assert "WidgetPort" in md
    assert "WidgetAdapter" in md
    assert "FakeWidget" in md
    assert "```mermaid" in md
    assert "WidgetPort --> WidgetAdapter" in md
    assert "WidgetPort -.-> FakeWidget" in md  # fakes drawn dashed


def test_flags_port_without_fake():
    ports = [
        PortInfo(
            name="LonelyPort",
            module="src.ports",
            source_path="src/ports.py",
            methods=["x"],
            fake=None,
        )
    ]
    md = render_port_map(ports)
    assert "⚠️" in md or "no fake" in md.lower()
