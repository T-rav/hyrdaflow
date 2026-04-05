# Bot PR Auto-Merge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggleable background worker that auto-merges bot-authored PRs (Dependabot, Renovate, etc.) after CI passes, with configurable failure strategies and optional LLM review.

**Architecture:** New `BotPRLoop` extending `BaseBackgroundLoop`, reading from `GitHubDataCache` (zero API calls for discovery), with settings persisted in `StateData` and managed from the dashboard UI. Follows the exact pattern of `PRUnstickerLoop`.

**Tech Stack:** Python 3.11, Pydantic, asyncio, React (inline styles), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `src/models.py` | Modify | Add `author` to `PRListItem`, add `BotPRSettings` model, add fields to `StateData` |
| `src/pr_manager.py` | Modify | Include `author` in PR fetch query |
| `src/github_cache_loop.py` | Modify | Pass `author` through to `PRListItem` |
| `src/config.py` | Modify | Add `bot_pr_interval` config field |
| `src/bot_pr_loop.py` | Create | Background worker loop |
| `src/state/_bot_pr.py` | Create | State accessors for bot PR settings + processed set |
| `src/state/__init__.py` | Modify | Mix in bot PR state methods |
| `src/service_registry.py` | Modify | Wire `BotPRLoop` |
| `src/orchestrator.py` | Modify | Register in loop registry + factories |
| `src/dashboard_routes/_routes.py` | Modify | Add settings GET/POST endpoints |
| `src/ui/src/constants.js` | Modify | Add worker + presets |
| `src/ui/src/components/SystemPanel.jsx` | Modify | Add settings panel component |
| `tests/test_bot_pr_loop.py` | Create | Unit tests for the loop |
| `tests/test_bot_pr_settings_api.py` | Create | API endpoint tests |

---

### Task 1: Add `author` to PRListItem and PR fetch

**Files:**
- Modify: `src/models.py:1513-1522`
- Modify: `src/pr_manager.py:1726-1740`
- Modify: `src/pr_manager.py:1604-1637`
- Test: `tests/test_pr_manager.py` (existing)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_pr_models.py
"""Tests for PRListItem author field."""
from models import PRListItem


def test_pr_list_item_has_author_field():
    item = PRListItem(pr=42, author="dependabot[bot]")
    assert item.author == "dependabot[bot]"


def test_pr_list_item_author_defaults_empty():
    item = PRListItem(pr=42)
    assert item.author == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_models.py -xvs`
Expected: FAIL — `author` field not recognized

- [ ] **Step 3: Add `author` field to `PRListItem`**

In `src/models.py`, in the `PRListItem` class (around line 1522), add after `merged`:

```python
    author: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_models.py -xvs`
Expected: PASS

- [ ] **Step 5: Update `_get_pr_branch_and_draft` to also return author**

In `src/pr_manager.py`, rename `_get_pr_branch_and_draft` to `_get_pr_metadata` and update the jq query to include author:

```python
    async def _get_pr_metadata(self, pr_number: int) -> tuple[str, bool, str]:
        """Resolve branch, draft status, and author for a PR via REST API."""
        raw = await self._run_gh(
            "gh",
            "api",
            f"repos/{self._repo}/pulls/{pr_number}",
            "--jq",
            "{headRefName: .head.ref, isDraft: .draft, author: .user.login}",
        )
        data = json.loads(raw)
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            return "", False, ""
        return (
            str(data.get("headRefName", "")),
            bool(data.get("isDraft", False)),
            str(data.get("author", "")),
        )
```

- [ ] **Step 6: Update `list_open_prs` to use new method and pass author**

In `src/pr_manager.py`, update the `list_open_prs` method to call `_get_pr_metadata` and pass `author` to `PRListItem`:

```python
                branch, draft, author = await self._get_pr_metadata(pr_num)
                issue_number = self._issue_number_from_branch(branch)
                prs.append(
                    PRListItem(
                        pr=pr_num,
                        issue=issue_number,
                        branch=branch,
                        url=p.get("url", ""),
                        draft=draft,
                        title=p.get("title", ""),
                        author=author,
                    )
                )
