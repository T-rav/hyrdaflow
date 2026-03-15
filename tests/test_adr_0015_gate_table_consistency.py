"""Tests that ADR-0015 gate table is consistent with source code.

These tests validate structural consistency between the ADR gate inventory
and the actual codebase — they do NOT test markdown prose content.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ADR_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "adr"
    / "0015-protocol-callback-gate-pattern.md"
)
MODELS_PATH = Path(__file__).resolve().parents[1] / "src" / "models.py"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "src" / "config.py"
REVIEW_PHASE_PATH = Path(__file__).resolve().parents[1] / "src" / "review_phase.py"


@pytest.fixture()
def adr_content() -> str:
    return ADR_PATH.read_text()


@pytest.fixture()
def gate_table_rows(adr_content: str) -> list[dict[str, str]]:
    """Parse the gate table into structured rows."""
    lines = adr_content.splitlines()
    rows: list[dict[str, str]] = []
    in_table = False
    headers: list[str] = []
    for line in lines:
        if "| Gate |" in line:
            headers = [h.strip() for h in line.split("|")[1:-1]]
            in_table = True
            continue
        if in_table and line.strip().startswith("|---"):
            continue
        if in_table and line.strip().startswith("|"):
            cols = [c.strip() for c in line.split("|")[1:-1]]
            if len(cols) == len(headers):
                rows.append(dict(zip(headers, cols, strict=False)))
        elif in_table:
            break
    return rows


class TestAdr0015GateTableConsistency:
    """Verify gate table entries match actual source code artifacts."""

    def test_merge_conflict_fix_has_config_guard(
        self, gate_table_rows: list[dict[str, str]]
    ) -> None:
        """Merge conflict fix row references the real config field, not a runtime trigger."""
        row = next(r for r in gate_table_rows if r["Gate"] == "Merge conflict fix")
        assert "max_merge_conflict_fix_attempts" in row["Config Guard"]
        # Verify the config field actually exists
        config_src = CONFIG_PATH.read_text()
        assert "max_merge_conflict_fix_attempts" in config_src

    def test_status_publishing_has_rule3_exception(
        self, gate_table_rows: list[dict[str, str]], adr_content: str
    ) -> None:
        """Status publishing row discloses its Rule 3 exception via footnote."""
        row = next(r for r in gate_table_rows if r["Gate"] == "Status publishing")
        # Must have a footnote marker
        assert "[^1]" in row["Config Guard"]
        # Footnote body must exist and mention Rule 3
        assert "[^1]:" in adr_content
        footnote_start = adr_content.index("[^1]:")
        footnote_text = adr_content[footnote_start : footnote_start + 500]
        assert "Rule 3" in footnote_text

    def test_adversarial_threshold_names_method(
        self, gate_table_rows: list[dict[str, str]]
    ) -> None:
        """Adversarial threshold row names the method rather than describing its return type."""
        row = next(r for r in gate_table_rows if r["Gate"] == "Adversarial threshold")
        protocol_col = row["Protocol / Decision"]
        # Should NOT say "Returns ReviewResult"
        assert "Returns" not in protocol_col
        # Should reference the actual method name
        assert "_check_adversarial_threshold" in protocol_col
        # Verify the method actually exists in review_phase.py
        review_src = REVIEW_PHASE_PATH.read_text()
        assert "_check_adversarial_threshold" in review_src

    def test_all_protocol_names_exist_in_models(
        self, gate_table_rows: list[dict[str, str]]
    ) -> None:
        """Every Protocol/Decision backtick-quoted name in the table exists in models.py."""
        models_src = MODELS_PATH.read_text()
        for row in gate_table_rows:
            names = re.findall(r"`(\w+)`", row["Protocol / Decision"])
            for name in names:
                # Skip method names (start with _)
                if name.startswith("_"):
                    continue
                assert name in models_src, (
                    f"{name} from gate '{row['Gate']}' not found in models.py"
                )

    def test_no_undisclosed_rule3_violations(
        self, gate_table_rows: list[dict[str, str]], adr_content: str
    ) -> None:
        """Every gate without a config boolean/threshold has a footnote disclosure."""
        config_guard_pattern = re.compile(
            r"`\w+\s*(>|==|!=|<|>=|<=)\s*\d+`|`\w+_enabled`"
        )
        for row in gate_table_rows:
            guard = row["Config Guard"]
            has_config_ref = bool(config_guard_pattern.search(guard))
            if not has_config_ref:
                # Must have a footnote marker disclosing the exception
                assert re.search(r"\[\^\d+\]", guard), (
                    f"Gate '{row['Gate']}' has no config boolean/threshold "
                    f"and no footnote disclosing a Rule 3 exception"
                )
