"""Fair multi-repo worker scheduler.

Provides global stage budgets with per-repo min/max quotas and
round-robin fairness to prevent a single busy repo from starving
others of worker slots.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

logger = logging.getLogger("hydraflow.scheduler")

STAGES = ("triage", "plan", "implement", "review", "hitl")


@dataclass
class StageQuota:
    """Budget configuration for a single pipeline stage."""

    global_max: int = 4
    per_repo_max: int = 2
    per_repo_min: int = 0


@dataclass
class SchedulerConfig:
    """Configuration for the fair scheduler."""

    triage: StageQuota = field(
        default_factory=lambda: StageQuota(global_max=2, per_repo_max=1)
    )
    plan: StageQuota = field(
        default_factory=lambda: StageQuota(global_max=2, per_repo_max=1)
    )
    implement: StageQuota = field(
        default_factory=lambda: StageQuota(global_max=4, per_repo_max=2)
    )
    review: StageQuota = field(
        default_factory=lambda: StageQuota(global_max=4, per_repo_max=2)
    )
    hitl: StageQuota = field(
        default_factory=lambda: StageQuota(global_max=2, per_repo_max=1)
    )

    def quota_for(self, stage: str) -> StageQuota:
        """Return the quota for a stage."""
        return getattr(self, stage, StageQuota())


class StageBudget:
    """Tracks global and per-repo worker slot usage for one stage.

    The global semaphore caps total concurrent workers across all repos.
    Per-repo counters enforce per_repo_max and enable fairness metrics.
    """

    def __init__(self, quota: StageQuota) -> None:
        self._quota = quota
        self._global_sem = asyncio.Semaphore(quota.global_max)
        self._repo_active: dict[str, int] = {}
        self._lock = asyncio.Lock()
        # Round-robin tracking: last slug that was granted a slot
        self._last_granted: str = ""

    @property
    def quota(self) -> StageQuota:
        return self._quota

    async def try_acquire(self, slug: str) -> bool:
        """Try to acquire a worker slot for a repo (non-blocking).

        Returns ``True`` if a slot was acquired, ``False`` if the repo
        is at its per-repo max or the global budget is exhausted.
        """
        async with self._lock:
            active = self._repo_active.get(slug, 0)
            if active >= self._quota.per_repo_max:
                return False
            # Try non-blocking acquire on global semaphore
            if self._global_sem._value <= 0:  # noqa: SLF001
                return False
            await self._global_sem.acquire()
            self._repo_active[slug] = active + 1
            self._last_granted = slug
            return True

    async def release(self, slug: str) -> None:
        """Release a worker slot."""
        async with self._lock:
            count = self._repo_active.get(slug, 0)
            if count > 0:
                self._repo_active[slug] = count - 1
        self._global_sem.release()

    def active_for(self, slug: str) -> int:
        """Return the number of active workers for a repo."""
        return self._repo_active.get(slug, 0)

    @property
    def total_active(self) -> int:
        """Total active workers across all repos."""
        return sum(self._repo_active.values())

    @property
    def available(self) -> int:
        """Number of available global slots."""
        return self._global_sem._value  # noqa: SLF001

    def snapshot(self) -> dict[str, int]:
        """Return per-repo active counts for metrics."""
        return dict(self._repo_active)


class FairScheduler:
    """Coordinates worker slot allocation across repos with fairness.

    Each pipeline stage has a :class:`StageBudget` that enforces global
    caps and per-repo quotas.  Repos acquire/release slots through
    this scheduler so no single repo can monopolize all workers.
    """

    def __init__(self, config: SchedulerConfig | None = None) -> None:
        self._config = config or SchedulerConfig()
        self._budgets: dict[str, StageBudget] = {
            stage: StageBudget(self._config.quota_for(stage)) for stage in STAGES
        }

    def budget_for(self, stage: str) -> StageBudget:
        """Return the budget tracker for a stage."""
        if stage not in self._budgets:
            msg = f"Unknown stage: {stage}"
            raise ValueError(msg)
        return self._budgets[stage]

    async def acquire(self, stage: str, slug: str) -> bool:
        """Try to acquire a worker slot for a repo in a stage."""
        return await self._budgets[stage].try_acquire(slug)

    async def release(self, stage: str, slug: str) -> None:
        """Release a worker slot."""
        await self._budgets[stage].release(slug)

    def can_acquire(self, stage: str, slug: str) -> bool:
        """Check if a slot could be acquired (non-blocking check)."""
        budget = self._budgets[stage]
        return (
            budget.active_for(slug) < budget.quota.per_repo_max and budget.available > 0
        )

    def metrics(self) -> dict[str, dict[str, int | dict[str, int]]]:
        """Return fairness metrics for all stages."""
        return {
            stage: {
                "global_max": budget.quota.global_max,
                "total_active": budget.total_active,
                "available": budget.available,
                "per_repo": budget.snapshot(),
            }
            for stage, budget in self._budgets.items()
        }
