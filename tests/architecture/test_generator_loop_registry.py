from arch._models import LoopInfo
from arch.generators.loop_registry import render_loop_registry


def test_renders_table_with_one_row_per_loop():
    loops = [
        LoopInfo(
            name="AlphaLoop",
            module="src.alpha_loop",
            source_path="src/alpha_loop.py",
            tick_interval_seconds=300,
            event_subscriptions=["PR_OPENED"],
            kill_switch_var="HYDRAFLOW_DISABLE_ALPHA_LOOP",
            adr_refs=["ADR-0029"],
        ),
        LoopInfo(
            name="BetaLoop", module="src.beta_loop", source_path="src/beta_loop.py"
        ),
    ]
    md = render_loop_registry(loops)
    assert "# Loop Registry" in md
    assert "AlphaLoop" in md
    assert "BetaLoop" in md
    assert "300" in md  # tick interval
    assert "HYDRAFLOW_DISABLE_ALPHA_LOOP" in md
    assert "ADR-0029" in md
    assert md.count("\n| ") >= 3  # header + separator + 2 rows
    assert "{{ARCH_FOOTER}}" in md


def test_byte_stable_under_unsorted_input():
    a = [
        LoopInfo(name="B", module="m", source_path="p"),
        LoopInfo(name="A", module="m", source_path="p"),
    ]
    b = [
        LoopInfo(name="A", module="m", source_path="p"),
        LoopInfo(name="B", module="m", source_path="p"),
    ]
    assert render_loop_registry(a) == render_loop_registry(b)
