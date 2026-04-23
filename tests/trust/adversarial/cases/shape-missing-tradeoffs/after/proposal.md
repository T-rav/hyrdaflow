# Shape proposal — `hf status` CLI

## Option A — Build it now

Implement a new `hf status` subcommand in `src/cli/status.py` that
reads the state tracker and prints a compact summary of every active
issue. This is the best option.

## Option B — Extend the existing dashboard script

Graft `hf status` onto the existing `scripts/dashboard.py` so it
reuses the dashboard's renderer. This is the easiest path.

## Option C — Defer

Wait until we have telemetry to show the command would be used. Cost
of inaction: operators keep tailing logs manually; onboarding stays
slow.
