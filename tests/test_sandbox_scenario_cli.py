"""sandbox_scenario CLI — invocation surface tests.

Doesn't actually boot docker — patches subprocess.run. Verifies the
correct compose commands are issued for each subcommand.
"""

from __future__ import annotations

from unittest.mock import patch

from scripts import sandbox_scenario


def test_seed_subcommand_writes_json(tmp_path) -> None:
    seeds_dir = tmp_path / "seeds"
    with (
        patch.object(sandbox_scenario, "SEEDS_DIR", seeds_dir),
        patch.object(sandbox_scenario, "load_scenario") as load,
    ):
        load.return_value.NAME = "s00_smoke"
        load.return_value.seed.return_value.to_json.return_value = '{"x": 1}'
        sandbox_scenario.cmd_seed("s00_smoke")
    assert (seeds_dir / "s00_smoke.json").read_text() == '{"x": 1}'


def test_down_subcommand_calls_compose_down() -> None:
    with patch("subprocess.run") as run:
        sandbox_scenario.cmd_down()
    args = run.call_args[0][0]
    assert "docker" in args[0] and "compose" in args
    assert "down" in args
