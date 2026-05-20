"""Sandbox entrypoint — boots HydraFlow with Fake adapters injected.

Used by docker-compose.sandbox.yml and by anyone wanting to run HydraFlow
against simulated GitHub/LLM state. Reads a seed JSON path from argv[1]
or from $HYDRAFLOW_MOCKWORLD_SEED.

Production runs the `hydraflow` console script (server:main) which never
imports this module — Fakes are unreachable from the production code path.
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

from dashboard import HydraFlowDashboard
from events import EventBus
from mockworld.fakes import (
    FakeGitHub,
    FakeIssueFetcher,
    FakeIssueStore,
    FakeLLM,
    FakeWorkspace,
)
from mockworld.fakes.fake_docker import FakeDocker
from mockworld.fakes.fake_subprocess_runner import FakeSubprocessRunner
from mockworld.seed import MockWorldSeed
from orchestrator import HydraFlowOrchestrator
from ports import IssueFetcherPort, IssueStorePort, PRPort, WorkspacePort
from runtime_config import load_runtime_config
from service_registry import (
    WorkerRegistryCallbacks,
    build_services,
    build_state_tracker,
)


def _load_seed() -> MockWorldSeed:
    """Read the seed file path from argv or env, return the seed."""
    path: str | None = sys.argv[1] if len(sys.argv) > 1 else None
    if path is None:
        path = os.environ.get("HYDRAFLOW_MOCKWORLD_SEED")
    if not path:
        return MockWorldSeed()
    return MockWorldSeed.from_json(Path(path).read_text())


def _load_phase_script(
    fake_llm: FakeLLM, phase_name: str, issue_number: int, payload: object
) -> None:
    """Translate one seed.phase_scripts entry into FakeLLM.script_* calls.

    Each phase has a different inner shape (see ``MockWorldSeed.phase_scripts``
    docstring). This loader is the single point where the JSON shapes are
    decoded; the FakeLLM ``script_*`` methods themselves take typed kwargs.

    Unknown phase names log a warning and are skipped — sandbox scenarios
    cannot regress the seed loader by misnaming a phase, but they also can't
    silently land an unwired phase that looks correct.
    """
    if phase_name == "discover":
        assert isinstance(payload, list)
        for entry in payload:
            fake_llm.script_discover(
                issue_number,
                coherent=bool(entry.get("coherent", True)),
                queries_required=list(entry.get("queries_required", []) or []),
                summary=str(entry.get("summary", "") or ""),
                findings=list(entry.get("findings", []) or []),
            )
    elif phase_name == "plan_review":
        assert isinstance(payload, list)
        for entry in payload:
            fake_llm.script_plan_review(
                issue_number,
                verdict=entry["verdict"],
                gaps=list(entry.get("gaps", []) or []),
            )
    elif phase_name == "shape_council":
        assert isinstance(payload, dict)
        # Inner keys are round numbers; from_json coerces them to int.
        fake_llm.script_shape_council(issue_number, payload)
    elif phase_name == "implement_spec_review":
        assert isinstance(payload, list)
        for entry in payload:
            fake_llm.script_implement_spec_review(
                issue_number,
                compliant=bool(entry.get("compliant", True)),
                gaps=list(entry.get("gaps", []) or []),
                reasoning=str(entry.get("reasoning", "") or ""),
            )
    else:
        # Unknown phase name — log and skip so a typo can't silently break.
        import logging  # noqa: PLC0415

        logging.getLogger("hydraflow.sandbox_main").warning(
            "Unknown phase_scripts phase %r for issue #%d — ignored",
            phase_name,
            issue_number,
        )


def _build_caretaker_enabled_cb(
    loops_enabled: list[str] | None,
) -> Callable[[str], bool]:
    """Build the kill-switch gate for caretaker loops (ADR-0049).

    Semantics of ``MockWorldSeed.loops_enabled``:

    - ``None`` — all caretaker loops enabled (production default; scenario
      didn't opt into a subset).
    - ``[]`` — no caretaker loops enabled (universal kill-switch — proves
      ADR-0049 wiring; phase orchestrators are unaffected because they
      consult ``BGWorkerManager.is_enabled`` via the orchestrator's own
      ``is_bg_worker_enabled``, not this callback).
    - ``["name1", "name2", ...]`` — only those caretakers are enabled.
      Names match the keys in ``HydraFlowOrchestrator._bg_loop_registry``
      (e.g. ``"workspace_gc"``, ``"dependabot_merge"``, ``"ci_monitor"``).

    This callback is fed into ``WorkerRegistryCallbacks.is_enabled`` and
    becomes each caretaker's ``LoopDeps.enabled_cb`` — the in-body
    ``self._enabled_cb(self._worker_name)`` gate every
    ``BaseBackgroundLoop`` subclass checks per ADR-0049. Phase
    orchestrators (``_triage_loop``, ``_discover_loop``, ``_shape_loop``,
    ``_plan_loop``, ``_implement_loop``, ``_review_loop``, ``_hitl_loop``)
    use a different gate (``orchestrator.is_bg_worker_enabled`` →
    ``BGWorkerManager``) and so are not affected here. That's the
    per-triage-comment-on-#8483 contract: the kill-switch suppresses
    cadence-driven loops, not work-driven phase orchestrators.
    """
    if loops_enabled is None:
        return lambda *_a, **_kw: True
    allowed = frozenset(loops_enabled)
    return lambda name, *_a, **_kw: name in allowed


async def main() -> None:
    config = load_runtime_config()
    # Sandbox-specific config overrides — disable downstream code paths
    # that spawn real `claude` subprocesses. The sandbox is `internal: true`
    # per docker-compose.sandbox.yml, so these subprocesses hang for ~30s
    # of api_retry exponential backoff before failing with "unknown"
    # network errors. With multiple parallel issues (s02_batch_three_issues)
    # the cumulative hang exceeds the per-scenario 60s test timeout.
    #
    # The four primary LLM-backed runners (triage/plan/agent/review) are
    # already overridden via `runners=fake_llm` below; these flags turn
    # off the remaining secondary `claude` callers:
    #
    # - TranscriptSummarizer: spawns `claude` via subprocess_util.run_simple
    #   after each agent phase to summarize the transcript.
    # - ResearchRunner: spawns `claude` via _execute before each plan phase
    #   to gather codebase context. PlanPhase._should_research() honors
    #   this flag (see src/plan_phase.py).
    config.transcript_summarization_enabled = False  # type: ignore[misc]
    config.research_enabled = False  # type: ignore[misc]
    seed = _load_seed()
    event_bus = EventBus()
    state = build_state_tracker(config)
    stop_event = asyncio.Event()

    # Build the Fake adapter set from the seed.
    # NOTE: Casts here intentionally bypass strict Port conformance — the
    # current FakeIssueStore / FakeIssueFetcher have a narrower surface
    # than the production Ports require (no get_triageable / mark_active /
    # fetch_issues_by_labels yet). PR B widens the Fakes to satisfy the
    # full IssueStorePort / IssueFetcherPort contract; until then the
    # cast lets sandbox_main type-check while signaling the gap. At
    # runtime the FakeLLM / FakeWorkspace / FakeGitHub adapters carry
    # the entire required surface for the loops PR A actually exercises.
    workspaces = cast(WorkspacePort, FakeWorkspace(config.workspace_base))
    # Single FakeGitHub instance — shared by all three Fake adapters.
    # Using ``from_seed`` independently would create three isolated copies,
    # so a PR created via ``prs.create_pr`` wouldn't be visible to the
    # fetcher's ``fetch_reviewable_prs`` and the review loop would loop
    # forever requeuing the issue. The fetcher / store wrap the same
    # ``FakeGitHub`` so any state mutation is visible to all readers.
    shared_github = FakeGitHub.from_seed(seed)
    fetcher = cast(IssueFetcherPort, FakeIssueFetcher(github=shared_github))
    store = cast(
        IssueStorePort, FakeIssueStore(github=shared_github, event_bus=event_bus)
    )
    prs = cast(PRPort, shared_github)

    # FakeLLM provides triage_runner / planners / agents / reviewers from
    # the seed.scripts payload. Without this, the sandbox would attempt
    # real LLM calls and fail under the air-gapped network.
    fake_llm = FakeLLM()
    for phase, by_issue in seed.scripts.items():
        for issue_number, results in by_issue.items():
            getattr(fake_llm, f"script_{phase}")(issue_number, results)

    # Advisor scripts use a 3-arg shape: (issue_number, role, results) — the
    # 2-arg ``script_<phase>`` loop above can't carry the role axis, so they
    # live in their own seed field. Empty for non-advisor scenarios, which
    # keeps every existing seed payload unchanged.
    for issue_number, by_role in seed.advisor_scripts.items():
        for role, results in by_role.items():
            fake_llm.script_advisor(issue_number, role, results)

    # ADR-0063 phase-level scripts (W3a/W3b/W4/W5). Each phase entry maps
    # to a distinct FakeLLM.script_* call. Empty for pre-W3a/W3b/W4/W5
    # scenarios so existing seeds carry no payload here.
    for phase_name, by_issue in seed.phase_scripts.items():
        for issue_number, payload in by_issue.items():
            _load_phase_script(fake_llm, phase_name, int(issue_number), payload)

    # Every async-touched ``subprocess.run`` site in production code now
    # specifies ``timeout=`` (PRs #8454, #8456, #8468 — enforced by
    # ``tests/regressions/test_async_subprocess_timeouts.py``), so caretaker
    # loops that try to call out under air-gap fail fast instead of hanging
    # the dashboard's uvicorn bind. No sandbox-specific carve-out is needed.
    # ADR-0049 universal kill-switch wiring (#8483). ``seed.loops_enabled``
    # gates caretaker-loop ``enabled_cb`` only; phase orchestrators consult
    # ``BGWorkerManager.is_enabled`` and are unaffected. See
    # ``_build_caretaker_enabled_cb`` docstring for full semantics.
    callbacks = WorkerRegistryCallbacks(
        update_status=lambda *_a, **_kw: None,
        is_enabled=_build_caretaker_enabled_cb(seed.loops_enabled),
        get_interval=lambda *_a, **_kw: 60,
    )

    # FakeSubprocessRunner short-circuits every remaining shell-out to
    # ``claude -p`` that isn't covered by ``runners=fake_llm`` — most
    # critically ``TranscriptSummarizer``, ``HITLRunner``, and the
    # pre-quality-review skill subprocesses inside ``AgentRunner``.
    # Without this override they hit the air-gapped network, retry for
    # ~90s each, and overrun the scenario timeout.  The default
    # FakeDocker response is a single ``{success: True}`` event that
    # returns instantly.
    fake_docker = FakeDocker()
    fake_subprocess_runner = FakeSubprocessRunner(fake_docker)

    svc = build_services(
        config,
        event_bus,
        state,
        stop_event,
        callbacks,
        prs=prs,
        workspaces=workspaces,
        store=store,
        fetcher=fetcher,
        runners=fake_llm,
        subprocess_runner=fake_subprocess_runner,
    )

    # Attach the advisor-routing sentinel — mirrors
    # tests/scenarios/fakes/mock_world.py::_wire_targets so
    # ReviewPhase._build_post_verify_runner's ``_PostVerifyRunner.run``
    # adapter routes advisor consults into FakeLLM (via
    # ``pop_advisor_result``) instead of falling through to
    # ``ReviewRunner._execute``, which would spawn a real Claude
    # subprocess and fail under the sandbox's air-gapped network.
    #
    # The sentinel must land on the SAME object the production runner
    # adapter probes (``parent._reviewers.__dict__``). With
    # ``runners=fake_llm`` above, ``svc.reviewers`` IS the
    # ``_FakeReviewRunner`` — a plain Python instance whose ``__dict__``
    # carries the assignment cleanly.
    svc.reviewers._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]

    # ADR-0063 sentinel wiring (W3a/W3b/W4/W5). Each runner consults the
    # sentinel via ``getattr(self, "_mockworld_fake_llm", None)`` in its
    # subprocess-dispatch method; setting the attribute here lets sandbox
    # scenarios drive failure-path recovery without producing synthetic
    # subprocess transcripts.
    discover_runner = getattr(svc.discover_phase, "_runner", None)
    if discover_runner is not None:
        discover_runner._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    plan_reviewer = getattr(svc.planner_phase, "_plan_reviewer", None)
    if plan_reviewer is not None:
        plan_reviewer._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    expert_council = getattr(svc.shape_phase, "_council", None)
    if expert_council is not None:
        expert_council._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]
    spec_reviewer = getattr(svc.implementer, "_spec_reviewer", None)
    if spec_reviewer is not None:
        spec_reviewer._mockworld_fake_llm = fake_llm  # type: ignore[attr-defined]

    orch = HydraFlowOrchestrator(
        config,
        event_bus=event_bus,
        state=state,
        services=svc,
    )

    dashboard = HydraFlowDashboard(
        config=config,
        event_bus=event_bus,
        state=state,
        orchestrator=orch,
    )
    await dashboard.start()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    # Drive the pipeline. Without this, the dashboard would serve /healthz
    # but no loops would tick, no issues would advance, and Tier-2
    # scenarios would always time out at the API-poll step.
    orch_task = asyncio.create_task(orch.run(), name="hydraflow-orchestrator")

    try:
        await stop_event.wait()
    finally:
        if orch.running:
            await orch.stop()
        # Allow orch_task to clean up (it observes stop_event via orch.stop()).
        if not orch_task.done():
            orch_task.cancel()
        await asyncio.gather(orch_task, return_exceptions=True)
        await dashboard.stop()


if __name__ == "__main__":
    asyncio.run(main())
