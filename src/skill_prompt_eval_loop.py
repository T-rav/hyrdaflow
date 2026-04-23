"""SkillPromptEvalLoop — weekly corpus backstop + weak-case audit.

Spec: `docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md`
§4.6. Two roles:

1. **Backstop.** Runs the *full* adversarial corpus weekly (§4.1). Once
   the corpus grows past `trust_rc_subset_size` the RC gate shifts to a
   sampled subset; this loop catches regressions the weekly sample
   misses. Files `skill-prompt-drift` issues for PASS→FAIL transitions.
2. **Weak-case audit.** Samples 10% of `provenance: learning-loop`
   cases and flags any whose `expected_catcher` skill passes them — a
   weak-case signal the §4.1 v2 learner uses. Files `corpus-case-weak`
   issues for human triage.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import random
import time
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from models import WorkCycleResult

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from dedup_store import DedupStore
    from pr_manager import PRManager
    from state import StateTracker

logger = logging.getLogger("hydraflow.skill_prompt_eval_loop")

_MAX_ATTEMPTS = 3
_WEAK_SAMPLE_RATE = 0.10


class SkillPromptEvalLoop(BaseBackgroundLoop):
    """Weekly skill-prompt drift detector + corpus-health auditor (spec §4.6)."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        state: StateTracker,
        pr_manager: PRManager,
        dedup: DedupStore,
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="skill_prompt_eval",
            config=config,
            deps=deps,
            run_on_startup=False,
        )
        self._state = state
        self._pr = pr_manager
        self._dedup = dedup

    def _get_default_interval(self) -> int:
        return self._config.skill_prompt_eval_interval

    async def _run_corpus(self) -> list[dict[str, Any]]:
        """Invoke `make trust-adversarial` → list of case-result dicts.

        Each dict carries ``{case_id, skill, status, provenance,
        expected_catcher}``. Owned by Plan 1 (`make trust-adversarial
        --format=json`). Missing keys are tolerated — cases without
        ``provenance`` are treated as ``hand-crafted``.
        """
        cmd = ["make", "trust-adversarial", "FORMAT=json"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode not in (0, 1):  # 1 = failures present; still valid output
            logger.warning(
                "trust-adversarial exit=%d: %s",
                proc.returncode,
                stderr.decode(errors="replace")[:400],
            )
            return []
        try:
            return json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            logger.warning("trust-adversarial non-JSON response")
            return []

    async def _file_drift_issue(self, case: dict[str, Any], last_status: str) -> int:
        title = (
            f"Skill prompt drift: {case.get('skill', '?')} "
            f"missed {case.get('case_id', '?')}"
        )
        body = (
            f"## Regression\n\n"
            f"Case `{case.get('case_id')}` regressed "
            f"**{last_status} → {case.get('status')}** on "
            f"skill `{case.get('skill')}`.\n\n"
            f"**Expected catcher:** `{case.get('expected_catcher', '?')}`\n"
            f"**Provenance:** `{case.get('provenance', 'unknown')}`\n\n"
            f"_Spec §4.6 — filed by `skill_prompt_eval` loop. Standard "
            f"repair path: edit the skill prompt or the skill's code._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "skill-prompt-drift"]
        )

    async def _file_weak_case_issue(self, case: dict[str, Any]) -> int:
        title = (
            f"Weak corpus case: {case.get('case_id')} "
            f"bypassed {case.get('expected_catcher')}"
        )
        body = (
            f"## Weak-case signal\n\n"
            f"Learning-loop case `{case.get('case_id')}` was PASSED by the "
            f"skill (`{case.get('skill')}`) that was *expected* to catch it "
            f"(`{case.get('expected_catcher')}`). This is the weak-case "
            f"signal the §4.1 v2 learner uses — flag it for human review "
            f"so the corpus self-improves.\n\n"
            f"_Spec §4.6 — filed by `skill_prompt_eval` loop._"
        )
        return await self._pr.create_issue(
            title, body, ["hydraflow-find", "corpus-case-weak"]
        )

    async def _file_escalation(self, case_id: str, attempts: int) -> int:
        title = f"HITL: skill prompt drift {case_id} unresolved after {attempts}"
        body = (
            f"`skill_prompt_eval` filed `skill-prompt-drift` for `{case_id}` "
            f"{attempts} times without closure. Human review needed.\n\n"
            f"_Spec §3.2: closing this issue clears the dedup key._"
        )
        return await self._pr.create_issue(
            title, body, ["hitl-escalation", "skill-prompt-stuck"]
        )

    async def _reconcile_closed_escalations(self) -> None:
        """Clear dedup keys for closed `skill-prompt-stuck` escalations."""
        cmd = [
            "gh",
            "issue",
            "list",
            "--repo",
            self._config.repo,
            "--state",
            "closed",
            "--label",
            "hitl-escalation",
            "--label",
            "skill-prompt-stuck",
            "--author",
            "@me",
            "--limit",
            "100",
            "--json",
            "title",
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return
        try:
            closed = json.loads(stdout.decode() or "[]")
        except json.JSONDecodeError:
            return
        current = self._dedup.get()
        keep = set(current)
        for issue in closed:
            title = issue.get("title", "")
            for key in list(keep):
                if (
                    key.startswith("skill_prompt_eval:")
                    and key.split(":", 1)[1] in title
                ):
                    keep.discard(key)
                    self._state.clear_skill_prompt_attempts(key.split(":", 1)[1])
        if keep != current:
            self._dedup.set_all(keep)

    def _sample_learning_cases(
        self, cases: list[dict[str, Any]], seed: int = 0
    ) -> list[dict[str, Any]]:
        learning = [c for c in cases if c.get("provenance") == "learning-loop"]
        if not learning:
            return []
        n = max(1, math.ceil(len(learning) * _WEAK_SAMPLE_RATE))
        rng = random.Random(seed or 1)
        return rng.sample(learning, min(n, len(learning)))

    async def _do_work(self) -> WorkCycleResult:
        """Weekly eval — backstop + weak-case sampling."""
        t0 = time.perf_counter()
        await self._reconcile_closed_escalations()

        cases = await self._run_corpus()
        if not cases:
            return {"status": "no_cases", "filed": 0}

        # Role 1 — backstop. PASS→FAIL regressions.
        last_green = self._state.get_skill_prompt_last_green()
        current: dict[str, str] = {
            c["case_id"]: c.get("status", "UNKNOWN") for c in cases
        }
        filed = 0
        escalated = 0
        dedup = self._dedup.get()
        for case in cases:
            case_id = case.get("case_id")
            if not case_id:
                continue
            was = last_green.get(case_id, "PASS")
            now = case.get("status")
            if was == "PASS" and now == "FAIL":
                key = f"skill_prompt_eval:{case_id}"
                if key in dedup:
                    continue
                attempts = self._state.inc_skill_prompt_attempts(case_id)
                if attempts >= _MAX_ATTEMPTS:
                    await self._file_escalation(case_id, attempts)
                    escalated += 1
                else:
                    await self._file_drift_issue(case, was)
                    filed += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

        # Save the new snapshot — tests that currently PASS become the
        # new last-green. Tests that remain FAIL stay in the dedup set.
        self._state.set_skill_prompt_last_green(
            {cid: "PASS" for cid, status in current.items() if status == "PASS"}
        )

        # Role 2 — weak-case audit. Learning-loop cases that expected
        # catcher passed through.
        weak_flagged = 0
        sample = self._sample_learning_cases(cases)
        for case in sample:
            skill = case.get("skill")
            catcher = case.get("expected_catcher")
            status = case.get("status")
            if skill == catcher and status == "PASS":
                key = f"skill_prompt_eval:weak:{case.get('case_id')}"
                if key in dedup:
                    continue
                await self._file_weak_case_issue(case)
                weak_flagged += 1
                dedup.add(key)
                self._dedup.set_all(dedup)

        self._emit_trace(t0, cases_seen=len(cases))
        return {
            "status": "ok",
            "filed": filed,
            "escalated": escalated,
            "weak_cases_flagged": weak_flagged,
            "cases_seen": len(cases),
        }

    def _emit_trace(self, t0: float, *, cases_seen: int) -> None:
        try:
            from trace_collector import emit_loop_subprocess_trace  # noqa: PLC0415
        except ImportError:
            return
        duration_ms = int((time.perf_counter() - t0) * 1000)
        emit_loop_subprocess_trace(
            loop=self._worker_name,
            command=["make", "trust-adversarial", "FORMAT=json"],
            exit_code=0,
            duration_ms=duration_ms,
            stderr_excerpt=f"cases_seen={cases_seen}",
        )
