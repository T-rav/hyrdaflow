"""Production adapters wiring TermProposerLoop to real subprocess infrastructure.

`ClaudeCLIClient` implements the `LLMClient` Protocol by shelling out to a
configured agent CLI tool (`claude`/`codex`/`gemini`) via the project's
`SubprocessRunner`. Mirrors the lightweight-call pattern from
`wiki_compiler.WikiCompiler._call_model`.

`OpenAutoPRBotPRPort` implements the `BotPRPort` Protocol by writing draft
files to disk and delegating to `auto_pr.open_automated_pr_async` for the
worktree → commit → push → `gh pr create` flow.

Wired into `service_registry.build_services` (replaces the chunk-2
placeholder clients that raised NotImplementedError on first tick).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agent_cli import AgentTool

if TYPE_CHECKING:
    from execution import SubprocessRunner

logger = logging.getLogger("hydraflow.term_proposer_runtime")


class ClaudeCLIClient:
    """Subprocess-CLI adapter for the LLMClient Protocol.

    Invokes `claude -p` (or another agent tool) one-shot via SubprocessRunner;
    parses JSON out of stdout. Tolerant of markdown fences around the JSON
    payload (model output sometimes wraps in ```json ... ```).
    """

    def __init__(
        self,
        runner: SubprocessRunner,
        *,
        tool: AgentTool = "claude",
        model: str = "claude-sonnet-4-5",
        timeout: int = 180,
    ) -> None:
        self._runner = runner
        self._tool: AgentTool = tool
        self._model = model
        self._timeout = timeout

    async def complete_structured(
        self, *, prompt: str, schema: dict[str, Any]
    ) -> dict[str, Any]:
        """Send prompt to the CLI tool and return the parsed JSON object.

        `schema` is unused by the CLI path (the prompt itself instructs the
        model on output shape); kept in the signature to satisfy the Protocol.
        """
        del schema
        from agent_cli import build_lightweight_command  # noqa: PLC0415

        cmd, cmd_input = build_lightweight_command(
            tool=self._tool, model=self._model, prompt=prompt
        )
        result = await self._runner.run_simple(
            cmd, input=cmd_input, timeout=self._timeout
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"{self._tool} CLI failed (rc={result.returncode}): "
                f"{result.stderr[:200]}"
            )
        return self._extract_json(result.stdout)

    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """Pull a JSON object out of CLI stdout (tolerant of markdown fences)."""
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise RuntimeError(f"no JSON object in CLI output: {text[:200]}")
        return json.loads(match.group(0))


class OpenAutoPRBotPRPort:
    """BotPRPort adapter wrapping auto_pr.open_automated_pr_async.

    Writes each draft term file under repo_root, then delegates the full
    worktree-copy → commit → push → `gh pr create` flow to the existing
    helper. Sets `auto_merge=False` — DependabotMergeLoop handles auto-merge
    once the PR carries `hydraflow-ul-proposed`.
    """

    def __init__(self, *, repo_root: Path, gh_token: str = "") -> None:
        self._repo_root = repo_root
        self._gh_token = gh_token

    async def open_bot_pr(
        self,
        *,
        branch: str,
        title: str,
        body: str,
        labels: list[str],
        files: dict[str, str],
    ) -> int:
        """Write files to disk and open a PR. Returns the PR number."""
        from auto_pr import open_automated_pr_async  # noqa: PLC0415

        written_paths: list[Path] = []
        for rel_path, content in files.items():
            abs_path = self._repo_root / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            written_paths.append(abs_path)

        result = await open_automated_pr_async(
            repo_root=self._repo_root,
            branch=branch,
            files=written_paths,
            pr_title=title,
            pr_body=body,
            base="main",
            auto_merge=False,
            gh_token=self._gh_token,
            raise_on_failure=False,
            labels=labels,
        )

        if result.status != "opened" or result.pr_url is None:
            raise RuntimeError(
                f"open_automated_pr_async returned status={result.status!r} "
                f"error={result.error!r}"
            )
        return self._extract_pr_number(result.pr_url)

    @staticmethod
    def _extract_pr_number(pr_url: str) -> int:
        """Parse a github.com PR URL like '.../pull/4242' to its int number."""
        match = re.search(r"/pull/(\d+)", pr_url)
        if not match:
            raise RuntimeError(f"could not parse PR number from {pr_url!r}")
        return int(match.group(1))
