"""CLI: install all Tier-1 + Tier-2 plugins declared in the active HydraFlow config.

Invoked by ``make install-plugins``. Reads the same config HydraFlow boots
with and runs ``claude plugin install`` for each missing plugin via the
shared :func:`preflight.install_plugin` helper.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from config import HydraFlowConfig
from plugin_skill_registry import DEFAULT_CACHE_ROOT, parse_plugin_spec
from preflight import install_plugin, plugin_exists

logger = logging.getLogger("hydraflow.install_plugins_cli")


def run(config: HydraFlowConfig, *, cache_root: Path | None = None) -> int:
    """Install every plugin in ``config`` not yet present in ``cache_root``.

    Returns process exit code: 0 on success, non-zero if any install failed.
    """
    root = cache_root or DEFAULT_CACHE_ROOT
    all_entries = list(config.required_plugins)
    for plugins in config.language_plugins.values():
        all_entries.extend(plugins)

    failures: list[str] = []
    for entry in all_entries:
        try:
            name, marketplace = parse_plugin_spec(entry)
        except ValueError as exc:
            failures.append(str(exc))
            continue
        if plugin_exists(root, name):
            logger.info("already installed: %s@%s", name, marketplace)
            continue
        ok, detail = install_plugin(name, marketplace)
        if ok:
            logger.info("installed %s@%s", name, marketplace)
        else:
            failures.append(f"{name}@{marketplace}: {detail}")

    if failures:
        for failure in failures:
            logger.error("%s", failure)
        return 1
    return 0


def main() -> int:
    """Entry point for ``python -m install_plugins_cli``."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    cfg = HydraFlowConfig()  # defaults; no CLI args — matches make target expectations
    return run(cfg)


if __name__ == "__main__":
    sys.exit(main())
