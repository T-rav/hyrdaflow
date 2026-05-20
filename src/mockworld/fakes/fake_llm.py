"""Scripted LLM runner fakes for scenario testing.

FakeLLM provides per-phase, per-issue result sequences. Each runner method
pops the next result from a deque. When the deque is empty, a default
success result is returned.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from mockworld.fakes._factories import (
    PlanResultFactory,
    ReviewResultFactory,
    TriageResultFactory,
    WorkerResultFactory,
)
from models import EpicDecompResult, ReviewVerdict


@dataclass(slots=True)
class _BudgetState:
    """Per-issue token budget accounting used by FakeLLM."""

    max: int
    per_call: int
    used: int = 0


class _ScriptedRunner:
    """Base for a runner that returns scripted results by issue number."""

    def __init__(self) -> None:
        self._scripts: dict[int, deque[Any]] = {}
        self._last_scripted: dict[int, Any] = {}

    def _add_script(self, issue_number: int, results: list[Any]) -> None:
        self._scripts[issue_number] = deque(results)
        # Clear any stale last-scripted so the new script takes precedence
        self._last_scripted.pop(issue_number, None)

    def add_script(self, issue_number: int, results: list[Any]) -> None:
        self._add_script(issue_number, results)

    def _pop(self, issue_number: int, default_factory: Callable[[], Any]) -> Any:
        q = self._scripts.get(issue_number)
        if q:
            result = q.popleft()
            self._last_scripted[issue_number] = result
            return result
        # Deque empty — repeat last scripted result if we had one
        if issue_number in self._last_scripted:
            return self._last_scripted[issue_number]
        return default_factory()

    def set_tracing_context(self, _context: Any) -> None:
        pass

    def clear_tracing_context(self) -> None:
        pass

    @property
    def active_count(self) -> int:
        """Number of currently running subprocesses.

        Real ``BaseRunner.active_count`` returns ``len(self._active_procs)``;
        the orchestrator emits this in pipeline stats. The Fake doesn't
        spawn subprocesses, so the count is always 0.
        """
        return 0

    def terminate(self) -> None:
        """Stop all in-flight subprocesses (no-op stub).

        Real ``BaseRunner.terminate`` walks ``self._active_procs`` and
        sends SIGTERM. The Fake doesn't spawn subprocesses, so there's
        nothing to terminate. Required because ``orchestrator.run()``
        calls ``self._svc.{planners,agents,reviewers,hitl_runner}.terminate()``
        unconditionally during shutdown.
        """
        return None


class _FakeTriageRunner(_ScriptedRunner):
    def __init__(self) -> None:
        super().__init__()
        self._decomposition_scripts: dict[int, EpicDecompResult] = {}

    def script_decomposition(self, issue_number: int, result: EpicDecompResult) -> None:
        """Script the EpicDecompResult returned for the given issue."""
        self._decomposition_scripts[issue_number] = result

    async def evaluate(self, issue: Any, _worker_id: int = 0) -> Any:
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        return self._pop(
            issue_number,
            lambda: TriageResultFactory.create(issue_number=issue_number, ready=True),
        )

    async def run_decomposition(self, task: Any) -> EpicDecompResult:
        issue_number = getattr(task, "id", getattr(task, "number", 0))
        return self._decomposition_scripts.get(
            issue_number, EpicDecompResult(should_decompose=False)
        )


class _FakePlannerRunner(_ScriptedRunner):
    def __init__(self, parent: FakeLLM) -> None:
        super().__init__()
        self._parent = parent

    async def plan(
        self,
        task: Any,
        *,
        worker_id: int = 0,
        research_context: str = "",
        **_unused: Any,
    ) -> Any:
        _ = (worker_id, research_context)
        issue_number = getattr(task, "id", getattr(task, "number", 0))
        if not self._parent._consume_budget(issue_number):
            return PlanResultFactory.create(
                issue_number=issue_number,
                success=False,
                error="token_budget exceeded",
            )
        return self._pop(
            issue_number,
            lambda: PlanResultFactory.create(issue_number=issue_number, success=True),
        )

    async def run_gap_review(
        self,
        _epic_number: int,
        _child_plans: dict[Any, Any],
        _child_titles: dict[Any, Any],
    ) -> str:
        return ""


class _FakeAgentRunner(_ScriptedRunner):
    def __init__(self) -> None:
        super().__init__()
        self._streams: dict[int, list[Any]] = {}
        self._prior_failures: dict[int, list[str]] = {}

    async def run(
        self,
        task: Any,
        worktree_path: Path,
        branch: str,
        *,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        **_unused: Any,
    ) -> Any:
        _ = (worker_id, review_feedback, bead_mapping)
        issue_number = getattr(task, "id", getattr(task, "number", 0))
        if prior_failure:
            self._prior_failures.setdefault(issue_number, []).append(prior_failure)
        return self._pop(
            issue_number,
            lambda: WorkerResultFactory.create(
                issue_number=issue_number,
                branch=branch,
                workspace_path=str(worktree_path),
                success=True,
                commits=1,
            ),
        )

    def script_stream(self, issue_number: int, events: list[Any]) -> None:
        self._streams[issue_number] = list(events)

    def events_for(self, issue_number: int) -> list[Any]:
        return list(self._streams.get(issue_number, []))

    def prior_failures_seen_for(self, issue_number: int) -> list[str]:
        return list(self._prior_failures.get(issue_number, []))


class _FakeReviewRunner(_ScriptedRunner):
    def __init__(self, parent: FakeLLM) -> None:
        super().__init__()
        self._parent = parent
        self._last_alerts_received: dict[int, list[Any]] = {}

    async def review(
        self,
        pr: Any,
        issue: Any,
        _worktree_path: Path,
        _diff: str,
        *,
        worker_id: int = 0,
        code_scanning_alerts: list[Any] | None = None,
        bead_tasks: list[Any] | None = None,
        **_unused: Any,
    ) -> Any:
        _ = (worker_id, bead_tasks)
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        self._last_alerts_received[issue_number] = list(code_scanning_alerts or [])
        pr_number = getattr(pr, "number", 0)
        if not self._parent._consume_budget(issue_number):
            return ReviewResultFactory.create(
                pr_number=pr_number,
                issue_number=issue_number,
                verdict=ReviewVerdict.REQUEST_CHANGES,
                merged=False,
                ci_passed=False,
                error="token_budget exceeded",
            )
        return self._pop(
            issue_number,
            lambda: ReviewResultFactory.create(
                pr_number=pr_number,
                issue_number=issue_number,
                verdict=ReviewVerdict.APPROVE,
                merged=True,
                ci_passed=True,
            ),
        )

    async def fix_ci(
        self,
        pr: Any,
        issue: Any,
        _worktree_path: Path,
        _failure_summary: str,
        **_kwargs: Any,
    ) -> Any:
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        pr_number = getattr(pr, "number", 0)
        scripted = self._parent._fix_ci_scripts.get(issue_number)
        if scripted is not None:
            return scripted
        return ReviewResultFactory.create(
            pr_number=pr_number,
            issue_number=issue_number,
            verdict=ReviewVerdict.APPROVE,
            ci_passed=True,
            fixes_made=True,
        )

    async def fix_review_findings(
        self,
        pr: Any,
        issue: Any,
        _worktree_path: Path,
        _review_summary: str,
        **_kwargs: Any,
    ) -> Any:
        """Default fake: report fixes_made=True so the retry loop re-reviews.

        Production ``ReviewRunner.fix_review_findings`` would spawn a real
        subprocess. The retry path triggered by the post-verify advisor's
        VETO branch lands here in MockWorld scenarios — the executor is
        treated as having committed a fix, so the next ``review()`` pop
        decides the outcome.
        """
        issue_number = getattr(issue, "id", getattr(issue, "number", 0))
        pr_number = getattr(pr, "number", 0)
        return ReviewResultFactory.create(
            pr_number=pr_number,
            issue_number=issue_number,
            verdict=ReviewVerdict.APPROVE,
            fixes_made=True,
        )


class _FakeAdvisorRunner:
    """Per-(issue, role) scripted advisor responses for MockWorld scenarios.

    Distinct from _ScriptedRunner because advisor calls are addressed by a
    compound key (issue_number, role) rather than just issue_number, and they
    should not collide with the per-issue scripts used by other phases.
    """

    def __init__(self) -> None:
        self._scripts: dict[tuple[int, str], list[Any]] = {}
        self._role_call_counts: dict[str, int] = {}

    def script(self, issue_number: int, role: str, results: list[Any]) -> None:
        key = (issue_number, role)
        self._scripts[key] = list(results)

    def pop(self, issue_number: int, role: str) -> Any:
        key = (issue_number, role)
        queue = self._scripts.get(key, [])
        result = queue.pop(0) if queue else None
        self._role_call_counts[role] = self._role_call_counts.get(role, 0) + 1
        return result

    def call_count_for(self, role: str) -> int:
        return self._role_call_counts.get(role, 0)


@dataclass(slots=True)
class ScriptedDiscoverEval:
    """One scripted outcome for ``DiscoverRunner._evaluate_brief`` (ADR-0063 W3a).

    ``coherent=False`` causes the runner to see a failed coherence verdict
    and dispatch the discover-expander. ``queries_required`` are the new
    research queries the expander is scripted to surface; they are returned
    verbatim from the expander dispatch.
    """

    coherent: bool
    queries_required: list[str] = field(default_factory=list)
    summary: str = ""
    findings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScriptedPlanReview:
    """One scripted outcome for ``PlanReviewer.review`` (ADR-0063 W3b).

    ``verdict="reject"`` with ``gaps`` triggers the touchpoint-expander on
    the first failure inside ``PlanPhase._maybe_expand_touchpoints``.
    ``verdict="accept"`` returns a clean PlanReview with no blocking
    findings so the issue advances past Plan.
    """

    verdict: Literal["accept", "reject"]
    gaps: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ScriptedSpecReview:
    """One scripted outcome for ``DefaultSpecComplianceReviewer.review`` (ADR-0063 W5).

    ``compliant=False`` with ``gaps`` causes ImplementPhase to persist gaps
    into ``WorkerResultMeta.spec_review_gaps`` and prepend them to the next
    attempt's ``prior_failure`` prompt anchor.
    """

    compliant: bool
    gaps: list[str] = field(default_factory=list)
    reasoning: str = ""


class _FakePhaseScripts:
    """Per-issue FIFO queues for phase-level scripted outcomes (ADR-0063).

    Distinct from the per-runner ``_ScriptedRunner`` queues because these
    address failure-path probes that production phase code consults via the
    ``_mockworld_fake_llm`` sentinel rather than via the four primary
    runners (planners/agents/reviewers/triage). When a queue is exhausted
    the consumer falls through to default behavior (no further scripting)
    instead of repeating the last scripted result.
    """

    def __init__(self) -> None:
        # Per-issue queues for each phase script type.
        self.discover: dict[int, deque[ScriptedDiscoverEval]] = {}
        self.plan_review: dict[int, deque[ScriptedPlanReview]] = {}
        # Council scripts are keyed by issue → {round_num: verdict}. The
        # round map persists across consume calls (unlike a deque) because
        # the same scenario may ask "what does round 2 look like?" twice
        # if the phase code re-runs the predicate. The map is read-only;
        # ``script_shape_council`` replaces it wholesale per issue.
        self.shape_council: dict[int, dict[int, Literal["consensus", "split"]]] = {}
        self.implement_spec_review: dict[int, deque[ScriptedSpecReview]] = {}


class FakeLLM:
    """Composable scripted LLM runners for all pipeline phases."""

    _is_fake_adapter = True  # read by dashboard for MOCKWORLD banner

    def __init__(self) -> None:
        self._token_budgets: dict[int, _BudgetState] = {}
        self._fix_ci_scripts: dict[int, Any] = {}
        self.triage_runner = _FakeTriageRunner()
        self.planners = _FakePlannerRunner(self)
        self.agents = _FakeAgentRunner()
        self.reviewers = _FakeReviewRunner(self)
        self._advisor = _FakeAdvisorRunner()
        # ADR-0063 phase-level scripted outcomes (W3a/W3b/W4/W5).
        self._phase_scripts = _FakePhaseScripts()

    def script_triage(self, issue_number: int, results: list[Any]) -> None:
        self.triage_runner.add_script(
            issue_number, [self._coerce_triage(issue_number, r) for r in results]
        )

    def script_plan(self, issue_number: int, results: list[Any]) -> None:
        self.planners.add_script(
            issue_number, [self._coerce_plan(issue_number, r) for r in results]
        )

    def script_implement(self, issue_number: int, results: list[Any]) -> None:
        self.agents.add_script(
            issue_number, [self._coerce_implement(issue_number, r) for r in results]
        )

    def script_review(self, issue_number: int, results: list[Any]) -> None:
        self.reviewers.add_script(
            issue_number, [self._coerce_review(issue_number, r) for r in results]
        )

    def script_advisor(self, issue_number: int, role: str, results: list[Any]) -> None:
        """Script advisor responses for (issue_number, role).

        Distinct from script_review/script_plan: advisor calls are addressed
        by a (issue, role) compound key so a single issue can have separate
        queues for ``pre_flight``, ``post_verify``, etc.
        """
        self._advisor.script(issue_number, role, results)

    def pop_advisor_result(self, issue_number: int, role: str) -> Any:
        """Pop the next advisor result for (issue_number, role).

        Returns None when no script is queued. Each call increments the
        per-role call counter regardless of whether a result was scripted.
        """
        return self._advisor.pop(issue_number, role)

    def advisor_call_count_for(self, role: str) -> int:
        """Number of advisor pops observed for ``role`` across all issues."""
        return self._advisor.call_count_for(role)

    # ------------------------------------------------------------------
    # ADR-0063 phase-level script hooks (W3a / W3b / W4 / W5).
    #
    # These do NOT go through the four primary runner attrs; production
    # phase code consults FakeLLM directly via the ``_mockworld_fake_llm``
    # sentinel attached by ``mockworld.sandbox_main`` (and the in-process
    # MockWorld harness). The hooks let sandbox scenarios script the
    # exact failure-path branches the recovery workstreams were built to
    # exercise: coherence-failure → discover-expander dispatch,
    # plan-reviewer reject → touchpoint-expander dispatch, council split →
    # round-3 diversified panel, and zero-diff implement → spec-compliance
    # reviewer two-stage feedback.
    # ------------------------------------------------------------------

    def script_discover(
        self,
        issue_number: int,
        *,
        coherent: bool,
        queries_required: list[str] | None = None,
        summary: str = "",
        findings: list[str] | None = None,
    ) -> None:
        """Append one scripted DiscoverRunner coherence outcome to the queue.

        ``coherent=False`` makes the next ``_evaluate_brief`` call return a
        failed verdict so the bounded retry loop dispatches the
        discover-expander; ``queries_required`` is what the expander then
        returns to be injected into the retry prompt.

        Multiple calls append to the queue (FIFO consumption).
        """
        q = self._phase_scripts.discover.setdefault(issue_number, deque())
        q.append(
            ScriptedDiscoverEval(
                coherent=coherent,
                queries_required=list(queries_required or []),
                summary=summary,
                findings=list(findings or []),
            )
        )

    def pop_discover_script(self, issue_number: int) -> ScriptedDiscoverEval | None:
        """Pop the next scripted DiscoverRunner outcome for *issue_number*.

        Returns ``None`` when no script is queued. Each call removes one
        entry from the FIFO so re-entrant phase ticks see fresh values.
        Production callers route through this when ``_mockworld_fake_llm``
        is set on the runner instance.
        """
        q = self._phase_scripts.discover.get(issue_number)
        if not q:
            return None
        return q.popleft()

    def script_plan_review(
        self,
        issue_number: int,
        *,
        verdict: Literal["accept", "reject"],
        gaps: list[str] | None = None,
    ) -> None:
        """Append one scripted PlanReviewer verdict to the queue.

        ``verdict="reject"`` with non-empty ``gaps`` produces a PlanReview
        carrying blocking findings so ``PlanPhase._maybe_expand_touchpoints``
        dispatches the touchpoint-expander. ``"accept"`` returns a clean
        review with no findings so the issue advances past Plan.
        """
        q = self._phase_scripts.plan_review.setdefault(issue_number, deque())
        q.append(ScriptedPlanReview(verdict=verdict, gaps=list(gaps or [])))

    def pop_plan_review_script(self, issue_number: int) -> ScriptedPlanReview | None:
        """Pop the next scripted PlanReviewer verdict for *issue_number*."""
        q = self._phase_scripts.plan_review.get(issue_number)
        if not q:
            return None
        return q.popleft()

    def script_shape_council(
        self,
        issue_number: int,
        round_to_verdict: dict[int, Literal["consensus", "split"]],
    ) -> None:
        """Set the per-round council vote verdict map for *issue_number*.

        Used by ``ExpertCouncil.vote`` / ``vote_diversified`` to synthesize
        a CouncilResult matching the scripted convergence pattern. The map
        is read-only — successive ``shape_council_verdict_for_round`` reads
        are idempotent so the council can be queried more than once per
        round without consuming state.

        Example::

            llm.script_shape_council(3, {1: "split", 2: "split", 3: "consensus"})

        exercises the W4 round-3 diversified-persona panel.
        """
        self._phase_scripts.shape_council[issue_number] = dict(round_to_verdict)

    def shape_council_verdict_for_round(
        self, issue_number: int, round_num: int
    ) -> Literal["consensus", "split"] | None:
        """Return the scripted verdict for *issue_number*/*round_num*.

        Returns ``None`` when no script is set so the production council
        falls through to its default subprocess-driven behavior.
        """
        by_round = self._phase_scripts.shape_council.get(issue_number)
        if not by_round:
            return None
        return by_round.get(round_num)

    def script_implement_spec_review(
        self,
        issue_number: int,
        *,
        compliant: bool,
        gaps: list[str] | None = None,
        reasoning: str = "",
    ) -> None:
        """Append one scripted spec-compliance reviewer verdict to the queue.

        ``compliant=False`` with non-empty ``gaps`` causes ImplementPhase to
        persist the gaps to ``WorkerResultMeta.spec_review_gaps`` and
        prepend them to the next attempt's ``prior_failure`` prompt anchor.
        """
        q = self._phase_scripts.implement_spec_review.setdefault(issue_number, deque())
        q.append(
            ScriptedSpecReview(
                compliant=compliant,
                gaps=list(gaps or []),
                reasoning=reasoning,
            )
        )

    def pop_implement_spec_review_script(
        self, issue_number: int
    ) -> ScriptedSpecReview | None:
        """Pop the next scripted spec-compliance verdict for *issue_number*."""
        q = self._phase_scripts.implement_spec_review.get(issue_number)
        if not q:
            return None
        return q.popleft()

    # ------------------------------------------------------------------
    # Dict → typed-result coercion
    #
    # Scenarios are loaded from JSON seeds, where script payloads are
    # plain dicts. Production code calls ``result.duration_seconds``,
    # ``result.success`` etc. on the concrete Pydantic model. The Fake
    # would otherwise leak dicts through ``_pop`` into the implement /
    # review phases. Each helper either (a) returns the value as-is when
    # it's already the right type, or (b) routes through the factory to
    # build a typed instance from the dict's keys.
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_kwargs(factory_create: Any, raw: dict[str, Any]) -> dict[str, Any]:
        """Drop dict keys the factory's `create` method doesn't accept.

        JSON seeds may carry diagnostic fields (``task_count``, ``branch``)
        that don't map onto the factory's keyword args. Forwarding them
        unfiltered would raise ``TypeError: unexpected keyword argument``.
        """
        import inspect

        sig = inspect.signature(factory_create)
        accepted = {p for p in sig.parameters if p != "self"}
        return {k: v for k, v in raw.items() if k in accepted}

    @classmethod
    def _coerce_triage(cls, issue_number: int, raw: Any) -> Any:
        if isinstance(raw, dict):
            kw = cls._filter_kwargs(TriageResultFactory.create, raw)
            return TriageResultFactory.create(issue_number=issue_number, **kw)
        return raw

    @classmethod
    def _coerce_plan(cls, issue_number: int, raw: Any) -> Any:
        if isinstance(raw, dict):
            kw = cls._filter_kwargs(PlanResultFactory.create, raw)
            return PlanResultFactory.create(issue_number=issue_number, **kw)
        return raw

    @classmethod
    def _coerce_implement(cls, issue_number: int, raw: Any) -> Any:
        if isinstance(raw, dict):
            kw = cls._filter_kwargs(WorkerResultFactory.create, raw)
            return WorkerResultFactory.create(issue_number=issue_number, **kw)
        return raw

    @classmethod
    def _coerce_review(cls, issue_number: int, raw: Any) -> Any:
        if isinstance(raw, dict):
            kw = cls._filter_kwargs(ReviewResultFactory.create, raw)
            kw.setdefault("pr_number", 0)
            # Coerce string verdict ("approve" / "request-changes" / "comment")
            # into the StrEnum so pydantic doesn't reject the model.
            verdict = kw.get("verdict")
            if isinstance(verdict, str):
                kw["verdict"] = ReviewVerdict(verdict)
            return ReviewResultFactory.create(issue_number=issue_number, **kw)
        return raw

    def script_fix_ci(self, issue_number: int, result: Any) -> None:
        """Script the ReviewResult returned by reviewers.fix_ci for an issue.

        Default (no script): returns ReviewResult(verdict=APPROVE, fixes_made=True,
        ci_passed=True). Scripting lets scenarios exercise the 'fix_ci gives up'
        branch (fixes_made=False).
        """
        self._fix_ci_scripts[issue_number] = result

    def alerts_received_by_reviewer(self, issue_number: int) -> list[Any]:
        """Return the code_scanning_alerts last passed to reviewers.review for this issue."""
        return list(self.reviewers._last_alerts_received.get(issue_number, []))

    def set_token_budget(
        self,
        *,
        issue_number: int,
        max_tokens: int,
        tokens_per_call: int = 100,
    ) -> None:
        """Gate scripted planner/reviewer results by cumulative token cost.

        Each ``planners.plan`` and ``reviewers.review`` call for
        ``issue_number`` adds ``tokens_per_call`` to the running total. Once
        the total would exceed ``max_tokens``, subsequent calls return a
        synthetic failure (``error="token_budget exceeded"``) instead of
        popping the scripted queue.

        Triage and agent runners are intentionally exempt:

        - Triage: production rarely token-bounded at this stage.
        - Agent: in ``use_real_agent_runner=True`` mode the scripted
          ``_FakeAgentRunner`` is replaced; the realistic path uses the
          FakeDocker ``"budget_exceeded"`` stream event instead (see
          scenario A5 in ``test_agent_realistic.py``).
        """
        self._token_budgets[issue_number] = _BudgetState(
            max=max_tokens, per_call=tokens_per_call
        )

    def _consume_budget(self, issue_number: int) -> bool:
        """Return True if the call fits the budget; False if exceeded.

        When the budget is exceeded, the scripted queue is NOT popped — the
        caller short-circuits to a synthetic failure result. A subsequent
        call (after the block) therefore still sees the full remaining queue.
        """
        state = self._token_budgets.get(issue_number)
        if state is None:
            return True
        new_used = state.used + state.per_call
        if new_used > state.max:
            return False
        state.used = new_used
        return True