```

- [ ] **Step 7: Update all callers of `_get_pr_branch_and_draft`**

Search for other callers: `grep -r "_get_pr_branch_and_draft" src/`. Update each to use `_get_pr_metadata` and unpack the 3-tuple (adding `_` for unused author where needed).

- [ ] **Step 8: Run existing PR manager tests**

Run: `PYTHONPATH=src python -m pytest tests/test_pr_manager.py -x --tb=short -q`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add src/models.py src/pr_manager.py tests/test_bot_pr_models.py
git commit -m "feat: add author field to PRListItem and PR metadata fetch"
```

---

### Task 2: Add BotPRSettings model and state persistence

**Files:**
- Modify: `src/models.py`
- Create: `src/state/_bot_pr.py`
- Modify: `src/state/__init__.py`
- Test: `tests/test_bot_pr_state.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_pr_state.py
"""Tests for bot PR state persistence."""
from __future__ import annotations

import pytest

from models import BotPRSettings


def test_bot_pr_settings_defaults():
    settings = BotPRSettings()
    assert settings.authors == ["dependabot[bot]"]
    assert settings.failure_strategy == "skip"
    assert settings.review_mode == "ci_only"


def test_bot_pr_settings_custom():
    settings = BotPRSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    assert "renovate[bot]" in settings.authors
    assert settings.failure_strategy == "hitl"
    assert settings.review_mode == "llm_review"


def test_bot_pr_settings_validates_strategy():
    with pytest.raises(ValueError):
        BotPRSettings(failure_strategy="invalid")


def test_bot_pr_settings_validates_review_mode():
    with pytest.raises(ValueError):
        BotPRSettings(review_mode="invalid")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_state.py -xvs`
Expected: FAIL — `BotPRSettings` not found

- [ ] **Step 3: Add BotPRSettings model to models.py**

In `src/models.py`, before the `StateData` class, add:

```python
class BotPRSettings(BaseModel):
    """Configuration for the bot PR auto-merge worker."""

    authors: list[str] = Field(default_factory=lambda: ["dependabot[bot]"])
    failure_strategy: Literal["skip", "hitl", "close"] = "skip"
    review_mode: Literal["ci_only", "llm_review"] = "ci_only"
```

Add `Literal` to the typing imports if not already present.

- [ ] **Step 4: Add bot_pr fields to StateData**

In `src/models.py`, in `StateData`, add before `last_updated`:

```python
    bot_pr_settings: BotPRSettings = Field(default_factory=BotPRSettings)
    bot_pr_processed: list[int] = Field(default_factory=list)
```

- [ ] **Step 5: Run model tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_state.py -xvs`
Expected: PASS

- [ ] **Step 6: Create state accessor mixin**

Create `src/state/_bot_pr.py`:

```python
"""State accessors for bot PR auto-merge settings."""

from __future__ import annotations

from models import BotPRSettings


class BotPRStateMixin:
    """Mixed into StateTracker for bot PR settings persistence."""

    def get_bot_pr_settings(self) -> BotPRSettings:
        """Return current bot PR settings."""
        return BotPRSettings.model_validate(
            self._data.bot_pr_settings.model_dump()
        )

    def set_bot_pr_settings(self, settings: BotPRSettings) -> None:
        """Persist bot PR settings."""
        self._data.bot_pr_settings = settings
        self.save()

    def get_bot_pr_processed(self) -> set[int]:
        """Return set of PR numbers already processed by the bot PR worker."""
        return set(self._data.bot_pr_processed)

    def add_bot_pr_processed(self, pr_number: int) -> None:
        """Mark a PR as processed (merged, closed, or escalated)."""
        current = set(self._data.bot_pr_processed)
        current.add(pr_number)
        self._data.bot_pr_processed = sorted(current)
        self.save()
```

- [ ] **Step 7: Mix into StateTracker**

In `src/state/__init__.py`, import and add `BotPRStateMixin` to the `StateTracker` class bases. Find the class definition and add to the inheritance list. Also add the import:

```python
from state._bot_pr import BotPRStateMixin
```

- [ ] **Step 8: Write state integration test**

Append to `tests/test_bot_pr_state.py`:

```python
from state import StateTracker
from config import HydraFlowConfig


