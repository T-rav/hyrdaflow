# Shared Prompt Prefix Cache Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Structure parallel subagent prompts to share an identical context prefix, maximizing KV cache reuse across concurrent agents.

**Architecture:** Enhance existing `SharedPromptPrefix` to build a full prefix (manifest + CLAUDE.md + 5-bank memory + repo state). Phases build the prefix once before batch dispatch. Runners receive it via `shared_prefix` parameter, skip redundant loading, and do a small issue-specific memory top-up as a suffix. Telemetry tracks cache reuse ratio.

**Tech Stack:** Python 3.11, async, Pydantic, existing Hindsight/PromptDeduplicator/ContextSectionCache infrastructure.

---

### Task 1: Add `hindsight` property to BaseRunner

**Files:**
- Modify: `src/base_runner.py:56-59`
- Test: `tests/test_base_runner_shared_prefix.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_base_runner_shared_prefix.py`:

```python
"""Tests for BaseRunner shared_prefix integration."""

from unittest.mock import AsyncMock, MagicMock

from base_runner import BaseRunner


def _make_runner(*, hindsight=None):
    config = MagicMock()
    config.model = "opus"
    config.implementation_tool = "claude"
    config.data_dir = "/tmp/test"
    event_bus = MagicMock()
    runner = MagicMock()
    # BaseRunner is abstract-ish — instantiate directly for property tests
    br = BaseRunner.__new__(BaseRunner)
    br._config = config
    br._bus = event_bus
    br._active_procs = set()
    br._runner = runner
    br._prompt_telemetry = MagicMock()
    br._last_context_stats = {"cache_hits": 0, "cache_misses": 0}
    br._hindsight = hindsight
    return br


class TestBaseRunnerHindsightProperty:
    def test_hindsight_returns_client(self):
        client = MagicMock()
        br = _make_runner(hindsight=client)
        assert br.hindsight is client

    def test_hindsight_returns_none(self):
        br = _make_runner(hindsight=None)
        assert br.hindsight is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_base_runner_shared_prefix.py::TestBaseRunnerHindsightProperty -v`
Expected: FAIL with `AttributeError: 'BaseRunner' object has no attribute 'hindsight'`

- [ ] **Step 3: Write minimal implementation**

Add to `src/base_runner.py` after the `active_count` property (after line 59):

```python
    @property
    def hindsight(self) -> HindsightClient | None:
        """Read-only access to the Hindsight client for shared prefix building."""
        return self._hindsight
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_base_runner_shared_prefix.py::TestBaseRunnerHindsightProperty -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/base_runner.py tests/test_base_runner_shared_prefix.py
git commit -m "feat: add hindsight property to BaseRunner (#5938)"
```

---

### Task 2: Enhance SharedPromptPrefix — manifest, 5 banks, dedup, ContextSectionCache

**Files:**
- Modify: `src/shared_prompt_prefix.py`
- Create: `tests/test_shared_prompt_prefix.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_shared_prompt_prefix.py`:

