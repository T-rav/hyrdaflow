"""ADR Council Reviewer — multi-agent review of proposed ADRs."""

from __future__ import annotations

import difflib
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from models import ADRCouncilResult, CouncilVerdict, CouncilVote
from subprocess_util import make_clean_env, run_subprocess

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from execution import SubprocessRunner
    from pr_manager import PRManager

logger = logging.getLogger("hydraflow.adr_reviewer")

_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(\w+)", re.IGNORECASE)
_ADR_FILE_RE = re.compile(r"^(\d{4})-.*\.md$")
_DUPLICATE_THRESHOLD = 0.7


class ADRCouncilReviewer:
    """Runs a multi-agent council review on proposed ADRs."""

    def __init__(
        self,
        config: HydraFlowConfig,
        event_bus: EventBus,
        pr_manager: PRManager,
        runner: SubprocessRunner,
    ) -> None:
        self._config = config
        self._bus = event_bus
        self._prs = pr_manager
        self._runner = runner

    async def review_proposed_adrs(self) -> dict[str, int]:
        """Scan for proposed ADRs and run council reviews.

        Returns stats: {reviewed, accepted, rejected, escalated, duplicates, rounds_total}.
        """
        adr_dir = Path(self._config.repo_root) / "docs" / "adr"
        if not adr_dir.is_dir():
            logger.info("No ADR directory found at %s", adr_dir)
            return {"reviewed": 0}

        proposed = self._find_proposed_adrs(adr_dir)
        if not proposed:
            logger.info("No proposed ADRs found")
            return {"reviewed": 0}

        all_adrs = self._load_all_adrs(adr_dir)
        index_context = self._build_index_context(all_adrs)

        stats = {
            "reviewed": 0,
            "accepted": 0,
            "rejected": 0,
            "escalated": 0,
            "duplicates": 0,
            "rounds_total": 0,
        }

        for adr_number, adr_path, adr_content in proposed:
            adr_title = (
                adr_path.stem.split("-", 1)[-1].replace("-", " ")
                if "-" in adr_path.stem
                else adr_path.stem
            )
            logger.info("Reviewing ADR-%04d: %s", adr_number, adr_title)

            duplicates = self._detect_duplicates(adr_number, adr_content, all_adrs)
            duplicate_context = self._build_duplicate_context(duplicates)

            result = await self._run_council_session(
                adr_number, adr_title, adr_content, index_context, duplicate_context
            )

            stats["reviewed"] += 1
            stats["rounds_total"] += result.rounds_needed
            await self._route_result(result, adr_path, adr_dir, stats)

        logger.info("ADR review complete: %s", stats)
        return stats

    def _find_proposed_adrs(self, adr_dir: Path) -> list[tuple[int, Path, str]]:
        """Find ADR files with Status: Proposed."""
        results: list[tuple[int, Path, str]] = []
        for path in sorted(adr_dir.glob("*.md")):
            match = _ADR_FILE_RE.match(path.name)
            if not match:
                continue
            adr_number = int(match.group(1))
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                logger.warning("Skipping unreadable ADR file: %s", path)
                continue
            status_match = _STATUS_RE.search(content)
            if status_match and status_match.group(1).lower() == "proposed":
                results.append((adr_number, path, content))
        return results

    def _load_all_adrs(self, adr_dir: Path) -> list[tuple[int, str, str]]:
        """Load all ADR files as (number, title, content)."""
        results: list[tuple[int, str, str]] = []
        for path in sorted(adr_dir.glob("*.md")):
            match = _ADR_FILE_RE.match(path.name)
            if not match:
                continue
            adr_number = int(match.group(1))
            title = (
                path.stem.split("-", 1)[-1].replace("-", " ")
                if "-" in path.stem
                else path.stem
            )
            try:
                content = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                logger.warning("Skipping unreadable ADR file: %s", path)
                continue
            results.append((adr_number, title, content))
        return results

    def _build_index_context(self, all_adrs: list[tuple[int, str, str]]) -> str:
        """Build a summary index of all ADRs for council context."""
        lines: list[str] = []
        for number, title, content in all_adrs:
            status_match = _STATUS_RE.search(content)
            status = status_match.group(1) if status_match else "Unknown"
            lines.append(f"- ADR-{number:04d}: {title} (Status: {status})")
        return "\n".join(lines) if lines else "No existing ADRs found."

    def _detect_duplicates(
        self,
        adr_number: int,
        content: str,
        all_adrs: list[tuple[int, str, str]],
    ) -> list[tuple[int, str, float]]:
        """Detect potential duplicates using title + Decision section similarity."""
        decision = self._extract_decision(content)
        title = self._extract_title(content)

        candidates: list[tuple[int, str, float]] = []
        for other_number, other_title, other_content in all_adrs:
            if other_number == adr_number:
                continue
            other_decision = self._extract_decision(other_content)

            title_ratio = difflib.SequenceMatcher(
                None, title.lower(), other_title.lower()
            ).ratio()
            decision_ratio = (
                difflib.SequenceMatcher(
                    None, decision.lower(), other_decision.lower()
                ).ratio()
                if decision and other_decision
                else 0.0
            )
            score = max(title_ratio, decision_ratio)
            if score >= _DUPLICATE_THRESHOLD:
                candidates.append((other_number, other_title, score))

        return sorted(candidates, key=lambda x: x[2], reverse=True)

    def _extract_decision(self, content: str) -> str:
        """Extract the Decision section from an ADR."""
        match = re.search(r"## Decision\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        return match.group(1).strip() if match else ""

    def _extract_title(self, content: str) -> str:
        """Extract the title from an ADR (first H1 heading)."""
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        return match.group(1).strip() if match else ""

    def _build_duplicate_context(self, duplicates: list[tuple[int, str, float]]) -> str:
        """Format duplicate warnings for the orchestrator prompt."""
        if not duplicates:
            return "No duplicate warnings."
        lines = ["Potential duplicates detected:"]
        for number, title, score in duplicates:
            lines.append(f"- ADR-{number:04d}: {title} (similarity: {score:.0%})")
        return "\n".join(lines)

    async def _run_council_session(
        self,
        adr_number: int,
        adr_title: str,
        adr_content: str,
        index_context: str,
        duplicate_context: str,
    ) -> ADRCouncilResult:
        """Run the orchestrator subprocess and parse its result."""
        prompt = self._build_orchestrator_prompt(
            adr_content, index_context, duplicate_context
        )
        transcript = await self._execute_orchestrator(prompt)
        if transcript is None:
            logger.warning("ADR-%04d: orchestrator returned no output", adr_number)
            return ADRCouncilResult(
                adr_number=adr_number,
                adr_title=adr_title,
                final_decision="NO_CONSENSUS",
                summary="Orchestrator returned no output",
            )
        return self._parse_council_result(transcript, adr_number, adr_title)

    def _build_orchestrator_prompt(
        self,
        adr_content: str,
        index_context: str,
        duplicate_context: str,
    ) -> str:
        """Construct the chair prompt for the council meeting."""
        threshold = self._config.adr_review_approval_threshold
        max_rounds = self._config.adr_review_max_rounds
        return f"""You are chairing an ADR Review Council meeting with up to {max_rounds} rounds of voting.
Your job: spawn judge agents, check for consensus, run deliberation if needed,
and output a structured final result.

## ADR Under Review
{adr_content}

## Existing ADR Index
{index_context}

## Duplicate Warnings
{duplicate_context}

## Judge Roles
- Architect: structural soundness, consistency with existing ADRs, scope
- Pragmatist: practical value, implementation status, significance threshold
- Editor: clarity, completeness, duplicates, formatting

## Meeting Protocol

### ROUND 1 — Independent Voting
Spawn 3 judges IN PARALLEL (single message, 3 Agent tool calls).
Each judge receives the full ADR, index context, and duplicate warnings.
Each must end with:
  VERDICT: APPROVE | REJECT | REQUEST_CHANGES | DUPLICATE
  DUPLICATE_OF: <number> (only if DUPLICATE)
  REASONING: <2-4 sentences>

After Round 1, check:
- Any DUPLICATE → skip to final output (duplicate takes priority)
- All 3 same verdict → consensus reached, skip to final output
- >= {threshold} APPROVE → consensus reached, skip to final output
- Otherwise → proceed to Round 2

### ROUND 2 — Deliberation
Spawn 3 judges again IN PARALLEL, but this time include ALL Round 1 votes
and reasoning in each judge's prompt. Tell each judge:
  "The council did not reach consensus in Round 1. Review your colleagues'
   positions and reasoning below. You may maintain or change your vote.
   Address specific disagreements in your reasoning."

After Round 2, check same consensus rules. If still no consensus → Round 3.

### ROUND 3 — Final Vote
Same as Round 2 but include Round 1 AND Round 2 votes. Tell each judge:
  "This is the final round. The council must reach a decision. If you have
   concerns but the majority disagrees, consider whether your concerns are
   blocking or advisory. Vote accordingly."

After Round 3, the chair forces a decision by majority. If still tied,
the verdict is REQUEST_CHANGES (safest default — escalates to human).

## Required Output Format
After all rounds complete, output EXACTLY this block:

COUNCIL_RESULT:
rounds_needed: <1|2|3>
architect_verdict: <final verdict>
architect_reasoning: <final reasoning>
pragmatist_verdict: <final verdict>
pragmatist_reasoning: <final reasoning>
editor_verdict: <final verdict>
editor_reasoning: <final reasoning>
approve_count: <N>
reject_count: <N>
final_decision: ACCEPT | REJECT | REQUEST_CHANGES | DUPLICATE
summary: <1-2 sentence synthesis of the council's discussion>
duplicate_of: <number or none>
minority_note: <dissenting opinion if not unanimous, or "none">"""

    def _parse_council_result(
        self, transcript: str, adr_number: int, adr_title: str
    ) -> ADRCouncilResult:
        """Parse COUNCIL_RESULT block from orchestrator transcript."""
        # Greedy match to capture full block (fields are single-line key:value,
        # so we grab everything after the header until end-of-string).
        match = re.search(r"COUNCIL_RESULT:\s*\n(.+)", transcript, re.DOTALL)
        if not match:
            logger.warning("ADR-%04d: no COUNCIL_RESULT block found", adr_number)
            return ADRCouncilResult(
                adr_number=adr_number,
                adr_title=adr_title,
                final_decision="NO_CONSENSUS",
                summary="Failed to parse council result",
            )

        block = match.group(1)
        fields = self._parse_kv_block(block)

        try:
            rounds_needed = int(fields.get("rounds_needed", "1"))
        except ValueError:
            rounds_needed = 1
        final_decision = fields.get("final_decision", "REQUEST_CHANGES").upper()
        duplicate_of_str = fields.get("duplicate_of", "none")
        try:
            duplicate_of = int(duplicate_of_str) if duplicate_of_str.isdigit() else None
        except ValueError:
            duplicate_of = None

        votes: list[CouncilVote] = []
        all_round_votes: list[list[CouncilVote]] = []
        for role in ("architect", "pragmatist", "editor"):
            verdict_str = fields.get(f"{role}_verdict", "").upper()
            reasoning = fields.get(f"{role}_reasoning", "")
            verdict = self._map_verdict(verdict_str)
            vote = CouncilVote(
                role=role,
                verdict=verdict,
                reasoning=reasoning,
                round_number=rounds_needed,
                duplicate_of=duplicate_of
                if verdict == CouncilVerdict.DUPLICATE
                else None,
            )
            votes.append(vote)

        if votes:
            all_round_votes.append(votes)

        duplicate_detected = any(v.verdict == CouncilVerdict.DUPLICATE for v in votes)

        # Map ACCEPT/REJECT/etc to canonical forms
        if final_decision in ("ACCEPT", "REJECT"):
            pass
        elif final_decision == "DUPLICATE":
            duplicate_detected = True
        elif final_decision not in ("REQUEST_CHANGES",):
            final_decision = "NO_CONSENSUS"

        return ADRCouncilResult(
            adr_number=adr_number,
            adr_title=adr_title,
            rounds_needed=rounds_needed,
            votes=votes,
            all_round_votes=all_round_votes,
            final_decision=final_decision,
            duplicate_detected=duplicate_detected,
            duplicate_of=duplicate_of,
            summary=fields.get("summary", ""),
            minority_note=fields.get("minority_note", "none"),
        )

    def _parse_kv_block(self, block: str) -> dict[str, str]:
        """Parse key: value lines from a structured text block."""
        result: dict[str, str] = {}
        for line in block.strip().splitlines():
            if ":" in line:
                key, _, value = line.partition(":")
                result[key.strip().lower()] = value.strip()
        return result

    def _map_verdict(self, verdict_str: str) -> CouncilVerdict:
        """Map a verdict string to a CouncilVerdict enum."""
        mapping = {
            "APPROVE": CouncilVerdict.APPROVE,
            "REJECT": CouncilVerdict.REJECT,
            "REQUEST_CHANGES": CouncilVerdict.REQUEST_CHANGES,
            "DUPLICATE": CouncilVerdict.DUPLICATE,
        }
        return mapping.get(verdict_str, CouncilVerdict.REQUEST_CHANGES)

    async def _execute_orchestrator(self, prompt: str) -> str | None:
        """Call the configured CLI backend to run the council session."""
        tool = self._config.background_tool
        if tool == "inherit":
            tool = "claude"
        model = self._config.adr_review_model

        if tool == "codex":
            cmd = [
                "codex",
                "exec",
                "--json",
                "--model",
                model,
                "--sandbox",
                "danger-full-access",
                "--dangerously-bypass-approvals-and-sandbox",
                "--skip-git-repo-check",
                prompt,
            ]
            cmd_input = None
        else:
            cmd = [tool, "-p", prompt, "--model", model]
            cmd_input = None

        env = make_clean_env(self._config.gh_token)
        try:
            result = await self._runner.run_simple(
                cmd,
                env=env,
                input=cmd_input,
                timeout=self._config.agent_timeout,
            )
            if result.returncode != 0:
                logger.warning(
                    "ADR council orchestrator failed (rc=%d): %s",
                    result.returncode,
                    result.stderr[:200],
                )
                return None
            return result.stdout if result.stdout else None
        except TimeoutError:
            logger.warning("ADR council orchestrator timed out")
            return None
        except (OSError, FileNotFoundError, NotImplementedError) as exc:
            logger.warning("ADR council orchestrator unavailable: %s", exc)
            return None

    async def _route_result(
        self,
        result: ADRCouncilResult,
        adr_path: Path,
        adr_dir: Path,
        stats: dict[str, int],
    ) -> None:
        """Route council result to the appropriate handler."""
        if result.duplicate_detected:
            await self._handle_duplicate(result)
            stats["duplicates"] += 1
        elif result.final_decision == "ACCEPT":
            await self._accept_adr(result, adr_path, adr_dir)
            stats["accepted"] += 1
        elif result.final_decision == "REJECT":
            routed = await self._route_to_triage(result, reason="rejected")
            if not routed:
                await self._escalate_to_hitl(result, reason="rejected")
            stats["rejected"] += 1
        elif result.final_decision == "REQUEST_CHANGES":
            # Attempt a single clerk-assisted amendment + re-review pass before
            # routing back into the main pipeline.
            auto_accepted = await self._attempt_clerk_amend_and_revote(
                result,
                adr_path,
                adr_dir,
            )
            if auto_accepted:
                stats["accepted"] += 1
                return
            routed = await self._route_to_triage(result, reason="changes_requested")
            if not routed:
                await self._escalate_to_hitl(result, reason="changes_requested")
            stats["escalated"] += 1
        else:
            routed = await self._route_to_triage(result, reason="no_consensus")
            if not routed:
                await self._escalate_to_hitl(result, reason="no_consensus")
            stats["escalated"] += 1

    async def _route_to_triage(self, result: ADRCouncilResult, *, reason: str) -> bool:
        """Create a follow-up issue in triage so normal plan/fix flow can run.

        Returns True when a triage issue was created; otherwise False so callers
        can escalate to HITL as a fallback.
        """
        reason_labels = {
            "rejected": "Council recommends rejection",
            "changes_requested": "Council requests changes",
            "no_consensus": "Council deadlocked",
        }
        reason_text = reason_labels.get(reason, reason)
        summary = self._build_council_summary(result)

        title = f"[ADR Follow-up] ADR-{result.adr_number:04d}: {reason_text}"
        if len(title) > 70:
            title = title[:67] + "..."
        body = (
            "## Context\n\n"
            "The ADR council reviewed an ADR and requested additional work.\n\n"
            f"**ADR:** ADR-{result.adr_number:04d} — {result.adr_title}\n"
            f"**Council outcome:** {result.final_decision}\n"
            f"**Reason:** {reason_text}\n\n"
            "## Requested Follow-Up\n\n"
            "Route through triage and attempt a normal plan -> implement -> review cycle.\n"
            "Escalate to HITL only if triage/planning cannot produce a viable fix.\n\n"
            "## Council Summary\n\n"
            f"{summary}\n\n"
            "---\n"
            "Generated by HydraFlow ADR Council"
        )
        try:
            issue_number = await self._prs.create_issue(
                title,
                body,
                labels=list(self._config.find_label),
            )
        except Exception:
            logger.exception(
                "ADR-%04d triage routing failed; will fallback to HITL",
                result.adr_number,
            )
            return False
        if issue_number <= 0:
            logger.warning(
                "ADR-%04d triage routing returned invalid issue number (%s)",
                result.adr_number,
                issue_number,
            )
            return False

        logger.info(
            "ADR-%04d routed to triage via follow-up issue #%d (%s)",
            result.adr_number,
            issue_number,
            reason,
        )
        return True

    async def _attempt_clerk_amend_and_revote(
        self,
        result: ADRCouncilResult,
        adr_path: Path,
        adr_dir: Path,
    ) -> bool:
        """Try one deterministic clerk edit pass, then re-run council once.

        Returns True when the amended ADR is accepted after re-vote.
        """
        try:
            original = adr_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            logger.warning(
                "ADR-%04d clerk amend skipped (unable to read file: %s)",
                result.adr_number,
                adr_path,
            )
            return False

        amended = self._build_clerk_amendment(original, result)
        if amended == original:
            return False
        ok, review_note = self._clerk_self_review(
            original=original,
            amended=amended,
            result=result,
        )
        if not ok:
            logger.info(
                "ADR-%04d clerk self-review failed: %s",
                result.adr_number,
                review_note,
            )
            return False

        all_adrs = self._load_all_adrs(adr_dir)
        index_context = self._build_index_context(all_adrs)
        duplicates = self._detect_duplicates(result.adr_number, amended, all_adrs)
        duplicate_context = self._build_duplicate_context(duplicates)
        rerun = await self._run_council_session(
            result.adr_number,
            result.adr_title,
            amended,
            index_context,
            duplicate_context,
        )

        if rerun.final_decision != "ACCEPT" or rerun.duplicate_detected:
            logger.info(
                "ADR-%04d clerk amend did not produce acceptance (decision=%s)",
                result.adr_number,
                rerun.final_decision,
            )
            return False

        try:
            adr_path.write_text(amended, encoding="utf-8")
        except OSError:
            logger.exception(
                "ADR-%04d clerk amend accepted but file write failed", result.adr_number
            )
            return False

        logger.info(
            "ADR-%04d accepted after clerk amendment re-vote",
            result.adr_number,
        )
        await self._accept_adr(rerun, adr_path, adr_dir)
        return True

    def _build_clerk_amendment(self, content: str, result: ADRCouncilResult) -> str:
        """Append a focused amendment section based on non-approve votes."""
        suggestions: list[str] = []
        for vote in result.votes:
            if vote.verdict == CouncilVerdict.APPROVE:
                continue
            reasoning = vote.reasoning.strip()
            if reasoning:
                suggestions.append(f"- {vote.role.capitalize()}: {reasoning}")
        if not suggestions and result.summary.strip():
            suggestions.append(f"- Council summary: {result.summary.strip()}")
        if not suggestions:
            return content

        section = (
            "## Council Amendment Notes\n\n"
            "The following amendments were generated from council feedback:\n\n"
            + "\n".join(suggestions)
            + "\n\n"
            "These notes are intended to be incorporated before final acceptance."
        )

        pattern = re.compile(
            r"(?ims)^##\s+Council Amendment Notes\s*\n.*?(?=^##\s+|\Z)"
        )
        if pattern.search(content):
            return pattern.sub(section + "\n\n", content, count=1)

        suffix = "\n\n" if not content.endswith("\n") else "\n"
        return content.rstrip() + suffix + section + "\n"

    def _clerk_self_review(
        self,
        *,
        original: str,
        amended: str,
        result: ADRCouncilResult,
    ) -> tuple[bool, str]:
        """Validate clerk amendments before re-vote.

        Ensures the amendment section exists and that non-approve feedback was
        actually carried into the proposed update.
        """
        if amended == original:
            return False, "no-op amendment"
        if "## Council Amendment Notes" not in amended:
            return False, "missing amendment notes section"

        missing_feedback: list[str] = []
        for vote in result.votes:
            if vote.verdict == CouncilVerdict.APPROVE:
                continue
            reasoning = vote.reasoning.strip()
            if reasoning and reasoning not in amended:
                missing_feedback.append(f"{vote.role}:{reasoning[:80]}")
        if missing_feedback:
            return False, "missing feedback items: " + "; ".join(missing_feedback)

        lowered = amended.lower()
        required = ("## context", "## decision", "## consequences")
        missing_sections = [heading for heading in required if heading not in lowered]
        if missing_sections:
            return False, "missing ADR sections: " + ", ".join(missing_sections)
        return True, "ok"

    async def _accept_adr(
        self,
        result: ADRCouncilResult,
        adr_path: Path,
        adr_dir: Path,
    ) -> None:
        """Accept an ADR: update status, update README, commit and create PR."""
        logger.info("ADR-%04d accepted by council", result.adr_number)

        try:
            content = adr_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            logger.exception("Failed to read ADR file: %s", adr_path)
            return

        # Update status in ADR file
        updated = _STATUS_RE.sub("**Status:** Accepted", content, count=1)
        adr_path.write_text(updated, encoding="utf-8")

        # Update README if present
        readme_path = adr_dir / "README.md"
        if readme_path.exists():
            self._update_readme_status(readme_path, result.adr_number)

        # Commit and create PR
        await self._commit_acceptance(adr_path, readme_path, result)

    def _update_readme_status(self, readme_path: Path, adr_number: int) -> None:
        """Update the ADR status in README.md from Proposed to Accepted."""
        content = readme_path.read_text(encoding="utf-8")
        # Match table rows like "| 0001 | ... | Proposed |"
        pattern = re.compile(
            rf"(\|\s*{adr_number:04d}\s*\|.*?\|)\s*Proposed\s*\|",
            re.IGNORECASE,
        )
        updated = pattern.sub(r"\1 Accepted |", content)
        if updated != content:
            readme_path.write_text(updated, encoding="utf-8")

    async def _commit_acceptance(
        self,
        adr_path: Path,
        readme_path: Path,
        result: ADRCouncilResult,
    ) -> None:
        """Create worktree, commit status update, push, and create PR."""
        if self._config.dry_run:
            logger.info(
                "[dry-run] Would commit acceptance for ADR-%04d", result.adr_number
            )
            return

        repo_root = Path(self._config.repo_root)
        branch = f"adr/accept-{result.adr_number:04d}"
        worktree_path = (
            Path(self._config.worktree_base) / f"adr-accept-{result.adr_number:04d}"
        )

        try:
            # Create an isolated worktree to avoid corrupting the primary checkout
            await run_subprocess(
                "git",
                "worktree",
                "add",
                "-b",
                branch,
                str(worktree_path),
                cwd=repo_root,
                gh_token=self._config.gh_token,
            )

            # Copy updated files into the worktree
            wt_adr_path = worktree_path / adr_path.relative_to(repo_root)
            wt_adr_path.parent.mkdir(parents=True, exist_ok=True)
            wt_adr_path.write_text(
                adr_path.read_text(encoding="utf-8"), encoding="utf-8"
            )
            await run_subprocess(
                "git",
                "add",
                str(wt_adr_path.relative_to(worktree_path)),
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )

            if readme_path.exists():
                wt_readme = worktree_path / readme_path.relative_to(repo_root)
                wt_readme.parent.mkdir(parents=True, exist_ok=True)
                wt_readme.write_text(
                    readme_path.read_text(encoding="utf-8"), encoding="utf-8"
                )
                await run_subprocess(
                    "git",
                    "add",
                    str(wt_readme.relative_to(worktree_path)),
                    cwd=worktree_path,
                    gh_token=self._config.gh_token,
                )

            minority = (
                f"\n\nMinority note: {result.minority_note}"
                if result.minority_note and result.minority_note != "none"
                else ""
            )
            message = (
                f"Accept ADR-{result.adr_number:04d}: {result.adr_title}"
                f"\n\nCouncil decision: {result.summary}{minority}"
            )
            await run_subprocess(
                "git",
                "commit",
                "-m",
                message,
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
            await run_subprocess(
                "git",
                "push",
                "-u",
                "origin",
                branch,
                cwd=worktree_path,
                gh_token=self._config.gh_token,
            )
        except RuntimeError:
            logger.exception("Failed to commit ADR-%04d acceptance", result.adr_number)
            return
        finally:
            # Always clean up the worktree
            try:
                await run_subprocess(
                    "git",
                    "worktree",
                    "remove",
                    str(worktree_path),
                    "--force",
                    cwd=repo_root,
                    gh_token=self._config.gh_token,
                )
            except RuntimeError:
                logger.debug("Worktree cleanup failed for %s", worktree_path)

        summary = self._build_council_summary(result)
        title = f"Accept ADR-{result.adr_number:04d}: {result.adr_title}"
        if len(title) > 70:
            title = title[:67] + "..."
        body = (
            f"## ADR Council Review\n\n"
            f"The ADR review council has voted to **accept** "
            f"ADR-{result.adr_number:04d}.\n\n"
            f"{summary}\n\n"
            f"---\n"
            f"Generated by HydraFlow ADR Council"
        )

        try:
            await run_subprocess(
                "gh",
                "pr",
                "create",
                "--title",
                title,
                "--body",
                body,
                "--base",
                self._config.main_branch,
                "--head",
                branch,
                cwd=repo_root,
                gh_token=self._config.gh_token,
            )
        except RuntimeError:
            logger.exception("Failed to create PR for ADR-%04d", result.adr_number)

    async def _escalate_to_hitl(self, result: ADRCouncilResult, *, reason: str) -> None:
        """Create a GitHub issue for HITL escalation."""
        logger.info("ADR-%04d escalated to HITL: %s", result.adr_number, reason)

        reason_labels = {
            "rejected": "Council recommends rejection",
            "changes_requested": "Council requests changes",
            "no_consensus": "Council deadlocked",
        }
        reason_text = reason_labels.get(reason, reason)
        summary = self._build_council_summary(result)

        title = f"[ADR Review] ADR-{result.adr_number:04d}: {reason_text}"
        if len(title) > 70:
            title = title[:67] + "..."
        body = (
            f"## ADR Council Review — Escalation\n\n"
            f"**ADR:** {result.adr_number:04d} — {result.adr_title}\n"
            f"**Reason:** {reason_text}\n"
            f"**Rounds needed:** {result.rounds_needed}\n\n"
            f"## Council Summary\n\n{summary}\n\n"
            f"---\n"
            f"Generated by HydraFlow ADR Council"
        )

        await self._prs.create_issue(title, body, labels=list(self._config.hitl_label))

    async def _handle_duplicate(self, result: ADRCouncilResult) -> None:
        """Create a GitHub issue flagging a duplicate ADR pair."""
        dup_of = result.duplicate_of
        logger.info(
            "ADR-%04d flagged as duplicate of ADR-%s",
            result.adr_number,
            f"{dup_of:04d}" if dup_of is not None else "unknown",
        )

        if dup_of is not None:
            title = (
                f"[ADR Duplicate] ADR-{result.adr_number:04d} "
                f"may duplicate ADR-{dup_of:04d}"
            )
            dup_line = f"**Potential duplicate of:** ADR-{dup_of:04d}\n\n"
        else:
            title = f"[ADR Duplicate] ADR-{result.adr_number:04d}"
            dup_line = "**Potential duplicate of:** unknown\n\n"

        if len(title) > 70:
            title = title[:67] + "..."
        summary = self._build_council_summary(result)

        body = (
            f"## Duplicate ADR Detected\n\n"
            f"**ADR under review:** {result.adr_number:04d} — {result.adr_title}\n"
            f"{dup_line}"
            f"A council judge flagged this ADR as a potential duplicate.\n"
            f"Please review both ADRs and determine whether to merge, "
            f"supersede, or keep both.\n\n"
            f"## Council Summary\n\n{summary}\n\n"
            f"---\n"
            f"Generated by HydraFlow ADR Council"
        )

        await self._prs.create_issue(title, body, labels=list(self._config.hitl_label))

    def _build_council_summary(self, result: ADRCouncilResult) -> str:
        """Format the full deliberation record."""
        lines: list[str] = [
            f"**Final decision:** {result.final_decision}",
            f"**Rounds needed:** {result.rounds_needed}",
            "",
            "### Final Votes",
        ]
        for vote in result.votes:
            lines.append(
                f"- **{vote.role.capitalize()}:** {vote.verdict.value}"
                f" — {vote.reasoning}"
            )

        if result.minority_note and result.minority_note != "none":
            lines.extend(["", "### Minority Note", "", result.minority_note])

        if result.summary:
            lines.extend(["", "### Summary", "", result.summary])

        return "\n".join(lines)
