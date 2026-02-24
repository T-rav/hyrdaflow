"""Event correlation and aggregation into per-issue lifecycle timelines."""

from __future__ import annotations

from datetime import datetime

from events import EventBus, EventType, HydraFlowEvent
from models import IssueTimeline, PipelineStage, PRInfoExtract, StageStatus, TimelineStage

STAGE_ORDER: list[PipelineStage] = [
    PipelineStage.TRIAGE,
    PipelineStage.PLAN,
    PipelineStage.IMPLEMENT,
    PipelineStage.REVIEW,
    PipelineStage.MERGE,
]

# Map EventType to pipeline stage
EVENT_TYPE_TO_STAGE: dict[EventType, PipelineStage] = {
    EventType.TRIAGE_UPDATE: PipelineStage.TRIAGE,
    EventType.PLANNER_UPDATE: PipelineStage.PLAN,
    EventType.WORKER_UPDATE: PipelineStage.IMPLEMENT,
    EventType.PR_CREATED: PipelineStage.IMPLEMENT,
    EventType.HITL_UPDATE: PipelineStage.IMPLEMENT,
    EventType.REVIEW_UPDATE: PipelineStage.REVIEW,
    EventType.CI_CHECK: PipelineStage.REVIEW,
    EventType.HITL_ESCALATION: PipelineStage.REVIEW,
    EventType.MERGE_UPDATE: PipelineStage.MERGE,
}

# Map TRANSCRIPT_LINE source field to stage
SOURCE_TO_STAGE: dict[str, PipelineStage] = {
    "triage": PipelineStage.TRIAGE,
    "planner": PipelineStage.PLAN,
    "reviewer": PipelineStage.REVIEW,
    "hitl": PipelineStage.IMPLEMENT,
}

# Statuses that indicate a stage is terminal
TERMINAL_STATUSES = {"done", "merged", "passed", "failed"}

# Statuses that map to "done"
DONE_STATUSES = {"done", "merged", "passed"}