```python
"""Tests for SharedPromptPrefix — shared context prefix for parallel agents."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from shared_prompt_prefix import SharedPromptPrefix


def _make_config(repo_root="/tmp/test-repo"):
    config = MagicMock()
    config.repo_root = repo_root
    config.max_memory_prompt_chars = 4000
    config.data_path.return_value = MagicMock()
    return config


class TestSharedPromptPrefixBuild:
    @pytest.mark.asyncio
    async def test_build_caches_on_second_call(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        with patch.object(builder, "_load_claude_md", return_value="# CLAUDE"), \
             patch.object(builder, "_load_manifest", return_value="# Manifest"), \
             patch.object(builder, "_recall_shared_memory", new_callable=AsyncMock, return_value="## Memory\n\nlearnings"), \
             patch.object(builder, "_get_repo_state", return_value="Branch: main"):
            first = await builder.build(hindsight=MagicMock())
            second = await builder.build(hindsight=MagicMock())
            assert first == second
            assert first is second  # same object, not rebuilt

    @pytest.mark.asyncio
    async def test_build_includes_all_sections(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        with patch.object(builder, "_load_claude_md", return_value="conventions here"), \
             patch.object(builder, "_load_manifest", return_value="manifest here"), \
             patch.object(builder, "_recall_shared_memory", new_callable=AsyncMock, return_value="## Learnings\n\nmemory here"), \
             patch.object(builder, "_get_repo_state", return_value="Branch: main"):
            result = await builder.build(hindsight=MagicMock())
            assert "conventions here" in result
            assert "manifest here" in result
            assert "memory here" in result
            assert "Branch: main" in result

    @pytest.mark.asyncio
    async def test_build_without_hindsight_omits_memory(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        with patch.object(builder, "_load_claude_md", return_value="conventions"), \
             patch.object(builder, "_load_manifest", return_value=""), \
             patch.object(builder, "_get_repo_state", return_value=""):
            result = await builder.build(hindsight=None)
            assert "conventions" in result
            assert "Learnings" not in result

    def test_prefix_chars_before_build(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        assert builder.prefix_chars == 0

    @pytest.mark.asyncio
    async def test_prefix_chars_after_build(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        with patch.object(builder, "_load_claude_md", return_value="hello"), \
             patch.object(builder, "_load_manifest", return_value=""), \
             patch.object(builder, "_recall_shared_memory", new_callable=AsyncMock, return_value=""), \
             patch.object(builder, "_get_repo_state", return_value=""):
            await builder.build()
            assert builder.prefix_chars > 0


class TestSharedPromptPrefixWithTask:
    @pytest.mark.asyncio
    async def test_with_task_appends_suffix(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        with patch.object(builder, "_load_claude_md", return_value="conventions"), \
             patch.object(builder, "_load_manifest", return_value=""), \
             patch.object(builder, "_recall_shared_memory", new_callable=AsyncMock, return_value=""), \
             patch.object(builder, "_get_repo_state", return_value=""):
            await builder.build()
            result = builder.with_task("Do task X")
            assert "conventions" in result
            assert "Do task X" in result
            assert "---" in result

    def test_with_task_before_build_raises(self):
        config = _make_config()
        builder = SharedPromptPrefix(config)
        with pytest.raises(RuntimeError, match="Call build"):
            builder.with_task("anything")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_shared_prompt_prefix.py -v`
Expected: FAIL (missing `_load_manifest` method, missing 5-bank recall with dedup)

- [ ] **Step 3: Rewrite SharedPromptPrefix**

Replace `src/shared_prompt_prefix.py` with the enhanced version:

