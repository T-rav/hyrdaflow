"""FakeHoneycomb — captures OTel spans during scenario tests.

Mirrors the existing fake-of-the-destination convention (FakeSentry,
FakeGitHub). Internally wraps OTel SDK's InMemorySpanExporter so we use
the upstream test machinery rather than rolling our own tracer.
"""

from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
    InMemorySpanExporter,
)


class FakeHoneycomb:
    """Captures OTel spans during scenario tests. Replaces the real OTLP
    exporter at the global TracerProvider. Use SimpleSpanProcessor (sync,
    not batched) so spans are visible immediately after their ``with`` block."""

    def __init__(self) -> None:
        self._exporter = InMemorySpanExporter()
        self._provider = TracerProvider(
            resource=Resource.create({"service.name": "hydraflow-test"})
        )
        self._provider.add_span_processor(SimpleSpanProcessor(self._exporter))
        trace.set_tracer_provider(self._provider)

    @property
    def captured_spans(self) -> list[ReadableSpan]:
        return list(self._exporter.get_finished_spans())

    def find_spans(
        self,
        *,
        name: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> list[ReadableSpan]:
        out = []
        for s in self.captured_spans:
            if name is not None and s.name != name:
                continue
            if attrs is not None and not all(
                (s.attributes or {}).get(k) == v for k, v in attrs.items()
            ):
                continue
            out.append(s)
        return out

    def trace_for_issue(self, issue_num: int) -> list[ReadableSpan]:
        out = self.find_spans(attrs={"hf.issue": issue_num})
        return sorted(out, key=lambda s: s.start_time or 0)

    def assert_trace_shape(
        self,
        issue_num: int,
        *,
        expected_root: str,
        expected_children: list[str],
    ) -> None:
        spans = self.trace_for_issue(issue_num)
        if not spans:
            raise AssertionError(f"No spans found with hf.issue={issue_num}")
        roots = [s for s in spans if s.parent is None]
        if not any(r.name == expected_root for r in roots):
            raise AssertionError(
                f"Expected root span {expected_root!r} for issue {issue_num}, "
                f"got roots: {[r.name for r in roots]}"
            )
        child_names = {s.name for s in spans if s.parent is not None}
        missing = set(expected_children) - child_names
        if missing:
            raise AssertionError(
                f"Missing expected child spans for issue {issue_num}: {missing}; "
                f"actual children: {child_names}"
            )

    def assert_no_orphan_spans(self) -> None:
        """Every non-root span must have a parent in this batch."""
        ids = {s.context.span_id for s in self.captured_spans if s.context}
        for s in self.captured_spans:
            if s.parent is not None and s.parent.span_id not in ids:
                raise AssertionError(
                    f"Orphan span {s.name!r}: parent {s.parent.span_id} "
                    f"not in captured batch"
                )

    def assert_attribute_present(self, span_name: str, attr_key: str) -> None:
        matches = self.find_spans(name=span_name)
        if not matches:
            raise AssertionError(f"No span named {span_name!r} captured")
        for s in matches:
            if attr_key not in (s.attributes or {}):
                raise AssertionError(
                    f"Span {span_name!r} missing attribute {attr_key!r}; "
                    f"present attrs: {list((s.attributes or {}).keys())}"
                )

    def reset(self) -> None:
        self._exporter.clear()

    def shutdown(self) -> None:
        try:
            self._provider.shutdown()
        finally:
            # Reset global OTel provider state so subsequent tests can install
            # a fresh provider. Also clear the tracer cache so next-test span
            # operations resolve against the new provider.
            trace._TRACER_PROVIDER = None  # noqa: SLF001
            trace._TRACER_PROVIDER_SET_ONCE._done = False  # noqa: SLF001
            self._exporter.clear()
            try:
                from src.telemetry.spans import _get_tracer

                _get_tracer.cache_clear()
            except Exception:  # noqa: BLE001
                pass
