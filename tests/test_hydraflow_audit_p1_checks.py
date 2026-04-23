"""Tests for P1 (Documentation Contract) check functions.

Each test builds a minimal fake repo under `tmp_path`, runs one check, and
asserts the status. Uses the real registered check functions — no mocks —
to match the principle in P3.14 (stateful inspection beats call-count).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.hydraflow_audit import registry  # noqa: F401 — import side effect
from scripts.hydraflow_audit.checks import p1_docs  # noqa: F401 — registers checks
from scripts.hydraflow_audit.models import CheckContext, Status


def _ctx(root: Path, *, orchestration: bool = False) -> CheckContext:
    return CheckContext(root=root, is_orchestration_repo=orchestration)


def _run(check_id: str, ctx: CheckContext):
    fn = registry.get(check_id)
    assert fn is not None, f"check {check_id} is not registered"
    return fn(ctx)


@pytest.mark.parametrize(
    ("check_id", "relpath"),
    [
        ("P1.1", "CLAUDE.md"),
        ("P1.2", "docs/agents/README.md"),
        ("P1.3", "docs/agents/architecture.md"),
        ("P1.4", "docs/agents/worktrees.md"),
        ("P1.5", "docs/agents/testing.md"),
        ("P1.6", "docs/agents/avoided-patterns.md"),
        ("P1.7", "docs/agents/quality-gates.md"),
        ("P1.9", "docs/agents/sentry.md"),
        ("P1.10", "docs/agents/commands.md"),
    ],
)
def test_simple_file_exists_check_passes_when_file_present(
    check_id: str, relpath: str, tmp_path: Path
) -> None:
    (tmp_path / relpath).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / relpath).write_text("content", encoding="utf-8")
    result = _run(check_id, _ctx(tmp_path))
    assert result.status is Status.PASS


@pytest.mark.parametrize(
    "check_id",
    ["P1.1", "P1.2", "P1.3", "P1.5", "P1.9", "P1.10"],
)
def test_simple_file_exists_check_fails_when_file_absent(
    check_id: str, tmp_path: Path
) -> None:
    assert _run(check_id, _ctx(tmp_path)).status is Status.FAIL


def test_background_loops_doc_is_na_for_non_orchestration_repo(tmp_path: Path) -> None:
    result = _run("P1.8", _ctx(tmp_path, orchestration=False))
    assert result.status is Status.NA


def test_background_loops_doc_required_for_orchestration_repo(tmp_path: Path) -> None:
    result = _run("P1.8", _ctx(tmp_path, orchestration=True))
    assert result.status is Status.FAIL


def test_adr_readme_passes_with_index_row(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "README.md").write_text(
        "| ADR | Title |\n|---|---|\n| [0001](0001-foo.md) | foo |\n",
        encoding="utf-8",
    )
    assert _run("P1.11", _ctx(tmp_path)).status is Status.PASS


def test_adr_readme_fails_when_index_is_empty(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "README.md").write_text(
        "no index here", encoding="utf-8"
    )
    assert _run("P1.11", _ctx(tmp_path)).status is Status.FAIL


def test_quick_rules_section_required_in_claude_md(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text("# Project\n\nblurb.\n", encoding="utf-8")
    assert _run("P1.12", _ctx(tmp_path)).status is Status.FAIL


def test_quick_rules_section_passes_when_heading_present(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n## Quick rules\n", encoding="utf-8"
    )
    assert _run("P1.12", _ctx(tmp_path)).status is Status.PASS


def test_knowledge_lookup_heading_passes(tmp_path: Path) -> None:
    (tmp_path / "CLAUDE.md").write_text(
        "# Project\n\n## Knowledge Lookup\n\n| Source | Path |\n",
        encoding="utf-8",
    )
    assert _run("P1.13", _ctx(tmp_path)).status is Status.PASS


def test_load_bearing_adrs_na_for_non_orchestration(tmp_path: Path) -> None:
    assert _run("P1.14", _ctx(tmp_path, orchestration=False)).status is Status.NA


def test_load_bearing_adrs_fail_when_missing(tmp_path: Path) -> None:
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "docs" / "adr" / "0001-five-concurrent-async-loops.md").write_text(
        "x", encoding="utf-8"
    )
    # Only one of the seven load-bearing ADRs present — should fail.
    result = _run("P1.14", _ctx(tmp_path, orchestration=True))
    assert result.status is Status.FAIL
    assert "ADR-0002" in result.message


def test_load_bearing_adrs_pass_when_all_present(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    for number in ("0001", "0002", "0003", "0021", "0022", "0029", "0032"):
        (adr_dir / f"{number}-x.md").write_text("x", encoding="utf-8")
    assert _run("P1.14", _ctx(tmp_path, orchestration=True)).status is Status.PASS


def test_avoided_patterns_content_fails_on_stub(tmp_path: Path) -> None:
    (tmp_path / "docs" / "agents").mkdir(parents=True)
    (tmp_path / "docs" / "agents" / "avoided-patterns.md").write_text(
        "# Avoided patterns\n\ntodo.\n", encoding="utf-8"
    )
    assert _run("P1.15", _ctx(tmp_path)).status is Status.FAIL


def test_avoided_patterns_content_passes_when_populated(tmp_path: Path) -> None:
    body = "# Avoided patterns\n\n" + "\n".join(
        f"## Pattern {i}\n\n```python\nbad()\n```\n" for i in range(1, 6)
    )
    (tmp_path / "docs" / "agents").mkdir(parents=True)
    (tmp_path / "docs" / "agents" / "avoided-patterns.md").write_text(
        body, encoding="utf-8"
    )
    assert _run("P1.15", _ctx(tmp_path)).status is Status.PASS


def test_line_number_citation_warns(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-bad.md").write_text(
        "See `src/config.py:42` for details.\n", encoding="utf-8"
    )
    result = _run("P1.16", _ctx(tmp_path))
    assert result.status is Status.WARN
    assert "config.py:42" in result.message


def test_line_number_citation_clean_adr_passes(tmp_path: Path) -> None:
    adr_dir = tmp_path / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0001-clean.md").write_text(
        "See `src/config.py:HydraFlowConfig` for the class.\n", encoding="utf-8"
    )
    assert _run("P1.16", _ctx(tmp_path)).status is Status.PASS