```python
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

# Broad query for shared memory recall — not issue-specific
_GENERIC_QUERY = "project conventions, common patterns, known issues, troubleshooting"


class SharedPromptPrefix:
    """Builds a shared context prefix for parallel subagent dispatch.

    The prefix is identical across all agents in a batch, maximizing
    KV cache reuse. Task-specific instructions are appended as suffixes
    via :meth:`with_task`.
    """

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

        Includes: project manifest, CLAUDE.md content, 5-bank memory
        recall (deduplicated), repo state snapshot.
        The prefix is cached — subsequent calls return the same string.
        """
        if self._prefix is not None:
            return self._prefix

        parts: list[str] = []

        # 1. Project manifest (static per repo)
        manifest = self._load_manifest(context_cache)
        if manifest:
            parts.append(f"## Project Manifest\n\n{manifest}")

        # 2. Project conventions from CLAUDE.md
        claude_md = self._load_claude_md(context_cache)
        if claude_md:
            parts.append(f"## Project Conventions\n\n{claude_md}")

        # 3. Memory context — all 5 banks, deduplicated, recalled once
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

    def _load_claude_md(self, context_cache: ContextSectionCache | None = None) -> str:
        """Load CLAUDE.md from repo root if it exists."""
        path = Path(self._config.repo_root) / "CLAUDE.md"
        if context_cache is not None:
            try:
                content, _hit = context_cache.get_or_load(
                    key="claude_md",
                    source_path=path,
                    loader=lambda cfg: _read_file_safe(Path(cfg.repo_root) / "CLAUDE.md", cfg.max_memory_prompt_chars),
                )
                return content
            except Exception:  # noqa: BLE001
                pass
        return _read_file_safe(path, self._config.max_memory_prompt_chars)

    def _load_manifest(self, context_cache: ContextSectionCache | None = None) -> str:
        """Load the project manifest if it exists."""
        from manifest import load_project_manifest  # noqa: PLC0415

        try:
            return load_project_manifest(self._config)
        except Exception:  # noqa: BLE001
            return ""

    async def _recall_shared_memory(
        self,
        hindsight: HindsightClient,
    ) -> str:
        """Recall memory from all 5 Hindsight banks, deduplicated."""
        try:
            from hindsight import Bank, format_memories_as_markdown, recall_safe  # noqa: PLC0415
            from prompt_dedup import PromptDeduplicator  # noqa: PLC0415

            max_chars = self._config.max_memory_prompt_chars
            all_items: list[str] = []
            bank_sections: dict[str, str] = {}

            banks = [
                (Bank.LEARNINGS, "Accumulated Learnings"),
                (Bank.TROUBLESHOOTING, "Known Troubleshooting Patterns"),
                (Bank.RETROSPECTIVES, "Past Retrospectives"),
                (Bank.REVIEW_INSIGHTS, "Common Review Patterns"),
                (Bank.HARNESS_INSIGHTS, "Known Pipeline Patterns"),
            ]

            for bank, heading in banks:
                try:
                    memories = await recall_safe(hindsight, bank, _GENERIC_QUERY)
                    raw = format_memories_as_markdown(memories)
                    if raw:
                        raw = raw[:max_chars]
                        bank_sections[heading] = raw
                        items = [f"- {chunk}" for chunk in raw.split("\n- ") if chunk.strip()]
                        if items and items[0].startswith("- - "):
                            items[0] = items[0][2:]
                        all_items.extend(items)
                except Exception:  # noqa: BLE001
                    pass

            # Deduplicate across banks
            deduper = PromptDeduplicator()
            deduped = set(deduper.dedup_memories(all_items))

            # Rebuild sections with only deduped items
            combined_parts: list[str] = []
            for heading, raw in bank_sections.items():
                items = [f"- {chunk}" for chunk in raw.split("\n- ") if chunk.strip()]
                if items and items[0].startswith("- - "):
                    items[0] = items[0][2:]
                kept = [item for item in items if item in deduped]
                if kept:
                    combined_parts.append(f"## {heading}\n\n" + "\n".join(kept))

            if combined_parts:
                combined = "\n\n".join(combined_parts)
                return combined[:max_chars]
            return ""
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


def _read_file_safe(path: Path, max_chars: int) -> str:
    """Read a file, returning empty string on any error."""
    try:
        if path.exists():
            return path.read_text()[:max_chars]
    except OSError:
        logger.debug("Could not read %s", path, exc_info=True)
    return ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_shared_prompt_prefix.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/shared_prompt_prefix.py tests/test_shared_prompt_prefix.py
git commit -m "feat: enhance SharedPromptPrefix with manifest, 5 banks, dedup (#5938)"
```

---

### Task 3: Add shared_prefix mode to _inject_manifest_and_memory

**Files:**
- Modify: `src/base_runner.py:180-370`
- Test: `tests/test_base_runner_shared_prefix.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_base_runner_shared_prefix.py`:

```python
import pytest


class TestInjectManifestAndMemorySharedPrefix:
    @pytest.mark.asyncio
    async def test_shared_prefix_skips_full_recall(self):
        """When shared_prefix is provided, skip manifest and full 5-bank recall."""
        hindsight = MagicMock()
        br = _make_runner(hindsight=hindsight)
        br._config.max_memory_prompt_chars = 4000

        with patch("base_runner.recall_safe", new_callable=AsyncMock) as mock_recall, \
             patch("base_runner.format_memories_as_markdown", return_value="- topup item"):
            mock_recall.return_value = [MagicMock()]

            prefix_section, topup_section = await br._inject_manifest_and_memory(
                query_context="issue about auth",
                shared_prefix="SHARED PREFIX CONTENT",
            )

            assert prefix_section == "SHARED PREFIX CONTENT"
            assert "topup" in topup_section
            # Should recall only once (LEARNINGS top-up), not 5 times
            assert mock_recall.call_count == 1

    @pytest.mark.asyncio
    async def test_shared_prefix_none_uses_existing_behavior(self):
        """When shared_prefix is None, full existing behavior runs."""
        br = _make_runner(hindsight=None)
        br._config.max_memory_prompt_chars = 4000

        prefix_section, memory_section = await br._inject_manifest_and_memory(
            query_context="test",
            shared_prefix=None,
        )

        # Without hindsight, both sections are empty strings
        assert prefix_section == ""
        assert memory_section == ""

    @pytest.mark.asyncio
    async def test_shared_prefix_topup_capped(self):
        """Top-up memory is capped at max_memory_prompt_chars // 4."""
        hindsight = MagicMock()
        br = _make_runner(hindsight=hindsight)
        br._config.max_memory_prompt_chars = 400  # top-up cap = 100

        long_memory = "x" * 500

        with patch("base_runner.recall_safe", new_callable=AsyncMock) as mock_recall, \
             patch("base_runner.format_memories_as_markdown", return_value=long_memory):
            mock_recall.return_value = [MagicMock()]

            _, topup_section = await br._inject_manifest_and_memory(
                query_context="test",
                shared_prefix="PREFIX",
            )

            # Top-up should be capped
            assert len(topup_section) <= 400 // 4 + 50  # some heading overhead
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_base_runner_shared_prefix.py::TestInjectManifestAndMemorySharedPrefix -v`
Expected: FAIL (shared_prefix parameter not accepted)

