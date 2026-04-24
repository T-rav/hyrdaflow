"""Tests for the parse-warning smoke signal in CodeGroomingLoop.

Closes the LLM-audit gap where a grooming run that produced prose
output (wrong shape) silently filed zero findings with no operator
alert. Parsing remains best-effort — we just log when the signal
looks suspicious.
"""

from __future__ import annotations

import logging

from code_grooming_loop import CodeGroomingLoop


def test_parse_empty_transcript_is_silent(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        findings = CodeGroomingLoop._parse_findings("")
    assert findings == []
    assert "zero parseable findings" not in caplog.text


def test_parse_short_transcript_is_silent(caplog) -> None:
    """Under 500 chars = "nothing to audit" signal, not prompt drift."""
    with caplog.at_level(logging.WARNING):
        findings = CodeGroomingLoop._parse_findings("Nothing to groom today.")
    assert findings == []
    assert "zero parseable findings" not in caplog.text


def test_parse_long_prose_transcript_emits_warning(caplog) -> None:
    """Large transcript with zero JSON findings = probable prompt drift."""
    prose = (
        "The code base appears to be in good shape. I examined " * 40
        + "the core modules and found no critical issues."
    )
    with caplog.at_level(logging.WARNING):
        findings = CodeGroomingLoop._parse_findings(prose)
    assert findings == []
    assert "zero parseable findings" in caplog.text


def test_parse_valid_json_findings_no_warning(caplog) -> None:
    transcript = (
        "Here are the findings from the audit run.\n\n"
        '{"id": "X-1", "severity": "high", "title": "t", "description": "d"}\n'
        '{"id": "X-2", "severity": "critical", "title": "u", "description": "e"}\n'
        "End of report.\n"
    )
    with caplog.at_level(logging.WARNING):
        findings = CodeGroomingLoop._parse_findings(transcript)
    assert len(findings) == 2
    assert "zero parseable findings" not in caplog.text


def test_parse_malformed_json_in_long_output_emits_warning(caplog) -> None:
    """Matches regex but fails json.loads — still flagged."""
    transcript = 'Here is a finding: {"id": "broken, "severity": "high"} ' * 30
    with caplog.at_level(logging.WARNING):
        findings = CodeGroomingLoop._parse_findings(transcript)
    assert findings == []
    assert "zero parseable findings" in caplog.text
