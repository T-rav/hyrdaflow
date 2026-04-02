#!/usr/bin/env python3
"""Generate boilerplate for a new BaseBackgroundLoop subclass.

Usage::

    python scripts/scaffold_loop.py my_worker "My Worker" "Does cool things every hour" --interval 3600

Generates:
- ``src/my_worker_loop.py``   -- loop skeleton
- ``tests/test_my_worker_loop.py`` -- test skeleton

Prints manual wiring instructions for the remaining integration points.
"""

from __future__ import annotations

import argparse
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
TESTS = ROOT / "tests"


def _class_name(worker_name: str) -> str:
    """Convert snake_case worker_name to PascalCase class name + 'Loop'."""
    return "".join(part.capitalize() for part in worker_name.split("_")) + "Loop"


def _generate_loop_file(
    worker_name: str, label: str, description: str, interval: int
) -> str:
    cls = _class_name(worker_name)
    return textwrap.dedent(f'''\
        """{description}"""

        from __future__ import annotations

        import logging
        from typing import Any

        from base_background_loop import BaseBackgroundLoop, LoopDeps
        from config import HydraFlowConfig

        logger = logging.getLogger("hydraflow.{worker_name}_loop")


        class {cls}(BaseBackgroundLoop):
            """{label} background loop.

            {description}
            """

            def __init__(
                self,
                *,
                config: HydraFlowConfig,
                deps: LoopDeps,
            ) -> None:
                super().__init__(worker_name="{worker_name}", config=config, deps=deps)

            def _get_default_interval(self) -> int:
                return self._config.{worker_name}_interval

            async def _do_work(self) -> dict[str, Any] | None:
                logger.info("{label} cycle starting")
                # TODO: implement loop body
                return None
    ''')


def _generate_test_file(worker_name: str, label: str, interval: int) -> str:
    cls = _class_name(worker_name)
    return textwrap.dedent(f'''\
        """Tests for {cls}."""

        from __future__ import annotations

        import asyncio
        from unittest.mock import MagicMock

        import pytest

        from {worker_name}_loop import {cls}
        from base_background_loop import LoopDeps


        def _make_loop(*, config: MagicMock | None = None) -> {cls}:
            """Create a {cls} with sensible test defaults."""
            if config is None:
                config = MagicMock()
                config.{worker_name}_interval = {interval}
                config.dry_run = False
                config.data_root = MagicMock()
                config.data_root.__truediv__ = MagicMock(return_value=MagicMock(exists=MagicMock(return_value=False)))

            deps = LoopDeps(
                event_bus=MagicMock(),
                stop_event=asyncio.Event(),
                status_cb=MagicMock(),
                enabled_cb=MagicMock(return_value=True),
                sleep_fn=MagicMock(),
                interval_cb=None,
            )
            return {cls}(config=config, deps=deps)


        class TestDefaultInterval:
            def test_returns_config_interval(self) -> None:
                loop = _make_loop()
                assert loop._get_default_interval() == {interval}


        class TestDryRun:
            @pytest.mark.asyncio
            async def test_do_work_succeeds(self) -> None:
                loop = _make_loop()
                result = await loop._do_work()
                # Skeleton returns None -- replace with real assertions
                assert result is None
    ''')


def _print_wiring_instructions(worker_name: str, label: str, interval: int) -> None:
    cls = _class_name(worker_name)
    print(f"\n{'=' * 70}")
    print(f"  Generated: src/{worker_name}_loop.py")
    print(f"  Generated: tests/test_{worker_name}_loop.py")
    print(f"{'=' * 70}")
    print("\n  Manual wiring steps:\n")

    print("  1. src/config.py -- add Field + _ENV_INT_OVERRIDES entry:\n")
    print(f"     {worker_name}_interval: int = Field({interval}, ge=60, le=604800)")
    print(
        f'     ("{worker_name}_interval", "HYDRAFLOW_{worker_name.upper()}_INTERVAL", {interval}),\n'
    )

    print("  2. src/service_registry.py -- add import + dataclass field:\n")
    print(f"     from {worker_name}_loop import {cls}")
    print(f"     {worker_name}_loop: {cls}  # in ServiceRegistry dataclass\n")

    print("  3. src/service_registry.py -- add to build_services():\n")
    print(f"     {worker_name}_loop = {cls}(config=config, deps=loop_deps)")
    print(
        f"     # and include {worker_name}_loop= in the ServiceRegistry(...) return\n"
    )

    print("  4. src/orchestrator.py -- add to bg_loop_registry:\n")
    print(f'     "{worker_name}": svc.{worker_name}_loop,\n')

    print("  5. src/ui/src/constants.js -- add to BACKGROUND_WORKERS:\n")
    print(
        f"     {{ key: '{worker_name}', label: '{label}', description: '...', color: theme.accent }},\n"
    )

    print("  6. src/dashboard_routes/_common.py -- add to _INTERVAL_BOUNDS:\n")
    print(f'     "{worker_name}": (60, 604800),\n')

    print("  Run tests/test_loop_wiring_completeness.py to verify wiring.\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Scaffold a new background loop")
    parser.add_argument("worker_name", help="Snake-case worker name (e.g. my_worker)")
    parser.add_argument("label", help="Human-readable label (e.g. 'My Worker')")
    parser.add_argument("description", help="One-line description")
    parser.add_argument(
        "--interval", type=int, default=3600, help="Default interval in seconds"
    )
    args = parser.parse_args(argv)

    loop_path = SRC / f"{args.worker_name}_loop.py"
    test_path = TESTS / f"test_{args.worker_name}_loop.py"

    if loop_path.exists():
        print(f"ERROR: {loop_path} already exists", file=sys.stderr)
        sys.exit(1)
    if test_path.exists():
        print(f"ERROR: {test_path} already exists", file=sys.stderr)
        sys.exit(1)

    loop_path.write_text(
        _generate_loop_file(
            args.worker_name, args.label, args.description, args.interval
        )
    )
    test_path.write_text(
        _generate_test_file(args.worker_name, args.label, args.interval)
    )

    _print_wiring_instructions(args.worker_name, args.label, args.interval)


if __name__ == "__main__":
    main()
