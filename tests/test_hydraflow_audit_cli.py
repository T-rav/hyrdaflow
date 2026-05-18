"""CLI behaviour tests for ``python -m scripts.hydraflow_audit``.

Guards the contract that ``--json`` emits a JSON payload on **stdout**.
``principles_audit_loop`` parses subprocess stdout; an earlier regression
shipped ``--json`` that only wrote the report file and printed nothing,
causing the loop to fail every cycle with ``JSONDecodeError``.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from scripts.hydraflow_audit.__main__ import main


def _seed_target(target: Path) -> None:
    """Create a minimal ADR-0044 file so the audit can run."""
    adr_dir = target / "docs" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "0044-hydraflow-principles.md").write_text(
        "# ADR-0044: HydraFlow Principles\n\n"
        "**Status:** Accepted\n\n"
        "### P1. Documentation Contract\n\n"
        "| check_id | type | source | what | remediation |\n"
        "|---|---|---|---|---|\n"
        "| P1.1 | STRUCTURAL | CLAUDE.md | CLAUDE.md exists | touch CLAUDE.md |\n",
        encoding="utf-8",
    )


def test_json_flag_writes_payload_to_stdout(tmp_path: Path) -> None:
    _seed_target(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main([str(tmp_path), "--json"])

    payload = json.loads(buf.getvalue())
    assert payload["version"] == 1
    assert "summary" in payload
    assert "findings" in payload
    assert isinstance(payload["findings"], list)


def test_json_flag_also_writes_report_file(tmp_path: Path) -> None:
    _seed_target(tmp_path)
    with redirect_stdout(io.StringIO()):
        main([str(tmp_path), "--json"])

    report = tmp_path / ".hydraflow" / "audit-report.json"
    assert report.exists()
    on_disk = json.loads(report.read_text())
    assert on_disk["version"] == 1


def test_terminal_mode_does_not_emit_json_on_stdout(tmp_path: Path) -> None:
    _seed_target(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        main([str(tmp_path)])

    out = buf.getvalue()
    assert "HydraFlow Conformance Audit" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)
