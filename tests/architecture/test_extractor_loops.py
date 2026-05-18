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


def test_tick_from_get_default_interval_literal(fixture_src_tree):
    """Tick is extracted from _get_default_interval returning a literal int."""
    root = fixture_src_tree(
        {
            "src/diagram_loop.py": """
            from base_background_loop import BaseBackgroundLoop

            class DiagramLoop(BaseBackgroundLoop):
                def _get_default_interval(self) -> int:
                    # 4 hours
                    return 14400
            """,
        }
    )
    loops = extract_loops(root / "src")
    assert len(loops) == 1
    assert loops[0].tick_interval_seconds == 14400


def test_tick_from_get_default_interval_module_constant(fixture_src_tree):
    """Tick is extracted from _get_default_interval returning a module-level constant."""
    root = fixture_src_tree(
        {
            "src/merge_loop.py": """
            from base_background_loop import BaseBackgroundLoop

            _DEFAULT_INTERVAL_SECONDS = 600

            class MergeLoop(BaseBackgroundLoop):
                def _get_default_interval(self) -> int:
                    return _DEFAULT_INTERVAL_SECONDS
            """,
        }
    )
    loops = extract_loops(root / "src")
    assert len(loops) == 1
    assert loops[0].tick_interval_seconds == 600


def test_tick_from_get_default_interval_config_field(fixture_src_tree):
    """Tick is extracted from _get_default_interval returning self._config.<field>
    where the field default is declared in config.py as Field(default=<int>)."""
    root = fixture_src_tree(
        {
            "src/ci_monitor_loop.py": """
            from base_background_loop import BaseBackgroundLoop

            class CIMonitorLoop(BaseBackgroundLoop):
                def _get_default_interval(self) -> int:
                    return self._config.ci_monitor_interval
            """,
            "src/config.py": """
            from pydantic import Field

            class HydraFlowConfig:
                ci_monitor_interval: int = Field(default=300)
            """,
        }
    )
    loops = extract_loops(root / "src")
    assert len(loops) == 1
    assert loops[0].tick_interval_seconds == 300


def test_kill_switch_from_module_level_constant(fixture_src_tree):
    """Kill switch env var is found even when defined as a module-level constant
    referenced by name inside the class body (not inlined as a string literal)."""
    root = fixture_src_tree(
        {
            "src/diagram_loop.py": """
            import os
            from base_background_loop import BaseBackgroundLoop

            _KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"

            class DiagramLoop(BaseBackgroundLoop):
                def _do_work(self):
                    if os.environ.get(_KILL_SWITCH_ENV) == "1":
                        return {"skipped": "kill_switch"}
            """,
        }
    )
    loops = extract_loops(root / "src")
    assert len(loops) == 1
    assert loops[0].kill_switch_var == "HYDRAFLOW_DISABLE_DIAGRAM_LOOP"