- [ ] **Step 3: Modify _inject_manifest_and_memory**

In `src/base_runner.py`, change the method signature at line 180:

```python
    async def _inject_manifest_and_memory(
        self, *, query_context: str = "", shared_prefix: str | None = None
    ) -> tuple[str, str]:
```

Add early-return path at line ~192 (before existing logic):

```python
        # --- Shared prefix mode: skip full recall, do issue-specific top-up ---
        if shared_prefix is not None:
            topup_section = ""
            if self._hindsight and query_context:
                try:
                    from hindsight import Bank, format_memories_as_markdown, recall_safe

                    topup_cap = self._config.max_memory_prompt_chars // 4
                    memories = await recall_safe(
                        self._hindsight, Bank.LEARNINGS, query_context
                    )
                    raw = format_memories_as_markdown(memories)
                    if raw:
                        topup_section = f"\n\n## Issue-Specific Context\n\n{raw[:topup_cap]}"
                except Exception:  # noqa: BLE001
                    pass  # Must not interrupt pipeline
            self._last_context_stats = {
                "cache_hits": 1,
                "cache_misses": 0,
                "context_chars_before": len(shared_prefix) + len(topup_section),
                "context_chars_after": len(shared_prefix) + len(topup_section),
                "dedup_items_removed": 0,
                "dedup_chars_saved": 0,
            }
            return shared_prefix, topup_section

        # --- Existing full-recall path (unchanged) ---
```

The rest of the method stays unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_base_runner_shared_prefix.py -v`
Expected: PASS

Also run existing base_runner tests for regression:

Run: `python -m pytest tests/test_base_runner.py -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/base_runner.py tests/test_base_runner_shared_prefix.py
git commit -m "feat: add shared_prefix mode to _inject_manifest_and_memory (#5938)"
```

---

### Task 4: Thread shared_prefix through AgentRunner

**Files:**
- Modify: `src/agent.py:141-182` (run method), `src/agent.py:543-549` (_build_prompt_with_stats)

- [ ] **Step 1: Add shared_prefix parameter to run()**

In `src/agent.py`, modify the `run()` method signature at line 141:

```python
    async def run(
        self,
        task: Task,
        worktree_path: Path,
        branch: str,
        worker_id: int = 0,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        shared_prefix: str | None = None,
    ) -> WorkerResult:
```

At line 177-182, pass `shared_prefix` to `_build_prompt_with_stats`:

```python
            prompt, prompt_stats = await self._build_prompt_with_stats(
                task,
                review_feedback=review_feedback,
                prior_failure=prior_failure,
                bead_mapping=bead_mapping,
                shared_prefix=shared_prefix,
            )
```

- [ ] **Step 2: Add shared_prefix parameter to _build_prompt_with_stats()**

At line 543, add the parameter:

```python
    async def _build_prompt_with_stats(
        self,
        issue: Task,
        review_feedback: str = "",
        prior_failure: str = "",
        bead_mapping: dict[str, str] | None = None,
        shared_prefix: str | None = None,
    ) -> tuple[str, dict[str, object]]:
```

At line 656, pass `shared_prefix` to `_inject_manifest_and_memory`:

```python
        manifest_section, memory_section = await self._inject_manifest_and_memory(
            query_context=f"{issue.title}\n{(issue.body or '')[:200]}",
            shared_prefix=shared_prefix,
        )
```

- [ ] **Step 3: Run existing agent tests for regression**

Run: `python -m pytest tests/test_agent.py -v --tb=short -x`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/agent.py
git commit -m "feat: thread shared_prefix through AgentRunner (#5938)"
```