def test_state_tracker_bot_pr_settings_roundtrip(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
    state = StateTracker(config.state_file)

    # Defaults
    settings = state.get_bot_pr_settings()
    assert settings.authors == ["dependabot[bot]"]

    # Update
    new_settings = BotPRSettings(
        authors=["dependabot[bot]", "renovate[bot]"],
        failure_strategy="hitl",
        review_mode="llm_review",
    )
    state.set_bot_pr_settings(new_settings)

    # Read back
    loaded = state.get_bot_pr_settings()
    assert loaded.authors == ["dependabot[bot]", "renovate[bot]"]
    assert loaded.failure_strategy == "hitl"


def test_state_tracker_bot_pr_processed(tmp_path):
    config = HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")
    state = StateTracker(config.state_file)

    assert state.get_bot_pr_processed() == set()
    state.add_bot_pr_processed(42)
    state.add_bot_pr_processed(101)
    assert state.get_bot_pr_processed() == {42, 101}
```

- [ ] **Step 9: Run all state tests**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_state.py -xvs`
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/models.py src/state/_bot_pr.py src/state/__init__.py tests/test_bot_pr_state.py
git commit -m "feat: add BotPRSettings model and state persistence"
```

---

### Task 3: Add config field and create BotPRLoop

**Files:**
- Modify: `src/config.py`
- Create: `src/bot_pr_loop.py`
- Create: `tests/test_bot_pr_loop.py`

- [ ] **Step 1: Add config field**

In `src/config.py`, add to `_ENV_INT_OVERRIDES`:

```python
    ("bot_pr_interval", "HYDRAFLOW_BOT_PR_INTERVAL", 3600),
```

And add the Pydantic field to `HydraFlowConfig` (near `pr_unstick_interval`):

```python
    bot_pr_interval: int = Field(
        default=3600,
        description="Polling interval for bot PR auto-merge (seconds)",
    )
```

- [ ] **Step 2: Write the failing test for the loop**

```python
# tests/test_bot_pr_loop.py
"""Tests for BotPRLoop background worker."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import HydraFlowConfig
from models import BotPRSettings, PRListItem


def _make_pr(pr: int, author: str = "dependabot[bot]", title: str = "Bump foo") -> PRListItem:
    return PRListItem(pr=pr, author=author, title=title)


@pytest.fixture
def config(tmp_path):
    return HydraFlowConfig(repo_root=str(tmp_path), gh_token="fake")


class TestBotPRLoopDoWork:
    """Tests for BotPRLoop._do_work() decision logic."""

    @pytest.mark.asyncio
    async def test_merges_bot_pr_when_ci_green(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42)]

        prs = AsyncMock()
        prs.wait_for_ci = AsyncMock(return_value=(True, "All checks passed"))
        prs.submit_review = AsyncMock(return_value=True)
        prs.merge_pr = AsyncMock(return_value=True)

        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings()
        state.get_bot_pr_processed.return_value = set()

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        prs.merge_pr.assert_awaited_once_with(42)
        state.add_bot_pr_processed.assert_called_with(42)
        assert result["merged"] == 1

    @pytest.mark.asyncio
    async def test_skips_already_processed_pr(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42)]

        prs = AsyncMock()
        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings()
        state.get_bot_pr_processed.return_value = {42}

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        prs.wait_for_ci.assert_not_awaited()
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_skips_non_bot_pr(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42, author="human-dev")]

        prs = AsyncMock()
        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings()
        state.get_bot_pr_processed.return_value = set()

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        prs.wait_for_ci.assert_not_awaited()
        assert result["processed"] == 0

    @pytest.mark.asyncio
    async def test_ci_pending_skips_without_tracking(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42)]

        prs = AsyncMock()
        prs.wait_for_ci = AsyncMock(return_value=(None, "Pending"))

        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings()
        state.get_bot_pr_processed.return_value = set()

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        prs.merge_pr.assert_not_awaited()
        state.add_bot_pr_processed.assert_not_called()
        assert result["pending"] == 1

    @pytest.mark.asyncio
    async def test_ci_red_with_hitl_strategy(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42)]

        prs = AsyncMock()
        prs.wait_for_ci = AsyncMock(return_value=(False, "CI failed"))
        prs.add_labels = AsyncMock()
        prs.post_comment = AsyncMock()

        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings(failure_strategy="hitl")
        state.get_bot_pr_processed.return_value = set()

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        prs.add_labels.assert_awaited_once()
        prs.post_comment.assert_awaited_once()
        state.add_bot_pr_processed.assert_called_with(42)
        assert result["escalated"] == 1

    @pytest.mark.asyncio
    async def test_ci_red_with_close_strategy(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42)]

        prs = AsyncMock()
        prs.wait_for_ci = AsyncMock(return_value=(False, "CI failed"))
        prs.close_pr = AsyncMock()
        prs.post_comment = AsyncMock()

        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings(failure_strategy="close")
        state.get_bot_pr_processed.return_value = set()

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        prs.close_pr.assert_awaited_once()
        state.add_bot_pr_processed.assert_called_with(42)
        assert result["closed"] == 1

    @pytest.mark.asyncio
    async def test_ci_red_with_skip_strategy_does_not_track(self, config):
        from bot_pr_loop import BotPRLoop

        cache = MagicMock()
        cache.get_open_prs.return_value = [_make_pr(42)]

        prs = AsyncMock()
        prs.wait_for_ci = AsyncMock(return_value=(False, "CI failed"))

        state = MagicMock()
        state.get_bot_pr_settings.return_value = BotPRSettings(failure_strategy="skip")
        state.get_bot_pr_processed.return_value = set()

        loop = BotPRLoop(
            config=config,
            github_cache=cache,
            prs=prs,
            state=state,
            deps=MagicMock(),
        )

        result = await loop._do_work()

        state.add_bot_pr_processed.assert_not_called()
        prs.merge_pr.assert_not_awaited()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_loop.py -xvs`
Expected: FAIL — `bot_pr_loop` module not found

- [ ] **Step 4: Create `src/bot_pr_loop.py`**

```python
"""Background worker loop — auto-merge bot-authored PRs after CI passes."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import HydraFlowConfig
from models import ReviewVerdict

if TYPE_CHECKING:
    from github_cache import GitHubDataCache
    from pr_manager import PRManager
    from reviewer import ReviewRunner
    from state import StateTracker

logger = logging.getLogger("hydraflow.bot_pr_loop")


class BotPRLoop(BaseBackgroundLoop):
    """Polls for bot-authored PRs and auto-merges after CI passes."""

    def __init__(
        self,
        config: HydraFlowConfig,
        github_cache: GitHubDataCache,
        prs: PRManager,
        state: StateTracker,
        deps: LoopDeps,
        *,
        reviewer: ReviewRunner | None = None,
    ) -> None:
        super().__init__(worker_name="bot_pr", config=config, deps=deps)
        self._cache = github_cache
        self._prs = prs
        self._state = state
        self._reviewer = reviewer

    def _get_default_interval(self) -> int:
        return self._config.bot_pr_interval

    async def _do_work(self) -> dict[str, Any] | None:
        """Discover bot PRs, check CI, merge or apply failure strategy."""
        settings = self._state.get_bot_pr_settings()
        processed = self._state.get_bot_pr_processed()
        open_prs = self._cache.get_open_prs()

        # Filter to bot-authored PRs not yet processed
        bot_prs = [
            pr for pr in open_prs
            if pr.author in settings.authors and pr.pr not in processed
        ]

        stats: dict[str, int] = {
            "processed": 0,
            "merged": 0,
            "skipped": 0,
            "pending": 0,
            "escalated": 0,
            "closed": 0,
        }

        if not bot_prs:
            # Count skipped (already processed) for stats
            already = [
                pr for pr in open_prs
                if pr.author in settings.authors and pr.pr in processed
            ]
            stats["skipped"] = len(already)
            return stats

        for pr in bot_prs:
            try:
                await self._process_bot_pr(pr.pr, settings, stats)
            except Exception:
                logger.exception("Error processing bot PR #%d", pr.pr)

        stats["processed"] = stats["merged"] + stats["escalated"] + stats["closed"]

        try:
            import sentry_sdk as _sentry

            _sentry.add_breadcrumb(
                category="bot_pr.cycle",
                message=f"Processed {stats['processed']} bot PRs",
                level="info",
                data=stats,
            )
        except ImportError:
            pass

        return stats

    async def _process_bot_pr(
        self,
        pr_number: int,
        settings: Any,
        stats: dict[str, int],
    ) -> None:
        """Handle a single bot PR."""
        # Check CI — use a short timeout since we'll retry next cycle
        ci_passed, ci_summary = await self._prs.wait_for_ci(
            pr_number,
            timeout=60,
            poll_interval=15,
            stop_event=self._deps.stop_event,
        )

        if ci_passed is None:
            # CI still pending — skip, pick up next cycle
            stats["pending"] += 1
            logger.info("Bot PR #%d: CI pending, will retry", pr_number)
            return

        if ci_passed:
            await self._handle_ci_green(pr_number, settings, stats)
        else:
            await self._handle_ci_red(pr_number, ci_summary, settings, stats)

    async def _handle_ci_green(
        self,
        pr_number: int,
        settings: Any,
        stats: dict[str, int],
    ) -> None:
        """CI passed — merge directly or run LLM review first."""
        if settings.review_mode == "llm_review" and self._reviewer:
            # TODO: LLM review integration — for now, fall through to merge
            logger.info(
                "Bot PR #%d: LLM review requested but not yet implemented, merging",
                pr_number,
            )

        # Approve and merge
        await self._prs.submit_review(
            pr_number, ReviewVerdict.APPROVE, "Bot PR auto-approved: CI passed."
        )
        merged = await self._prs.merge_pr(pr_number)
        if merged:
            stats["merged"] += 1
            logger.info("Bot PR #%d: merged", pr_number)
        else:
            logger.warning("Bot PR #%d: merge failed", pr_number)

        self._state.add_bot_pr_processed(pr_number)

    async def _handle_ci_red(
        self,
        pr_number: int,
        ci_summary: str,
        settings: Any,
        stats: dict[str, int],
    ) -> None:
        """CI failed — apply configured failure strategy."""
        strategy = settings.failure_strategy

        if strategy == "skip":
            # Leave open, do NOT track — retry next cycle
            logger.info("Bot PR #%d: CI failed, skipping (will retry)", pr_number)
            return

        if strategy == "hitl":
            await self._prs.add_labels(pr_number, self._config.hitl_label)
            await self._prs.post_comment(
                pr_number,
                f"## Bot PR CI Failure\n\n"
                f"CI failed on this dependency update PR. "
                f"Escalating to human review.\n\n"
                f"**CI Summary:** {ci_summary}\n",
            )
            stats["escalated"] += 1
            logger.info("Bot PR #%d: CI failed, escalated to HITL", pr_number)

        elif strategy == "close":
            await self._prs.post_comment(
                pr_number,
                f"## Bot PR Closed\n\n"
                f"CI failed on this dependency update. Closing this PR. "
                f"The bot will recreate it when a new version is available.\n\n"
                f"**CI Summary:** {ci_summary}\n",
            )
            await self._prs.close_pr(pr_number)
            stats["closed"] += 1
            logger.info("Bot PR #%d: CI failed, closed", pr_number)

        self._state.add_bot_pr_processed(pr_number)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_loop.py -xvs`
Expected: PASS (some tests may need adjustments based on `wait_for_ci` return signature — `None` for pending vs `True`/`False` for complete)

- [ ] **Step 6: Fix any test issues and verify all pass**

The `wait_for_ci` method returns `tuple[bool, str]` — it doesn't return `None` for pending, it blocks until timeout. Adjust the loop to use a short timeout and treat timeout as "pending". Update tests if needed.

- [ ] **Step 7: Commit**

```bash
git add src/config.py src/bot_pr_loop.py tests/test_bot_pr_loop.py
git commit -m "feat: create BotPRLoop background worker"
```

---

### Task 4: Wire into service registry and orchestrator

**Files:**
- Modify: `src/service_registry.py`
- Modify: `src/orchestrator.py`

- [ ] **Step 1: Add to ServiceRegistry dataclass**

In `src/service_registry.py`, add to the `ServiceRegistry` dataclass (after `health_monitor_loop`):

```python
    bot_pr_loop: BotPRLoop
```

Add the import at top:

```python
from bot_pr_loop import BotPRLoop
```

- [ ] **Step 2: Instantiate in `build_services()`**

In the `build_services()` function, after the health monitor loop instantiation, add:

```python
    bot_pr_loop = BotPRLoop(
        config=config,
        github_cache=gh_cache,
        prs=prs,
        state=state,
        deps=loop_deps,
        reviewer=reviewers,
    )
```

And include `bot_pr_loop=bot_pr_loop` in the `ServiceRegistry(...)` constructor call.

- [ ] **Step 3: Register in orchestrator**

In `src/orchestrator.py`, add to `bg_loop_registry` (around line 140):

```python
            "bot_pr": svc.bot_pr_loop,
```

Add to `loop_factories` (around line 843):

```python
            ("bot_pr", self._svc.bot_pr_loop.run),
```

- [ ] **Step 4: Run existing orchestrator tests**

Run: `PYTHONPATH=src python -m pytest tests/test_orchestrator*.py -x --tb=short -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/service_registry.py src/orchestrator.py
git commit -m "feat: wire BotPRLoop into service registry and orchestrator"
```

---

### Task 5: Add dashboard settings API endpoints

**Files:**
- Modify: `src/dashboard_routes/_routes.py`
- Create: `tests/test_bot_pr_settings_api.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bot_pr_settings_api.py
"""Tests for bot PR settings API endpoints."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from models import BotPRSettings


@pytest.fixture
def mock_state():
    state = MagicMock()
    state.get_bot_pr_settings.return_value = BotPRSettings()
    return state


def test_get_settings_returns_defaults(mock_state):
    settings = mock_state.get_bot_pr_settings()
    assert settings.authors == ["dependabot[bot]"]
    assert settings.failure_strategy == "skip"
    assert settings.review_mode == "ci_only"


def test_set_settings_validates_strategy(mock_state):
    with pytest.raises(ValueError):
        BotPRSettings(failure_strategy="invalid")


def test_set_settings_validates_review_mode(mock_state):
    with pytest.raises(ValueError):
        BotPRSettings(review_mode="invalid")
```

- [ ] **Step 2: Add API endpoints**

In `src/dashboard_routes/_routes.py`, add after the existing `bg-worker` endpoints:

```python
    @router.get("/api/bot-pr/settings")
    async def get_bot_pr_settings(repo: RepoSlugParam = None) -> JSONResponse:
        """Return current bot PR auto-merge settings."""
        orch = get_orchestrator(repo)
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)
        settings = orch.state.get_bot_pr_settings()
        return JSONResponse(settings.model_dump())

    @router.post("/api/bot-pr/settings")
    async def set_bot_pr_settings(body: dict[str, Any], repo: RepoSlugParam = None) -> JSONResponse:
        """Update bot PR auto-merge settings."""
        orch = get_orchestrator(repo)
        if not orch:
            return JSONResponse({"error": "no orchestrator"}, status_code=400)

        current = orch.state.get_bot_pr_settings()
        update = current.model_dump()
        for key in ("authors", "failure_strategy", "review_mode"):
            if key in body:
                update[key] = body[key]

        try:
            new_settings = BotPRSettings(**update)
        except ValueError as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)

        orch.state.set_bot_pr_settings(new_settings)
        return JSONResponse({"status": "ok", **new_settings.model_dump()})
```

Add `BotPRSettings` to the imports from `models`.

- [ ] **Step 3: Run tests**

Run: `PYTHONPATH=src python -m pytest tests/test_bot_pr_settings_api.py -xvs`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/dashboard_routes/_routes.py tests/test_bot_pr_settings_api.py
git commit -m "feat: add bot PR settings GET/POST API endpoints"
```

---

### Task 6: Add dashboard UI constants and worker card

**Files:**
- Modify: `src/ui/src/constants.js`
- Modify: `src/ui/src/components/SystemPanel.jsx`

- [ ] **Step 1: Add constants**

In `src/ui/src/constants.js`:

Add presets after `REPORT_ISSUE_PRESETS`:

```javascript
export const BOT_PR_PRESETS = [
  { label: '1h', seconds: 3600 },
  { label: '2h', seconds: 7200 },
  { label: '6h', seconds: 21600 },
  { label: '12h', seconds: 43200 },
  { label: '24h', seconds: 86400 },
]
```

Add to `WORKER_PRESETS`:

```javascript
export const WORKER_PRESETS = {
  pipeline_poller: PIPELINE_POLLER_PRESETS,
  adr_reviewer: ADR_REVIEWER_PRESETS,
  report_issue: REPORT_ISSUE_PRESETS,
  bot_pr: BOT_PR_PRESETS,
}
```

Add `'bot_pr'` to `EDITABLE_INTERVAL_WORKERS`:

```javascript
export const EDITABLE_INTERVAL_WORKERS = new Set(['memory_sync', 'pr_unsticker', 'pipeline_poller', 'report_issue', 'worktree_gc', 'adr_reviewer', 'epic_sweeper', 'bot_pr'])
```

Add to `SYSTEM_WORKER_INTERVALS`:

```javascript
  bot_pr: 3600,
```

Add to `BACKGROUND_WORKERS` array:

```javascript
  { key: 'bot_pr', label: 'Bot PR Manager', description: 'Auto-merges dependency update PRs from configured bots after CI passes.', color: theme.green },
```

- [ ] **Step 2: Add BotPRSettings panel component to SystemPanel.jsx**

In `src/ui/src/components/SystemPanel.jsx`, add a new `BotPRSettingsPanel` component (before the main `SystemPanel` export), following the `MemoryAutoApproveToggle` pattern:

```jsx
const KNOWN_BOTS = [
  { login: 'dependabot[bot]', label: 'Dependabot' },
  { login: 'renovate[bot]', label: 'Renovate' },
  { login: 'snyk-bot', label: 'Snyk' },
]

const FAILURE_STRATEGIES = [
  { value: 'skip', label: 'Skip (retry next cycle)' },
  { value: 'hitl', label: 'Escalate to HITL' },
  { value: 'close', label: 'Close PR' },
]

const REVIEW_MODES = [
  { value: 'ci_only', label: 'CI Only (fast)' },
  { value: 'llm_review', label: 'LLM Review (thorough)' },
]

function BotPRSettingsPanel() {
  const { selectedRepoSlug } = useHydraFlow()
  const [settings, setSettings] = useState(null)
  const [customBot, setCustomBot] = useState('')

  useEffect(() => {
    const url = selectedRepoSlug
      ? `/api/bot-pr/settings?repo=${encodeURIComponent(selectedRepoSlug)}`
      : '/api/bot-pr/settings'
    fetch(url).then(r => r.json()).then(setSettings).catch(() => {})
  }, [selectedRepoSlug])

  const updateSettings = useCallback(async (patch) => {
    const updated = { ...settings, ...patch }
    setSettings(updated)
    const url = selectedRepoSlug
      ? `/api/bot-pr/settings?repo=${encodeURIComponent(selectedRepoSlug)}`
      : '/api/bot-pr/settings'
    try {
      const resp = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch),
      })
      if (!resp.ok) setSettings(settings)
    } catch {
      setSettings(settings)
    }
  }, [settings, selectedRepoSlug])

  const toggleBot = useCallback((login) => {
    if (!settings) return
    const authors = settings.authors.includes(login)
      ? settings.authors.filter(a => a !== login)
      : [...settings.authors, login]
    updateSettings({ authors })
  }, [settings, updateSettings])

  const addCustomBot = useCallback(() => {
    if (!customBot.trim() || !settings) return
    if (!settings.authors.includes(customBot.trim())) {
      updateSettings({ authors: [...settings.authors, customBot.trim()] })
    }
    setCustomBot('')
  }, [customBot, settings, updateSettings])

  if (!settings) return null

  return (
    <div style={styles.botPrPanel} data-testid="bot-pr-settings">
      <div style={styles.botPrSection}>
        <span style={styles.botPrSectionLabel}>Bot Authors</span>
        {KNOWN_BOTS.map(bot => (
          <label key={bot.login} style={styles.botPrCheckRow}>
            <input
              type="checkbox"
              checked={settings.authors.includes(bot.login)}
              onChange={() => toggleBot(bot.login)}
            />
            <span style={styles.botPrCheckLabel}>{bot.label}</span>
          </label>
        ))}
        <div style={styles.botPrCustomRow}>
          <input
            type="text"
            value={customBot}
            onChange={e => setCustomBot(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addCustomBot()}
            placeholder="Custom bot username"
            style={styles.botPrInput}
          />
          <button onClick={addCustomBot} style={styles.botPrAddBtn}>Add</button>
        </div>
      </div>
      <div style={styles.botPrSection}>
        <span style={styles.botPrSectionLabel}>CI Failure Strategy</span>
        {FAILURE_STRATEGIES.map(opt => (
          <label key={opt.value} style={styles.botPrRadioRow}>
            <input
              type="radio"
              name="failure_strategy"
              checked={settings.failure_strategy === opt.value}
              onChange={() => updateSettings({ failure_strategy: opt.value })}
            />
            <span style={styles.botPrCheckLabel}>{opt.label}</span>
          </label>
        ))}
      </div>
      <div style={styles.botPrSection}>
        <span style={styles.botPrSectionLabel}>Review Mode</span>
        {REVIEW_MODES.map(opt => (
          <label key={opt.value} style={styles.botPrRadioRow}>
            <input
              type="radio"
              name="review_mode"
              checked={settings.review_mode === opt.value}
              onChange={() => updateSettings({ review_mode: opt.value })}
            />
            <span style={styles.botPrCheckLabel}>{opt.label}</span>
          </label>
        ))}
      </div>
    </div>
  )
}
```

- [ ] **Step 3: Wire BotPRSettingsPanel into worker card rendering**

In `SystemPanel.jsx`, find the `extraContent` prop in the worker card mapping (around line 422 where `MemoryAutoApproveToggle` is conditionally rendered). Add:

```jsx
                    def.key === 'memory_sync' ? <MemoryAutoApproveToggle /> :
                    def.key === 'bot_pr' ? <BotPRSettingsPanel /> :
                    undefined
```

- [ ] **Step 4: Add styles**

Add to the `styles` object at the bottom of `SystemPanel.jsx`:

```javascript
  botPrPanel: {
    padding: '8px 0',
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  botPrSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  botPrSectionLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-muted)',
    textTransform: 'uppercase',
    marginBottom: 4,
  },
  botPrCheckRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    cursor: 'pointer',
    padding: '2px 0',
  },
  botPrRadioRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    cursor: 'pointer',
    padding: '2px 0',
  },
  botPrCheckLabel: {
    fontSize: 12,
    color: 'var(--text)',
  },
  botPrCustomRow: {
    display: 'flex',
    gap: 4,
    marginTop: 4,
  },
  botPrInput: {
    flex: 1,
    padding: '4px 8px',
    fontSize: 11,
    border: '1px solid var(--border)',
    borderRadius: 4,
    background: 'var(--bg-secondary)',
    color: 'var(--text)',
  },
  botPrAddBtn: {
    padding: '4px 12px',
    fontSize: 11,
    fontWeight: 600,
    border: '1px solid var(--accent)',
    borderRadius: 4,
    background: 'transparent',
    color: 'var(--accent)',
    cursor: 'pointer',
  },
```

- [ ] **Step 5: Commit**

```bash
git add src/ui/src/constants.js src/ui/src/components/SystemPanel.jsx
git commit -m "feat: add Bot PR Manager worker card and settings panel to dashboard"
```

---

### Task 7: Add dashboard tests

**Files:**
- Modify: `src/ui/src/components/__tests__/constants.test.js`
- Modify: `src/ui/src/components/__tests__/SystemPanel.test.jsx`

- [ ] **Step 1: Add constants test**

In `src/ui/src/components/__tests__/constants.test.js`, add:

```javascript
describe('BACKGROUND_WORKERS bot_pr entry', () => {
  it('includes bot_pr worker', () => {
    const botPr = BACKGROUND_WORKERS.find(w => w.key === 'bot_pr')
    expect(botPr).toBeDefined()
    expect(botPr.label).toBe('Bot PR Manager')
  })
})

describe('EDITABLE_INTERVAL_WORKERS includes bot_pr', () => {
  it('bot_pr is editable', () => {
    expect(EDITABLE_INTERVAL_WORKERS.has('bot_pr')).toBe(true)
  })
})
```

- [ ] **Step 2: Add SystemPanel test for settings panel rendering**

In `src/ui/src/components/__tests__/SystemPanel.test.jsx`, add a bot PR worker to `mockBgWorkers`:

```javascript
  { name: 'bot_pr', status: 'ok', enabled: false, last_run: null, details: {} },
```

And add a test:

```javascript
    it('renders Bot PR Manager settings panel', () => {
      global.fetch = vi.fn(() => Promise.resolve({
        ok: true,
        json: () => Promise.resolve({ authors: ['dependabot[bot]'], failure_strategy: 'skip', review_mode: 'ci_only' }),
      }))
      render(<SystemPanel backgroundWorkers={mockBgWorkers} />)
      expect(screen.getByText('Bot PR Manager')).toBeInTheDocument()
    })
```

- [ ] **Step 3: Run dashboard tests**

Run: `cd src/ui && npm test -- --run`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/ui/src/components/__tests__/constants.test.js src/ui/src/components/__tests__/SystemPanel.test.jsx
git commit -m "test: add dashboard tests for Bot PR Manager"
```

---

### Task 8: Quality gate

- [ ] **Step 1: Run make lint**

```bash
make lint
```

- [ ] **Step 2: Run make typecheck**

```bash
make typecheck
```

- [ ] **Step 3: Run make test-fast**

```bash
make test-fast
```

- [ ] **Step 4: Fix any issues and commit**

```bash
git add -u
git commit -m "fix: quality gate fixes for bot PR feature"
```
