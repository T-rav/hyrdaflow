# Dark-Factory Compatibility Sweep — 2026-05-12

**Audit SHA:** `01177be4` (branch `audit/dark-factory-compat`, fresh from `origin/staging`)
**Audit date:** 2026-05-12
**Scope:** Slice #3 of 5 — columns NOT already enforced by existing CI tests.

---

## Column criteria

### Loops table

| Column | Pass criterion |
|--------|---------------|
| **In-body kill-switch** | `_do_work` calls `if not self._enabled_cb(self._worker_name): return {"status": "disabled"}` — the canonical ADR-0049 pattern. Loops using raw env-var checks (`os.environ.get(_KILL_SWITCH_ENV)`) or config-field gates (`self._config.<x>_enabled`) without also calling `_enabled_cb` are flagged ❌. |
| **Static config gate** | A `<stem>_enabled: bool` field in `src/config.py` with a matching `HYDRAFLOW_<STEM>_ENABLED` env override, per dark-factory.md §2.1 #3. |
| **Subprocess reraise** | If `_do_work` (or a method it calls) spawns a subprocess AND that call is enclosed in a broad `except Exception` block: `reraise_on_credit_or_bug(exc)` must be called before the log/continue. Loops where subprocess calls are not enclosed in broad excepts (only narrow or no except) are `n/a`. |

### Ports table

| Column | Pass criterion |
|--------|---------------|
| **Has fake** | A `Fake<Port>` class in `src/mockworld/fakes/` (or equivalent) that implements the port Protocol. |
| **Adapter has contract test** | A `tests/trust/contracts/test_fake_<adapter>_contract.py` that cassette-replays the real adapter against the fake. |

### Runners table

| Column | Pass criterion |
|--------|---------------|
| **BaseRunner OR reraise** | Inherits `BaseRunner` (which provides auth-retry scaffolding) OR explicitly calls `reraise_on_credit_or_bug(exc)` in a broad except block. |

---

## Cell vocabulary

`covered` — passes the criterion.
`missing` — fails the criterion; a `[bd:advisor-*]` bead has been filed.
`n/a` — not applicable (e.g., loop spawns no subprocess, or port has no fake to test).
`source_not_found` — source file could not be located on this branch.

---

## Loops table (41 rows)

> **Note:** `EntryEvidenceLoop` is listed in the matrix but its source file
> (`src/entry_evidence_loop.py`) does not exist on this branch. It may be
> in-flight on another branch. All three columns are `source_not_found`.

| Loop | In-body kill-switch | Static config gate | Subprocess reraise |
|------|--------------------|--------------------|-------------------|
| `ADRReviewerLoop` | covered | missing [bd:advisor-405m] | n/a |
| `AdrTouchpointAuditorLoop` | covered | missing [bd:advisor-405m] | n/a |
| `AutoAgentPreflightLoop` | covered | covered | n/a |
| `CIMonitorLoop` | covered | missing [bd:advisor-405m] | n/a |
| `CodeGroomingLoop` | covered | covered | n/a |
| `ContractRefreshLoop` | covered | missing [bd:advisor-405m] | n/a |
| `CorpusLearningLoop` | covered | missing [bd:advisor-405m] | missing [bd:advisor-zshh] |
| `CostBudgetWatcherLoop` | missing [bd:advisor-uk9q] | missing [bd:advisor-405m] | n/a |
| `DependabotMergeLoop` | covered | missing [bd:advisor-405m] | n/a |
| `DiagnosticLoop` | covered | missing [bd:advisor-405m] | n/a |
| `DiagramLoop` | missing [bd:advisor-v0s4] | missing [bd:advisor-405m] | n/a |
| `EdgeProposerLoop` | missing [bd:advisor-u93e] | covered | n/a |
| `EntryEvidenceLoop` | source_not_found | source_not_found | source_not_found |
| `EpicMonitorLoop` | covered | missing [bd:advisor-405m] | n/a |
| `EpicSweeperLoop` | covered | missing [bd:advisor-405m] | n/a |
| `FakeCoverageAuditorLoop` | covered | missing [bd:advisor-405m] | n/a |
| `FlakeTrackerLoop` | covered | missing [bd:advisor-405m] | n/a |
| `GitHubCacheLoop` | covered | missing [bd:advisor-405m] | n/a |
| `HealthMonitorLoop` | covered | missing [bd:advisor-405m] | n/a |
| `MergeStateWatcherLoop` | covered | missing [bd:advisor-405m] | n/a |
| `PRUnstickerLoop` | covered | missing [bd:advisor-405m] | n/a |
| `PricingRefreshLoop` | missing [bd:advisor-f6lf] | missing [bd:advisor-405m] | n/a |
| `PrinciplesAuditLoop` | covered | missing [bd:advisor-405m] | missing [bd:advisor-0nqv] |
| `RCBudgetLoop` | covered | missing [bd:advisor-405m] | n/a |
| `RepoWikiLoop` | covered | missing [bd:advisor-405m] | n/a |
| `ReportIssueLoop` | covered | missing [bd:advisor-405m] | n/a |
| `RetrospectiveLoop` | covered | missing [bd:advisor-405m] | n/a |
| `RunsGCLoop` | covered | missing [bd:advisor-405m] | n/a |
| `SandboxFailureFixerLoop` | covered | covered | n/a |
| `SecurityPatchLoop` | covered | missing [bd:advisor-405m] | n/a |
| `SentryLoop` | covered | missing [bd:advisor-405m] | n/a |
| `SkillPromptEvalLoop` | covered | missing [bd:advisor-405m] | n/a |
| `StagingBisectLoop` | covered | missing [bd:advisor-405m] | n/a |
| `StagingPromotionLoop` | covered | missing [bd:advisor-405m] | n/a |
| `StaleIssueGCLoop` | covered | missing [bd:advisor-405m] | n/a |
| `StaleIssueLoop` | covered | missing [bd:advisor-405m] | n/a |
| `TermProposerLoop` | missing [bd:advisor-vr8h] | covered | n/a |
| `TermPrunerLoop` | missing [bd:advisor-taqs] | covered | n/a |
| `TrustFleetSanityLoop` | covered | missing [bd:advisor-405m] | missing [bd:advisor-fbnt] |
| `WikiRotDetectorLoop` | covered | missing [bd:advisor-405m] | missing [bd:advisor-v9f9] |
| `WorkspaceGCLoop` | covered | missing [bd:advisor-405m] | n/a |

