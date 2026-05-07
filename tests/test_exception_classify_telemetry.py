"""Unit tests verifying reraise_on_credit_or_bug tags the active span."""

from __future__ import annotations

import pytest
from opentelemetry import trace

from mockworld.fakes.fake_honeycomb import FakeHoneycomb


@pytest.fixture
def fake():
    fh = FakeHoneycomb()
    yield fh
    fh.shutdown()


def test_reraise_tags_active_span_with_slug(fake):
    from exception_classify import reraise_on_credit_or_bug
    from subprocess_util import CreditExhaustedError

    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("test-op"), pytest.raises(CreditExhaustedError):
        try:
            raise CreditExhaustedError("boom")
        except CreditExhaustedError as exc:
            reraise_on_credit_or_bug(exc)

    span = fake.captured_spans[0]
    assert span.attributes.get("error") is True
    assert span.attributes.get("exception.slug") == "err-credit-exhausted"


def test_reraise_does_not_break_with_no_active_span():
    """Without an active span, classifier still re-raises correctly."""
    from exception_classify import reraise_on_credit_or_bug
    from subprocess_util import CreditExhaustedError

    with pytest.raises(CreditExhaustedError):
        try:
            raise CreditExhaustedError("boom")
        except CreditExhaustedError as exc:
            reraise_on_credit_or_bug(exc)
