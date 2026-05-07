"""CorpusLearningLoop — grow the adversarial corpus from escape signals (§4.1 v2).

Phase 2 Tasks 11–15 are wired in:

- **Task 11** (reader): the loop queries
  ``PRManager.list_issues_by_label`` for open issues tagged with the
  configured escape label (default :data:`DEFAULT_ESCAPE_LABEL`),
  filters to the last :data:`DEFAULT_LOOKBACK_DAYS` days, and
  materializes each row into an :class:`EscapeSignal` dataclass.
- **Task 12** (synthesis): :meth:`CorpusLearningLoop._synthesize_case`
  turns an :class:`EscapeSignal` into a :class:`SynthesizedCase` by
  parsing a structured escape-issue body convention (see module
  docstring on :class:`SynthesizedCase` for the expected template).
  Malformed or minimal signals surface as ``None`` so the loop skips
  them instead of crashing.
- **Task 13** (self-validation): :meth:`CorpusLearningLoop._validate_case`
  runs three gates against a :class:`SynthesizedCase`:

    a. *harness accepts it* — the before/after pair produces a non-empty
       synthetic diff (matches the precondition in
       :func:`tests.trust.adversarial.test_adversarial_corpus.test_case`).
    b. *expected catcher trips* — feeding the deterministic fixture
       transcript for the named catcher into that skill's
       ``result_parser`` returns ``passed=False`` *and* the keyword
       appears in the summary (same contract the harness asserts via
       ``_read_keyword``).
    c. *unambiguous* — no *other* registered skill's ``result_parser``
       returns ``passed=False`` against the same transcript. A case
       that trips more than one catcher is ambiguous and must be
       rejected before it rots the corpus.

- **Task 14** (wiring): :meth:`CorpusLearningLoop._do_work` ticks through
  the escape signals, synthesizes + validates each, and returns a
  status dict with ``escape_issues_seen``, ``cases_synthesized``, and
  ``cases_validated``.

- **Task 15** (materialize + PR): validated cases are written to
  ``tests/trust/adversarial/cases/<slug>/`` (via
  :meth:`CorpusLearningLoop._materialize_case_on_disk`) and filed as
  PRs (via :meth:`CorpusLearningLoop._open_pr_for_case`, which
  delegates to :func:`auto_pr.open_automated_pr_async`). A
  :class:`dedup_store.DedupStore` keyed on
  ``corpus_learning:<issue_number>:<slug>`` prevents re-filing the
  same case on subsequent ticks. The final status dict gains a
  ``cases_filed`` counter.

Kill-switch: :meth:`LoopDeps.enabled_cb` with ``worker_name="corpus_learning"``
— **no ``corpus_learning_enabled`` config field** (spec §12.2).
"""

from __future__ import annotations

import asyncio
import difflib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from auto_pr import open_automated_pr_async
from base_background_loop import BaseBackgroundLoop, LoopDeps  # noqa: TCH001
from models import WorkCycleResult  # noqa: TCH001
from skill_registry import BUILTIN_SKILLS, AgentSkill

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.corpus_learning_loop")

#: Default GitHub label that marks an issue as a production escape
#: signal. Task 15 will surface this as a
#: Default label for backwards-compatible single-label callers (tests).
#: Production reads :data:`DEFAULT_ESCAPE_SIGNAL_LABELS` via the
#: ``corpus_learning_signal_labels`` config field (spec §4.1).
DEFAULT_ESCAPE_LABEL = "skill-escape"

#: Spec §4.1: the loop reads three escape-label families. ``skill-escape``
#: covers post-impl skills; ``discover-escape`` and ``shape-escape``
#: cover product-phase evaluator escapes (§4.10). Configurable via
#: ``HydraFlowConfig.corpus_learning_signal_labels``.
DEFAULT_ESCAPE_SIGNAL_LABELS: tuple[str, ...] = (
    "skill-escape",
    "discover-escape",
    "shape-escape",
)

#: Default recency window (days) for escape signals. Issues whose
#: ``updated_at`` is older than this are dropped from the reader so the
#: synthesizer focuses on live regressions, not archived noise.
DEFAULT_LOOKBACK_DAYS = 30

#: Spec §4.1 v2 step 5: 3 consecutive self-validation failures on the
#: same escape issue trigger a `corpus-learning-stuck` escalation.
_CORPUS_STUCK_ATTEMPTS = 3

#: Parses ``Corpus learning stuck on escape #1234: …`` titles for
#: reconcile-on-close (spec §3.2 lifecycle).
_STUCK_TITLE_RE = re.compile(
    r"^Corpus learning stuck on escape #(?P<num>\d+):", re.MULTILINE
)

