"""Discover all sandbox scenarios under tests/sandbox_scenarios/scenarios/."""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from types import ModuleType


def load_all_scenarios() -> list[ModuleType]:
    """Import every s*.py module under tests/sandbox_scenarios/scenarios/."""
    import tests.sandbox_scenarios.scenarios as scenarios_pkg

    out: list[ModuleType] = []
    pkg_path = Path(scenarios_pkg.__file__).parent
    for _finder, name, _ispkg in pkgutil.iter_modules([str(pkg_path)]):
        if not name.startswith("s"):
            continue
        mod = importlib.import_module(f"tests.sandbox_scenarios.scenarios.{name}")
        out.append(mod)
    return sorted(out, key=lambda m: m.NAME)