---

### Task 5: Thread shared_prefix through PlannerRunner

**Files:**
- Modify: `src/planner.py:40-74` (plan method), `src/planner.py:290-340` (_build_prompt_with_stats)

- [ ] **Step 1: Add shared_prefix parameter to plan()**

In `src/planner.py`, modify the `plan()` method signature at line 40:

```python
    async def plan(
        self,
        task: Task,
        worker_id: int = 0,
        research_context: str = "",
        shared_prefix: str | None = None,
    ) -> PlanResult:
```

At line 72, pass to `_build_prompt_with_stats`:

```python
            prompt, prompt_stats = await self._build_prompt_with_stats(
                task, scale=scale, research_context=research_context,
                shared_prefix=shared_prefix,
            )
```

- [ ] **Step 2: Add shared_prefix to _build_prompt_with_stats()**

At the method signature (line ~290):

```python
    async def _build_prompt_with_stats(
        self,
        issue: Task,
        *,
        scale: PlanScale = "full",
        research_context: str = "",
        shared_prefix: str | None = None,
    ) -> tuple[str, dict[str, object]]:
```

At line 338, pass to `_inject_manifest_and_memory`:

```python
        manifest_section, memory_section = await self._inject_manifest_and_memory(
            query_context=f"{issue.title}\n{(issue.body or '')[:200]}",
            shared_prefix=shared_prefix,
        )
```

- [ ] **Step 3: Run existing planner tests for regression**