#: Catchers the synthesizer is allowed to target. Mirrors the
#: post-implementation skills the harness fixture builder knows how to
#: emit a deterministic RETRY marker for. ``arch-compliance`` is
#: intentionally excluded until we add a marker mapping for it.
_SYNTHESIZABLE_CATCHERS: frozenset[str] = frozenset(
    {"diff-sanity", "scope-check", "test-adequacy", "plan-compliance"}
)

#: Marker token each skill emits in its ``<SKILL>_RESULT: RETRY``
#: line. Used by :meth:`CorpusLearningLoop._fixture_transcript_for` to
#: build the deterministic gate-(b) fixture without a live LLM call.
_CATCHER_MARKERS: dict[str, str] = {
    "diff-sanity": "DIFF_SANITY_RESULT",
    "scope-check": "SCOPE_CHECK_RESULT",
    "test-adequacy": "TEST_ADEQUACY_RESULT",
    "plan-compliance": "PLAN_COMPLIANCE_RESULT",
}

#: Upper bound on the derived case-directory slug. Anything longer is
#: ugly on disk, harder to grep, and runs into filesystem name limits
#: when combined with the cases-root prefix.
_SLUG_MAX_LEN = 64

#: Relative (to ``repo_root``) root for all materialized cases. Kept as a
#: module constant so Task 16's integration test and Task 18's MockWorld
#: scenario reference the same single source of truth.
_CASES_ROOT = Path("tests") / "trust" / "adversarial" / "cases"

#: Labels applied to every PR the loop opens. ``hydraflow-agent`` is the
#: generic auto-opened-PR tag the promotion flow already recognizes;
#: ``corpus-learning`` lets operators filter this loop's traffic.
_CASE_PR_LABELS: tuple[str, ...] = ("hydraflow-agent", "corpus-learning")


@dataclass(frozen=True, slots=True)
class EscapeSignal:
    """A parsed escape-signal row from a ``skill-escape``-labeled issue.

    Intentionally narrow: carries just the fields Task 12's synthesizer
    needs (``issue_number``, ``title``, ``body``) plus the provenance
    bits (``updated_at``, ``label``) the loop uses for filtering and
    telemetry. Reading new GitHub fields means extending this shape —
    never stashing raw ``dict`` rows downstream.
    """

    issue_number: int
    title: str
    body: str
    updated_at: str
    label: str


