"""Factories for synthetic Fake payloads.

Lives in src/ so the Fakes (which are in src/mockworld/fakes/) can import
without a src→tests dependency. Re-exported by tests/conftest.py for
back-compat — tests can keep importing the original names from
``tests.conftest`` while production-side fakes (loaded from ``src/`` only,
e.g. inside PR B's docker container that does NOT COPY tests/) resolve
the same factories from this module.

Why these five?

- ``PRInfoFactory`` — used by ``FakeGitHub`` to mint ``PRInfo`` rows when
  scenario seeds open or merge a PR.
- ``PlanResultFactory`` / ``ReviewResultFactory`` / ``TriageResultFactory``
  / ``WorkerResultFactory`` — used by ``FakeLLM`` to script per-phase,
  per-issue runner outputs.

The companion ``Builder`` classes and other Result/Event factories
(``HITLResultFactory``, ``EventFactory``, ``AnalysisResultFactory``, …)
remain in ``tests/conftest.py``: they aren't referenced from any Fake.

If a future Fake needs another Factory, move it here too rather than
re-introducing the ``src→tests`` import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import (
        NewIssueSpec,
        PRInfo,
        ReviewResult,
        ReviewVerdict,
        TriageResult,
    )


class WorkerResultFactory:
    """Factory for WorkerResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        branch: str = "agent/issue-42",
        success: bool | None = None,
        transcript: str | None = None,
        commits: int | None = None,
        workspace_path: str | None = None,
        error: str | None = None,
        duration_seconds: float | None = None,
        pre_quality_review_attempts: int | None = None,
        quality_fix_attempts: int | None = None,
        pr_info: PRInfo | None = None,
        use_defaults: bool = False,
    ):
        """Create a WorkerResult instance.

        By default (``use_defaults=False``), factory-defined hardcoded values are
        applied for all unspecified optional fields (e.g. ``success=True``,
        ``transcript="Implemented the feature."``).

        With ``use_defaults=True``, only explicitly provided keyword arguments are
        forwarded to the constructor and the underlying Pydantic model's own field
        defaults are used for everything else.  Prefer this mode when you need a
        minimal/sparse object to test model-level behaviour or when factory defaults
        would incorrectly satisfy a field under test.
        """
        from models import WorkerResult

        if use_defaults:
            kwargs: dict[str, Any] = {
                "issue_number": issue_number,
                "branch": branch,
            }
            if workspace_path is not None:
                kwargs["workspace_path"] = workspace_path
            if success is not None:
                kwargs["success"] = success
            if error is not None:
                kwargs["error"] = error
            if transcript is not None:
                kwargs["transcript"] = transcript
            if commits is not None:
                kwargs["commits"] = commits
            if duration_seconds is not None:
                kwargs["duration_seconds"] = duration_seconds
            if pre_quality_review_attempts is not None:
                kwargs["pre_quality_review_attempts"] = pre_quality_review_attempts
            if quality_fix_attempts is not None:
                kwargs["quality_fix_attempts"] = quality_fix_attempts
            if pr_info is not None:
                kwargs["pr_info"] = pr_info
            return WorkerResult(**kwargs)

        return WorkerResult(
            issue_number=issue_number,
            branch=branch,
            workspace_path=(
                workspace_path
                if workspace_path is not None
                # Synthetic test workspace path; never used as a real
                # filesystem location — WorkerResult is a pydantic data
                # carrier and downstream code only reads ``workspace_path``
                # for logging/identification.
                else "/tmp/worktrees/issue-42"  # nosec B108
            ),
            success=True if success is None else success,
            error=error,
            transcript=(
                transcript if transcript is not None else "Implemented the feature."
            ),
            commits=commits if commits is not None else 1,
            duration_seconds=(
                duration_seconds if duration_seconds is not None else 0.0
            ),
            pre_quality_review_attempts=(
                pre_quality_review_attempts
                if pre_quality_review_attempts is not None
                else 0
            ),
            quality_fix_attempts=(
                quality_fix_attempts if quality_fix_attempts is not None else 0
            ),
            pr_info=pr_info,
        )


