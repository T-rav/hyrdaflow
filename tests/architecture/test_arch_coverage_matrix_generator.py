"""Tests for src/arch/generators/coverage_matrix.py.

Structural assertions:
- At least 41 loop rows (baseline was 41; new loops added after the audit
  will push the count higher as the generator tracks live source).
- Exactly 9 port rows (stable set of Port Protocols).
- Every non-header, non-separator table cell follows the ✅/⚠️/❌/N/A vocabulary.
- Counts reconcile between the generator and the live extractors.
- Section 3 is emitted as a cross-reference note (not regenerable prose).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from arch._models import LoopInfo, PortInfo
from arch.extractors.loops import extract_loops
from arch.extractors.ports import extract_ports
from arch.generators.coverage_matrix import (
    LOOP_ALIASES,
    PORT_ALIASES,
    _snake,
    render_coverage_matrix,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def repo_root() -> Path:
    """Absolute path to the live repo root (parents[3] from this test file)."""
    return Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def live_loops(repo_root: Path) -> list[LoopInfo]:
    return extract_loops(repo_root / "src")


@pytest.fixture(scope="module")
def live_ports(repo_root: Path) -> list[PortInfo]:
    return extract_ports(
        src_dir=repo_root / "src",
        fakes_dir=repo_root / "src/mockworld/fakes",
    )


@pytest.fixture(scope="module")
def matrix_md(
    live_loops: list[LoopInfo], live_ports: list[PortInfo], repo_root: Path
) -> str:
    return render_coverage_matrix(live_loops, live_ports, repo_root=repo_root)


# ---------------------------------------------------------------------------
# Row count tests
# ---------------------------------------------------------------------------


def test_loop_row_count_at_least_41(matrix_md: str) -> None:
    """Generator emits at least 41 loop rows (baseline audit count).

    The live source tree may have more loops than the audit snapshot; the
    generator tracks live source so this is >= 41 not == 41.
    """
    loop_rows = [
        line for line in matrix_md.splitlines() if re.match(r"^\| `\w+Loop`", line)
    ]
    assert len(loop_rows) >= 41, f"Expected >= 41 loop rows, got {len(loop_rows)}"


def test_loop_row_count_matches_extractor(
    matrix_md: str, live_loops: list[LoopInfo]
) -> None:
    """Generator loop row count == number of loops found by the extractor."""
    loop_rows = [
        line for line in matrix_md.splitlines() if re.match(r"^\| `\w+Loop`", line)
    ]
    assert len(loop_rows) == len(live_loops), (
        f"Matrix has {len(loop_rows)} loop rows but extractor found "
        f"{len(live_loops)} loops"
    )


def test_port_row_count_is_nine(matrix_md: str) -> None:
    """Generator emits exactly 9 port rows."""
    port_rows = [
        line for line in matrix_md.splitlines() if re.match(r"^\| `\w+Port`", line)
    ]
    assert len(port_rows) == 9, f"Expected 9 port rows, got {len(port_rows)}"


def test_port_row_count_matches_extractor(
    matrix_md: str, live_ports: list[PortInfo]
) -> None:
    """Generator port row count == number of ports found by the extractor."""
    port_rows = [
        line for line in matrix_md.splitlines() if re.match(r"^\| `\w+Port`", line)
    ]
    assert len(port_rows) == len(live_ports), (
        f"Matrix has {len(port_rows)} port rows but extractor found "
        f"{len(live_ports)} ports"
    )


# ---------------------------------------------------------------------------
# Cell vocabulary tests
# ---------------------------------------------------------------------------

_VALID_CELL_PREFIXES = ("✅", "⚠️", "❌", "N/A")


def _extract_data_cells(matrix_md: str) -> list[str]:
    """Return all non-header, non-separator table cells from the matrix."""
    cells: list[str] = []
    for line in matrix_md.splitlines():
        if not line.startswith("|"):
            continue
        # Skip header rows (contain column names like "Loop", "ADR")
        if re.match(r"^\| (?:Loop|Port|Phase)", line):
            continue
        # Skip separator rows
        if re.match(r"^\|[-| ]+\|", line):
            continue
        # Skip the row name cell (first cell, backtick name)
        parts = [p.strip() for p in line.split("|")]
        # parts[0] is empty (before first |), parts[1] is the name cell
        for cell in parts[2:]:
            if not cell:
                continue
            cells.append(cell)
    return cells


def test_all_cells_use_valid_vocabulary(matrix_md: str) -> None:
    """Every data cell starts with ✅, ⚠️, ❌, or N/A."""
    cells = _extract_data_cells(matrix_md)
    assert cells, "No data cells found — matrix may be empty"
    bad = [c for c in cells if not any(c.startswith(p) for p in _VALID_CELL_PREFIXES)]
    assert not bad, (
        f"{len(bad)} cells have invalid vocabulary (first 10):\n"
        + "\n".join(f"  {c!r}" for c in bad[:10])
    )


# ---------------------------------------------------------------------------
# Structure tests
# ---------------------------------------------------------------------------


def test_header_present(matrix_md: str) -> None:
    assert "# Coverage Matrix" in matrix_md


def test_generated_comment_present(matrix_md: str) -> None:
    assert "do not hand-edit" in matrix_md


def test_section1_header(matrix_md: str) -> None:
    assert "## Section 1: Loops" in matrix_md


def test_section2_header(matrix_md: str) -> None:
    assert "## Section 2: Ports" in matrix_md


def test_section3_is_note_not_prose(matrix_md: str) -> None:
    """Section 3 emits a cross-reference note, not a full phase table."""
    assert "## Section 3: Factory phases" in matrix_md
    assert "hand-curated" in matrix_md
    # The section must NOT emit a phases table with pipe-separated rows
    # like "| triage | ... | ... | ... |". If such a table existed it
    # would mean we accidentally regenerated the hand-curated content.
    phase_table_row = re.compile(
        r"^\| `(?:triage|discover|shape|plan|implement|review|HITL|merge)`"
    )
    has_phase_row = any(phase_table_row.match(line) for line in matrix_md.splitlines())
    assert not has_phase_row, "Section 3 must not contain a regenerated phase table"


def test_footer_sentinel(matrix_md: str) -> None:
    assert "{{ARCH_FOOTER}}" in matrix_md


def test_all_loop_names_present(matrix_md: str, live_loops: list[LoopInfo]) -> None:
    """Every loop discovered by the extractor has a row in the matrix."""
    for loop in live_loops:
        assert f"`{loop.name}`" in matrix_md, (
            f"Loop {loop.name!r} not found in coverage matrix"
        )


def test_all_port_names_present(matrix_md: str, live_ports: list[PortInfo]) -> None:
    """Every port discovered by the extractor has a row in the matrix."""
    for port in live_ports:
        assert f"`{port.name}`" in matrix_md, (
            f"Port {port.name!r} not found in coverage matrix"
        )


# ---------------------------------------------------------------------------
# Ports-specific: N/A columns
# ---------------------------------------------------------------------------


def test_ports_have_na_cassette_and_contract(matrix_md: str) -> None:
    """All port rows carry N/A in the Cassette and Contract columns."""
    for line in matrix_md.splitlines():
        if not re.match(r"^\| `\w+Port`", line):
            continue
        assert "N/A" in line, f"Port row missing N/A for Cassette/Contract: {line!r}"


# ---------------------------------------------------------------------------
# Unit: snake-case helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name,expected",
    [
        ("CIMonitorLoop", "ci_monitor_loop"),
        ("PRUnstickerLoop", "pr_unsticker_loop"),
        ("ADRReviewerLoop", "adr_reviewer_loop"),
        ("DiagramLoop", "diagram_loop"),
        ("StaleIssueGCLoop", "stale_issue_gc_loop"),
        ("WorkspaceGCLoop", "workspace_gc_loop"),
        ("AdrTouchpointAuditorLoop", "adr_touchpoint_auditor_loop"),
        ("StagingPromotionLoop", "staging_promotion_loop"),
        ("TrustFleetSanityLoop", "trust_fleet_sanity_loop"),
        ("RCBudgetLoop", "rc_budget_loop"),
    ],
)
def test_snake_conversion(name: str, expected: str) -> None:
    assert _snake(name) == expected


# ---------------------------------------------------------------------------
# Byte-stability test (same inputs → same output)
# ---------------------------------------------------------------------------


def test_render_is_deterministic(
    live_loops: list[LoopInfo],
    live_ports: list[PortInfo],
    repo_root: Path,
) -> None:
    """Two calls with the same inputs produce identical output."""
    md1 = render_coverage_matrix(live_loops, live_ports, repo_root=repo_root)
    md2 = render_coverage_matrix(live_loops, live_ports, repo_root=repo_root)
    assert md1 == md2


# ---------------------------------------------------------------------------
# Minimal render with synthetic inputs
# ---------------------------------------------------------------------------


def test_render_with_minimal_inputs(tmp_path: Path) -> None:
    """Generator does not crash when dirs are empty / non-existent."""
    # Create a minimal repo structure
    (tmp_path / "docs/adr").mkdir(parents=True)
    (tmp_path / "docs/wiki").mkdir(parents=True)
    (tmp_path / "docs/standards").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "tests/scenarios/catalog").mkdir(parents=True)
    (tmp_path / "tests/sandbox_scenarios/scenarios").mkdir(parents=True)
    (tmp_path / "src/mockworld/fakes").mkdir(parents=True)
    (tmp_path / "docs/arch/generated").mkdir(parents=True)

    loops = [
        LoopInfo(
            name="AlphaLoop", module="src.alpha_loop", source_path="src/alpha_loop.py"
        ),
    ]
    ports = [
        PortInfo(name="AlphaPort", module="src.ports", source_path="src/ports.py"),
    ]
    md = render_coverage_matrix(loops, ports, repo_root=tmp_path)
    assert "`AlphaLoop`" in md
    assert "`AlphaPort`" in md
    assert "# Coverage Matrix" in md
    # All cells must follow vocabulary even with missing dirs
    cells = _extract_data_cells(md)
    bad = [c for c in cells if not any(c.startswith(p) for p in _VALID_CELL_PREFIXES)]
    assert not bad, f"Bad cells in minimal render: {bad}"


# ---------------------------------------------------------------------------
# Constants accessible
# ---------------------------------------------------------------------------


def test_constants_are_accessible() -> None:
    """LOOP_ALIASES and PORT_ALIASES are importable dicts."""
    assert isinstance(LOOP_ALIASES, dict)
    assert isinstance(PORT_ALIASES, dict)
