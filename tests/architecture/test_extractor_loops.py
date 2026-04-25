from arch.extractors.loops import extract_loops


def test_extracts_basebackgroundloop_subclass(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/widget_loop.py": '''
            """A widget loop.

            Per ADR-0029, ADR-0049.
            """
            import os
            from base_background_loop import BaseBackgroundLoop
            from events import EventType

            class WidgetLoop(BaseBackgroundLoop):
                tick_interval_seconds = 3600

                def __init__(self, bus):
                    self._kill = os.environ.get("HYDRAFLOW_DISABLE_WIDGET_LOOP")
                    bus.subscribe(EventType.PR_OPENED, self._on_pr)
                    bus.subscribe(EventType.RC_RED, self._on_red)
        ''',
        }
    )

    loops = extract_loops(root / "src")

    assert len(loops) == 1
    info = loops[0]
    assert info.name == "WidgetLoop"
    assert info.module == "src.widget_loop"
    assert info.source_path == "src/widget_loop.py"
    assert info.tick_interval_seconds == 3600
    assert info.kill_switch_var == "HYDRAFLOW_DISABLE_WIDGET_LOOP"
    assert info.adr_refs == ["ADR-0029", "ADR-0049"]
    # Event subscriptions are sorted; both are captured.
    assert info.event_subscriptions == ["PR_OPENED", "RC_RED"]


def test_skips_non_loop_classes(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/foo.py": "class NotALoop: pass",
        }
    )
    assert extract_loops(root / "src") == []


def test_skips_basebackgroundloop_itself(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/base_background_loop.py": """
            class BaseBackgroundLoop: pass
        """,
        }
    )
    assert extract_loops(root / "src") == []


def test_output_is_sorted_by_name(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/zebra_loop.py": "from base_background_loop import BaseBackgroundLoop\nclass ZebraLoop(BaseBackgroundLoop): pass",
            "src/alpha_loop.py": "from base_background_loop import BaseBackgroundLoop\nclass AlphaLoop(BaseBackgroundLoop): pass",
        }
    )
    names = [loop.name for loop in extract_loops(root / "src")]
    assert names == ["AlphaLoop", "ZebraLoop"]
