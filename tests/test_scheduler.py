"""Tests for the fair multi-repo scheduler."""

from __future__ import annotations

import asyncio

import pytest

from scheduler import FairScheduler, SchedulerConfig, StageBudget, StageQuota

# ---------------------------------------------------------------------------
# StageQuota
# ---------------------------------------------------------------------------


class TestStageQuota:
    def test_default_values(self) -> None:
        q = StageQuota()
        assert q.global_max == 4
        assert q.per_repo_max == 2
        assert q.per_repo_min == 0

    def test_custom_values(self) -> None:
        q = StageQuota(global_max=8, per_repo_max=3, per_repo_min=1)
        assert q.global_max == 8
        assert q.per_repo_max == 3
        assert q.per_repo_min == 1


# ---------------------------------------------------------------------------
# SchedulerConfig
# ---------------------------------------------------------------------------


class TestSchedulerConfig:
    def test_default_stage_quotas(self) -> None:
        cfg = SchedulerConfig()
        assert cfg.implement.global_max == 4
        assert cfg.implement.per_repo_max == 2

    def test_quota_for_known_stage(self) -> None:
        cfg = SchedulerConfig()
        q = cfg.quota_for("implement")
        assert q.global_max == 4

    def test_quota_for_unknown_stage_returns_default(self) -> None:
        cfg = SchedulerConfig()
        q = cfg.quota_for("nonexistent")
        assert q.global_max == 4  # StageQuota default


# ---------------------------------------------------------------------------
# StageBudget
# ---------------------------------------------------------------------------


class TestStageBudget:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        budget = StageBudget(StageQuota(global_max=2, per_repo_max=2))
        assert await budget.try_acquire("repo-a")
        assert budget.active_for("repo-a") == 1
        assert budget.total_active == 1
        await budget.release("repo-a")
        assert budget.active_for("repo-a") == 0

    @pytest.mark.asyncio
    async def test_per_repo_max_enforced(self) -> None:
        budget = StageBudget(StageQuota(global_max=4, per_repo_max=1))
        assert await budget.try_acquire("repo-a")
        # Second acquire should fail (per-repo max = 1)
        assert not await budget.try_acquire("repo-a")
        # Different repo should succeed
        assert await budget.try_acquire("repo-b")

    @pytest.mark.asyncio
    async def test_global_max_enforced(self) -> None:
        budget = StageBudget(StageQuota(global_max=2, per_repo_max=2))
        assert await budget.try_acquire("repo-a")
        assert await budget.try_acquire("repo-b")
        # Global max reached (2)
        assert not await budget.try_acquire("repo-c")
        # Release one, then repo-c should succeed
        await budget.release("repo-a")
        assert await budget.try_acquire("repo-c")

    @pytest.mark.asyncio
    async def test_snapshot_shows_per_repo_counts(self) -> None:
        budget = StageBudget(StageQuota(global_max=4, per_repo_max=2))
        await budget.try_acquire("repo-a")
        await budget.try_acquire("repo-b")
        await budget.try_acquire("repo-a")
        snap = budget.snapshot()
        assert snap == {"repo-a": 2, "repo-b": 1}


# ---------------------------------------------------------------------------
# FairScheduler
# ---------------------------------------------------------------------------


class TestFairScheduler:
    @pytest.mark.asyncio
    async def test_acquire_and_release(self) -> None:
        sched = FairScheduler()
        assert await sched.acquire("implement", "repo-a")
        await sched.release("implement", "repo-a")

    @pytest.mark.asyncio
    async def test_can_acquire_check(self) -> None:
        cfg = SchedulerConfig(
            implement=StageQuota(global_max=1, per_repo_max=1),
        )
        sched = FairScheduler(cfg)
        assert sched.can_acquire("implement", "repo-a")
        await sched.acquire("implement", "repo-a")
        assert not sched.can_acquire("implement", "repo-a")
        assert not sched.can_acquire("implement", "repo-b")  # global exhausted

    @pytest.mark.asyncio
    async def test_unknown_stage_raises(self) -> None:
        sched = FairScheduler()
        with pytest.raises(ValueError, match="Unknown stage"):
            sched.budget_for("nonexistent")

    @pytest.mark.asyncio
    async def test_metrics_structure(self) -> None:
        sched = FairScheduler()
        await sched.acquire("implement", "repo-a")
        m = sched.metrics()
        assert "implement" in m
        assert m["implement"]["total_active"] == 1
        assert m["implement"]["per_repo"]["repo-a"] == 1

    @pytest.mark.asyncio
    async def test_two_repos_fair_contention(self) -> None:
        """Two repos compete for 2 global implement slots (max 1 each).

        Each repo should get exactly 1 slot, not 0 or 2.
        """
        cfg = SchedulerConfig(
            implement=StageQuota(global_max=2, per_repo_max=1),
        )
        sched = FairScheduler(cfg)

        assert await sched.acquire("implement", "repo-a")
        assert await sched.acquire("implement", "repo-b")
        # Both at max, neither can get more
        assert not await sched.acquire("implement", "repo-a")
        assert not await sched.acquire("implement", "repo-b")

        # Release repo-a, repo-b still can't (at max), but repo-a can again
        await sched.release("implement", "repo-a")
        assert await sched.acquire("implement", "repo-a")

    @pytest.mark.asyncio
    async def test_starvation_prevention(self) -> None:
        """A busy repo cannot consume all global slots when per-repo max is set."""
        cfg = SchedulerConfig(
            implement=StageQuota(global_max=4, per_repo_max=2),
        )
        sched = FairScheduler(cfg)

        # Repo-A takes 2 slots (its max)
        assert await sched.acquire("implement", "repo-a")
        assert await sched.acquire("implement", "repo-a")
        assert not await sched.acquire("implement", "repo-a")

        # Repo-B can still get its 2 slots
        assert await sched.acquire("implement", "repo-b")
        assert await sched.acquire("implement", "repo-b")

        # Global budget now exhausted
        assert not await sched.acquire("implement", "repo-c")

    @pytest.mark.asyncio
    async def test_immediate_refill_on_release(self) -> None:
        """When a repo releases a slot, another repo can immediately acquire it."""
        cfg = SchedulerConfig(
            implement=StageQuota(global_max=1, per_repo_max=1),
        )
        sched = FairScheduler(cfg)

        assert await sched.acquire("implement", "repo-a")
        assert not await sched.acquire("implement", "repo-b")

        await sched.release("implement", "repo-a")
        # Immediately available for repo-b
        assert await sched.acquire("implement", "repo-b")

    @pytest.mark.asyncio
    async def test_concurrent_contention(self) -> None:
        """Simulate concurrent acquisition across two repos."""
        cfg = SchedulerConfig(
            implement=StageQuota(global_max=3, per_repo_max=2),
        )
        sched = FairScheduler(cfg)
        results: dict[str, int] = {"repo-a": 0, "repo-b": 0}

        async def acquire_many(slug: str, count: int) -> None:
            for _ in range(count):
                if await sched.acquire("implement", slug):
                    results[slug] += 1

        await asyncio.gather(
            acquire_many("repo-a", 5),
            acquire_many("repo-b", 5),
        )

        # Each repo should get at most per_repo_max=2
        assert results["repo-a"] <= 2
        assert results["repo-b"] <= 2
        # Total should not exceed global_max=3
        assert results["repo-a"] + results["repo-b"] <= 3
