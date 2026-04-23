# Shape proposal — structured JSON logging

## Option A — Adopt structlog

Replace the legacy `logging.getLogger` call sites with `structlog` and
standardise on a JSON renderer. Trade-off: structlog adds a runtime
dependency and a small per-call overhead (~15µs) on hot paths.

## Option B — Home-grow JSON formatter

Write a custom `logging.Formatter` subclass that emits JSON, keep the
stdlib logger surface. Trade-off: we own the formatter forever,
including rotating-handler quirks and Windows stream corner cases.

## Option C — Partial adoption

Adopt structlog only in new code; leave legacy call sites on the
stdlib logger until they are touched for other reasons. Trade-off:
two logging conventions coexist indefinitely; log aggregation dashboards
must parse both shapes.
