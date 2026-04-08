# Sentry Error Tracking

HydraFlow uses **Sentry** (`sentry_sdk`) for error monitoring. Follow these rules to keep Sentry signal-to-noise high.

## What goes to Sentry

- **Real code bugs only.** `TypeError`, `KeyError`, `AttributeError`, `ValueError`, `IndexError`, `NotImplementedError`.
- The `before_send` filter in `src/server.py` drops all exceptions that are NOT in the bug-types tuple.
- `LoggingIntegration` captures `logger.error()` calls — these also go through the `before_send` filter.

## What does NOT go to Sentry

- **Transient errors** — network timeouts, auth failures, rate limits, subprocess crashes. These are operational, not bugs.
- **Handled exceptions** — if you catch an error and handle it, use `logger.warning()`, not `logger.error()` or `logger.exception()`.
- **Test mock exceptions** — never let test mocks raise through code paths that log at `error` level when `SENTRY_DSN` is set.

## Rules for new code

1. Use `logger.warning()` for expected or transient failures (network, auth, rate limit).
2. Use `logger.error()` or `logger.exception()` ONLY for unexpected code bugs you want Sentry to capture.
3. Never use bare `except: pass` — always log at `warning` level minimum.
4. When adding a new background loop, catch operational errors and log at `warning`; let real bugs propagate to the base class error handler which logs at `error`.
5. The `_before_send` callback in `src/server.py` is the gatekeeper — if you add new exception types that indicate real bugs, add them to `_BUG_TYPES`.
6. The `SentryIngestLoop` in `src/sentry_loop.py` polls Sentry for unresolved issues and files them as GitHub issues — avoid creating noise that feeds back into this loop.

## Key files

- `src/server.py` — Sentry init, `_before_send` filter, `_BUG_TYPES` tuple
- `src/sentry_loop.py` — Background loop that ingests Sentry issues into GitHub
