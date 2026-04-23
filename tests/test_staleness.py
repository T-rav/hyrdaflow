"""Tests for staleness evaluator and valid_to duration parsing."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from staleness import ParseError, parse_valid_to


def test_parse_none_returns_none():
    assert parse_valid_to(None, now=datetime.now(UTC)) is None


def test_parse_empty_string_returns_none():
    assert parse_valid_to("", now=datetime.now(UTC)) is None


def test_parse_iso_date_passthrough():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    result = parse_valid_to("2027-01-01", now=now)
    assert result == "2027-01-01T00:00:00+00:00"


def test_parse_iso_datetime_passthrough():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    result = parse_valid_to("2027-01-01T12:00:00+00:00", now=now)
    assert result == "2027-01-01T12:00:00+00:00"


def test_parse_duration_days():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    result = parse_valid_to("90d", now=now)
    # 2026-04-22 + 90 days = 2026-07-21
    assert result.startswith("2026-07-21")


def test_parse_duration_months():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    result = parse_valid_to("6mo", now=now)
    # 6 months treated as 6 * 30 days = 180 days
    assert result.startswith("2026-10-19")


def test_parse_duration_years():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    result = parse_valid_to("1y", now=now)
    # 1 year treated as 365 days
    assert result.startswith("2027-04-22")


def test_parse_duration_zero_rejected():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    with pytest.raises(ParseError):
        parse_valid_to("0d", now=now)


def test_parse_duration_negative_rejected():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    with pytest.raises(ParseError):
        parse_valid_to("-5d", now=now)


def test_parse_garbage_rejected():
    now = datetime(2026, 4, 22, tzinfo=UTC)
    with pytest.raises(ParseError):
        parse_valid_to("banana", now=now)


from staleness import evaluate


def _entry(**overrides):
    from repo_wiki import WikiEntry

    defaults = {"title": "t", "content": "c", "source_type": "plan"}
    defaults.update(overrides)
    return WikiEntry(**defaults)


NOW = datetime(2026, 4, 22, 12, 0, tzinfo=UTC)


def test_evaluate_indefinite_entry_is_current():
    e = _entry(valid_from=NOW.isoformat(), valid_to=None)
    assert evaluate(e, now=NOW) == "current"


def test_evaluate_entry_before_valid_from_is_future():
    future = datetime(2027, 1, 1, tzinfo=UTC).isoformat()
    e = _entry(valid_from=future, valid_to=None)
    # Future entries are not current yet — treat as "pending" (not injected)
    assert evaluate(e, now=NOW) == "pending"


def test_evaluate_entry_after_valid_to_is_expired():
    past = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    e = _entry(valid_from=past, valid_to=datetime(2026, 3, 1, tzinfo=UTC).isoformat())
    assert evaluate(e, now=NOW) == "expired"


def test_evaluate_superseded_wins_over_current_window():
    past = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    e = _entry(
        valid_from=past, valid_to=None, superseded_by="01HQ0000000000000000000000"
    )
    assert evaluate(e, now=NOW) == "superseded"


def test_evaluate_superseded_wins_over_expired():
    past = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    expired = datetime(2026, 3, 1, tzinfo=UTC).isoformat()
    e = _entry(
        valid_from=past,
        valid_to=expired,
        superseded_by="01HQ0000000000000000000000",
    )
    # superseded classification takes precedence
    assert evaluate(e, now=NOW) == "superseded"


def test_evaluate_at_exact_valid_to_is_expired():
    at = datetime(2026, 4, 22, 12, 0, tzinfo=UTC).isoformat()
    e = _entry(valid_from="2026-01-01T00:00:00+00:00", valid_to=at)
    # boundary: now == valid_to → expired
    assert evaluate(e, now=NOW) == "expired"