@dataclass(frozen=True, slots=True)
class SynthesizedCase:
    """An in-memory spec for a would-be ``cases/<slug>/`` directory.

    Produced by :meth:`CorpusLearningLoop._synthesize_case` from a
    parseable :class:`EscapeSignal`. The expected escape-issue body
    convention is::

        <free-form reproduction prose — becomes README.md body>

        Expected-Catcher: diff-sanity
        Keyword: <substring-that-must-appear-in-retry-summary>

        ```before:src/path/to/file.py
        <pre-diff contents>
        ```

        ```after:src/path/to/file.py
        <post-diff contents>
        ```

        (optional)
        ```plan
        <plan text — scope-check/plan-compliance only>
        ```

    Task 15's :meth:`CorpusLearningLoop._materialize_case_on_disk`
    writes this spec out under
    ``tests/trust/adversarial/cases/<slug>/``.
    """

    issue_number: int
    slug: str
    expected_catcher: str
    keyword: str
    before_files: dict[str, str]
    after_files: dict[str, str]
    readme: str
    plan_text: str = ""


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of :meth:`CorpusLearningLoop._validate_case`.

    ``ok=True`` means all three gates passed. On failure, ``failing_gate``
    identifies *which* gate rejected the case so telemetry (and Task 15's
    HITL escalation) can attribute the rejection precisely:

    - ``"harness_accepts"`` — gate (a) failed (e.g. empty diff).
    - ``"expected_catcher_trips"`` — gate (b) failed (named catcher did
      not report RETRY, or keyword absent from summary).
    - ``"unambiguous"`` — gate (c) failed (another catcher also tripped).
    """

    ok: bool
    reason: str = ""
    failing_gate: str = ""


class CorpusLearningLoop(BaseBackgroundLoop):
    """Grows ``tests/trust/adversarial/cases/`` from production escape signals.

    Current state (Tasks 11–15): reads escape signals, synthesizes
    in-memory case specs, self-validates them with three gates,
    materializes the survivors to disk, and files them as PRs against
    the configured base branch.  Five-checkpoint status wiring is Task
    15's other half; the release-gating scenario is Task 18.
    """

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
        state: StateTracker | None = None,
    ) -> None:
        super().__init__(
            worker_name="corpus_learning",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._prs = prs
        self._dedup = dedup
        self._state = state
        # G17: warn at construction time if the synthesis model overlaps the
        # production skill model. Spec §4.1 v2 (cross-model synthesis): "If
        # the synthesis model matches the skill's production model, the loop
        # logs a warning and proceeds with reduced diversity." Today's
        # synthesis path is template-driven (parses structured markdown from
        # the escape issue), so the warning is forward-compatible insurance:
        # whenever a future plan upgrades synthesis to an LLM call, this
        # guard already catches the overlap. Spec is explicit that the same
        # model would mean the corpus inherits the production model's blind
        # spots — false trust.
        self._warn_on_synthesis_model_overlap()

    def _warn_on_synthesis_model_overlap(self) -> None:
        """Log a warning if `corpus_learning_synthesis_model` matches the
        production post-impl skill model. See spec §4.1 v2."""
        synthesis_model = getattr(
            self._config, "corpus_learning_synthesis_model", "opus"
        )
        production_model = getattr(
            self._config, "background_default_model", ""
        ) or getattr(self._config, "model", "")
        if synthesis_model and production_model and synthesis_model == production_model:
            logger.warning(
                "corpus-learning: synthesis model %r matches production "
                "skill model — corpus may inherit production blind spots. "
                "Set HYDRAFLOW_CORPUS_LEARNING_SYNTHESIS_MODEL to a "
                "different model to restore cross-model diversity (spec §4.1).",
                synthesis_model,
            )

    def _get_default_interval(self) -> int:
        return self._config.corpus_learning_interval

    async def _list_escape_signals(
        self,
        *,
        label: str = DEFAULT_ESCAPE_LABEL,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    ) -> list[EscapeSignal]:
        """Return escape-signal issues labeled ``label`` from the last ``lookback_days``.

        Delegates to :meth:`PRManager.list_issues_by_label` (the
        canonical ``gh issue list`` wrapper) so CI-mocked and
        scenario-mocked runs stay on a single seam. Rows without a
        usable ``number`` or with an unparseable ``updated_at`` are
        dropped — better to skip a malformed row than poison Task 12's
        synthesizer with ``issue_number=0`` or a ``None`` timestamp.
        """
        raw_issues = await self._prs.list_issues_by_label(label)
        if not raw_issues:
            return []

        cutoff = datetime.now(UTC) - timedelta(days=lookback_days)
        signals: list[EscapeSignal] = []
        for row in raw_issues:
            issue_number = row.get("number", 0)
            if not issue_number:
                continue
            updated_at_raw = row.get("updated_at", "") or ""
            parsed = _parse_iso_timestamp(updated_at_raw)
            if parsed is None:
                logger.debug(
                    "corpus-learning: dropping issue #%d with unparseable updated_at=%r",
                    issue_number,
                    updated_at_raw,
                )
                continue
            if parsed < cutoff:
                continue
            signals.append(
                EscapeSignal(
                    issue_number=issue_number,
                    title=row.get("title", "") or "",
                    body=row.get("body", "") or "",
                    updated_at=updated_at_raw,
                    label=label,
                )
            )
        return signals

    # ------------------------------------------------------------------
    # Task 12 — in-process synthesis
    # ------------------------------------------------------------------

    def _synthesize_case(self, signal: EscapeSignal) -> SynthesizedCase | None:
        """Parse an escape signal's body into a :class:`SynthesizedCase`.

        Returns ``None`` when the body lacks any required element
        (expected-catcher, keyword, before-block, after-block) or when
        the catcher names a skill the synthesizer does not support. The
        tick loop treats ``None`` as a "skip this signal" — never a
        crash.
        """
        body = signal.body or ""
        if not body.strip():
            return None

        catcher = _extract_header(body, "Expected-Catcher")
        if not catcher or catcher not in _SYNTHESIZABLE_CATCHERS:
            logger.debug(
                "corpus-learning: #%d — missing/unknown Expected-Catcher=%r",
                signal.issue_number,
                catcher,
            )
            return None

        keyword = _extract_header(body, "Keyword")
        if not keyword:
            logger.debug(
                "corpus-learning: #%d — missing Keyword header", signal.issue_number
            )
            return None

        before_files = _extract_fenced_files(body, "before")
        after_files = _extract_fenced_files(body, "after")
        if not before_files or not after_files:
            logger.debug(
                "corpus-learning: #%d — missing before/after fenced block(s)",
                signal.issue_number,
            )
            return None

        plan_blocks = _extract_fenced_blocks(body, "plan")
        plan_text = plan_blocks[0] if plan_blocks else ""

        # README prose = the body text *before* the first header or
        # fenced block. Keeps the human-written repro description
        # without the machine-parseable bits.
        readme = _extract_prose_preamble(body)

        slug = _slugify(signal.title)
        if not slug:
            # Fall back to a number-based slug so the case still has a
            # stable, filesystem-safe identifier even for titles that
            # slugify to empty (all punctuation, non-latin, etc.).
            slug = f"escape-{signal.issue_number}"

        return SynthesizedCase(
            issue_number=signal.issue_number,
            slug=slug,
            expected_catcher=catcher,
            keyword=keyword,
            before_files=before_files,
            after_files=after_files,
            readme=readme,
            plan_text=plan_text,
        )

    # ------------------------------------------------------------------
    # Task 13 — three-gate self-validation
    # ------------------------------------------------------------------

    def _validate_case(self, case: SynthesizedCase) -> ValidationResult:
        """Run the three self-validation gates against a :class:`SynthesizedCase`.

        Gates match the harness's preconditions + pass contract so that
        Task 15's disk materialization + harness run will agree with
        what this check already said in-memory.
        """
        # Gate (a): harness accepts it — same check as
        # test_adversarial_corpus.test_case's "before/after produced
        # empty diff" assertion.
        diff = _synthesize_diff(case.before_files, case.after_files)
        if not diff.strip():
            return ValidationResult(
                ok=False,
                reason="before/after produced empty diff",
                failing_gate="harness_accepts",
            )

        # Gate (b): expected catcher trips + keyword present in summary.
        expected_skill = _skill_by_name(case.expected_catcher)
        if expected_skill is None:
            # Should be unreachable — synthesis guards against unknown
            # catchers — but we keep the check so a registry rename
            # fails loud instead of silently auto-passing.
            return ValidationResult(
                ok=False,
                reason=f"unknown catcher {case.expected_catcher!r}",
                failing_gate="expected_catcher_trips",
            )

        transcript = self._fixture_transcript_for(case, case.expected_catcher)
        passed, summary, findings = expected_skill.result_parser(transcript)
        if passed:
            return ValidationResult(
                ok=False,
                reason=(
                    f"expected_catcher {case.expected_catcher!r} returned OK "
                    f"(summary={summary!r})"
                ),
                failing_gate="expected_catcher_trips",
            )
        haystack = (summary + "\n" + "\n".join(findings)).lower()
        if case.keyword.lower() not in haystack:
            return ValidationResult(
                ok=False,
                reason=(
                    f"expected_catcher {case.expected_catcher!r} returned RETRY "
                    f"but keyword {case.keyword!r} missing from summary/findings"
                ),
                failing_gate="expected_catcher_trips",
            )

        # Gate (c): shallow marker-collision check. For each other skill
        # we run its parser against the transcript that was built for the
        # EXPECTED catcher (above). If a foreign parser's own RETRY marker
        # happens to appear in that transcript text (e.g. the case's
        # keyword collides with another skill's lexicon), the foreign
        # parser returns ``passed=False`` and we flag the case as
        # ambiguous. This is intentionally a lexical collision check, not
        # a semantic equivalence — running each foreign parser against a
        # transcript tailored to IT would vacuously trip every parser
        # since _fixture_transcript_for writes each skill's marker
        # verbatim. See review finding #1 (commit 1d245c8f review).
        also_tripped: list[str] = []
        for skill in BUILTIN_SKILLS:
            if skill.name == case.expected_catcher:
                continue
            other_passed, _other_summary, _other_findings = skill.result_parser(
                transcript,
            )
            if not other_passed:
                also_tripped.append(skill.name)
        if also_tripped:
            return ValidationResult(
                ok=False,
                reason=(f"ambiguous — these catchers also tripped: {also_tripped!r}"),
                failing_gate="unambiguous",
            )

        return ValidationResult(ok=True)

    async def _record_validation_failure(
        self, signal: EscapeSignal, result: ValidationResult
    ) -> bool:
        """Increment the per-issue validation-failure counter.

        Spec §4.1 v2 step 5: 3 consecutive failures on the same escape
        issue → file ``hitl-escalation`` + ``corpus-learning-stuck``,
        record the rejection reason, move on. Returns ``True`` when an
        escalation issue was filed in this call.

        State is optional in tests — if ``self._state`` is ``None`` (a
        partial test fixture), the function logs and returns False
        without escalating. Production always wires state.
        """
        if self._state is None or not hasattr(
            self._state, "increment_corpus_validation_attempts"
        ):
            return False

        attempts = self._state.increment_corpus_validation_attempts(signal.issue_number)
        if attempts < _CORPUS_STUCK_ATTEMPTS:
            return False
        # Already at threshold — only file once. Beyond threshold the
        # counter will keep climbing and we never refile until the
        # operator closes the escalation (which clears via reconcile).
        if attempts > _CORPUS_STUCK_ATTEMPTS:
            return False

        title = (
            f"Corpus learning stuck on escape #{signal.issue_number}: "
            f"{signal.title or '(no title)'}"
        )
        body = (
            f"## Self-validation failed {attempts} times\n\n"
            f"`CorpusLearningLoop` could not validate a synthesized case "
            f"for escape issue #{signal.issue_number} after "
            f"{attempts} consecutive ticks. Latest rejection:\n\n"
            f"- Gate: `{result.failing_gate}`\n"
            f"- Reason: {result.reason}\n\n"
            f"The synthesizer is template-driven (parses structured "
            f"markdown from the escape body); a persistent failure means "
            f"the escape issue's `Expected-Catcher`, `Keyword`, or "
            f"before/after fenced blocks aren't producing a case the "
            f"validator accepts.\n\n"
            f"_Closing this issue clears the attempt counter (§3.2 "
            f"lifecycle); the loop will retry on the next tick._"
        )
        try:
            await self._prs.create_issue(
                title,
                body,
                [
                    self._config.hitl_escalation_label[0],
                    self._config.corpus_learning_stuck_label[0],
                ],
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "corpus-learning: failed to file `corpus-learning-stuck` "
                "escalation for #%d",
                signal.issue_number,
                exc_info=True,
            )
            return False
        return True

    def _fixture_transcript_for(self, case: SynthesizedCase, skill_name: str) -> str:
        """Build the deterministic RETRY transcript for ``skill_name``.

        Mirrors the convention the corpus uses for
        ``expected_transcript.txt`` fixtures (see e.g.
        ``cases/renamed-symbol-callsite/expected_transcript.txt``). The
        keyword must appear in ``SUMMARY`` so the harness's keyword
        check is satisfied alongside the result parser.

        Exposed as a method (not a module function) so tests can
        monkey-patch it to simulate LLM-shaped misbehavior (missing
        keyword, cross-catcher marker collisions, etc.).
        """
        marker = _CATCHER_MARKERS[skill_name]
        return (
            f"{marker}: RETRY\n"
            f"SUMMARY: {case.keyword} — synthesized fixture\n"
            f"FINDINGS:\n- {case.slug} — synthesized from escape #{case.issue_number}\n"
        )

    # ------------------------------------------------------------------
    # Task 15 — materialize + PR
    # ------------------------------------------------------------------

    def _materialize_case_on_disk(
        self, case: SynthesizedCase, repo_root: Path
    ) -> list[Path]:
        """Write a :class:`SynthesizedCase` out under ``tests/trust/adversarial/cases/<slug>/``.

        Layout mirrors the existing authored cases: every entry in
        ``case.before_files`` lands under ``before/<rel>`` and every
        entry in ``case.after_files`` lands under ``after/<rel>``; the
        expected catcher name lives in ``expected_catcher.txt`` and the
        human-readable repro description lives in ``README.md``.

        The keyword convention — the harness reads ``_read_keyword``
        from README.md — is preserved by prepending a ``Keyword:`` line
        so the harness's ``_read_keyword`` helper finds it there.

        Returns the list of absolute paths actually written so the
        caller can pass them straight to
        :func:`auto_pr.open_automated_pr_async` without a second
        `os.walk`.
        """
        case_dir = repo_root / _CASES_ROOT / case.slug
        written: list[Path] = []

        for rel_path, content in case.before_files.items():
            target = case_dir / "before" / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(target)

        for rel_path, content in case.after_files.items():
            target = case_dir / "after" / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content)
            written.append(target)

        catcher_path = case_dir / "expected_catcher.txt"
        catcher_path.parent.mkdir(parents=True, exist_ok=True)
        catcher_path.write_text(case.expected_catcher + "\n")
        written.append(catcher_path)

        readme_lines = [
            f"# {case.slug}",
            "",
            f"Keyword: {case.keyword}",
            "",
            f"Expected-Catcher: {case.expected_catcher}",
            "",
            f"Synthesized from escape issue #{case.issue_number}.",
            "",
        ]
        if case.readme:
            readme_lines.append(case.readme)
            readme_lines.append("")
        if case.plan_text:
            readme_lines.extend(["## Plan", "", case.plan_text, ""])
        readme_path = case_dir / "README.md"
        readme_path.write_text("\n".join(readme_lines))
        written.append(readme_path)

        return written

    async def _open_pr_for_case(
        self,
        case: SynthesizedCase,
        paths: list[Path],
        *,
        title: str,
        body: str,
    ) -> int | None:
        """File a PR for ``case`` via :func:`auto_pr.open_automated_pr_async`.

        Returns the parsed PR number on success, or ``None`` when the
        case has already been filed (dedup hit) or
        ``open_automated_pr_async`` reported a non-``opened`` status.
        The dedup key is ``corpus_learning:<issue_number>:<slug>`` —
        encoded with both components so that a retitled issue (new
        slug) and a re-filing of the original escape (same slug) are
        handled distinctly.

        Only records the dedup entry on a successful filing; a transient
        ``gh``/``git`` failure leaves the set untouched so the next tick
        retries instead of silently dropping the case.
        """
        dedup_key = f"corpus_learning:{case.issue_number}:{case.slug}"
        if dedup_key in self._dedup.get():
            logger.info(
                "corpus-learning: skipping already-filed case %s (#%d)",
                case.slug,
                case.issue_number,
            )
            return None

        branch = f"hydraflow/corpus-learning/issue-{case.issue_number}-{case.slug}"
        # T2 (audit pass-5): emit a fleet trace for the PR-open
        # subprocess fan-out (auto_pr shells out gh + git multiple times).
        # Spec §4.11 mandates emit_loop_subprocess_trace on every
        # subprocess invocation across all 10 trust loops.
        t0 = time.perf_counter()
        result = await open_automated_pr_async(
            repo_root=self._config.repo_root,
            branch=branch,
            files=paths,
            pr_title=title,
            pr_body=body,
            base=self._config.base_branch(),
            # Spec §4.1 v2: "Rationale for auto-merge: a new corpus
            # case is a new test, not a production-code change. The
            # self-validation gate proves the case actually catches
            # what it claims to catch; `make quality` enforces the
            # usual quality bar. Holding these PRs for human review
            # contradicts §3.2." Auto-merge through the standard gate.
            auto_merge=True,
            labels=list(_CASE_PR_LABELS),
            gh_token="",
            raise_on_failure=False,
            commit_author_name=self._config.git_user_name,
            commit_author_email=self._config.git_user_email,
        )
        self._emit_pr_trace(t0, branch, getattr(result, "status", None))

        if getattr(result, "status", None) != "opened":
            logger.warning(
                "corpus-learning: PR open failed for #%d (%s): status=%r error=%r",
                case.issue_number,
                case.slug,
                getattr(result, "status", None),
                getattr(result, "error", None),
            )
            return None

        self._dedup.add(dedup_key)
        return _parse_pr_number(getattr(result, "pr_url", None)) or case.issue_number

    def _emit_pr_trace(self, t0: float, branch: str, status: str | None) -> None:
        """Spec §4.11: emit a fleet trace per subprocess invocation.

        ``open_automated_pr_async`` shells out to ``git`` and ``gh``
        multiple times under the hood; we record one synthetic trace
        per logical PR-open call so deploy-time observability surfaces
        slow/broken PR opens without cracking open the loop.
        """
        try:
            from trace_collector import (  # noqa: PLC0415
                emit_loop_subprocess_trace,
            )
        except ImportError:
            return
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["auto_pr.open_automated_pr_async", branch],
            exit_code=0 if status == "opened" else 1,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            stderr_excerpt=f"status={status}" if status else None,
        )

    async def _reconcile_closed_corpus_escalations(self) -> None:
        """Clear `corpus_learning_validation_attempts` for every closed
        ``corpus-learning-stuck`` issue.

        Spec §3.2 lifecycle: an operator closing the escalation issue
        must clear the per-issue counter so the loop will retry on the
        next tick. Best-effort — gh-list failures or parse errors log
        and return; reconciliation is bounded by the loop interval.
        """
        if self._state is None or not hasattr(
            self._state, "reset_corpus_validation_attempts"
        ):
            return
        try:
            proc = await asyncio.create_subprocess_exec(
                "gh",
                "issue",
                "list",
                "--repo",
                self._config.repo,
                "--state",
                "closed",
                "--label",
                self._config.corpus_learning_stuck_label[0],
                "--json",
                "title",
                "--limit",
                "100",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, _ = await proc.communicate()
            if proc.returncode != 0:
                return
            issues = json.loads(out or b"[]")
        except Exception:  # noqa: BLE001
            logger.debug("corpus-learning reconcile: skipped", exc_info=True)
            return
        for issue in issues:
            title = str(issue.get("title", ""))
            m = _STUCK_TITLE_RE.match(title)
            if m is None:
                continue
            try:
                issue_number = int(m.group("num"))
            except ValueError:
                continue
            self._state.reset_corpus_validation_attempts(issue_number)

    # ------------------------------------------------------------------
    # Task 14+15 — tick
    # ------------------------------------------------------------------

    async def _do_work(self) -> WorkCycleResult:
        """Tick the loop.

        When the kill-switch is off, short-circuits with
        ``{"status": "disabled"}``. Otherwise fetches escape signals,
        synthesizes + validates each, then materializes survivors to
        disk and files one PR per validated case. Returns a status dict
        with ``escape_issues_seen``, ``cases_synthesized``,
        ``cases_validated``, and ``cases_filed``.
        """
        if not self._enabled_cb(self._worker_name):
            return {"status": "disabled"}

        # Reconcile closed `corpus-learning-stuck` escalations so the
        # operator's "close issue → clear counter" lifecycle (spec §3.2)
        # actually works. Best-effort; errors don't block the tick.
        await self._reconcile_closed_corpus_escalations()

        # Tolerate PR-query failures — a broken ``gh`` in the env must
        # not propagate as an AuthenticationError that pauses the whole
        # orchestrator. Next tick retries.
        # Spec §4.1: the loop reads ALL escape-signal label families
        # (skill-escape, discover-escape, shape-escape by default) so
        # product-phase escapes from §4.10 feed the same synthesis
        # pipeline as post-impl skill escapes.
        labels = (
            getattr(self._config, "corpus_learning_signal_labels", None)
            or DEFAULT_ESCAPE_SIGNAL_LABELS
        )
        signals: list[EscapeSignal] = []
        try:
            seen_issues: set[int] = set()
            for label in labels:
                for sig in await self._list_escape_signals(label=label):
                    if sig.issue_number in seen_issues:
                        continue
                    seen_issues.add(sig.issue_number)
                    signals.append(sig)
        except Exception:  # noqa: BLE001
            logger.warning(
                "corpus-learning: escape-signal query failed — skipping tick",
                exc_info=True,
            )
            return {
                "status": "skipped",
                "escape_issues_seen": 0,
                "cases_synthesized": 0,
                "cases_validated": 0,
                "cases_filed": 0,
            }
        if signals:
            logger.info(
                "corpus-learning: %d escape signal(s) within %d-day window",
                len(signals),
                DEFAULT_LOOKBACK_DAYS,
            )

        cases_synthesized = 0
        cases_validated = 0
        cases_filed = 0
        cases_escalated = 0
        validated_cases: list[SynthesizedCase] = []
        for signal in signals:
            case = self._synthesize_case(signal)
            if case is None:
                continue
            cases_synthesized += 1
            result = self._validate_case(case)
            if result.ok:
                cases_validated += 1
                validated_cases.append(case)
                # Reset the per-issue counter on a successful validation
                # so a future regression on the same escape can re-escalate.
                if self._state is not None and hasattr(
                    self._state, "reset_corpus_validation_attempts"
                ):
                    self._state.reset_corpus_validation_attempts(signal.issue_number)
            else:
                # Spec §4.1 v2 step 5: 3× validation failures on the same
                # escape issue → file `hitl-escalation` + `corpus-learning-stuck`,
                # naming the rejection reason. Counter clears on issue close.
                escalated = await self._record_validation_failure(signal, result)
                if escalated:
                    cases_escalated += 1
                logger.info(
                    "corpus-learning: #%d validation rejected at gate %s: %s",
                    signal.issue_number,
                    result.failing_gate,
                    result.reason,
                )

        repo_root = Path(self._config.repo_root)
        # Per-tick cap. Spec §3.2: a misbehaving loop must not flood
        # the issue queue. The dedup is keyed on (issue_number, slug),
        # so a burst of escape issues with churning slugs (e.g. retitled
        # between ticks) bypasses dedup. The trust-fleet-sanity loop's
        # `issues_per_hour` detector is post-hoc — by the time it fires,
        # the burst has already happened. This cap bounds blast radius
        # to a known multiple before any anomaly detector runs.
        max_per_tick = self._config.corpus_learning_max_prs_per_tick
        truncated = False
        for case in validated_cases:
            if cases_filed >= max_per_tick:
                truncated = True
                break
            paths = self._materialize_case_on_disk(case, repo_root)
            title = f"test(trust): corpus-learning case for escape #{case.issue_number}"
            body = _build_pr_body(case)
            pr_number = await self._open_pr_for_case(
                case, paths, title=title, body=body
            )
            if pr_number is not None:
                cases_filed += 1
        if truncated:
            logger.warning(
                "corpus-learning: per-tick cap %d hit — %d validated cases "
                "deferred until next tick",
                max_per_tick,
                len(validated_cases) - cases_filed,
            )

        return {
            "status": "noop",
            "escape_issues_seen": len(signals),
            "cases_synthesized": cases_synthesized,
            "cases_validated": cases_validated,
            "cases_filed": cases_filed,
        }


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _parse_iso_timestamp(value: str) -> datetime | None:
    """Parse a GitHub-style ISO-8601 timestamp, returning ``None`` on failure.

    GitHub returns ``updated_at`` as e.g. ``"2026-04-22T14:05:00Z"``.
    :meth:`datetime.fromisoformat` accepts ``+00:00`` natively but only
    accepts the trailing ``Z`` since Python 3.11 — we normalize it
    explicitly so the intent is obvious and the parser never surprises
    a reader hunting a ``ValueError``.
    """
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


_HEADER_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _extract_header(body: str, header: str) -> str:
    """Return the value of a ``Header: value`` line, or ``""`` if absent.

    Matches case-insensitively at the start of a line. Leading/trailing
    whitespace is stripped. An empty value (``"Header:"``) counts as
    absent.
    """
    pattern = _HEADER_RE_CACHE.get(header)
    if pattern is None:
        pattern = re.compile(
            rf"^\s*{re.escape(header)}\s*:\s*(.*?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
        _HEADER_RE_CACHE[header] = pattern
    match = pattern.search(body)
    if not match:
        return ""
    return match.group(1).strip()


# Fenced block: ```<tag>[:<suffix>]\n<body>\n```
# We use a non-greedy body match and anchor the closing fence at the
# start of a line so nested backticks inside the body don't confuse us.
_FENCED_RE = re.compile(
    r"```(?P<tag>[A-Za-z0-9_-]+)(?::(?P<suffix>[^\n`]+))?\n"
    r"(?P<body>.*?)\n```",
    re.DOTALL,
)


def _extract_fenced_files(body: str, tag: str) -> dict[str, str]:
    """Return ``{path: content}`` for every ``\\`\\`\\`<tag>:<path>`` block."""
    out: dict[str, str] = {}
    for match in _FENCED_RE.finditer(body):
        if match.group("tag").lower() != tag.lower():
            continue
        suffix = (match.group("suffix") or "").strip()
        if not suffix:
            continue
        # Ensure file content ends with a trailing newline so synthetic
        # diffs line up with how authored case files are written.
        content = match.group("body")
        if not content.endswith("\n"):
            content += "\n"
        out[suffix] = content
    return out


def _extract_fenced_blocks(body: str, tag: str) -> list[str]:
    """Return the bodies of every ``\\`\\`\\`<tag>`` block (no suffix required)."""
    out: list[str] = []
    for match in _FENCED_RE.finditer(body):
        if match.group("tag").lower() != tag.lower():
            continue
        out.append(match.group("body"))
    return out


def _extract_prose_preamble(body: str) -> str:
    """Return the body text before the first structured element.

    Structured elements are either a ``Header: ...`` line or a fenced
    code block. Empty preamble returns ``""``.
    """
    lines = body.splitlines()
    preamble: list[str] = []
    header_re = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_-]*\s*:\s*\S")
    for line in lines:
        if line.lstrip().startswith("```"):
            break
        if header_re.match(line):
            break
        preamble.append(line)
    return "\n".join(preamble).strip()


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def _slugify(text: str) -> str:
    """Return a filesystem-safe kebab slug capped at :data:`_SLUG_MAX_LEN`."""
    lower = text.lower()
    collapsed = _SLUG_STRIP_RE.sub("-", lower).strip("-")
    if len(collapsed) > _SLUG_MAX_LEN:
        collapsed = collapsed[:_SLUG_MAX_LEN].rstrip("-")
    return collapsed


def _synthesize_diff(before: dict[str, str], after: dict[str, str]) -> str:
    """Build a unified diff from before/after file maps.

    Mirrors :func:`tests.trust.adversarial.test_adversarial_corpus._synthesize_diff`
    so validation's gate (a) is byte-equivalent to what the live harness
    would see after Task 15 materializes the case.
    """
    chunks: list[str] = []
    for rel in sorted(set(before) | set(after)):
        b = before.get(rel, "")
        a = after.get(rel, "")
        if b == a:
            continue
        diff = difflib.unified_diff(
            b.splitlines(keepends=True),
            a.splitlines(keepends=True),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
        )
        chunks.append(f"diff --git a/{rel} b/{rel}\n")
        chunks.extend(diff)
    return "".join(chunks)


def _skill_by_name(name: str) -> AgentSkill | None:
    for skill in BUILTIN_SKILLS:
        if skill.name == name:
            return skill
    return None


_PR_URL_TAIL_RE = re.compile(r"/pull/(?P<num>\d+)")


def _parse_pr_number(pr_url: str | None) -> int | None:
    """Extract the PR number from a ``gh pr create`` URL, or ``None``.

    ``gh`` prints URLs like ``https://github.com/org/repo/pull/123``.
    We also accept the shorter ``org/repo/pull/123`` form test stubs
    sometimes emit, which the regex handles uniformly.
    """
    if not pr_url:
        return None
    match = _PR_URL_TAIL_RE.search(pr_url)
    if match is None:
        return None
    try:
        return int(match.group("num"))
    except ValueError:
        return None


def _build_pr_body(case: SynthesizedCase) -> str:
    """Compose the PR body for a synthesized corpus case."""
    lines = [
        f"Synthesized adversarial corpus case for escape issue #{case.issue_number}.",
        "",
        f"**Catcher:** `{case.expected_catcher}`",
        f"**Keyword:** `{case.keyword}`",
        "",
    ]
    if case.readme:
        lines.extend(["## Reasoning", "", case.readme, ""])
    lines.append(f"Closes #{case.issue_number}")
    return "\n".join(lines)