class TimelineBuilder:
    """Builds structured lifecycle timelines from flat EventBus history."""

    def __init__(self, event_bus: EventBus, max_transcript_lines: int = 5) -> None:
        self._bus = event_bus
        self._max_transcript_lines = max_transcript_lines

    def build_all(self) -> list[IssueTimeline]:
        events = self._bus.get_history()
        grouped = self._group_events_by_issue(events)
        timelines = [
            self._build_timeline(issue_num, evts)
            for issue_num, evts in sorted(grouped.items())
        ]
        return timelines

    def build_for_issue(self, issue_number: int) -> IssueTimeline | None:
        events = self._bus.get_history()
        grouped = self._group_events_by_issue(events)
        if issue_number not in grouped:
            return None
        return self._build_timeline(issue_number, grouped[issue_number])

    def _group_events_by_issue(
        self, events: list[HydraFlowEvent]
    ) -> dict[int, list[HydraFlowEvent]]:
        # First pass: build pr_to_issue map from PR_CREATED events
        pr_to_issue: dict[int, int] = {}
        for event in events:
            if event.type == EventType.PR_CREATED:
                pr_num = event.data.get("pr")
                issue_num = event.data.get("issue")
                if isinstance(pr_num, int) and isinstance(issue_num, int):
                    pr_to_issue[pr_num] = issue_num

        # Second pass: group events by issue number
        grouped: dict[int, list[HydraFlowEvent]] = {}
        for event in events:
            issue_num = self._extract_issue_number(event, pr_to_issue)
            if issue_num is None:
                continue
            grouped.setdefault(issue_num, []).append(event)
        return grouped

    def _extract_issue_number(
        self, event: HydraFlowEvent, pr_to_issue: dict[int, int]
    ) -> int | None:
        data = event.data
        # Direct issue field
        issue = data.get("issue")
        if isinstance(issue, int):
            return issue
        # ISSUE_CREATED uses "number"
        number = data.get("number")
        if isinstance(number, int):
            return number
        # Correlate via PR number
        pr = data.get("pr")
        if isinstance(pr, int) and pr in pr_to_issue:
            return pr_to_issue[pr]
        return None

    def _build_timeline(
        self, issue_number: int, events: list[HydraFlowEvent]
    ) -> IssueTimeline:
        # Partition events by stage
        stage_events: dict[PipelineStage, list[HydraFlowEvent]] = {
            s: [] for s in STAGE_ORDER
        }

        for event in events:
            stage = self._event_to_stage(event)
            if stage and stage in stage_events:
                stage_events[stage].append(event)

        # Build stages (only include stages that have events)
        stages: list[TimelineStage] = []
        for stage_name in STAGE_ORDER:
            if stage_events[stage_name]:
                stages.append(self._build_stage(stage_name, stage_events[stage_name]))

        # Extract title and PR info
        title = self._extract_title(events)
        pr_number, pr_url, branch = self._extract_pr_info(events)

        # Determine current stage (last non-empty stage)
        current_stage: PipelineStage | str = ""
        if stages:
            current_stage = stages[-1].stage

        # Calculate total duration
        total_duration: float | None = None
        if stages and stages[0].started_at:
            try:
                first_start = datetime.fromisoformat(stages[0].started_at)
                # Use last stage's completed_at if available, else last stage's started_at
                last_stage = stages[-1]
                end_ts = last_stage.completed_at or last_stage.started_at
                if end_ts:
                    last_end = datetime.fromisoformat(end_ts)
                    total_duration = (last_end - first_start).total_seconds()
            except (ValueError, TypeError):
                pass

        return IssueTimeline(
            issue_number=issue_number,
            title=title,
            current_stage=current_stage,
            stages=stages,
            total_duration_seconds=total_duration,
            pr_number=pr_number,
            pr_url=pr_url,
            branch=branch,
        )

    def _event_to_stage(self, event: HydraFlowEvent) -> PipelineStage | None:
        if event.type == EventType.TRANSCRIPT_LINE:
            source = event.data.get("source", "")
            return SOURCE_TO_STAGE.get(source, PipelineStage.IMPLEMENT)
        return EVENT_TYPE_TO_STAGE.get(event.type)

    def _build_stage(
        self, stage_name: PipelineStage, events: list[HydraFlowEvent]
    ) -> TimelineStage:
        if not events:
            return TimelineStage(stage=stage_name, status=StageStatus.PENDING)

        started_at = events[0].timestamp
        completed_at: str | None = None
        status = StageStatus.IN_PROGRESS
        metadata: dict[str, object] = {}

        # Find terminal status and extract metadata
        for event in events:
            event_status = event.data.get("status", "")
            if isinstance(event_status, str) and event_status in TERMINAL_STATUSES:
                completed_at = event.timestamp
                if event_status in DONE_STATUSES:
                    status = StageStatus.DONE
                elif event_status == "failed":
                    status = StageStatus.FAILED

            # Extract useful metadata
            verdict = event.data.get("verdict")
            if verdict:
                metadata["verdict"] = verdict
            duration = event.data.get("duration")
            if duration is not None:
                metadata["duration"] = duration
            commits = event.data.get("commits")
            if commits is not None:
                metadata["commits"] = commits
            if event.type == EventType.HITL_ESCALATION:
                cause = event.data.get("cause")
                if cause:
                    metadata["hitl_cause"] = cause

        # Calculate duration
        duration_seconds: float | None = None
        if completed_at:
            try:
                start = datetime.fromisoformat(started_at)
                end = datetime.fromisoformat(completed_at)
                duration_seconds = (end - start).total_seconds()
            except (ValueError, TypeError):
                pass

        # Extract transcript preview
        transcript_preview = self._extract_transcript_preview(events)

        return TimelineStage(
            stage=stage_name,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=duration_seconds,
            transcript_preview=transcript_preview,
            metadata=metadata,
        )

    def _extract_transcript_preview(self, events: list[HydraFlowEvent]) -> list[str]:
        lines: list[str] = []
        for event in events:
            if event.type == EventType.TRANSCRIPT_LINE:
                line = event.data.get("line", "")
                if isinstance(line, str) and line:
                    lines.append(line)

        if not lines:
            return []

        max_lines = self._max_transcript_lines
        if len(lines) <= max_lines:
            return lines

        # Take first half and last half
        first_n = max_lines // 2
        last_n = max_lines - first_n
        return lines[:first_n] + lines[-last_n:]

    def _extract_title(self, events: list[HydraFlowEvent]) -> str:
        for event in events:
            title = event.data.get("title")
            if isinstance(title, str) and title:
                return title
        return ""

    def _extract_pr_info(self, events: list[HydraFlowEvent]) -> PRInfoExtract:
        for event in events:
            if event.type == EventType.PR_CREATED:
                pr_num = event.data.get("pr")
                pr_url = event.data.get("url", "")
                branch = event.data.get("branch", "")
                return PRInfoExtract(
                    pr_number=pr_num if isinstance(pr_num, int) else None,
                    url=str(pr_url),
                    branch=str(branch),
                )
        return PRInfoExtract(pr_number=None, url="", branch="")
