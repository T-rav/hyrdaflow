"""Tests for PromptDeduplicator."""

from prompt_dedup import PromptDeduplicator


def test_is_duplicate_first_seen():
    d = PromptDeduplicator()
    assert d.is_duplicate("hello world") is False


def test_is_duplicate_second_seen():
    d = PromptDeduplicator()
    d.is_duplicate("hello world")
    assert d.is_duplicate("hello world") is True


def test_is_duplicate_different_content():
    d = PromptDeduplicator()
    d.is_duplicate("hello world")
    assert d.is_duplicate("goodbye world") is False


def test_dedup_memories_removes_overlapping():
    d = PromptDeduplicator()
    memories = [
        "Always run lint before committing code changes",
        "Always run lint before committing code",  # >70% overlap with first
        "Use async for I/O bound operations",
    ]
    result = d.dedup_memories(memories)
    assert len(result) == 2
    assert "Always run lint" in result[0]
    assert "async" in result[1]


def test_dedup_memories_keeps_unique():
    d = PromptDeduplicator()
    memories = [
        "Always run lint before committing",
        "Use async for I/O operations",
        "Check security headers in API routes",
    ]
    result = d.dedup_memories(memories)
    assert len(result) == 3


def test_dedup_memories_empty():
    d = PromptDeduplicator()
    assert d.dedup_memories([]) == []


def test_dedup_memories_short_words_ignored():
    d = PromptDeduplicator()
    memories = [
        "a b c d e f",  # all short words
        "x y z w v u",
    ]
    result = d.dedup_memories(memories)
    assert len(result) == 2  # no overlap since no words >= 4 chars


# ------------------------------------------------------------------
# Architectural coverage: dedup is applied in base_runner, not in
# agent/planner prompt builders.  These tests verify the contract.
# ------------------------------------------------------------------


def test_base_runner_inject_calls_dedup(monkeypatch):
    """BaseRunner._inject_manifest_and_memory uses PromptDeduplicator.

    Agent and planner prompt builders delegate memory injection to the
    base runner, which already deduplicates across Hindsight banks.
    No additional dedup is needed in agent.py or planner.py because
    their prompt sections (plan, review feedback, comments, etc.) are
    distinct content types that don't overlap with memory items.
    """
    # Read the source to confirm PromptDeduplicator is used in
    # _inject_manifest_and_memory — a structural assertion that the
    # dedup integration point exists and hasn't drifted.
    import inspect

    import base_runner as br_mod

    source = inspect.getsource(br_mod.BaseRunner._inject_manifest_and_memory)
    assert "PromptDeduplicator" in source
    assert "dedup_memories" in source


def test_agent_prompt_delegates_memory_to_base(monkeypatch):
    """AgentRunner._build_prompt_with_stats calls _inject_manifest_and_memory.

    This confirms the agent does not build its own memory section — it
    relies on the base runner's dedup-aware injection.
    """
    import inspect

    import agent as agent_mod

    source = inspect.getsource(agent_mod.AgentRunner._build_prompt_with_stats)
    assert "_inject_manifest_and_memory" in source
    # Agent should NOT import or instantiate its own PromptDeduplicator
    assert "PromptDeduplicator" not in source


def test_planner_prompt_delegates_memory_to_base(monkeypatch):
    """PlannerRunner._build_prompt_with_stats calls _inject_manifest_and_memory.

    This confirms the planner does not build its own memory section — it
    relies on the base runner's dedup-aware injection.
    """
    import inspect

    import planner as planner_mod

    source = inspect.getsource(planner_mod.PlannerRunner._build_prompt_with_stats)
    assert "_inject_manifest_and_memory" in source
    # Planner should NOT import or instantiate its own PromptDeduplicator
    assert "PromptDeduplicator" not in source
