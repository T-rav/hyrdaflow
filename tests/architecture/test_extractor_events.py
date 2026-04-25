from arch.extractors.events import extract_event_topology


def test_finds_publishers_and_subscribers(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/widget_loop.py": """
            from events import EventType
            class WidgetLoop:
                def __init__(self, bus):
                    bus.subscribe(EventType.PR_OPENED, self.on_open)
                def fire(self, bus):
                    bus.publish(EventType.WIDGET_DONE, payload={})
        """,
        }
    )
    topo = extract_event_topology(root / "src")
    events = {e.event: e for e in topo.events}
    assert "PR_OPENED" in events
    assert "WIDGET_DONE" in events
    assert any("widget_loop" in s for s in events["PR_OPENED"].subscribers)
    assert any("widget_loop" in p for p in events["WIDGET_DONE"].publishers)


def test_returns_empty_when_no_event_calls(fixture_src_tree):
    root = fixture_src_tree({"src/foo.py": "x = 1"})
    topo = extract_event_topology(root / "src")
    assert topo.events == []
