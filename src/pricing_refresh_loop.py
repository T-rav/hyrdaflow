"""PricingRefreshLoop — daily upstream-pricing refresh caretaker.

Per ADR-0029 (caretaker pattern), ADR-0049 (kill-switch convention),
and the design at docs/superpowers/specs/2026-04-26-pricing-refresh-loop-design.md.

Tick behavior:
  1. Fetch LiteLLM's model_prices_and_context_window.json (urllib stdlib, 30s).
  2. Filter to anthropic-provider entries; normalize Bedrock keys.
  3. Diff against src/assets/model_pricing.json. Bounds-guard rejects
     suspicious price moves.
  4. If no changes: log "no drift", return {drift: False}.
  5. Else: write proposed file, open/update PR via auto_pr.open_automated_pr_async
     on fixed branch `pricing-refresh-auto`.
  6. Bounds violations / parse errors / schema errors → open one
     `[pricing-refresh] ...` hydraflow-find issue (deduped by title prefix).
  7. Network errors → log + retry next tick (no issue spam).

Kill switch: HYDRAFLOW_DISABLE_PRICING_REFRESH=1.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import WorkCycleResult
from pricing_refresh_diff import (
    BoundsViolation,
    PricingDiff,
    compute_pricing_diff,
    filter_anthropic_entries,
)

logger = logging.getLogger(__name__)

_KILL_SWITCH_ENV = "HYDRAFLOW_DISABLE_PRICING_REFRESH"
_REGEN_BRANCH = "pricing-refresh-auto"
_PR_TITLE_PREFIX = "chore(pricing): refresh from LiteLLM"
_ISSUE_TITLE_PREFIX = "[pricing-refresh]"
_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)
_FETCH_TIMEOUT_S = 30


class PricingRefreshLoop(BaseBackgroundLoop):
    """Daily caretaker — keeps src/assets/model_pricing.json in sync with LiteLLM."""

    def __init__(
        self,
        *,
        config: HydraFlowConfig,
        pr_manager,  # PRPort
        deps: LoopDeps,
    ) -> None:
        super().__init__(
            worker_name="pricing-refresh-loop",
            config=config,
            deps=deps,
        )
        self._pr_manager = pr_manager
        self._repo_root = Path.cwd()

    def _set_repo_root(self, path: Path) -> None:
        """Test seam: redirect the loop at a worktree without subclassing."""
        self._repo_root = Path(path)

    def _get_default_interval(self) -> int:
        # 24 hours — daily.
        return 86400

    async def _do_work(self) -> WorkCycleResult:  # noqa: PLR0911 — linear gate checks, each with its own return path
        # Kill-switch (ADR-0049). Belt and suspenders.
        if os.environ.get(_KILL_SWITCH_ENV) == "1":
            return {"skipped": "kill_switch"}

        try:
            upstream_raw = await self._fetch_upstream()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            # Network errors are silent — retry next tick, no issue spam.
            logger.warning("PricingRefreshLoop fetch failed: %s", exc)
            return {"drift": False, "error": "network"}
        except json.JSONDecodeError as exc:
            # Upstream returned non-JSON (or partial JSON). This is unusual
            # enough to deserve a dedup'd issue — not silent.
            logger.warning("PricingRefreshLoop upstream parse failed: %s", exc)
            await self._open_parse_issue(str(exc))
            return {"drift": False, "error": "parse"}

        upstream = filter_anthropic_entries(upstream_raw)
        local = self._read_local_models()

        diff = compute_pricing_diff(local=local, upstream=upstream)

        if diff.bounds_violations:
            await self._open_bounds_issue(diff.bounds_violations)
            return {
                "drift": False,
                "error": "bounds",
                "violations": len(diff.bounds_violations),
            }

        if not diff.updated and not diff.added:
            return {"drift": False}

        # Atomic write+PR: capture original bytes so we can revert if the
        # PR-opening step fails. Without this, a successful file write
        # followed by an auto_pr failure would leave the worktree mutated
        # but no PR open — next tick reads the mutation as "local", sees
        # no diff vs upstream, and never proposes the change again.
        pricing_path = self._repo_root / "src" / "assets" / "model_pricing.json"
        original_bytes = pricing_path.read_bytes()
        self._apply_diff_to_pricing_file(diff)

        try:
            pr_url = await self._open_or_update_refresh_pr(diff)
        except Exception:
            pricing_path.write_bytes(original_bytes)
            raise

        if pr_url is None:
            # auto_pr returned a non-success status (logged inside
            # _open_or_update_refresh_pr). Revert so the file is consistent
            # with what landed on the remote.
            pricing_path.write_bytes(original_bytes)
            return {
                "drift": True,
                "updated": len(diff.updated),
                "added": len(diff.added),
                "pr_url": None,
                "error": "pr_failed",
            }

        return {
            "drift": True,
            "updated": len(diff.updated),
            "added": len(diff.added),
            "pr_url": pr_url,
        }

    async def _fetch_upstream(self) -> dict[str, Any]:
        """Fetch LiteLLM JSON via stdlib urllib. Raises on network/HTTP errors.

        ``json.JSONDecodeError`` from a malformed body propagates; the
        caller in ``_do_work`` handles parse errors as a deduped issue.
        """

        def _do() -> dict[str, Any]:
            with urllib.request.urlopen(_LITELLM_URL, timeout=_FETCH_TIMEOUT_S) as resp:
                return json.loads(resp.read())

        return await asyncio.to_thread(_do)

    def _read_local_models(self) -> dict[str, dict[str, Any]]:
        path = self._repo_root / "src" / "assets" / "model_pricing.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.get("models", {})
        if not isinstance(models, dict):
            return {}
        return models

    def _apply_diff_to_pricing_file(self, diff: PricingDiff) -> None:
        """Merge diff into the on-disk pricing file. Bumps updated_at."""
        path = self._repo_root / "src" / "assets" / "model_pricing.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        models = data.setdefault("models", {})

        for model, fields in diff.updated.items():
            entry = models.get(model)
            if entry is None:
                continue  # safety: shouldn't happen — updated was keyed off local
            entry.update(fields)

        for model, entry in diff.added.items():
            models[model] = entry

        data["updated_at"] = datetime.now(UTC).strftime("%Y-%m-%d")

        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    async def _open_or_update_refresh_pr(self, diff: PricingDiff) -> str | None:
        # Lazy import to avoid a top-level dependency cycle.
        from auto_pr import open_automated_pr_async  # noqa: PLC0415

        today = datetime.now(UTC).strftime("%Y-%m-%d")
        pr_title = f"{_PR_TITLE_PREFIX} — {today}"
        pr_body = self._build_pr_body(diff)

        files_to_commit = [self._repo_root / "src" / "assets" / "model_pricing.json"]

        result = await open_automated_pr_async(
            repo_root=self._repo_root,
            branch=_REGEN_BRANCH,
            files=files_to_commit,
            pr_title=pr_title,
            pr_body=pr_body,
            base="main",
            auto_merge=False,  # Always human-reviewed per spec §3.
            labels=["hydraflow-ready", "pricing-refresh"],
            raise_on_failure=False,
        )
        if result.status in {"opened", "no-diff"}:
            return result.pr_url
        logger.warning("PricingRefreshLoop PR creation failed: %s", result.error)
        return None

    def _build_pr_body(self, diff: PricingDiff) -> str:
        lines = [
            "Auto-generated by `PricingRefreshLoop`. The pricing data in",
            "`src/assets/model_pricing.json` was refreshed from LiteLLM's",
            "structured upstream JSON.",
            "",
        ]
        if diff.updated:
            lines.append(f"**Updated** ({len(diff.updated)} model(s)):")
            lines.append("")
            for model, fields in sorted(diff.updated.items()):
                changes = ", ".join(f"{k}={v}" for k, v in fields.items())
                lines.append(f"- `{model}`: {changes}")
            lines.append("")
        if diff.added:
            lines.append(f"**Added** ({len(diff.added)} model(s)):")
            lines.append("")
            for model in sorted(diff.added):
                lines.append(f"- `{model}`")
            lines.append("")
        lines.extend(
            [
                "Source: <https://github.com/BerriAI/litellm/blob/main/"
                "model_prices_and_context_window.json>",
                "",
                "Per ADR-0029 caretaker pattern. **Human review required**;",
                "loop never auto-merges pricing changes.",
            ]
        )
        return "\n".join(lines)

    async def _open_bounds_issue(self, violations: list[BoundsViolation]) -> None:
        title = f"{_ISSUE_TITLE_PREFIX} bounds violation"
        existing = await self._pr_manager.find_existing_issue(title)
        if existing:
            return
        body_lines = [
            "PricingRefreshLoop rejected an upstream pricing update because",
            "one or more cost fields moved outside the bounds guard (>+100% or <-50%).",
            "",
            "**Violations:**",
            "",
        ]
        for bv in violations:
            body_lines.append(
                f"- `{bv.model}` `{bv.field}`: {bv.old} → {bv.new} "
                f"(ratio={bv.ratio:.2f})"
            )
        body_lines.extend(
            [
                "",
                "Verify against <https://docs.anthropic.com/en/docs/about-claude/models>",
                "and update `src/assets/model_pricing.json` manually if the",
                "upstream values are correct.",
            ]
        )
        await self._pr_manager.create_issue(
            title=title,
            body="\n".join(body_lines),
            labels=["hydraflow-find", "pricing-refresh"],
        )

    async def _open_parse_issue(self, detail: str) -> None:
        title = f"{_ISSUE_TITLE_PREFIX} upstream parse error"
        existing = await self._pr_manager.find_existing_issue(title)
        if existing:
            return
        body = (
            "PricingRefreshLoop could not parse LiteLLM's upstream JSON.\n\n"
            f"**Source:** <{_LITELLM_URL}>\n\n"
            f"**Error:** `{detail}`\n\n"
            "If this persists, the upstream URL may have moved or the JSON "
            "schema may have changed. Update the loop's source URL or "
            "fetch path as needed."
        )
        await self._pr_manager.create_issue(
            title=title,
            body=body,
            labels=["hydraflow-find", "pricing-refresh"],
        )