### Notes on reraise column methodology

Loops that spawn subprocesses via `asyncio.create_subprocess_exec` or `subprocess.run`
were checked to determine whether those calls are enclosed in a **broad** `except Exception`
block (BLE001-suppressed). Only loops where a broad except block wraps a subprocess-spawning
code path are flagged as `missing`. Loops where the subprocess is:

- not enclosed in any except block, or
- enclosed only in narrow excepts (`TimeoutError`, `JSONDecodeError`, `CalledProcessError`)

are marked `n/a` because there is no swallowing path for `CreditExhaustedError`.

The 4 confirmed genuine gaps are CorpusLearningLoop, PrinciplesAuditLoop,
TrustFleetSanityLoop, and WikiRotDetectorLoop — all in the trust-fleet or
caretaking areas where `gh issue list` subprocess calls are wrapped in BLE001 excepts.

---

## Ports table (9 rows)

| Port | Has fake | Adapter has contract test |
|------|----------|--------------------------|
| `AgentPort` | missing [bd:advisor-ihgs] | missing [bd:advisor-ihgs] |
| `BotPRPort` | missing [bd:advisor-ihgs] | missing [bd:advisor-ihgs] |
| `IssueFetcherPort` | covered (`fake_issue_fetcher.py`) | covered (`test_fake_github_contract.py`) |
| `IssueStorePort` | covered (`fake_issue_store.py`) | covered (`test_fake_github_contract.py`) |
| `ObservabilityPort` | missing [bd:advisor-ihgs] | missing [bd:advisor-ihgs] |
| `PRPort` | covered (`fake_github.py`) | covered (`test_fake_github_contract.py`) |
| `ReviewInsightStorePort` | missing [bd:advisor-ihgs] | missing [bd:advisor-ihgs] |
| `RouteBackCounterPort` | missing [bd:advisor-ihgs] | missing [bd:advisor-ihgs] |
| `WorkspacePort` | covered (`fake_workspace.py`) | missing [bd:advisor-1mpg] |

---

## Runners table (subprocess-spawning runners)

All `*Runner` classes in `src/` were inspected. Non-subprocess runners are omitted.

