from arch._models import EventBusTopology, EventEdge
from arch.generators.event_bus import render_event_bus


def test_renders_publishers_subscribers_table():
    topo = EventBusTopology(
        events=[
            EventEdge(
                event="PR_OPENED",
                publishers=["src.runner:notify"],
                subscribers=["src.widget_loop:on_open", "src.audit:hook"],
            ),
            EventEdge(event="ORPHAN", publishers=["src.foo:f"], subscribers=[]),
        ]
    )
    md = render_event_bus(topo)
    assert "PR_OPENED" in md
    assert "src.widget_loop" in md
    assert "ORPHAN" in md
    assert "no subscribers" in md.lower() or "⚠️" in md


def test_handles_empty_topology():
    md = render_event_bus(EventBusTopology())
    assert "no events" in md.lower()
