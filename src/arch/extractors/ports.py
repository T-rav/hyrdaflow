"""Extract PortInfo records from src/*.py and tests/scenarios/fakes/*.py.

A "Port" is a `typing.Protocol` subclass whose name ends in `Port`. For each
discovered Port, we find:
- adapters: concrete classes in `src/` whose public method set is a superset
  of the Port's methods (best-effort heuristic).
- fake: a class under `tests/scenarios/fakes/` named `Fake<PortStem>`, with a
  fallback to any `Fake*` whose method set is a superset.

Pure AST analysis — no imports, no instantiation.
"""

from __future__ import annotations

import ast
from pathlib import Path

from arch._models import PortAdapterInfo, PortInfo


def _is_protocol_subclass(cls: ast.ClassDef) -> bool:
    for base in cls.bases:
        if isinstance(base, ast.Name) and base.id == "Protocol":
            return True
        if isinstance(base, ast.Attribute) and base.attr == "Protocol":
            return True
    return False


def _public_methods(cls: ast.ClassDef) -> list[str]:
    out = []
    for node in cls.body:
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef)
        ) and not node.name.startswith("__"):
            out.append(node.name)
    return sorted(out)


def _src_module_dotted(path: Path, src_dir: Path) -> str:
    """For src/foo/bar.py with src_dir=/repo/src, return 'src.foo.bar'."""
    rel = path.relative_to(src_dir.parent)
    return ".".join(rel.with_suffix("").parts)


def _repo_relative_module(path: Path, repo_root: Path) -> str:
    """For repo/tests/scenarios/fakes/fake_x.py, return 'tests.scenarios.fakes.fake_x'."""
    rel = path.relative_to(repo_root)
    return ".".join(rel.with_suffix("").parts)


def _collect_classes(scan_dir: Path) -> list[tuple[Path, ast.ClassDef]]:
    out: list[tuple[Path, ast.ClassDef]] = []
    if not scan_dir.exists():
        return out
    for py in sorted(scan_dir.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text())
        except SyntaxError:
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                out.append((py, node))
    return out


def extract_ports(*, src_dir: Path, fakes_dir: Path) -> list[PortInfo]:
    src_dir = Path(src_dir).resolve()
    fakes_dir = Path(fakes_dir).resolve()
    repo_root = src_dir.parent  # src_dir is <repo>/src; one up is the repo root

    src_classes = _collect_classes(src_dir)
    fake_classes = _collect_classes(fakes_dir) if fakes_dir.exists() else []

    ports: list[PortInfo] = []
    for path, cls in src_classes:
        if not cls.name.endswith("Port"):
            continue
        if not _is_protocol_subclass(cls):
            continue

        methods = _public_methods(cls)
        port_methods = set(methods)

        # Adapters: src classes (non-Protocol) whose public method set is a
        # superset of the Port's. Skip the Port class itself.
        adapters: list[PortAdapterInfo] = []
        for apath, acls in src_classes:
            if acls is cls:
                continue
            if _is_protocol_subclass(acls):
                continue
            if not port_methods.issubset(set(_public_methods(acls))):
                continue
            adapters.append(
                PortAdapterInfo(
                    name=acls.name,
                    module=_src_module_dotted(apath, src_dir),
                    source_path=str(apath.relative_to(repo_root)),
                )
            )

        # Fake: prefer Fake<PortStem>; fall back to any Fake* with superset methods.
        port_stem = cls.name[: -len("Port")]
        fake: PortAdapterInfo | None = None
        for fpath, fcls in fake_classes:
            if fcls.name == f"Fake{port_stem}":
                fake = PortAdapterInfo(
                    name=fcls.name,
                    module=_repo_relative_module(fpath, repo_root),
                    source_path=str(fpath.relative_to(repo_root)),
                    is_fake=True,
                )
                break
        if fake is None:
            for fpath, fcls in fake_classes:
                if not fcls.name.startswith("Fake"):
                    continue
                if not port_methods.issubset(set(_public_methods(fcls))):
                    continue
                fake = PortAdapterInfo(
                    name=fcls.name,
                    module=_repo_relative_module(fpath, repo_root),
                    source_path=str(fpath.relative_to(repo_root)),
                    is_fake=True,
                )
                break

        ports.append(
            PortInfo(
                name=cls.name,
                module=_src_module_dotted(path, src_dir),
                source_path=str(path.relative_to(repo_root)),
                methods=methods,
                adapters=sorted(adapters, key=lambda a: a.name),
                fake=fake,
            )
        )

    ports.sort(key=lambda port: port.name)
    return ports
