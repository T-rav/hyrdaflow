# Background Loop Guidelines

When creating a new background loop (`BaseBackgroundLoop` subclass):

1. **Use `make scaffold-loop`** to generate boilerplate — it handles all wiring.

2. **Restart safety.** Any `self._` state that affects behavior across cycles must either:
   - Be persisted via `StateTracker` or `DedupStore` (survives restart)
   - Be rehydrated from an external source (GitHub API) on first `_do_work()` cycle
   - Be explicitly documented as ephemeral with a `# ephemeral: lost on restart` comment

3. **Wiring checklist** (automated by `tests/test_loop_wiring_completeness.py`):
   - `src/service_registry.py` — dataclass field + `build_services()` instantiation
   - `src/orchestrator.py` — entry in `bg_loop_registry` dict
   - `src/ui/src/constants.js` — entry in `BACKGROUND_WORKERS`
   - `src/dashboard_routes/_common.py` — entry in `_INTERVAL_BOUNDS`
   - `src/config.py` — interval Field + `_ENV_INT_OVERRIDES` entry

Missing any of these five entries will cause `test_loop_wiring_completeness` to fail. Add them all in the same commit.

## Per-worker model overrides

Each background worker that dispatches an LLM call has its own `HYDRAFLOW_*_MODEL` env var so it can be tuned independently for cost. Most loops are logic-only (no LLM call) and don't appear here.

| Loop | Config field | Env var | Default |
|------|--------------|---------|---------|
| `report_issue_loop` | `report_issue_model` | `HYDRAFLOW_REPORT_ISSUE_MODEL` | `opus` |
| `sentry_loop` | `sentry_model` | `HYDRAFLOW_SENTRY_MODEL` | `opus` |
| `code_grooming_loop` | `code_grooming_model` | `HYDRAFLOW_CODE_GROOMING_MODEL` | `sonnet` |
| `adr_reviewer_loop` (council) | `adr_review_model` | `HYDRAFLOW_ADR_REVIEW_MODEL` | `sonnet` |
| tribal-memory judge | `memory_judge_model` | `HYDRAFLOW_MEMORY_JUDGE_MODEL` | `haiku` |
| memory_sync compaction | `memory_compaction_model` | `HYDRAFLOW_MEMORY_COMPACTION_MODEL` | `haiku` |
| wiki compaction | `wiki_compilation_model` | `HYDRAFLOW_WIKI_COMPILATION_MODEL` | `haiku` |
| transcript summarizer | `transcript_summary_model` | `HYDRAFLOW_TRANSCRIPT_SUMMARY_MODEL` | `haiku` |

`HYDRAFLOW_BACKGROUND_MODEL` is a cascade: when non-empty it applies to every field above that still equals its own default (`triage_model`, `transcript_summary_model`, `report_issue_model`, `sentry_model`, `code_grooming_model`). Per-worker overrides always win over the cascade.

When adding a new loop that makes LLM calls, add its own `HYDRAFLOW_<NAME>_MODEL` field to `src/config.py` and `_ENV_STR_OVERRIDES` — don't reuse an existing loop's field.

## Design rationale

See [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md) for the caretaker loop pattern, and [`docs/adr/0019-background-task-delegation-abstraction-layer.md`](../adr/0019-background-task-delegation-abstraction-layer.md) for the delegation abstraction.