Run: `python -m pytest tests/test_planner.py -v --tb=short -x`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/planner.py
git commit -m "feat: thread shared_prefix through PlannerRunner (#5938)"
```

---

### Task 6: Wire SharedPromptPrefix into ImplementPhase

**Files:**
- Modify: `src/implement_phase.py:97-182` (run_batch), `src/implement_phase.py:461-474` (_worker_inner)

- [ ] **Step 1: Build prefix before run_refilling_pool**

In `src/implement_phase.py`, add import at the top:

```python
from shared_prompt_prefix import SharedPromptPrefix
```

In `run_batch()`, before `run_refilling_pool` (before line 176), add:

```python
        # Build shared prefix once for batch when running multiple agents
        shared_prefix: str | None = None
        if self._config.max_workers > 1:
            try:
                builder = SharedPromptPrefix(self._config)
                shared_prefix = await builder.build(
                    hindsight=self._agents.hindsight,
                )
                logger.info(
                    "Built shared prompt prefix (%d chars) for %d concurrent workers",
                    builder.prefix_chars,
                    self._config.max_workers,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Failed to build shared prefix, falling back", exc_info=True)
                shared_prefix = None
```

- [ ] **Step 2: Pass shared_prefix through worker to _worker_inner**

The `_worker` closure at line 129 calls `self._worker_inner(idx, issue, branch)`. The `_worker_inner` method at line 184 calls `self._agents.run()` at line 469.

Modify `_worker_inner` signature (line 184) to accept `shared_prefix`:

```python
    async def _worker_inner(
        self, idx: int, issue: Task, branch: str, shared_prefix: str | None = None
    ) -> WorkerResult:
```

At line 469-473, add `shared_prefix` to the `run_kwargs`:

```python
        if shared_prefix is not None:
            run_kwargs["shared_prefix"] = shared_prefix
```

Update the closure `_worker` (line 129) to pass `shared_prefix`:

```python
        async def _worker(idx: int, issue: Task) -> WorkerResult:
            ...
                    try:
                        return await run_with_fatal_guard(
                            self._worker_inner(idx, issue, branch, shared_prefix=shared_prefix),
                            ...
                        )
```

- [ ] **Step 3: Run existing implement_phase tests for regression**

Run: `python -m pytest tests/test_implement_phase.py -v --tb=short -x`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/implement_phase.py
git commit -m "feat: wire SharedPromptPrefix into ImplementPhase (#5938)"
```

---

### Task 7: Wire SharedPromptPrefix into PlanPhase

**Files:**
- Modify: `src/plan_phase.py:440-484` (_plan_one), `src/plan_phase.py:695-749` (run_all)

- [ ] **Step 1: Build prefix in run_all before dispatch**

In `src/plan_phase.py`, add import at the top:

```python
from shared_prompt_prefix import SharedPromptPrefix
```

In `run_all()` (around line 698), before the `run_refilling_pool` call, add:

```python
        # Build shared prefix once for batch when running multiple planners
        shared_prefix: str | None = None
        if self._config.max_planners > 1:
            try:
                builder = SharedPromptPrefix(self._config)
                shared_prefix = await builder.build(
                    hindsight=self._planners.hindsight,
                )
                logger.info(
                    "Built shared prompt prefix (%d chars) for %d concurrent planners",
                    builder.prefix_chars,
                    self._config.max_planners,
                )
            except Exception:  # noqa: BLE001
                logger.warning("Failed to build shared prefix, falling back", exc_info=True)
                shared_prefix = None
```

- [ ] **Step 2: Thread shared_prefix through _plan_one to planners.plan()**

Modify `_plan_one` signature (line 440):

```python
    async def _plan_one(
        self, idx: int, issue: Task, semaphore: asyncio.Semaphore,
        shared_prefix: str | None = None,
    ) -> PlanResult:
```

At line 483, pass `shared_prefix`:

```python
                    result = await self._planners.plan(
                        issue, worker_id=idx, research_context=research_context,
                        shared_prefix=shared_prefix,
                    )
```

Update `_plan_worker` closure (line 736) to pass `shared_prefix`:

```python
        async def _plan_worker(idx: int, issue: Task) -> PlanResult:
            try:
                return await self._plan_one(idx, issue, semaphore, shared_prefix=shared_prefix)
            finally:
                release_batch_in_flight(self._store, {issue.id})
```

- [ ] **Step 3: Run existing plan_phase tests for regression**

Run: `python -m pytest tests/test_plan_phase.py -v --tb=short -x`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/plan_phase.py
git commit -m "feat: wire SharedPromptPrefix into PlanPhase (#5938)"
```

---

### Task 8: Add prefix cache telemetry

**Files:**
- Modify: `src/prompt_telemetry.py:69-92`
- Modify: `src/agent.py` (_build_prompt_with_stats stats dict)
- Modify: `src/planner.py` (_build_prompt_with_stats stats dict)

- [ ] **Step 1: Add telemetry fields to prompt_telemetry.py**

In `src/prompt_telemetry.py`, after the existing stats extraction (around line 91), add:

```python
        shared_prefix_chars = max(0, _as_int(st.get("shared_prefix_chars", 0)))
        unique_suffix_chars = max(0, _as_int(st.get("unique_suffix_chars", 0)))
        prefix_total = shared_prefix_chars + unique_suffix_chars
        prefix_cache_reuse_ratio = (
            round(shared_prefix_chars / prefix_total, 3) if prefix_total > 0 else 0.0
        )
```

Then include these in the inference record dict (find the `record = {` block and add):

```python
            "shared_prefix_chars": shared_prefix_chars,
            "unique_suffix_chars": unique_suffix_chars,
            "prefix_cache_reuse_ratio": prefix_cache_reuse_ratio,
```

- [ ] **Step 2: Emit telemetry stats from AgentRunner**

In `src/agent.py` `_build_prompt_with_stats()`, after prompt assembly (after line 684), add the prefix metrics to the stats dict:

```python
        stats = builder.build_stats()
        if shared_prefix is not None:
            stats["shared_prefix_chars"] = len(shared_prefix)
            stats["unique_suffix_chars"] = len(prompt) - len(shared_prefix)
```

- [ ] **Step 3: Emit telemetry stats from PlannerRunner**

In `src/planner.py` `_build_prompt_with_stats()`, after prompt assembly, add the same:

```python
        stats = builder.build_stats()
        if shared_prefix is not None:
            stats["shared_prefix_chars"] = len(shared_prefix)
            stats["unique_suffix_chars"] = len(prompt) - len(shared_prefix)
```

- [ ] **Step 4: Run existing telemetry tests for regression**

Run: `python -m pytest tests/test_prompt_telemetry.py -v --tb=short -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/prompt_telemetry.py src/agent.py src/planner.py
git commit -m "feat: add prefix cache reuse ratio telemetry (#5938)"
```

---

### Task 9: Run full quality gate

- [ ] **Step 1: Run backend quality checks**

Run: `make quality`
Expected: PASS

- [ ] **Step 2: Fix any issues found**

If any failures, fix and re-run until green.

- [ ] **Step 3: Final commit if needed**

```bash
git add -A
git commit -m "fix: quality gate fixes for shared prompt prefix (#5938)"
```
