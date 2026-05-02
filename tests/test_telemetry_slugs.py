"""Unit tests for src/telemetry/slugs.py — exception → static slug mapping."""

from src.telemetry.slugs import slug_for


class _UnknownErr(Exception):
    pass


def test_credit_exhausted_known_slug():
    from src.exception_classify import CreditExhaustedError

    assert slug_for(CreditExhaustedError("oops")) == "err-credit-exhausted"


def test_subprocess_timeout_known_slug():
    err = TimeoutError("subprocess timed out")
    assert slug_for(err) == "err-subprocess-timeout"


def test_unknown_exception_falls_back():
    assert slug_for(_UnknownErr("boom")) == "err-unclassified"


def test_slug_for_handles_none():
    assert slug_for(None) == "err-unclassified"


def test_slug_is_low_cardinality_string():
    from src.exception_classify import CreditExhaustedError

    slug = slug_for(CreditExhaustedError("oops"))
    assert isinstance(slug, str)
    assert slug.startswith("err-")
    assert " " not in slug
