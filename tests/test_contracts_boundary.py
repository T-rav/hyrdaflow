"""Unit tests for the I/O-boundary validation helper (Phase 7 of #8786)."""

from __future__ import annotations

import logging

import pytest

from contracts.boundary import (
    BoundaryParseResult,
    parse_list_with_shape,
    parse_with_shape,
)
from contracts.shapes import GhPRDetail, GhPRSummary

# ---------------------------------------------------------------------------
# parse_with_shape
# ---------------------------------------------------------------------------


def test_parse_with_shape_ok_on_valid_payload() -> None:
    """Valid JSON + valid shape → ok=True, model_instance populated."""
    payload = '{"number": 42, "title": "x", "state": "OPEN"}'
    result = parse_with_shape(payload, GhPRSummary)
    assert result.ok is True
    assert result.validation_error is None
    assert isinstance(result.model_instance, GhPRSummary)
    assert result.model_instance.number == 42


def test_parse_with_shape_logs_and_returns_partial_on_validation_fail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Validation failure → ok=False, payload still populated, WARN logged.
    Call sites that don't check ``ok`` keep working with the raw dict."""
    payload = '{"number": 42, "title": "x", "state": "QUEUED"}'  # bad enum
    with caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"):
        result = parse_with_shape(payload, GhPRSummary)
    assert result.ok is False
    assert result.model_instance is None
    assert result.payload == {"number": 42, "title": "x", "state": "QUEUED"}
    assert result.validation_error is not None
    assert result.validation_error.shape == "GhPRSummary"
    assert result.validation_error.failure_count >= 1
    assert any("boundary validation failed" in r.message for r in caplog.records)


def test_parse_with_shape_raises_on_json_parse_error() -> None:
    """A truly malformed payload is a callable bug — raise so the caller
    can't silently fall back."""
    with pytest.raises(ValueError, match="could not parse JSON"):
        parse_with_shape("not json", GhPRSummary)


def test_parse_with_shape_aliases_camelcase() -> None:
    """gh emits camelCase; the model accepts both via populate_by_name."""
    payload = (
        '{"number": 1, "headRefName": "feat/x", "baseRefName": "staging",'
        ' "mergeable": "MERGEABLE"}'
    )
    result = parse_with_shape(payload, GhPRDetail)
    assert result.ok
    assert result.model_instance is not None
    assert result.model_instance.head_ref_name == "feat/x"


# ---------------------------------------------------------------------------
# parse_list_with_shape
# ---------------------------------------------------------------------------


def test_parse_list_with_shape_returns_one_result_per_element() -> None:
    payload = (
        '[{"number": 1, "title": "x", "state": "OPEN"},'
        ' {"number": 2, "title": "y", "state": "MERGED"}]'
    )
    results = parse_list_with_shape(payload, GhPRSummary)
    assert len(results) == 2
    assert all(r.ok for r in results)


def test_parse_list_one_bad_does_not_poison_others(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A drifted element fires its own validation error; siblings remain OK."""
    payload = (
        '[{"number": 1, "title": "x", "state": "OPEN"},'
        ' {"number": 2, "title": "y", "state": "QUEUED"},'  # bad
        ' {"number": 3, "title": "z", "state": "MERGED"}]'
    )
    with caplog.at_level(logging.WARNING, logger="hydraflow.contracts.boundary"):
        results = parse_list_with_shape(payload, GhPRSummary)
    assert len(results) == 3
    assert results[0].ok and results[2].ok
    assert results[1].ok is False
    assert results[1].validation_error is not None
    assert "[1]" in next((r.message for r in caplog.records if "[1]" in r.message), "")


def test_parse_list_raises_on_non_list_payload() -> None:
    with pytest.raises(ValueError, match="expected JSON list"):
        parse_list_with_shape('{"not": "a list"}', GhPRSummary)


def test_parse_list_raises_on_json_error() -> None:
    with pytest.raises(ValueError, match="could not parse JSON list"):
        parse_list_with_shape("[oops", GhPRSummary)


# ---------------------------------------------------------------------------
# Call-site usage pattern (demo)
# ---------------------------------------------------------------------------


def test_call_site_pattern_strict_caller() -> None:
    """A strict caller checks ``ok`` and raises on drift."""
    payload = '{"number": 1, "title": "x", "state": "QUEUED"}'
    result = parse_with_shape(payload, GhPRSummary)
    if not result.ok:
        # The strict pattern: raise so the caller knows about drift.
        with pytest.raises(RuntimeError):
            msg = "gh response shape drift"
            raise RuntimeError(msg)


def test_call_site_pattern_lenient_caller() -> None:
    """A lenient caller accesses ``payload`` (raw dict) regardless of
    validation outcome — drift is observed via the WARN log, behavior
    is preserved."""
    payload = '{"number": 1, "title": "x", "state": "QUEUED"}'
    result = parse_with_shape(payload, GhPRSummary)
    # Lenient path: use the raw payload even when validation failed.
    assert isinstance(result.payload, dict)
    assert result.payload["number"] == 1


# Type contract: the result dataclass shape is part of the public API.


def test_boundary_parse_result_dataclass_fields() -> None:
    """Compile-time check that the dataclass exposes the documented fields."""
    fields = BoundaryParseResult.__dataclass_fields__
    assert set(fields) == {"payload", "model_instance", "validation_error"}


# ---------------------------------------------------------------------------
# field_or accessor — dedups the lenient-pattern boilerplate
# ---------------------------------------------------------------------------


def test_field_or_returns_typed_model_value_when_valid() -> None:
    """Validation succeeded → accessor pulls from the typed model."""
    from contracts.boundary import field_or

    result = parse_with_shape(
        '{"number": 42, "title": "x", "state": "OPEN"}', GhPRSummary
    )
    assert field_or(result, "number", 0) == 42
    assert field_or(result, "title", "") == "x"


def test_field_or_falls_back_to_payload_on_validation_fail() -> None:
    """Validation failed → accessor uses dict lookup on the raw payload."""
    from contracts.boundary import field_or

    result = parse_with_shape(
        '{"number": 42, "title": "x", "state": "QUEUED"}', GhPRSummary
    )
    assert result.model_instance is None
    assert field_or(result, "number", 0) == 42
    assert field_or(result, "title", "") == "x"


def test_field_or_default_when_attribute_missing() -> None:
    """Default returned when the attribute is missing from the typed model
    OR the raw dict."""
    from contracts.boundary import field_or

    result = parse_with_shape(
        '{"number": 1, "title": "x", "state": "OPEN"}', GhPRSummary
    )
    # body is optional, not set → None in the model; default fires.
    assert field_or(result, "body", "fallback") == "fallback"


def test_field_or_dict_key_override_for_camelcase_drift() -> None:
    """When validation fails, the dict still has camelCase fields. The
    ``dict_key`` override lets the accessor target the underlying key."""
    from contracts.boundary import field_or
    from contracts.shapes import GhPRDetail

    result = parse_with_shape('{"number": "bad", "headRefName": "feat/x"}', GhPRDetail)
    assert result.model_instance is None
    # The Python attribute is ``head_ref_name`` but the raw dict key is
    # ``headRefName`` — pass dict_key to target it.
    assert field_or(result, "head_ref_name", "", dict_key="headRefName") == "feat/x"
