"""Tests for P2 (Architecture) check functions."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401
from scripts.hydraflow_audit.checks import p2_architecture  # noqa: F401
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path) -> CheckContext:
    return CheckContext(root=root)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None
    return fn(ctx)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# --- P2.1 ----------------------------------------------------------------


def test_src_dir_check(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.1", _ctx(tmp_path)).status is Status.PASS


# --- P2.2 and P2.2a ------------------------------------------------------


_PORTS_WITH_TWO_PROTOCOLS = """
from typing import Protocol

class VCSPort(Protocol):
    def push(self) -> None: ...

class WorkspacePort(Protocol):
    def create(self) -> None: ...
"""

_PORTS_WITH_ONE_PROTOCOL = """
from typing import Protocol

class VCSPort(Protocol):
    def push(self) -> None: ...
"""

_PORTS_WITH_NO_PROTOCOLS = """
class NotAPort:
    pass
"""


def test_ports_with_two_protocols_passes(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ports.py", _PORTS_WITH_TWO_PROTOCOLS)
    assert _run("P2.2", _ctx(tmp_path)).status is Status.PASS
    assert _run("P2.2a", _ctx(tmp_path)).status is Status.PASS


def test_ports_with_one_protocol_warns_on_coverage(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ports.py", _PORTS_WITH_ONE_PROTOCOL)
    assert _run("P2.2", _ctx(tmp_path)).status is Status.PASS
    assert _run("P2.2a", _ctx(tmp_path)).status is Status.WARN


def test_ports_without_protocols_fails(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "ports.py", _PORTS_WITH_NO_PROTOCOLS)
    assert _run("P2.2", _ctx(tmp_path)).status is Status.FAIL


def test_missing_ports_file_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.2", _ctx(tmp_path)).status is Status.FAIL


# --- P2.3 / P2.4 / P2.7 (layer check) ------------------------------------

_LAYER_CHECK_ALWAYS_OK = """#!/usr/bin/env python3
import sys
sys.exit(0)
"""

_LAYER_CHECK_ALWAYS_FAIL = """#!/usr/bin/env python3
import sys
print("boundary violation")
sys.exit(1)
"""


def test_layer_check_script_present(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "check_layer_imports.py", _LAYER_CHECK_ALWAYS_OK)
    assert _run("P2.3", _ctx(tmp_path)).status is Status.PASS


def test_layer_check_passes_when_exits_zero(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "check_layer_imports.py", _LAYER_CHECK_ALWAYS_OK)
    assert _run("P2.4", _ctx(tmp_path)).status is Status.PASS
    assert _run("P2.7", _ctx(tmp_path)).status is Status.PASS


def test_layer_check_fails_on_nonzero_exit(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "check_layer_imports.py", _LAYER_CHECK_ALWAYS_FAIL)
    assert _run("P2.4", _ctx(tmp_path)).status is Status.FAIL
    assert _run("P2.7", _ctx(tmp_path)).status is Status.FAIL


# --- P2.5 composition root -----------------------------------------------


@pytest.mark.parametrize(
    "filename",
    ["service_registry.py", "composition_root.py", "container.py"],
)
def test_composition_root_detection(filename: str, tmp_path: Path) -> None:
    _write(tmp_path / "src" / filename, "registry = {}")
    assert _run("P2.5", _ctx(tmp_path)).status is Status.PASS


def test_composition_root_missing_fails(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.5", _ctx(tmp_path)).status is Status.FAIL


# --- P2.6 ALLOWLIST ------------------------------------------------------


def test_allowlist_declared_in_layer_check(tmp_path: Path) -> None:
    _write(
        tmp_path / "scripts" / "check_layer_imports.py",
        "ALLOWLIST = {'service_registry': True}\n",
    )
    assert _run("P2.6", _ctx(tmp_path)).status is Status.PASS


def test_allowlist_absent_warns(tmp_path: Path) -> None:
    _write(tmp_path / "scripts" / "check_layer_imports.py", "# no allowlist here\n")
    assert _run("P2.6", _ctx(tmp_path)).status is Status.WARN


# --- P2.8 anaemic domain -------------------------------------------------


_ANAEMIC_MODELS = """
class Issue:
    def __init__(self, id: int, title: str) -> None:
        self.id = id
        self.title = title

class Task:
    def __init__(self, name: str) -> None:
        self.name = name
"""

_RICH_MODELS = """
class Issue:
    def __init__(self, id: int, title: str) -> None:
        self.id = id
        self.title = title
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def reopen(self) -> None:
        self.closed = False

class Task:
    def __init__(self, name: str) -> None:
        self.name = name

    def run(self) -> None:
        pass
"""


def test_anaemic_domain_warns(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "models.py", _ANAEMIC_MODELS)
    assert _run("P2.8", _ctx(tmp_path)).status is Status.WARN


def test_rich_domain_passes(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "models.py", _RICH_MODELS)
    assert _run("P2.8", _ctx(tmp_path)).status is Status.PASS


def test_no_domain_sample_is_na(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    assert _run("P2.8", _ctx(tmp_path)).status is Status.NA


# --- P2.9 ubiquitous language --------------------------------------------


def test_ubiquitous_language_passes_when_terms_overlap(tmp_path: Path) -> None:
    """CLAUDE.md ToC terms appear in the wiki's architecture topic page."""
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: TaskRunner coordinates the pipeline. IssueTracker, LabelMachine, and PhaseGuard round it out.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture.md",
        "Core types include TaskRunner, IssueTracker, LabelMachine, PhaseGuard.\n",
    )
    assert _run("P2.9", _ctx(tmp_path)).status is Status.PASS


def test_ubiquitous_language_warns_on_divergence(tmp_path: Path) -> None:
    """CLAUDE.md names types the wiki never explains."""
    _write(
        tmp_path / "CLAUDE.md",
        "Key concepts: AlphaType, BetaType, GammaType, DeltaType.\n",
    )
    _write(
        tmp_path / "docs" / "wiki" / "architecture.md",
        "Some unrelated text.\n",
    )
    assert _run("P2.9", _ctx(tmp_path)).status is Status.WARN


def test_ubiquitous_language_na_when_docs_missing(tmp_path: Path) -> None:
    assert _run("P2.9", _ctx(tmp_path)).status is Status.NA
