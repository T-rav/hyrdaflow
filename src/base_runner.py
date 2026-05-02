"""Base runner class — shared lifecycle for all agent runners."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from adr_draft_opener import open_adr_draft_issue
from adr_index import (  # noqa: F401 — used in _inject_adr_index
    ADRIndex,
    render_full,
    render_titles_only,
)
from agent_cli import build_agent_command
from config import Credentials, HydraFlowConfig
from events import EventBus
from execution import get_default_runner
from models import LoopResult, TranscriptEventData
from prompt_telemetry import PromptTelemetry, parse_command_tool_model
from runner_utils import (
    AuthenticationRetryError,
    StreamConfig,
    stream_claude_process,
    terminate_processes,
)
from tracing_context import TracingContext
from wiki_compiler import parse_adr_draft_suggestion

if TYPE_CHECKING:
    from execution import SubprocessRunner
    from repo_wiki import RepoWikiStore  # noqa: TCH004
    from tribal_wiki import TribalWikiStore


def _weave_temporal_tags(markdown: str, tags: dict[str, str]) -> str:
    """Insert temporal tags as italic lines after matching ``### <title>``
    headings in the rendered wiki markdown. No-op on empty tags or empty
    markdown so callers can pass through unconditionally.
    """
    if not tags or not markdown:
        return markdown
    out: list[str] = []
    for line in markdown.splitlines():
        out.append(line)
        if line.startswith("### "):
            title = line[4:].strip()
            if title in tags:
                out.append(f"*({tags[title]})*")
    return "\n".join(out)


class BaseRunner:
    """Shared base for ``AgentRunner``, ``PlannerRunner``, ``ReviewRunner``, and ``HITLRunner``.

    Provides the common ``__init__``, ``terminate``, ``_execute``,
    ``_save_transcript``, ``_inject_memory``, and
    ``_verify_quality`` implementations so each subclass only needs to
    implement its own prompt-building and run logic.
    """

    _log: ClassVar[logging.Logger]
    _phase_name: ClassVar[str] = "unknown"

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        runner: SubprocessRunner | None = None,
        *,
        credentials: Credentials | None = None,
        wiki_store: RepoWikiStore | None = None,
        tribal_wiki_store: TribalWikiStore | None = None,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._active_procs: set[asyncio.subprocess.Process] = set()
        self._runner = runner or get_default_runner()
        self._prompt_telemetry = PromptTelemetry(config)
        self._last_context_stats: dict[str, int] = {"cache_hits": 0, "cache_misses": 0}
        # Per-phase-run tracing state, set by phase coordinators before
        # invoking runner.run() and cleared after. None when tracing is
        # not active (e.g. dry-run, background loops).
        self._tracing_ctx: TracingContext | None = None
        # Monotonic counter that allocates a unique ``subprocess_idx`` for
        # every ``_execute`` call within a phase run. Reset whenever the
        # tracing context is set or cleared. Without this, skills,
        # pre-quality review loops, and quality fix loops would overwrite
        # each other's ``subprocess-N.json`` files.
        self._trace_subprocess_counter: int = 0
        self._credentials = credentials or Credentials()
        self._wiki_store = wiki_store
        self._tribal_wiki_store = tribal_wiki_store
        # ADR runtime index — injected into plan/implement/review prompts.
        # Relative path from the worktree cwd. None-safe at read time.
        self._adr_index: ADRIndex | None = ADRIndex(Path("docs/adr"))

    @property
    def active_count(self) -> int:
        """Number of currently running subprocesses."""
        return len(self._active_procs)

    @property
    def tracing_context(self) -> TracingContext | None:
        """Read-only access to the active tracing context."""
        return self._tracing_ctx

    def set_tracing_context(self, ctx: TracingContext) -> None:
        """Set the per-phase-run tracing context. Called by phase coordinators."""
        self._tracing_ctx = ctx
        self._trace_subprocess_counter = 0

    def clear_tracing_context(self) -> None:
        """Clear the tracing context. Called after the phase run completes."""
        self._tracing_ctx = None
        self._trace_subprocess_counter = 0

    def _allocate_trace_subprocess_idx(self) -> int:
        """Allocate the next unique subprocess index for this phase run."""
        idx = self._trace_subprocess_counter
        self._trace_subprocess_counter += 1
        return idx

    def terminate(self) -> None:
        """Kill all active subprocesses."""
        terminate_processes(self._active_procs)

    _AUTH_RETRY_MAX = 3
    _AUTH_RETRY_BASE_DELAY = 5.0  # seconds

    async def _execute(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Path,
        event_data: TranscriptEventData,
        *,
        on_output: Callable[[str], bool] | None = None,
        telemetry_stats: Mapping[str, object] | None = None,
    ) -> str:
        """Run a claude subprocess and stream its output.

        Retries up to ``_AUTH_RETRY_MAX`` times on transient authentication
        failures (OAuth token refresh blips) with exponential backoff.
        """
        start = time.monotonic()
        transcript = ""
        succeeded = False
        usage_stats: dict[str, object] = {}

        # Build trace collector from active context, if any.
        # Created ONCE for the entire _execute call (including all auth retries)
        # and finalized exactly once on either success or exception.
        trace_collector: TraceCollector | None = None
        ctx = self._tracing_ctx
        if ctx is not None:
            from trace_collector import TraceCollector  # noqa: PLC0415

            trace_collector = TraceCollector(
                issue_number=ctx.issue_number,
                phase=ctx.phase,
                source=ctx.source,
                subprocess_idx=self._allocate_trace_subprocess_idx(),
                run_id=ctx.run_id,
                config=self._config,
                event_bus=self._bus,
            )

        try:
            import sentry_sdk as _sentry  # noqa: PLC0415
        except ImportError:
            _sentry = None  # Sentry not installed — optional dependency
        if _sentry is not None:
            # Programming errors (AttributeError, TypeError, etc.) from the
            # Sentry SDK must propagate so misconfiguration surfaces loudly.
            _sentry.set_tag("hydraflow.issue", str(event_data.get("issue", "")))
            _sentry.set_tag("hydraflow.source", str(event_data.get("source", "")))
            _sentry.set_context(
                "hydraflow_runner",
                {
                    "model": self._config.model,
                    "tool": self._config.implementation_tool,
                },
            )

        try:
            last_auth_error: AuthenticationRetryError | None = None
            for attempt in range(1, self._AUTH_RETRY_MAX + 1):
                try:
                    transcript = await stream_claude_process(
                        cmd=cmd,
                        prompt=prompt,
                        cwd=cwd,
                        active_procs=self._active_procs,
                        event_bus=self._bus,
                        event_data=event_data,
                        logger=self._log,
                        config=StreamConfig(
                            on_output=on_output,
                            timeout=self._config.agent_timeout,
                            runner=self._runner,
                            usage_stats=usage_stats,
                            gh_token=self._credentials.gh_token,
                            trace_collector=trace_collector,
                        ),
                    )
                    succeeded = True
                    if trace_collector is not None:
                        trace_collector.finalize(success=True)
                    return transcript
                except AuthenticationRetryError as exc:
                    last_auth_error = exc
                    if attempt < self._AUTH_RETRY_MAX:
                        delay = self._AUTH_RETRY_BASE_DELAY * (2 ** (attempt - 1))
                        self._log.warning(
                            "Auth failed (attempt %d/%d), retrying in %.0fs: %s",
                            attempt,
                            self._AUTH_RETRY_MAX,
                            delay,
                            exc,
                        )
                        await asyncio.sleep(delay)
                    else:
                        self._log.error(
                            "Auth failed after %d attempts: %s",
                            self._AUTH_RETRY_MAX,
                            exc,
                        )
            if last_auth_error is None:
                # Retry loop never executed (``_AUTH_RETRY_MAX`` ≤ 0).
                # Surface this as a meaningful RuntimeError instead of
                # ``raise None`` → TypeError (#6598).
                msg = (
                    "BaseRunner._execute: auth retry loop never ran "
                    f"(_AUTH_RETRY_MAX={self._AUTH_RETRY_MAX})"
                )
                raise RuntimeError(msg)
            raise last_auth_error
        except Exception:
            if trace_collector is not None:
                trace_collector.finalize(success=False)
            raise
        finally:
            duration = time.monotonic() - start
            source = str(event_data.get("source", "unknown"))
            issue_number = event_data.get("issue")
            pr_number = event_data.get("pr")
            tool, model = parse_command_tool_model(cmd)
            merged_stats = {
                **self._consume_context_stats(),
                **usage_stats,
                **(telemetry_stats or {}),
            }
            self._prompt_telemetry.record(
                source=source,
                tool=tool,
                model=model,
                issue_number=issue_number,
                pr_number=pr_number,
                session_id=self._bus.current_session_id,
                prompt_chars=len(prompt),
                transcript_chars=len(transcript),
                duration_seconds=duration,
                success=succeeded,
                stats=merged_stats,
            )

    def _save_transcript(self, prefix: str, identifier: int, transcript: str) -> None:
        """Write a transcript to ``.hydraflow/logs/<prefix>-<identifier>.txt``."""
        log_dir = self._config.log_dir
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            path = log_dir / f"{prefix}-{identifier}.txt"
            path.write_text(transcript)
            self._log.info("Transcript saved to %s", path)
        except OSError:
            self._log.warning(
                "Could not save transcript to %s",
                log_dir,
                exc_info=True,
            )
        # Schedule ADR-draft processing if we're inside a running event loop.
        # Called from sync test contexts there is no loop — skip gracefully.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._log.debug(
                "_save_transcript called outside event loop — ADR-draft pipeline skipped"
            )
            return
        loop.create_task(self._process_transcript_for_adr_draft(transcript))

    async def _process_transcript_for_adr_draft(self, transcript: str) -> None:
        """Scan transcript for ADR_DRAFT_SUGGESTION and run the 4-gate pipeline.

        Non-blocking: failures are logged and swallowed. No-ops silently when
        any required dependency is missing.
        """
        compiler = getattr(self, "_wiki_compiler", None)
        tribal = self._tribal_wiki_store
        gh = getattr(self, "_gh_client", None)
        bus = self._bus
        if compiler is None or tribal is None or gh is None:
            return

        try:
            suggestion = parse_adr_draft_suggestion(transcript)
            if suggestion is None:
                return
            decision = await compiler.judge_adr_draft(
                suggestion=suggestion,
                tribal=tribal,
            )
            if not decision.draft_ok:
                return
            issue_number = await open_adr_draft_issue(
                suggestion=suggestion,
                decision=decision,
                gh_client=gh,
            )
            if issue_number is None or bus is None:
                return
            from events import EventType, HydraFlowEvent  # noqa: PLC0415

            await bus.publish(
                HydraFlowEvent(
                    type=EventType.ADR_DRAFT_OPENED,
                    data={
                        "issue_number": issue_number,
                        "title": suggestion.get("title", ""),
                        "reason": decision.reason,
                    },
                )
            )
        except Exception:  # noqa: BLE001
            self._log.warning(
                "ADR draft pipeline failed — transcript ignored",
                exc_info=True,
            )

    async def _inject_memory(self, *, query_context: str = "") -> str:
        """Build the context section from wiki and ADR index.

        Returns the context section as a string, or an empty string when
        neither wiki nor ADR index is configured.
        """
        memory_section = ""

        # Append repo wiki context (Karpathy-style compiled knowledge)
        wiki_section = self._inject_repo_wiki(query_context=query_context)
        if wiki_section:
            memory_section += wiki_section

        # Append ADR index (load-bearing architectural decisions)
        adr_section = self._inject_adr_index()
        if adr_section:
            memory_section += adr_section

        self._last_context_stats = {
            "cache_hits": 0,
            "cache_misses": 0,
            "context_chars_before": 0,
            "context_chars_after": len(memory_section),
            "adr_chars": len(adr_section),
            "dedup_items_removed": 0,
            "dedup_chars_saved": 0,
        }

        return memory_section

    def _inject_repo_wiki(self, *, query_context: str = "") -> str:
        """Load compiled repo wiki + tribal wiki context for the current target repo.

        Returns concatenated markdown with a blank-line separator. Empty
        string when neither per-repo wiki nor tribal wiki is configured
        or both return empty.
        """
        if self._wiki_store is None:
            return ""
        repo = self._config.repo
        if not repo:
            return ""

        keywords = (
            [w for w in query_context.split() if len(w) > 3][:10]
            if query_context
            else None
        )
        tags: dict[str, str] = {}
        if hasattr(self._wiki_store, "query_with_tags"):
            per_repo_section, tags = self._wiki_store.query_with_tags(
                repo,
                keywords=keywords,
                max_chars=self._config.max_repo_wiki_chars,
            )
        else:
            per_repo_section = self._wiki_store.query(
                repo,
                keywords=keywords,
                max_chars=self._config.max_repo_wiki_chars,
            )
        per_repo_section = _weave_temporal_tags(per_repo_section, tags)

        tribal = self._tribal_wiki_store
        tribal_section = ""
        if tribal is not None:
            tribal_section = tribal.query(
                keywords=keywords,
                max_chars=self._config.max_repo_wiki_chars,
            )

        parts = [s for s in (per_repo_section, tribal_section) if s]
        if not parts:
            return ""
        return "\n\n" + "\n\n".join(parts)

    #: Prompt-size budget for the rendered ADR index section. If render_full
    #: exceeds this, we fall back to the titles-only view (which is bounded by
    #: ADR count, not summary length). Prevents large ADR corpora from
    #: dominating the plan prompt.
    _MAX_ADR_SECTION_CHARS: ClassVar[int] = 4000

    def _inject_adr_index(self) -> str:
        """Inject the ADR index into the current phase's prompt.

        Plan phase: full index (with summaries) — or titles-only if the full
        view would exceed ``_MAX_ADR_SECTION_CHARS``.
        Implement/review: titles-only (prompt-size conscious; excludes Superseded).
        Other phases: empty.
        """
        adr_index = self._adr_index
        if adr_index is None:
            return ""

        adrs = adr_index.adrs()
        if not adrs:
            return ""

        phase = self._phase_name
        if phase == "plan":
            body = render_full(adrs)
            if len(body) > self._MAX_ADR_SECTION_CHARS:
                body = render_titles_only(adrs)
        elif phase in ("implement", "review"):
            body = render_titles_only(adrs)
        else:
            return ""

        return f"\n\n{body}" if body else ""

    def _consume_context_stats(self) -> dict[str, int]:
        stats = dict(self._last_context_stats)
        self._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
        return stats

    def _build_command(self, _worktree_path: Path | None = None) -> list[str]:
        """Construct the default implementation CLI invocation.

        Used by runners that call the implementation tool (``agent.py`` and
        ``hitl_runner.py``).  Runners that use a different tool (planner,
        reviewer, triage) override this method.  The ``_worktree_path``
        parameter is optional — no current override uses the path to build
        the command; runners that operate against ``repo_root`` (e.g.
        ``PlannerRunner``, ``TriageRunner``, ``ReviewRunner``) call this
        without a path.
        """
        return build_agent_command(
            tool=self._config.implementation_tool,
            model=self._config.model,
        )

    async def _verify_quality(self, worktree_path: Path) -> LoopResult:
        """Run ``make quality`` and return a :class:`LoopResult`."""
        try:
            result = await self._runner.run_simple(
                ["make", "quality"],
                cwd=str(worktree_path),
                timeout=self._config.quality_timeout,
            )
        except FileNotFoundError:
            return LoopResult(
                passed=False, summary="make not found — cannot run quality checks"
            )
        except TimeoutError:
            return LoopResult(
                passed=False,
                summary=f"make quality timed out after {self._config.quality_timeout}s",
            )
        if result.returncode != 0:
            output = "\n".join(filter(None, [result.stdout, result.stderr]))
            return LoopResult(
                passed=False,
                summary=f"`make quality` failed:\n{output[-self._config.error_output_max_chars :]}",
            )
        return LoopResult(passed=True, summary="OK")
