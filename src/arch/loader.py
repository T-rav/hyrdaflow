from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from pathlib import Path
from typing import cast

from arch.models import Allowlist, Fitness, ImportGraph, LayerMap, RuleModule
from arch.python_ast import python_ast_extractor


class LoaderError(RuntimeError):
    pass


REQUIRED_FIELDS = ("EXTRACTOR", "LAYERS", "ALLOWLIST", "FITNESS")


def _build_synthetic_pkg() -> tuple[types.ModuleType, types.ModuleType]:
    pkg = types.ModuleType("hydraflow")
    pkg.__path__ = []  # type: ignore[attr-defined]
    sub = types.ModuleType("hydraflow.arch")
    sub.LayerMap = LayerMap  # type: ignore[attr-defined]
    sub.Allowlist = Allowlist  # type: ignore[attr-defined]
    sub.Fitness = Fitness  # type: ignore[attr-defined]
    sub.python_ast_extractor = python_ast_extractor  # type: ignore[attr-defined]
    try:
        from arch.tree_sitter import tree_sitter_extractor

        sub.tree_sitter_extractor = tree_sitter_extractor  # type: ignore[attr-defined]
    except ImportError:
        pass
    return pkg, sub


def load_rule_module(path: Path) -> RuleModule:
    if not path.is_file():
        raise LoaderError(f"rule module not found: {path}")

    pkg, sub = _build_synthetic_pkg()
    prev_pkg = sys.modules.get("hydraflow")
    prev_sub = sys.modules.get("hydraflow.arch")
    sys.modules["hydraflow"] = pkg
    sys.modules["hydraflow.arch"] = sub
    try:
        spec = importlib.util.spec_from_file_location("_hydraflow_rules", str(path))
        if spec is None or spec.loader is None:
            raise LoaderError(f"cannot build import spec for {path}")
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except SyntaxError as e:
            raise LoaderError(f"SyntaxError in {path}: {e}") from e
        except Exception as e:  # noqa: BLE001
            raise LoaderError(f"error loading {path}: {e}") from e

        missing = [f for f in REQUIRED_FIELDS if not hasattr(module, f)]
        if missing:
            raise LoaderError(f"{path}: required field(s) missing: {missing}")

        extractor = module.EXTRACTOR
        layers = module.LAYERS
        allowlist = module.ALLOWLIST
        fitness = module.FITNESS

        if not callable(extractor):
            raise LoaderError(f"{path}: EXTRACTOR must be callable")
        if not isinstance(layers, LayerMap):
            raise LoaderError(f"{path}: LAYERS must be a LayerMap")
        if not isinstance(allowlist, Allowlist):
            raise LoaderError(f"{path}: ALLOWLIST must be an Allowlist")
        if not isinstance(fitness, list) or not all(
            isinstance(f, Fitness) for f in fitness
        ):
            raise LoaderError(f"{path}: FITNESS must be list[Fitness]")

        return RuleModule(
            extractor=cast(Callable[[str], ImportGraph], extractor),
            layers=layers,
            allowlist=allowlist,
            fitness=fitness,
        )
    finally:
        if prev_pkg is not None:
            sys.modules["hydraflow"] = prev_pkg
        else:
            sys.modules.pop("hydraflow", None)
        if prev_sub is not None:
            sys.modules["hydraflow.arch"] = prev_sub
        else:
            sys.modules.pop("hydraflow.arch", None)
