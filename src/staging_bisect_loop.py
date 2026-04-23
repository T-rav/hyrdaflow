"""Staging-red attribution bisect loop (spec §4.3).

Polls ``StateTracker.last_rc_red_sha`` every ``staging_bisect_interval``
seconds. When the red SHA changes, the loop:

1. Flake-filters the red (Task 10).
2. Bisects between ``last_green_rc_sha`` and ``current_red_rc_sha``
   (Task 12).
3. Attributes the first-bad commit to its originating PR (Task 14).
4. Enforces the second-revert-in-cycle guardrail (Task 16).
5. Files an auto-revert PR (Task 17) and a retry issue (Task 19).
6. Watchdogs the next RC cycle for outcome verification (Task 20).

Trigger mechanism: state-tracker poll (not an event bus). Matches
HydraFlow's existing cadence-style loops; no new event infra.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from dedup_store import DedupStore

if TYPE_CHECKING:
    from pathlib import Path

    from ports import PRPort
    from state import StateTracker

logger = logging.getLogger("hydraflow.staging_bisect")


class BisectTimeoutError(RuntimeError):
    """Raised when a bisect exceeds ``staging_bisect_runtime_cap_seconds``."""


class BisectRangeError(RuntimeError):
    """Raised when the bisect range is invalid (e.g. unreachable green SHA)."""


class BisectHarnessError(RuntimeError):
    """Raised when git bisect itself errors for reasons unrelated to the probe."""


class RevertConflictError(RuntimeError):
    """Raised when ``git revert`` produced a merge conflict."""


class StagingBisectLoop(BaseBackgroundLoop):
    """Watchdog that reacts to RC-red state transitions. See ADR-0042 §4.3."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        prs: PRPort,
        deps: LoopDeps,
        state: StateTracker,
    ) -> None:
        super().__init__(worker_name="staging_bisect", config=config, deps=deps)
        self._prs = prs
        self._state = state
        # Persisted high-water mark of RC-red SHAs that have already been
        # processed (or skipped as flakes, or escalated). Keyed on rc_red_sha
        # (§4.3 idempotency); survives crash-restart.
        self._processed_dedup = DedupStore(
            "staging_bisect_processed_rc_red",
            config.data_root / "dedup" / "staging_bisect_processed.json",
        )
        # Seed from persisted store on startup; empty on first boot.
        processed = self._processed_dedup.get()
        self._last_processed_rc_red_sha: str = (
            max(processed, key=len) if processed else ""
        )

    def _get_default_interval(self) -> int:
        return self._config.staging_bisect_interval

    async def _do_work(self) -> dict[str, Any] | None:
        if not self._config.staging_enabled:
            return {"status": "staging_disabled"}

        red_sha = self._state.get_last_rc_red_sha()
        if not red_sha:
            return {"status": "no_red"}

        if red_sha == self._last_processed_rc_red_sha:
            return {"status": "already_processed", "sha": red_sha}

        if red_sha in self._processed_dedup.get():
            self._last_processed_rc_red_sha = red_sha
            return {"status": "already_processed", "sha": red_sha}

        # Flake filter — second probe against the red head (spec §4.3 step 1).
        probe_passed, probe_output = await self._run_bisect_probe(red_sha)
        if probe_passed:
            logger.warning(
                "StagingBisectLoop: second probe passed for %s — dismissing as flake",
                red_sha,
            )
            self._state.increment_flake_reruns_total()
            self._processed_dedup.add(red_sha)
            self._last_processed_rc_red_sha = red_sha
            return {"status": "flake_dismissed", "sha": red_sha}

        # Confirmed red — run the full bisect + revert + retry pipeline.
        result = await self._run_full_bisect_pipeline(red_sha, probe_output)
        self._processed_dedup.add(red_sha)
        self._last_processed_rc_red_sha = red_sha
        return result

    async def _run_bisect_probe(self, rc_sha: str) -> tuple[bool, str]:
        """Run ``make bisect-probe`` once against *rc_sha*.

        Returns ``(passed, combined_output)``. Task 12 replaces this with a
        worktree-scoped invocation; for now it shells out against the
        configured repo root.
        """
        from subprocess import run  # noqa: PLC0415 — lazy import

        logger.info("Running bisect-probe against %s", rc_sha)
        proc = run(
            ["make", "bisect-probe"],
            cwd=self._config.repo_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=self._config.staging_bisect_runtime_cap_seconds,
        )
        return proc.returncode == 0, (proc.stdout + proc.stderr)

    async def _run_full_bisect_pipeline(
        self, red_sha: str, probe_output: str
    ) -> dict[str, Any]:
        """Run bisect -> attribute -> guardrail -> revert -> retry -> watchdog.

        Implemented across Tasks 12-20. Stub returns a placeholder so the
        flake-filter test proves the flow routes past the filter.
        """
        logger.info(
            "StagingBisectLoop: pipeline not yet wired for %s (probe_output=%d chars)",
            red_sha,
            len(probe_output),
        )
        return {"status": "pipeline_stub", "sha": red_sha}

    async def _setup_worktree(self, rc_sha: str) -> Path:
        """Create a dedicated worktree at ``<data_root>/<repo_slug>/bisect/<rc_ref>/``."""
        worktree_dir = (
            self._config.data_root / self._config.repo_slug / "bisect" / rc_sha[:12]
        )
        worktree_dir.parent.mkdir(parents=True, exist_ok=True)
        if worktree_dir.exists():
            # Stale worktree from a previous aborted run — nuke it first
            await self._run_git(
                ["git", "worktree", "remove", "--force", str(worktree_dir)],
                cwd=self._config.repo_root,
                timeout=60,
            )
        rc, _out, err = await self._run_git(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(worktree_dir),
                rc_sha,
            ],
            cwd=self._config.repo_root,
            timeout=120,
        )
        if rc != 0:
            raise BisectHarnessError(
                f"git worktree add failed for {rc_sha}: rc={rc} stderr={err}"
            )
        return worktree_dir

    async def _cleanup_worktree(self, worktree_dir: Path) -> None:
        """Best-effort ``git worktree remove --force``."""
        try:
            await self._run_git(
                ["git", "worktree", "remove", "--force", str(worktree_dir)],
                cwd=self._config.repo_root,
                timeout=60,
            )
        except Exception:  # noqa: BLE001
            logger.warning(
                "StagingBisectLoop: worktree cleanup failed for %s",
                worktree_dir,
                exc_info=True,
            )

    async def _run_git(
        self, cmd: list[str], *, cwd: Path, timeout: int
    ) -> tuple[int, str, str]:
        """Run a git command and return ``(returncode, stdout, stderr)``.

        Overridden in tests via ``AsyncMock`` — production uses a
        subprocess runner.
        """
        import asyncio  # noqa: PLC0415

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            raise
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def _run_bisect(self, green_sha: str, red_sha: str) -> str:
        """Run bisect; return the first-bad SHA.

        Raises:
            BisectTimeoutError: wall-clock cap hit.
            BisectRangeError: bisect range invalid (e.g. unreachable green).
            BisectHarnessError: bisect internals failed for infra reasons.
        """
        import re  # noqa: PLC0415

        worktree_dir = await self._setup_worktree(red_sha)
        try:
            try:
                rc, _out, err = await self._run_git(
                    ["git", "bisect", "start", red_sha, green_sha],
                    cwd=worktree_dir,
                    timeout=60,
                )
            except TimeoutError as exc:
                raise BisectTimeoutError(
                    f"bisect exceeded {self._config.staging_bisect_runtime_cap_seconds}s"
                ) from exc
            if rc != 0:
                raise BisectRangeError(
                    f"git bisect start failed for {green_sha}..{red_sha}: {err}"
                )

            try:
                rc, out, err = await self._run_git(
                    [
                        "git",
                        "bisect",
                        "run",
                        "make",
                        "-C",
                        str(self._config.repo_root),
                        "bisect-probe",
                    ],
                    cwd=worktree_dir,
                    timeout=self._config.staging_bisect_runtime_cap_seconds,
                )
            except TimeoutError as exc:
                raise BisectTimeoutError(
                    f"bisect exceeded {self._config.staging_bisect_runtime_cap_seconds}s"
                ) from exc
            if rc not in (0, 1):
                raise BisectHarnessError(
                    f"git bisect run errored (rc={rc}): {err[:500]}"
                )
            match = re.search(r"([0-9a-f]{7,40})\s+is the first bad commit", out)
            if not match:
                raise BisectHarnessError(
                    f"could not parse first-bad SHA from bisect output: {out[:500]}"
                )
            return match.group(1)
        finally:
            await self._cleanup_worktree(worktree_dir)

    async def _run_gh(self, cmd: list[str]) -> str:
        """Run a ``gh`` command and return stdout. Overridable in tests."""
        import asyncio  # noqa: PLC0415

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=self._config.repo_root,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"gh failed: {stderr.decode()[:500]}")
        return stdout.decode()

    async def _attribute_culprit(self, sha: str) -> tuple[int, str]:
        """Resolve *sha* to ``(pr_number, pr_title)``.

        Spec §4.3 step 3: `gh api repos/.../commits/<sha>/pulls` returns the
        containing PR(s); we take the first (oldest) entry. Returns
        ``(0, "")`` if the commit belongs to no PR (direct push) or if
        ``gh`` returns malformed JSON — upstream callers treat zero as
        "unattributed" and escalate accordingly.
        """
        import json  # noqa: PLC0415

        raw = await self._run_gh(
            [
                "gh",
                "api",
                f"repos/{self._config.repo}/commits/{sha}/pulls",
                "--jq",
                "[.[] | {number, title, merge_commit_sha}]",
            ]
        )
        try:
            payload = json.loads(raw.strip() or "[]")
        except json.JSONDecodeError:
            logger.warning("Could not parse gh pulls output: %s", raw[:200])
            return 0, ""
        if not payload:
            return 0, ""
        first = payload[0]
        return int(first.get("number") or 0), str(first.get("title") or "")

    async def _check_guardrail_and_maybe_escalate(
        self,
        *,
        red_sha: str,
        culprit_sha: str,
        culprit_pr: int,
        bisect_log: str,
    ) -> dict[str, Any] | None:
        """Return None when safe to revert, escalation-result dict otherwise.

        Enforces the "second-revert-in-cycle" rule from spec §4.3 step 4.
        """
        if self._state.get_auto_reverts_in_cycle() == 0:
            return None

        title = (
            f"hitl: RC-red bisect exhausted — second red in cycle "
            f"{self._state.get_rc_cycle_id()} (rc_sha={red_sha[:12]})"
        )
        body = (
            "## RC-red bisect exhausted\n\n"
            f"A second red RC was detected inside the same cycle "
            f"(`rc_cycle_id={self._state.get_rc_cycle_id()}`).\n\n"
            f"- Current red RC head: `{red_sha}`\n"
            f"- Bisect-identified culprit: `{culprit_sha}`"
            f" (PR #{culprit_pr or 'unknown'})\n"
            f"- Auto-reverts already filed in this cycle: "
            f"{self._state.get_auto_reverts_in_cycle()}\n\n"
            "Either the prior bisect was wrong, or the damage is broader "
            "than one PR. Halting auto-revert per spec §4.3 step 4.\n\n"
            "### Bisect log\n\n"
            f"```\n{bisect_log[:5000]}\n```"
        )
        labels = ["hitl-escalation", "rc-red-bisect-exhausted"]
        issue = await self._prs.create_issue(title, body, labels)
        logger.error("StagingBisectLoop: guardrail tripped — escalated #%d", issue)
        return {"status": "guardrail_escalated", "escalation_issue": issue}

    async def _is_merge_commit(self, sha: str) -> bool:
        """Return True if *sha* has two or more parents."""
        rc, out, _err = await self._run_git(
            ["git", "rev-list", "--parents", "-n", "1", sha],
            cwd=self._config.repo_root,
            timeout=30,
        )
        if rc != 0:
            return False
        # Output is "<sha> <parent1> [<parent2> ...]"
        parts = out.strip().split()
        return len(parts) >= 3

    async def _create_pr_via_gh(
        self,
        *,
        title: str,
        body: str,
        branch: str,
        labels: list[str],
    ) -> int:
        """Open a PR via ``gh pr create``; return the PR number (0 on failure)."""
        import re  # noqa: PLC0415
        import tempfile  # noqa: PLC0415
        from pathlib import Path  # noqa: PLC0415

        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as body_fh:
            body_path = Path(body_fh.name)
            body_fh.write(body)
        try:
            cmd = [
                "gh",
                "pr",
                "create",
                "--repo",
                self._config.repo,
                "--head",
                branch,
                "--base",
                self._config.staging_branch,
                "--title",
                title,
                "--body-file",
                str(body_path),
            ]
            for label in labels:
                cmd.extend(["--label", label])
            out = await self._run_gh(cmd)
            match = re.search(r"/pull/(\d+)", out)
            return int(match.group(1)) if match else 0
        finally:
            body_path.unlink(missing_ok=True)

    async def _create_revert_pr(
        self,
        *,
        culprit_sha: str,
        culprit_pr: int,
        failing_tests: str,
        rc_pr_url: str,
        bisect_log: str,
        retry_issue_number: int,
    ) -> tuple[int, str]:
        """Create the auto-revert branch + PR. Return (pr_number, branch)."""
        from datetime import UTC, datetime  # noqa: PLC0415

        now = datetime.now(UTC)
        branch = f"auto-revert/pr-{culprit_pr}-rc-{now.strftime('%Y%m%d%H%M')}"

        # Create branch off staging
        await self._run_git(
            ["git", "fetch", "origin", self._config.staging_branch],
            cwd=self._config.repo_root,
            timeout=60,
        )
        await self._run_git(
            [
                "git",
                "checkout",
                "-b",
                branch,
                f"origin/{self._config.staging_branch}",
            ],
            cwd=self._config.repo_root,
            timeout=30,
        )

        # Run revert with -m 1 for merge commits
        is_merge = await self._is_merge_commit(culprit_sha)
        revert_cmd = ["git", "revert", "--no-edit"]
        if is_merge:
            revert_cmd += ["-m", "1"]
        revert_cmd.append(culprit_sha)
        rc, _out, err = await self._run_git(
            revert_cmd, cwd=self._config.repo_root, timeout=60
        )
        if rc != 0:
            # Abort any partial revert state
            await self._run_git(
                ["git", "revert", "--abort"],
                cwd=self._config.repo_root,
                timeout=30,
            )
            raise RevertConflictError(
                f"git revert failed for {culprit_sha}: {err[:500]}"
            )

        # Push branch
        await self._run_git(
            ["git", "push", "origin", branch],
            cwd=self._config.repo_root,
            timeout=120,
        )

        # Open PR
        title = f"Auto-revert: PR #{culprit_pr} — RC-red attribution on {failing_tests}"
        show_rc, show_out, _show_err = await self._run_git(
            ["git", "show", culprit_sha, "--stat"],
            cwd=self._config.repo_root,
            timeout=30,
        )
        stat_block = show_out if show_rc == 0 else "(git show failed)"
        retry_link = (
            f"- Retry issue: #{retry_issue_number}\n" if retry_issue_number else ""
        )
        body = (
            "## Auto-revert (StagingBisectLoop)\n\n"
            f"- Culprit SHA: `{culprit_sha}`\n"
            f"- Originating PR: #{culprit_pr}\n"
            f"- Failing tests: {failing_tests}\n"
            f"- Red RC PR: {rc_pr_url}\n"
            f"{retry_link}\n"
            "### `git show --stat`\n\n"
            f"```\n{stat_block[:3000]}\n```\n\n"
            "### Bisect log\n\n"
            f"```\n{bisect_log[:5000]}\n```\n\n"
            "_Filed per spec §4.3. Auto-merges on green per §3.2._"
        )
        pr_number = await self._create_pr_via_gh(
            title=title,
            body=body,
            branch=branch,
            labels=["hydraflow-find", "auto-revert", "rc-red-attribution"],
        )
        return pr_number, branch

    async def _file_retry_issue(
        self,
        *,
        culprit_pr: int,
        culprit_pr_title: str,
        culprit_sha: str,
        green_sha: str,
        red_sha: str,
        failing_tests: str,
        bisect_log: str,
        revert_pr_url: str,
    ) -> int:
        """File a ``hydraflow-find`` retry issue and return its number."""
        title = f"Retry: {culprit_pr_title or f'PR #{culprit_pr}'}"
        body = (
            "## Retry request\n\n"
            f"Original PR #{culprit_pr} (`{culprit_sha}`) was auto-reverted "
            f"after bisect attributed it to the red RC "
            f"({green_sha[:12]}..{red_sha[:12]}).\n\n"
            f"- Reverted PR: {revert_pr_url}\n"
            f"- Failing tests: {failing_tests}\n"
            f"- Time bounds: `{green_sha}` (last green) → `{red_sha}` (red)\n\n"
            "### Bisect log\n\n"
            f"```\n{bisect_log[:5000]}\n```\n\n"
            "_Factory picks up `hydraflow-find` issues; the work re-enters "
            "the standard implement/review pipeline._"
        )
        return await self._prs.create_issue(
            title, body, ["hydraflow-find", "rc-red-retry"]
        )
