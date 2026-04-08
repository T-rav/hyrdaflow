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

## Design rationale

See [`docs/adr/0029-caretaker-loop-pattern.md`](../adr/0029-caretaker-loop-pattern.md) for the caretaker loop pattern, and [`docs/adr/0019-background-task-delegation-abstraction-layer.md`](../adr/0019-background-task-delegation-abstraction-layer.md) for the delegation abstraction.
