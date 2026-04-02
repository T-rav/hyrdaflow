"""Shared prompt prefix builder for parallel subagent dispatch.

Constructs a deterministic, cacheable prefix that is identical across
all agents in a batch, maximizing KV cache reuse. Task-specific
instructions are appended as suffixes.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from hindsight import HindsightClient

logger = logging.getLogger("hydraflow.shared_prompt_prefix")


class SharedPromptPrefix:
    """Builds a shared context prefix for parallel subagent dispatch."""

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._prefix: str | None = None

    async def build(
        self,
        *,
        hindsight: HindsightClient | None = None,
        query_context: str = "",
    ) -> str:
        """Build the shared prefix once for the batch.

        Includes: CLAUDE.md content, memory context, repo state.
        The prefix is cached — subsequent calls return the same string.
        """
        if self._prefix is not None:
            return self._prefix

        parts: list[str] = []

        # 1. Project conventions (static per repo)
        claude_md = self._load_claude_md()
        if claude_md:
            parts.append(f"## Project Conventions\n\n{claude_md}")

        # 2. Memory context (recalled once, shared across agents)
        if hindsight and query_context:
            memory = await self._recall_shared_memory(hindsight, query_context)
            if memory:
                parts.append(memory)

        # 3. Repo state snapshot
        repo_state = self._get_repo_state()
        if repo_state:
            parts.append(f"## Repository State\n\n{repo_state}")

        self._prefix = "\n\n".join(parts)
        return self._prefix

    @property
    def prefix_chars(self) -> int:
        """Return the length of the cached prefix, or 0 if not yet built."""
        return len(self._prefix) if self._prefix else 0

    def with_task(self, task_instructions: str) -> str:
        """Append task-specific instructions to the shared prefix.

        Raises RuntimeError if build() has not been called.
        """
        if self._prefix is None:
            raise RuntimeError("Call build() before with_task()")
        return f"{self._prefix}\n\n---\n\n## Your Task\n\n{task_instructions}"

    def _load_claude_md(self) -> str:
        """Load CLAUDE.md from repo root if it exists."""
        path = Path(self._config.repo_root) / "CLAUDE.md"
        try:
            if path.exists():
                text = path.read_text()
                max_chars = self._config.max_memory_prompt_chars
                return text[:max_chars]
        except OSError:
            logger.debug("Could not read CLAUDE.md", exc_info=True)
        return ""

    async def _recall_shared_memory(
        self,
        hindsight: HindsightClient,
        query_context: str,
    ) -> str:
        """Recall memory from Hindsight once for the batch."""
        try:
            from hindsight import Bank, format_memories_as_markdown, recall_safe

            max_chars = self._config.max_memory_prompt_chars
            combined: list[str] = []

            for bank, heading in [
                (Bank.LEARNINGS, "Accumulated Learnings"),
                (Bank.TROUBLESHOOTING, "Known Troubleshooting Patterns"),
                (Bank.RETROSPECTIVES, "Past Retrospectives"),
            ]:
                try:
                    memories = await recall_safe(hindsight, bank, query_context)
                    raw = format_memories_as_markdown(memories)
                    if raw:
                        combined.append(f"## {heading}\n\n{raw[:max_chars]}")
                except Exception:  # noqa: BLE001
                    pass

            return "\n\n".join(combined) if combined else ""
        except ImportError:
            return ""

    def _get_repo_state(self) -> str:
        """Get a deterministic snapshot of repo state."""
        import subprocess  # noqa: PLC0415

        try:
            result = subprocess.run(  # noqa: S603, S607
                ["git", "log", "--oneline", "-5"],
                check=False,
                cwd=str(self._config.repo_root),
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                branch_result = subprocess.run(  # noqa: S603, S607
                    ["git", "branch", "--show-current"],
                    check=False,
                    cwd=str(self._config.repo_root),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                branch = (
                    branch_result.stdout.strip()
                    if branch_result.returncode == 0
                    else "unknown"
                )
                return f"Branch: {branch}\n\nRecent commits:\n{result.stdout.strip()}"
        except (OSError, subprocess.TimeoutExpired):
            pass
        return ""
