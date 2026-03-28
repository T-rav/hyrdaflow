"""Shape phase — propose product directions and await human selection."""

from __future__ import annotations

import asyncio
import logging
import re

from config import HydraFlowConfig
from events import EventBus, EventType, HydraFlowEvent
from issue_store import IssueStore
from models import ProductDirection, ShapeResult, Task
from phase_utils import (
    MemorySuggester,  # noqa: TCH001
    _sentry_transaction,
    run_refilling_pool,
    store_lifecycle,
)
from pr_manager import PRManager
from shape_runner import ShapeRunner  # noqa: TCH001
from state import StateTracker
from task_source import TaskTransitioner

logger = logging.getLogger("hydraflow.shape_phase")

# Marker comment prefix so we can detect shape options vs other comments
_SHAPE_OPTIONS_MARKER = "## Product Directions"
_DIRECTION_SELECTED_RE = re.compile(r"(?:direction|option)\s+([A-E])\b", re.IGNORECASE)


class ShapePhase:
    """Proposes product directions and waits for human/agent selection.

    Two-part loop:
    - Part A (generate): For issues newly in Shape, generate direction
      options and post as a structured comment.
    - Part B (poll): For issues awaiting a decision, poll for reply
      comments containing a selection. When found, parse the selection,
      enrich the issue, and transition to plan.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        state: StateTracker,
        store: IssueStore,
        prs: PRManager,
        event_bus: EventBus,
        stop_event: asyncio.Event,
        shape_runner: ShapeRunner | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._store = store
        self._prs = prs
        self._transitioner: TaskTransitioner = prs
        self._bus = event_bus
        self._stop_event = stop_event
        self._runner = shape_runner
        self._suggest_memory = MemorySuggester(config, prs, state)
        # Track issues that have had options posted (awaiting selection)
        self._awaiting_selection: set[int] = set()

    async def shape_issues(self) -> bool:
        """Process shape-labeled issues. Returns True if work was done."""

        async def _shape_one(_idx: int, issue: Task) -> int:
            if self._stop_event.is_set():
                return 0
            return await self._shape_single(issue)

        results = await run_refilling_pool(
            supply_fn=lambda: self._store.get_shapeable(1),
            worker_fn=_shape_one,
            max_concurrent=self._config.max_triagers,
            stop_event=self._stop_event,
        )
        return bool(sum(results))

    async def _shape_single(self, issue: Task) -> int:
        """Shape a single issue — generate options or check for selection."""
        with _sentry_transaction("pipeline.shape", f"shape:#{issue.id}"):
            async with store_lifecycle(self._store, issue.id, "shape"):
                # Check if options have already been posted
                enriched = await self._store.enrich_with_comments(issue)
                has_options = any(
                    _SHAPE_OPTIONS_MARKER in c for c in (enriched.comments or [])
                )

                if not has_options:
                    # Part A: Generate and post direction options
                    return await self._generate_options(issue)

                # Part B: Check for a selection in comments after the options
                selection = self._find_selection(enriched.comments or [])
                if selection:
                    return await self._process_selection(issue, selection)

                # No selection yet — re-enqueue for polling on next cycle
                self._store.enqueue_transition(issue, "shape")
                logger.debug("Issue #%d shape — awaiting direction selection", issue.id)
                return 0

    async def _generate_options(self, issue: Task) -> int:
        """Generate product direction options and post them."""
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={"issue": issue.id, "action": "generating_options"},
            )
        )

        if self._runner:
            # Extract research brief from discover phase comment (if present)
            enriched = await self._store.enrich_with_comments(issue)
            research_brief = self._extract_research_brief(enriched.comments or [])
            result = await self._runner.shape(issue, research_brief=research_brief)
        else:
            result = ShapeResult(
                issue_number=issue.id,
                directions=[
                    ProductDirection(
                        name="Direction A",
                        approach="Shape runner not configured",
                        tradeoffs="Configure ShapeRunner for real direction generation",
                        effort="TBD",
                        risk="TBD",
                    ),
                ],
                recommendation="Shape runner not configured — manual direction selection required.",
            )

        comment = self._format_options(issue, result)
        html = self.format_options_html(issue, result)
        if not self._config.dry_run:
            await self._transitioner.post_comment(issue.id, comment)
            self._awaiting_selection.add(issue.id)
            # Save HTML artifact for dashboard/canvas serving
            self._save_html_artifact(issue.id, html)

        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={
                    "issue": issue.id,
                    "action": "options_posted",
                    "html_artifact": html,
                    "directions_count": len(result.directions),
                },
            )
        )
        logger.info(
            "Issue #%d shape — direction options posted, awaiting selection",
            issue.id,
        )
        # Re-enqueue so the poll part picks it up next cycle
        self._store.enqueue_transition(issue, "shape")
        return 1

    def _find_selection(self, comments: list[str]) -> str | None:
        """Look for a direction selection in comments after the options marker.

        Returns the selected direction letter (A-E) or None.
        """
        found_options = False
        for comment in comments:
            if _SHAPE_OPTIONS_MARKER in comment:
                found_options = True
                continue
            if found_options:
                match = _DIRECTION_SELECTED_RE.search(comment)
                if match:
                    return match.group(1).upper()
        return None

    async def _process_selection(self, issue: Task, selection: str) -> int:
        """Process a direction selection and transition to plan."""
        self._awaiting_selection.discard(issue.id)

        # Extract refinement text from the selection comment
        enriched = await self._store.enrich_with_comments(issue)
        refinement = self._extract_refinement(enriched.comments or [], selection)

        # Build enrichment with full direction context for the planner
        direction_detail = self._get_selected_direction_detail(
            enriched.comments or [], selection
        )
        enrichment_parts = [
            "## Selected Product Direction\n",
            f"**Direction {selection}** was selected during product shaping.\n",
        ]
        if refinement:
            enrichment_parts.append(f"**Refinement:** {refinement}\n")
        if direction_detail:
            enrichment_parts.append(f"\n### Direction Detail\n\n{direction_detail}\n")
        enrichment_parts.append(
            "\n### Planning Guidance — DECOMPOSITION REQUIRED\n\n"
            "This issue came through the product discovery and shaping track. "
            "It is a BROAD product direction, NOT a single implementable task.\n\n"
            "**You MUST decompose this into 3-8 concrete sub-issues** using the "
            "NEW_ISSUES_START/NEW_ISSUES_END format. Each sub-issue should:\n"
            "- Be independently implementable and testable\n"
            "- Be scoped to a single concern (one component, one API, one UI piece)\n"
            "- Have a clear acceptance criteria in its body\n"
            "- Reference the selected direction above for context\n\n"
            "Do NOT plan this as a single large implementation. "
            "The value of the product track is that it breaks vague work "
            "into well-scoped engineering tasks."
        )
        enrichment = "\n".join(enrichment_parts)

        if not self._config.dry_run:
            await self._transitioner.post_comment(issue.id, enrichment)
            self._store.enqueue_transition(issue, "plan")
            await self._transitioner.transition(issue.id, "plan")
            self._state.increment_session_counter("shaped")

        # Write learning signal to memory — structured decision for taste profile
        learning_transcript = (
            "MEMORY_SUGGESTION_START\n"
            f"title: Product direction selected for #{issue.id}\n"
            f"learning: Direction {selection} chosen for '{issue.title}'. "
            f"{f'Refinement: {refinement}. ' if refinement else ''}"
            "This decision reflects product taste and scoping preferences.\n"
            f"context: Product shaping for issue #{issue.id}\n"
            "type: knowledge\n"
            "MEMORY_SUGGESTION_END"
        )
        await self._suggest_memory(learning_transcript, "shape", f"issue #{issue.id}")

        # Emit learning signal event for real-time consumers
        await self._bus.publish(
            HydraFlowEvent(
                type=EventType.SHAPE_UPDATE,
                data={
                    "issue": issue.id,
                    "action": "direction_selected",
                    "direction": selection,
                    "refinement": refinement,
                    "issue_title": issue.title,
                },
            )
        )
        logger.info(
            "Issue #%d shape — direction %s selected → %s",
            issue.id,
            selection,
            self._config.planner_label[0],
        )
        return 1

    @staticmethod
    def _extract_refinement(comments: list[str], selection: str) -> str:
        """Extract refinement text from the selection comment.

        The selection comment is expected to contain "Direction X" plus
        any additional text as refinement instructions.
        """
        found_options = False
        for comment in comments:
            if _SHAPE_OPTIONS_MARKER in comment:
                found_options = True
                continue
            if found_options:
                match = _DIRECTION_SELECTED_RE.search(comment)
                if match and match.group(1).upper() == selection:
                    # Remove the direction selection text, keep the rest
                    raw = _DIRECTION_SELECTED_RE.sub("", comment).strip()
                    # Clean up common separators
                    raw = raw.lstrip("—-–:,.").strip()
                    return raw
        return ""

    def _format_options(self, issue: Task, result: ShapeResult) -> str:
        """Format direction options as a structured GitHub comment."""
        lines = [
            f"{_SHAPE_OPTIONS_MARKER} for #{issue.id}",
            "",
        ]
        for i, direction in enumerate(result.directions):
            letter = chr(65 + i)  # A, B, C, ...
            lines.extend(
                [
                    f"### Direction {letter}: {direction.name}",
                    "",
                    f"**Approach:** {direction.approach}",
                    f"**Tradeoffs:** {direction.tradeoffs}",
                    f"**Effort:** {direction.effort} | **Risk:** {direction.risk}",
                ]
            )
            if direction.differentiator:
                lines.append(f"**Differentiator:** {direction.differentiator}")
            lines.append("")

        if result.recommendation:
            lines.extend(
                [
                    "### Recommendation",
                    "",
                    result.recommendation,
                    "",
                ]
            )

        lines.extend(
            [
                "---",
                "Reply with your selection (e.g. `Direction A`) and any refinements.",
                "The selected direction will be used to inform the implementation plan.",
            ]
        )
        return "\n".join(lines)

    def _save_html_artifact(self, issue_number: int, html: str) -> None:
        """Save HTML artifact for dashboard/canvas serving."""
        artifacts_dir = self._config.data_root / "artifacts" / "shape"
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        path = artifacts_dir / f"issue-{issue_number}.html"
        path.write_text(html, encoding="utf-8")
        logger.debug("Saved shape HTML artifact for issue #%d → %s", issue_number, path)

    @staticmethod
    def _get_selected_direction_detail(comments: list[str], selection: str) -> str:
        """Extract the full detail of the selected direction from the options comment."""
        for comment in comments:
            if _SHAPE_OPTIONS_MARKER not in comment:
                continue
            # Find the section for the selected direction
            header = f"### Direction {selection}:"
            start = comment.find(header)
            if start == -1:
                continue
            # Find the next direction header or end of comment
            next_header = comment.find("### Direction ", start + len(header))
            if next_header == -1:
                next_header = comment.find("### Recommendation", start + len(header))
            if next_header == -1:
                next_header = comment.find("---", start + len(header))
            if next_header == -1:
                return comment[start:].strip()
            return comment[start:next_header].strip()
        return ""

    @staticmethod
    def _extract_research_brief(comments: list[str]) -> str:
        """Extract the discovery research brief from issue comments."""
        for comment in comments:
            if "## Product Discovery Brief" in comment:
                return comment
        return ""

    @staticmethod
    def format_options_html(issue: Task, result: ShapeResult) -> str:
        """Render direction options as a self-contained HTML document for canvas display."""
        effort_colors = {"low": "#3fb950", "medium": "#d29922", "high": "#f85149"}
        risk_colors = {"low": "#3fb950", "medium": "#d29922", "high": "#f85149"}

        cards_html = []
        for i, d in enumerate(result.directions):
            letter = chr(65 + i)
            effort_color = effort_colors.get(d.effort.lower(), "#8b949e")
            risk_color = risk_colors.get(d.risk.lower(), "#8b949e")
            cards_html.append(f"""
        <div class="card" data-direction="{letter}">
          <div class="card-header">
            <span class="letter">{letter}</span>
            <span class="name">{d.name}</span>
          </div>
          <p class="approach">{d.approach}</p>
          <p class="tradeoffs"><strong>Tradeoffs:</strong> {d.tradeoffs}</p>
          <div class="badges">
            <span class="badge" style="background:{effort_color}20;color:{effort_color};border:1px solid {effort_color}">Effort: {d.effort}</span>
            <span class="badge" style="background:{risk_color}20;color:{risk_color};border:1px solid {risk_color}">Risk: {d.risk}</span>
          </div>
          {f'<p class="diff"><strong>Differentiator:</strong> {d.differentiator}</p>' if d.differentiator else ""}
        </div>""")

        rec_html = ""
        if result.recommendation:
            rec_html = f'<div class="recommendation"><strong>Recommendation:</strong> {result.recommendation}</div>'

        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Product Directions — #{issue.id}</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Helvetica,Arial,sans-serif;
         background:#0d1117; color:#c9d1d9; padding:24px; }}
  h1 {{ font-size:18px; margin-bottom:4px; }}
  .subtitle {{ color:#8b949e; font-size:13px; margin-bottom:20px; }}
  .cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); gap:12px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px;
           cursor:pointer; transition:border-color 0.2s,box-shadow 0.2s; }}
  .card:hover {{ border-color:#58a6ff; box-shadow:0 0 0 1px #58a6ff; }}
  .card-header {{ display:flex; align-items:center; gap:8px; margin-bottom:8px; }}
  .letter {{ background:#58a6ff20; color:#58a6ff; border:1px solid #58a6ff;
             border-radius:50%; width:28px; height:28px; display:flex; align-items:center;
             justify-content:center; font-weight:700; font-size:13px; flex-shrink:0; }}
  .name {{ font-weight:600; font-size:14px; }}
  .approach {{ font-size:13px; margin-bottom:8px; line-height:1.5; }}
  .tradeoffs {{ font-size:12px; color:#8b949e; margin-bottom:8px; line-height:1.4; }}
  .badges {{ display:flex; gap:6px; margin-bottom:8px; flex-wrap:wrap; }}
  .badge {{ font-size:11px; padding:2px 8px; border-radius:12px; font-weight:500; }}
  .diff {{ font-size:12px; color:#8b949e; line-height:1.4; }}
  .recommendation {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
                     padding:12px; margin-top:16px; font-size:13px; line-height:1.5; }}
</style></head><body>
<h1>Product Directions for #{issue.id}</h1>
<p class="subtitle">{issue.title}</p>
<div class="cards">{"".join(cards_html)}</div>
{rec_html}
</body></html>"""
