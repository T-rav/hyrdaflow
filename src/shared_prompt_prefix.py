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
    from context_cache import ContextSectionCache
    from hindsight import HindsightClient

logger = logging.getLogger("hydraflow.shared_prompt_prefix")

# Generic query used for all shared-prefix memory recalls.
_SHARED_QUERY = "project conventions, common patterns, known issues, troubleshooting"


class SharedPromptPrefix:
    """Builds a shared context prefix for parallel subagent dispatch."""

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._prefix: str | None = None

    async def build(
        self,
        *,
        hindsight: HindsightClient | None = None,
        context_cache: ContextSectionCache | None = None,
    ) -> str:
        """Build the shared prefix once for the batch.

        Includes: manifest, CLAUDE.md content, memory context, repo state.
        The prefix is cached — subsequent calls return the same string.
        """
        if self._prefix is not None:
            return self._prefix

        parts: list[str] = []

        # 1. Project manifest (auto-detected project metadata)
        manifest = self._load_manifest()
        if manifest:
            parts.append(manifest)

        # 2. Project conventions (static per repo)
        claude_md = self._load_claude_md(context_cache)
        if claude_md:
            parts.append(f"## Project Conventions\n\n{claude_md}")

        # 3. Memory context (recalled once, shared across agents)
        if hindsight is not None:
            memory = await self._recall_shared_memory(hindsight)
            if memory:
                parts.append(memory)

        # 4. Repo state snapshot
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

    def _load_manifest(self) -> str:
        """Load the project manifest from .hydraflow/manifest/manifest.md."""
        import manifest as manifest_mod  # noqa: PLC0415

        return manifest_mod.load_project_manifest(self._config)

    def _load_claude_md(self, context_cache: ContextSectionCache | None = None) -> str:
        """Load CLAUDE.md from repo root, using the cache when provided."""
        path = Path(self._config.repo_root) / "CLAUDE.md"
        if context_cache is not None:
            content, _ = context_cache.get_or_load(
                key="claude_md",
                source_path=path,
                loader=self._read_claude_md,
            )
            return content
        return self._read_claude_md(self._config)

    @staticmethod
    def _read_claude_md(config: HydraFlowConfig) -> str:
        """Read CLAUDE.md from disk (used as a loader callback)."""
        path = Path(config.repo_root) / "CLAUDE.md"
        try:
            if path.exists():
                text = path.read_text()
                max_chars = config.max_memory_prompt_chars
                return text[:max_chars]
        except OSError:
            logger.debug("Could not read CLAUDE.md", exc_info=True)
        return ""

    async def _recall_shared_memory(self, hindsight: HindsightClient) -> str:
        """Recall memory from all 5 Hindsight banks and deduplicate."""
        try:
            from hindsight import (  # noqa: PLC0415
                Bank,
                format_memories_as_markdown,
                recall_safe,
            )
        except ImportError:
            return ""

        max_chars = self._config.max_memory_prompt_chars
        query = _SHARED_QUERY

        bank_specs = [
            (Bank.LEARNINGS, "Accumulated Learnings"),
            (Bank.TROUBLESHOOTING, "Known Troubleshooting Patterns"),
            (Bank.RETROSPECTIVES, "Past Retrospectives"),
            (Bank.REVIEW_INSIGHTS, "Common Review Patterns"),
            (Bank.HARNESS_INSIGHTS, "Known Pipeline Patterns"),
        ]

        # Recall each bank independently; failures must not interrupt the build.
        raw_by_bank: list[tuple[str, str]] = []
        for bank, heading in bank_specs:
            try:
                memories = await recall_safe(hindsight, bank, query)
                raw = format_memories_as_markdown(memories)
                if raw:
                    raw_by_bank.append((heading, raw[:max_chars]))
            except Exception:  # noqa: BLE001
                pass

        if not raw_by_bank:
            return ""

        # Flatten all items for cross-bank deduplication.
        from prompt_dedup import PromptDeduplicator  # noqa: PLC0415

        deduper = PromptDeduplicator()
        all_items: list[str] = []
        for _, raw in raw_by_bank:
            items = [f"- {chunk}" for chunk in raw.split("\n- ") if chunk.strip()]
            if items and items[0].startswith("- - "):
                items[0] = items[0][2:]
            all_items.extend(items)

        deduped_set = set(deduper.dedup_memories(all_items))

        # Rebuild per-bank sections keeping only surviving items.
        combined: list[str] = []
        for heading, raw in raw_by_bank:
            items = [f"- {chunk}" for chunk in raw.split("\n- ") if chunk.strip()]
            if items and items[0].startswith("- - "):
                items[0] = items[0][2:]
            kept = [item for item in items if item in deduped_set]
            if kept:
                combined.append(f"## {heading}\n\n" + "\n".join(kept))

        return "\n\n".join(combined) if combined else ""

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
