# Area Review: Dashboard — 2026-05-12

**Slice:** 5.8 — per ADR-0007 and ADR-0008
**Auditor:** audit/area-dashboard
**Scope:** `src/dashboard_routes/**`, `src/ui/**`

---

## Summary

The Dashboard area is the most structurally mature in the codebase. It has comprehensive route test coverage, a healthy Vitest component test suite, and Playwright browser-contract tests that cover the full stack. Three specific gaps remain:

1. A known, unpatched security vulnerability in the WhatsApp webhook handler (issue #6651, xfail regression tests already filed).
2. Four UI components with no corresponding Vitest tests.
3. Four wiki sub-components (`WikiEntryDetail`, `WikiEntryList`, `WikiMaintenancePanel`, `WikiTopBar`) with no tests beyond `WikiExplorer`.
4. 26 routes still living in the monolithic `_routes.py` — extraction is incomplete.

---

## 1. Route / Code Quality

**Rating: clean / minor**

The package has been well-refactored from a single 2000+ line module into 13 sub-modules plus shared helpers. `RouteContext` (src/dashboard_routes/_routes.py:298) cleanly bundles all dependencies; sub-routers receive it explicitly, ending the old 17-variable closure anti-pattern. ADR-0007 and ADR-0008 are enforced by tests.

`_common.py` is a proper shared-constants module with guard tests in `test_dashboard_routes_common.py`.

**Minor issues found:**

- `_routes.py` still contains **26 route handlers** (`@router.` count) that have not been extracted, including: `/api/state`, `/api/stats`, `/api/queue`, `/api/prs`, `/api/pipeline`, `/api/pipeline/stats`, `/api/events`, `/api/issues/history`, `/api/timeline`, `/api/sessions`, `/api/request-changes`, `/api/hitl-recommendations`, `/api/adr-decisions`, `/api/verification-records`, `/api/shape/artifact/{issue_number}`, `/api/webhooks/whatsapp` (GET and POST). The extracted sub-modules together account for 94 routes. Extraction is half-done.

- `_epic_routes.py` directly accesses `orch._svc.epic_manager` (a private attribute). This is a layer violation — routes should not reach through the orchestrator's private service registry.

- `_factory_health_routes.py` is very thin (65 lines, 1 route) and inlines a `_load_jsonl` helper that duplicates logic found in other modules. A shared JSONL-reading utility would reduce the surface.

**Security gap (HIGH):**

`POST /api/webhooks/whatsapp` in `_routes.py` documents that it validates the `X-Hub-Signature-256` HMAC signature but does not implement the check. Regression tests at `tests/regressions/test_issue_6651.py` are marked `xfail` and confirm the bug is unfixed. An unauthenticated caller can inject arbitrary WhatsApp messages into active Shape conversations. This is tracked as issue #6651.

---

## 2. Endpoint Test Coverage

**Rating: covered (with thin spots)**

Backend route coverage is strong. Route-level tests exist for every extracted sub-module:

| Sub-module | Source lines | Test file | Test count |
|---|---|---|---|
| `_routes.py` (inline) | 2068 | test_dashboard_routes_core, _state, _jsonl, regressions | ~40+ |
| `_control_routes.py` | 885 | test_dashboard_routes_control.py | 670 lines |
| `_hitl_routes.py` | 383 | test_dashboard_routes_hitl.py | 1614 lines |
| `_state_routes.py` | 632 | test_dashboard_routes_state.py | 1691 lines |
| `_metrics_routes.py` | 339 | test_dashboard_routes_metrics.py | 507 lines |
| `_diagnostics_routes.py` | 420 | test_dashboard_routes_diagnostics.py | 224 lines |
| `_crates_routes.py` | 228 | test_dashboard_routes_repo.py (TestCrateEndpoints) | good |
| `_epic_routes.py` | 59 | test_epic_api.py (TestEpicRouteHandlers) | 6 handler tests |
| `_reports_routes.py` | 191 | test_dashboard_routes_core.py + test_tracked_reports.py | good |
| `_wiki_routes.py` | 442 | test_wiki_routes.py | 20 tests |
| `_trust_routes.py` | 448 | test_trust_fleet_route.py | 11 tests |
| `_factory_health_routes.py` | 65 | test_factory_health.py | 21 tests |
| `_waterfall_builder.py` | 359 | test_waterfall_builder.py | covered |
| `_cost_rollups.py` | 567 | test_cost_rollups_helpers.py, test_cost_rollups_by_model.py, test_diagnostics_cost_rollup_routes.py | covered |

**Thin spots:**

- `/api/pipeline/stats` — the handler is in `_routes.py` (line 1407) but no dedicated test exercises it. `test_dashboard_routes_state.py` covers `/api/pipeline` but not `/api/pipeline/stats`.
- `/api/webhooks/whatsapp` — only `xfail` regression tests exist (see security gap above). No green test for the happy path (valid signature accepted).
- `/api/shape/artifact/{issue_number}` — no dedicated test. The shape conversation tests cover the upstream logic, not the route handler.
- `POST /api/hitl/{issue_number}/approve-process` — covered in `test_dashboard_routes_hitl.py` but the label-swap path for non-triage targets is not exercised (the handler now hard-codes routing to `find_label[0]`).

---

## 3. UI Test Fidelity

**Rating: covered / thin spots in wiki sub-components**

The React/JSX layer uses Vitest. Coverage is broad:

- All 27 top-level components in `src/ui/src/components/` have `__tests__/` files **except four**: `insightsPrimitives.jsx`, `IntentInput.jsx`, `MockWorldBanner.jsx`, `ReviewTable.jsx`.
- All 14 diagnostics sub-components have paired tests.
- All 5 hooks have tests.
- Context, styles, utils are tested.

**Wiki component gap:** `WikiEntryDetail`, `WikiEntryList`, `WikiMaintenancePanel`, and `WikiTopBar` have no Vitest tests. Only `WikiExplorer.test.jsx` exists under `wiki/__tests__/`. These four components handle the read path, stale-marking, index-rebuild, and the filter bar for the wiki viewer — meaningful logic that is untested at the component level.

**Browser / Playwright (Tier 3):**

`tests/scenarios/browser/` provides a full Playwright harness:
- Smoke tests: boot + root serves 200
- Contract snapshots: 5 tab states (issues, outcomes, hitl, worklog, system) with screenshot diffing
- Full-scenario workflows: happy path, sad path, edge cases, HITL round-trip, config edit, PR approve, repo register, orchestrator controls
- MockWorld serves as the test double; `world.start_dashboard()` boots FastAPI + React on a real port

The browser tests use `@pytest.mark.scenario_browser` and are run separately from unit tests. The happy-path browser test (H1) notes a known limitation: clicking the UI "Start" button creates a fresh orchestrator, breaking the MockWorld wiring. The workaround is Python-side pipeline drive + UI assertion, which is documented in the test file.

---

## 4. Subprocess / Billing Safety

**Rating: n/a**

Route handlers are I/O bound (state reads, GitHub API calls, file reads). No subprocesses spawn from route handlers except:
- `_run_dialog_command` in `_routes.py` (folder picker, macOS-only feature). Uses `asyncio.create_subprocess_exec` with a timeout; no billing risk.
- `_detect_repo_slug_from_path` in `_state_routes.py` runs `git remote get-url` with a 10-second timeout; safe.

`reraise_on_credit_or_bug` is not relevant here — routes are not runner loops.

---

## 5. Wiki / ADR Currency

**Rating: documented**

Two dedicated ADRs cover this area:
- **ADR-0007** (`docs/adr/0007-dashboard-api-multi-repo-scoping.md`): Accepted. Enforced by `test_dashboard_routes_repo.py`. Covers `?repo=` query scoping and per-repo lifecycle endpoints.
- **ADR-0008** (`docs/adr/0008-multi-repo-dashboard-architecture.md`): Accepted. Covers supervisor-proxied aggregation model.

Both ADRs are structurally current. Related ADRs (ADR-0009, ADR-0030) cover the per-repo process model and product-track architecture.

Wiki entries in `architecture-layers.md`, `architecture-async-control.md`, and `architecture.md` contain relevant entries about `RouteContext` and the dashboard decomposition. No dedicated dashboard wiki entry exists, though the topic is distributed across the existing architecture files.

The functional areas map at `docs/arch/generated/functional_areas.md` correctly categorizes `src/dashboard_routes/**` and `src/ui/**` under the Dashboard area.

**Gap:** No wiki entry documents the `RouteContext` pattern or the sub-router extraction convention — a new contributor would have to read the source comments to understand how sub-routers receive their context and why `_routes.py` still exists as an orchestrator module.

---

## Gaps and Recommended Actions

| Priority | Gap | Suggested action |
|---|---|---|
| HIGH | `POST /api/webhooks/whatsapp` missing HMAC signature verification (issue #6651) | Fix before next release. Tests are already written (xfail in `tests/regressions/test_issue_6651.py`). Add `whatsapp_app_secret` to `Credentials`, compute HMAC-SHA256 over raw request body, reject non-matching requests with 403. |
| MED | 4 UI components without Vitest tests (`insightsPrimitives`, `IntentInput`, `MockWorldBanner`, `ReviewTable`) | Add component tests. `ReviewTable` is used in the HITL flow; priority is higher than the others. |
| MED | Wiki sub-components missing tests (`WikiEntryDetail`, `WikiEntryList`, `WikiMaintenancePanel`, `WikiTopBar`) | Add Vitest tests covering render with fixture data and user interactions. |
| MED | `/api/pipeline/stats`, `/api/shape/artifact/{issue_number}` — no route-level tests | Add tests similar to the `test_dashboard_routes_state.py` pattern. |
| LOW | `_epic_routes.py` accesses `orch._svc.epic_manager` directly | Expose `epic_manager` via a public property on the orchestrator or pass it through `RouteContext`. |
| LOW | `_factory_health_routes.py` inlines `_load_jsonl` | Move the helper to `_common.py` and import it. |
| LOW | No wiki entry for `RouteContext` / sub-router extraction pattern | Add a `docs/wiki/architecture-patterns-practices.md` entry or extend the existing one. |
| INFO | 26 routes remain in `_routes.py` rather than extracted sub-modules | Incremental extraction is fine; document the target state in a wiki entry so contributors know which routes are still to be moved. |

---

## Files Examined

- `src/dashboard_routes/__init__.py`
- `src/dashboard_routes/_routes.py`
- `src/dashboard_routes/_common.py`
- `src/dashboard_routes/_control_routes.py`
- `src/dashboard_routes/_hitl_routes.py`
- `src/dashboard_routes/_metrics_routes.py`
- `src/dashboard_routes/_diagnostics_routes.py`
- `src/dashboard_routes/_state_routes.py`
- `src/dashboard_routes/_wiki_routes.py`
- `src/dashboard_routes/_epic_routes.py`
- `src/dashboard_routes/_crates_routes.py`
- `src/dashboard_routes/_trust_routes.py`
- `src/dashboard_routes/_factory_health_routes.py`
- `src/dashboard_routes/_reports_routes.py`
- `src/dashboard_routes/_waterfall_builder.py`
- `src/dashboard_routes/_cost_rollups.py`
- `src/ui/src/` (all JSX components, hooks, context, utils)
- `tests/test_dashboard_routes_*.py` (all 12 files)
- `tests/test_session_routes.py`
- `tests/test_epic_api.py`, `test_crate_manager.py`, `test_tracked_reports.py`
- `tests/test_trust_fleet_route.py`, `test_wiki_routes.py`, `test_factory_health.py`
- `tests/regressions/test_issue_6651.py`
- `tests/scenarios/browser/` (all Playwright test files)
- `docs/adr/0007-dashboard-api-multi-repo-scoping.md`
- `docs/adr/0008-multi-repo-dashboard-architecture.md`
- `docs/arch/generated/functional_areas.md`