class PlanResultFactory:
    """Factory for PlanResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        success: bool | None = None,
        plan: str | None = None,
        summary: str | None = None,
        error: str | None = None,
        transcript: str | None = None,
        duration_seconds: float | None = None,
        new_issues: list[NewIssueSpec] | None = None,
        validation_errors: list[str] | None = None,
        retry_attempted: bool | None = None,
        already_satisfied: bool | None = None,
        actionability_score: int | None = None,
        actionability_rank: str | None = None,
        epic_number: int | None = None,
        use_defaults: bool = False,
    ):
        """Create a PlanResult instance.

        By default (``use_defaults=False``), factory-defined hardcoded values are
        applied for all unspecified optional fields (e.g. ``success=True``,
        ``plan="## Plan\\n\\n1. Do the thing\\n2. Test the thing"``).

        With ``use_defaults=True``, only explicitly provided keyword arguments are
        forwarded to the constructor and the underlying Pydantic model's own field
        defaults are used for everything else.  Prefer this mode when you need a
        minimal/sparse object to test model-level behaviour or when factory defaults
        would incorrectly satisfy a field under test.
        """
        from models import PlanResult

        if use_defaults:
            kwargs: dict[str, Any] = {"issue_number": issue_number}
            if success is not None:
                kwargs["success"] = success
            if plan is not None:
                kwargs["plan"] = plan
            if summary is not None:
                kwargs["summary"] = summary
            if error is not None:
                kwargs["error"] = error
            if transcript is not None:
                kwargs["transcript"] = transcript
            if duration_seconds is not None:
                kwargs["duration_seconds"] = duration_seconds
            if new_issues is not None:
                kwargs["new_issues"] = list(new_issues)
            if validation_errors is not None:
                kwargs["validation_errors"] = list(validation_errors)
            if retry_attempted is not None:
                kwargs["retry_attempted"] = retry_attempted
            if already_satisfied is not None:
                kwargs["already_satisfied"] = already_satisfied
            if actionability_score is not None:
                kwargs["actionability_score"] = actionability_score
            if actionability_rank is not None:
                kwargs["actionability_rank"] = actionability_rank
            if epic_number is not None:
                kwargs["epic_number"] = epic_number
            return PlanResult(**kwargs)

        success_value = True if success is None else success
        plan_value = (
            plan
            if plan is not None
            else "## Plan\n\n1. Do the thing\n2. Test the thing"
        )
        summary_value = (
            summary if summary is not None else "Plan to implement the feature"
        )
        transcript_value = (
            transcript
            if transcript is not None
            else "PLAN_START\n## Plan\n\n1. Do the thing\nPLAN_END\nSUMMARY: Plan to implement the feature"
        )
        duration_value = duration_seconds if duration_seconds is not None else 10.0
        retry_value = False if retry_attempted is None else retry_attempted
        already_satisfied_value = (
            False if already_satisfied is None else already_satisfied
        )
        actionability_score_value = (
            actionability_score if actionability_score is not None else 0
        )
        actionability_rank_value = (
            actionability_rank if actionability_rank is not None else "unknown"
        )
        epic_number_value = epic_number if epic_number is not None else 0

        return PlanResult(
            issue_number=issue_number,
            success=success_value,
            plan=plan_value,
            summary=summary_value,
            error=error,
            transcript=transcript_value,
            duration_seconds=duration_value,
            new_issues=list(new_issues) if new_issues is not None else [],
            validation_errors=list(validation_errors)
            if validation_errors is not None
            else [],
            retry_attempted=retry_value,
            already_satisfied=already_satisfied_value,
            actionability_score=actionability_score_value,
            actionability_rank=actionability_rank_value,
            epic_number=epic_number_value,
        )


class PRInfoFactory:
    """Factory for PRInfo instances."""

    @staticmethod
    def create(
        *,
        number: int = 101,
        issue_number: int = 42,
        branch: str = "agent/issue-42",
        url: str = "https://github.com/test-org/test-repo/pull/101",
        draft: bool = False,
    ):
        from models import PRInfo

        return PRInfo(
            number=number,
            issue_number=issue_number,
            branch=branch,
            url=url,
            draft=draft,
        )


class ReviewResultFactory:
    """Factory for ReviewResult instances."""

    @staticmethod
    def create(
        *,
        pr_number: int = 101,
        issue_number: int = 42,
        verdict: ReviewVerdict | None = None,
        success: bool | None = None,
        summary: str | None = None,
        fixes_made: bool | None = None,
        commit_stat: str | None = None,
        transcript: str | None = None,
        merged: bool | None = None,
        duration_seconds: float | None = None,
        ci_passed: bool | None = None,
        ci_fix_attempts: int | None = None,
        error: str | None = None,
        visual_passed: bool | None = None,
        files_changed: list[str] | None = None,
        use_defaults: bool = False,
    ) -> ReviewResult:
        """Create a ReviewResult instance.

        By default (``use_defaults=False``), factory-defined hardcoded values are
        applied for all unspecified optional fields (e.g. ``verdict=APPROVE``,
        ``summary="Looks good."``).

        With ``use_defaults=True``, only explicitly provided keyword arguments are
        forwarded to the constructor and the underlying Pydantic model's own field
        defaults are used for everything else.
        """
        from models import ReviewResult as RR
        from models import ReviewVerdict as RV

        if use_defaults:
            kwargs: dict[str, Any] = {
                "pr_number": pr_number,
                "issue_number": issue_number,
            }
            if verdict is not None:
                kwargs["verdict"] = verdict
            if success is not None:
                kwargs["success"] = success
            if summary is not None:
                kwargs["summary"] = summary
            if fixes_made is not None:
                kwargs["fixes_made"] = fixes_made
            if commit_stat is not None:
                kwargs["commit_stat"] = commit_stat
            if transcript is not None:
                kwargs["transcript"] = transcript
            if merged is not None:
                kwargs["merged"] = merged
            if duration_seconds is not None:
                kwargs["duration_seconds"] = duration_seconds
            if ci_passed is not None:
                kwargs["ci_passed"] = ci_passed
            if ci_fix_attempts is not None:
                kwargs["ci_fix_attempts"] = ci_fix_attempts
            if error is not None:
                kwargs["error"] = error
            if visual_passed is not None:
                kwargs["visual_passed"] = visual_passed
            if files_changed is not None:
                kwargs["files_changed"] = files_changed
            return RR(**kwargs)

        return RR(
            pr_number=pr_number,
            issue_number=issue_number,
            verdict=verdict if verdict is not None else RV.APPROVE,
            success=success if success is not None else False,
            summary=summary if summary is not None else "Looks good.",
            error=error,
            fixes_made=fixes_made if fixes_made is not None else False,
            commit_stat=commit_stat if commit_stat is not None else "",
            transcript=(
                transcript if transcript is not None else "THOROUGH_REVIEW_COMPLETE"
            ),
            merged=merged if merged is not None else False,
            duration_seconds=(
                duration_seconds if duration_seconds is not None else 0.0
            ),
            ci_passed=ci_passed,
            ci_fix_attempts=(ci_fix_attempts if ci_fix_attempts is not None else 0),
            visual_passed=visual_passed,
            files_changed=files_changed if files_changed is not None else [],
        )


class TriageResultFactory:
    """Factory for TriageResult instances."""

    @staticmethod
    def create(
        *,
        issue_number: int = 42,
        ready: bool = True,
        reasons: list[str] | None = None,
        complexity_score: int = 0,
        issue_type: str = "feature",
        enrichment: str = "",
        clarity_score: int = 10,
        needs_discovery: bool = False,
    ) -> TriageResult:
        from models import IssueType
        from models import TriageResult as TR

        return TR(
            issue_number=issue_number,
            ready=ready,
            reasons=reasons if reasons is not None else [],
            complexity_score=complexity_score,
            issue_type=IssueType(issue_type)
            if isinstance(issue_type, str)
            else issue_type,
            enrichment=enrichment,
            clarity_score=clarity_score,
            needs_discovery=needs_discovery,
        )


__all__ = [
    "PRInfoFactory",
    "PlanResultFactory",
    "ReviewResultFactory",
    "TriageResultFactory",
    "WorkerResultFactory",
]
