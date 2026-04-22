from __future__ import annotations

from arch.prompt import render_adr_section

from arch.models import AdrSummary


def _adr(n: str, title: str, one_line: str = "one line.") -> AdrSummary:
    return AdrSummary(slug=f"{n}-x", number=n, title=title, one_line=one_line)


def test_empty_list_returns_empty_string() -> None:
    assert render_adr_section([]) == ""


def test_contains_expected_header_and_entries() -> None:
    out = render_adr_section([_adr("0001", "Foo"), _adr("0002", "Bar")])
    assert "Accepted architecture decisions" in out
    assert "0001-x" in out
    assert "Foo" in out
    assert "0002-x" in out


def test_title_only_mode_when_over_budget() -> None:
    adrs = [
        _adr(str(i).zfill(4), f"Title {i}", "long summary " * 20) for i in range(100)
    ]
    out = render_adr_section(adrs, token_budget=500)
    assert "long summary" not in out
    assert "Title 0" in out


def test_framing_override_for_reviewer() -> None:
    out = render_adr_section([_adr("0001", "Foo")], framing="reviewer")
    assert "flag" in out.lower()