| Runner | File | Inherits BaseRunner | Reraise direct | Verdict |
|--------|------|--------------------:|---------------|---------|
| `AgentRunner` | `agent.py` | yes | yes | covered |
| `DiagnosticRunner` | `diagnostic_runner.py` | yes | no | covered (inherits) |
| `DiscoverRunner` | `discover_runner.py` | yes | yes | covered |
| `DockerRunner` | `docker_runner.py` | no | yes | covered |
| `HITLRunner` | `hitl_runner.py` | yes | yes | covered |
| `HostRunner` | `execution.py` | no | no (TimeoutError only) | n/a — thin adapter, no broad except |
| `PlannerRunner` | `planner.py` | yes | yes | covered |
| `ResearchRunner` | `research_runner.py` | yes | yes | covered |
| `ReviewRunner` | `reviewer.py` | yes | yes | covered |
| `ShapeRunner` | `shape_runner.py` | yes | yes | covered |
| `SubprocessRunner` | `execution.py` | Protocol (interface) | n/a | n/a — interface, no impl |
| `TriageRunner` | `triage.py` | yes | yes | covered |
| `_AdvisorSubagentRunner` | `review_advisor.py` | Protocol | yes | covered |

All concrete subprocess-spawning runners are covered. `HostRunner` is a thin
`asyncio.create_subprocess_exec` wrapper with no broad except block — it is not
a concern for `reraise_on_credit_or_bug`.

---

## Summary

| Table | Covered | Missing | n/a / source_not_found |
|-------|---------|---------|------------------------|
| Loops — kill-switch | 34 | 6 | 1 (source_not_found) |
| Loops — static gate | 6 | 34 | 1 (source_not_found) |
| Loops — subprocess reraise | 0 | 4 | 37 (n/a or source_not_found) |
| Ports — has fake | 4 | 5 | 0 |
| Ports — contract test | 3 | 6 | 0 |
| Runners — BaseRunner/reraise | 11 | 0 | 2 (n/a) |

**Beads filed: 13**

---

## Highlights

1. **Static gate is the widest gap (34 loops, [bd:advisor-405m]).** Every loop except the 6
   already toggled via config fields lacks a `*_enabled` env-var override. This is a single
   bulk PR to `src/config.py` — add a `<stem>_enabled` bool field per loop, default `True`.

2. **6 loops use non-canonical kill-switch patterns ([bd:advisor-uk9q], [bd:advisor-v0s4],
   [bd:advisor-u93e], [bd:advisor-f6lf], [bd:advisor-vr8h], [bd:advisor-taqs]).** Three use
   raw `os.environ.get(_KILL_SWITCH_ENV)` (CostBudgetWatcherLoop, DiagramLoop,
   PricingRefreshLoop) and three use a static config-field gate without the callback
   (EdgeProposerLoop, TermProposerLoop, TermPrunerLoop). The callback gate is what connects
   the operator UI toggle and loop-wiring test assertions. The existing gates provide
   _some_ protection but miss the dynamic path.

3. **4 trust-fleet and caretaking loops swallow `CreditExhaustedError`
   ([bd:advisor-zshh], [bd:advisor-0nqv], [bd:advisor-fbnt], [bd:advisor-v9f9]).**
   All four wrap `gh issue list` subprocess calls in BLE001 broad excepts without
   `reraise_on_credit_or_bug`. Under billing exhaustion, these loops would continue ticking
   silently rather than propagating the signal.

4. **5 ports have no fake implementation ([bd:advisor-ihgs]).** AgentPort, BotPRPort,
   ObservabilityPort, ReviewInsightStorePort, and RouteBackCounterPort cannot be used in
   MockWorld scenarios. This is partially expected for newer ports (BotPRPort is loop-local
   to TermProposerLoop) but AgentPort and ObservabilityPort are used in the core pipeline.

5. **Runners are clean.** All 11 concrete subprocess-spawning runner classes are covered via
   BaseRunner inheritance or direct `reraise_on_credit_or_bug` use. No gaps in the runner
   table.

---

## Bead index

| Bead ID | Title |
|---------|-------|
| `advisor-uk9q` | CostBudgetWatcherLoop missing in-body kill-switch gate |
| `advisor-v0s4` | DiagramLoop missing in-body kill-switch gate |
| `advisor-u93e` | EdgeProposerLoop missing in-body kill-switch gate |
| `advisor-f6lf` | PricingRefreshLoop missing in-body kill-switch gate |
| `advisor-vr8h` | TermProposerLoop missing in-body kill-switch gate |
| `advisor-taqs` | TermPrunerLoop missing in-body kill-switch gate |
| `advisor-zshh` | CorpusLearningLoop missing reraise_on_credit_or_bug |
| `advisor-0nqv` | PrinciplesAuditLoop missing reraise_on_credit_or_bug |
| `advisor-fbnt` | TrustFleetSanityLoop missing reraise_on_credit_or_bug |
| `advisor-v9f9` | WikiRotDetectorLoop missing reraise_on_credit_or_bug |
| `advisor-405m` | 34 loops missing static config gate |
| `advisor-ihgs` | 5 ports missing fake implementations |
| `advisor-1mpg` | WorkspacePort missing adapter contract test |
