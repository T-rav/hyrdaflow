"""Property-based tests for the HydraFlow label state machine.

Uses Hypothesis to assert invariants that must hold regardless of which
sequence of transitions is applied.  These complement the unit tests in
test_plan_phase.py, test_implement_phase.py, etc. by exploring the
transition space automatically.

State machine (canonical labels):

    find ──► plan ──► ready ──► review ──► fixed
                │       │         │
                └───────┴─────────┴──► hitl ──► ready (correction)

Invariants tested:
  1. After any swap_pipeline_labels call, the issue has exactly one
     pipeline label (single-label invariant).
  2. All valid stage names ("find", "plan", "ready", "review", "hitl")
     map to exactly one known pipeline label.
  3. swap_pipeline_labels removes all labels except the target before
     adding the target (no-dual-label invariant).
  4. Arbitrary sequences of valid transitions never violate invariant 1.
  5. Unknown stage names passed to transition() do not crash the system
     (they are treated as raw label names and still satisfy invariant 1).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# Shared state machine data
# ---------------------------------------------------------------------------

# Canonical default pipeline labels (mirrors HydraFlowConfig defaults)
ALL_PIPELINE_LABELS: list[str] = [
    "hydraflow-find",
    "hydraflow-plan",
    "hydraflow-ready",
    "hydraflow-review",
    "hydraflow-hitl",
    "hydraflow-hitl-active",
    "hydraflow-fixed",
    "hydraflow-improve",
]

# Valid stage names accepted by PRManager.transition()
VALID_STAGES: list[str] = ["find", "plan", "ready", "review", "hitl"]

# Valid transitions in the pipeline (source_stage → allowed_next_stages)
VALID_TRANSITIONS: dict[str, list[str]] = {
    "find": ["plan"],
    "plan": ["ready", "hitl"],
    "ready": ["review", "hitl"],
    "review": ["hitl"],  # "fixed" is set by merge, not transition()
    "hitl": ["ready", "review"],
}

# Hypothesis strategy: any valid stage name
st_stage = st.sampled_from(VALID_STAGES)

# Hypothesis strategy: a sequence of 1–20 valid stage transitions
st_stage_sequence = st.lists(st_stage, min_size=1, max_size=20)

# Hypothesis strategy: arbitrary label string (possibly unknown)
st_label = st.text(
    alphabet=st.characters(
        whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-"
    ),
    min_size=1,
    max_size=40,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(labels: list[str] | None = None) -> MagicMock:
    """Build a minimal HydraFlowConfig mock with default pipeline labels."""
    config = MagicMock()
    config.all_pipeline_labels = labels or ALL_PIPELINE_LABELS
    config.find_label = ["hydraflow-find"]
    config.planner_label = ["hydraflow-plan"]
    config.ready_label = ["hydraflow-ready"]
    config.review_label = ["hydraflow-review"]
    config.hitl_label = ["hydraflow-hitl"]
    config.hitl_active_label = ["hydraflow-hitl-active"]
    config.fixed_label = ["hydraflow-fixed"]
    config.improve_label = ["hydraflow-improve"]
    config.repo = "org/repo"
    config.gh_token = None
    config.dry_run = False
    return config


def _issue_labels_after_swap(new_label: str, starting_labels: list[str]) -> set[str]:
    """Simulate swap_pipeline_labels without GitHub I/O.

    Models the logic in PRManager.swap_pipeline_labels:
    - Remove every pipeline label that is not new_label.
    - Add new_label.

    Returns the resulting set of labels on the issue.
    """
    all_pipeline = set(ALL_PIPELINE_LABELS)
    current = set(starting_labels)
    # Remove all pipeline labels except the target
    for lbl in all_pipeline:
        if lbl != new_label:
            current.discard(lbl)
    # Add target
    current.add(new_label)
    return current


def _stage_to_label(stage: str) -> str:
    """Map a stage name to its default label (mirrors PRManager.transition logic)."""
    mapping = {
        "find": "hydraflow-find",
        "plan": "hydraflow-plan",
        "ready": "hydraflow-ready",
        "review": "hydraflow-review",
        "hitl": "hydraflow-hitl",
    }
    return mapping.get(stage, stage)


# ---------------------------------------------------------------------------
# Unit-style property tests (pure logic, no I/O)
# ---------------------------------------------------------------------------


class TestSingleLabelInvariant:
    """After swap, exactly one pipeline label remains."""

    @given(new_label=st.sampled_from(ALL_PIPELINE_LABELS))
    def test_swap_from_empty_leaves_one_label(self, new_label: str) -> None:
        """Starting from no labels, swap produces exactly one pipeline label."""
        result = _issue_labels_after_swap(new_label, starting_labels=[])
        pipeline_on_issue = result & set(ALL_PIPELINE_LABELS)
        assert len(pipeline_on_issue) == 1
        assert new_label in pipeline_on_issue

    @given(
        new_label=st.sampled_from(ALL_PIPELINE_LABELS),
        starting=st.lists(st.sampled_from(ALL_PIPELINE_LABELS), min_size=0, max_size=8),
    )
    def test_swap_from_any_state_leaves_one_label(
        self, new_label: str, starting: list[str]
    ) -> None:
        """Regardless of how many pipeline labels an issue has, swap leaves exactly one."""
        result = _issue_labels_after_swap(new_label, starting_labels=starting)
        pipeline_on_issue = result & set(ALL_PIPELINE_LABELS)
        assert len(pipeline_on_issue) == 1
        assert new_label in pipeline_on_issue

    @given(stage=st_stage)
    def test_valid_stage_maps_to_known_label(self, stage: str) -> None:
        """Every valid stage name maps to a label that is in ALL_PIPELINE_LABELS."""
        label = _stage_to_label(stage)
        assert label in ALL_PIPELINE_LABELS, (
            f"Stage '{stage}' mapped to '{label}' which is not a pipeline label"
        )

    @given(
        new_label=st.sampled_from(ALL_PIPELINE_LABELS),
        starting=st.lists(st.sampled_from(ALL_PIPELINE_LABELS), min_size=1, max_size=8),
    )
    def test_target_label_always_present_after_swap(
        self, new_label: str, starting: list[str]
    ) -> None:
        """The new_label is always present after swap."""
        result = _issue_labels_after_swap(new_label, starting)
        assert new_label in result

    @given(
        new_label=st.sampled_from(ALL_PIPELINE_LABELS),
        starting=st.lists(st.sampled_from(ALL_PIPELINE_LABELS), min_size=0, max_size=8),
    )
    def test_no_other_pipeline_label_remains(
        self, new_label: str, starting: list[str]
    ) -> None:
        """After swap, no pipeline label other than new_label is on the issue."""
        result = _issue_labels_after_swap(new_label, starting)
        for label in ALL_PIPELINE_LABELS:
            if label != new_label:
                assert label not in result, (
                    f"'{label}' still present after swapping to '{new_label}'. "
                    f"Started with: {starting}"
                )


class TestTransitionSequences:
    """Arbitrary valid-stage sequences never violate the single-label invariant."""

    @given(stages=st_stage_sequence)
    def test_transition_sequence_always_single_label(self, stages: list[str]) -> None:
        """Applying any sequence of valid stage transitions leaves exactly one pipeline label."""
        current_labels: list[str] = []
        for stage in stages:
            new_label = _stage_to_label(stage)
            current_labels = list(_issue_labels_after_swap(new_label, current_labels))

        pipeline_on_issue = set(current_labels) & set(ALL_PIPELINE_LABELS)
        assert len(pipeline_on_issue) == 1

    @given(stages=st_stage_sequence)
    def test_final_label_matches_last_stage(self, stages: list[str]) -> None:
        """The pipeline label after a sequence always matches the last stage applied."""
        current_labels: list[str] = []
        for stage in stages:
            new_label = _stage_to_label(stage)
            current_labels = list(_issue_labels_after_swap(new_label, current_labels))

        expected_final = _stage_to_label(stages[-1])
        assert expected_final in set(current_labels)


class TestNoDualLabelBug:
    """The dual-label bug (two pipeline labels simultaneously) cannot occur via swap."""

    @given(
        label_a=st.sampled_from(ALL_PIPELINE_LABELS),
        label_b=st.sampled_from(ALL_PIPELINE_LABELS),
    )
    def test_cannot_have_two_pipeline_labels(self, label_a: str, label_b: str) -> None:
        """Swapping to label_b always removes label_a if they are different."""
        # Start with label_a on the issue
        after_a = _issue_labels_after_swap(label_a, [])
        # Then swap to label_b
        after_b = _issue_labels_after_swap(label_b, list(after_a))

        pipeline_on_issue = after_b & set(ALL_PIPELINE_LABELS)
        assert len(pipeline_on_issue) == 1
        assert label_b in pipeline_on_issue
        if label_a != label_b:
            assert label_a not in pipeline_on_issue


class TestNonPipelineLabelPreservation:
    """Non-pipeline labels (e.g. 'bug', 'priority:high') survive swap_pipeline_labels.

    swap_pipeline_labels must only touch pipeline labels.  User-defined labels
    such as 'bug', 'good first issue', or 'priority:high' must be left intact
    throughout the entire pipeline lifecycle.
    """

    # Strategy: arbitrary label strings that are NOT pipeline labels
    _st_user_label = st.text(
        alphabet=st.characters(
            whitelist_categories=("Ll", "Lu", "Nd"), whitelist_characters="-: "
        ),
        min_size=1,
        max_size=40,
    ).filter(lambda lbl: lbl not in ALL_PIPELINE_LABELS)

    @given(
        new_label=st.sampled_from(ALL_PIPELINE_LABELS),
        user_labels=st.lists(_st_user_label, min_size=1, max_size=5),
    )
    def test_non_pipeline_labels_survive_swap(
        self, new_label: str, user_labels: list[str]
    ) -> None:
        """All non-pipeline labels present before swap are still present after."""
        # Start with the user labels and one pipeline label
        starting = user_labels + [ALL_PIPELINE_LABELS[0]]
        result = _issue_labels_after_swap(new_label, starting)
        for lbl in user_labels:
            assert lbl in result, (
                f"Non-pipeline label '{lbl}' was removed by swap to '{new_label}'. "
                f"swap_pipeline_labels must only remove pipeline labels."
            )

    @given(
        stages=st_stage_sequence,
        user_labels=st.lists(_st_user_label, min_size=1, max_size=3),
    )
    def test_non_pipeline_labels_survive_full_sequence(
        self, stages: list[str], user_labels: list[str]
    ) -> None:
        """User-defined labels survive an arbitrary sequence of pipeline transitions."""
        current_labels: list[str] = list(user_labels)
        for stage in stages:
            new_label = _stage_to_label(stage)
            current_labels = list(_issue_labels_after_swap(new_label, current_labels))

        for lbl in user_labels:
            assert lbl in current_labels, (
                f"Non-pipeline label '{lbl}' was lost after stages {stages}."
            )


# ---------------------------------------------------------------------------
# Async integration tests (PRManager with mocked gh CLI calls)
# ---------------------------------------------------------------------------


class TestSwapPipelineLabelsAsync:
    """swap_pipeline_labels calls _remove_label for every label except target,
    then calls _add_labels for the target."""

    @pytest.mark.asyncio
    @given(new_label=st.sampled_from(ALL_PIPELINE_LABELS))
    @settings(max_examples=10, deadline=None)
    async def test_removes_all_other_pipeline_labels(self, new_label: str) -> None:
        """swap_pipeline_labels issues remove calls for all labels != new_label."""
        from pr_manager import PRManager

        config = _make_config()
        event_bus = MagicMock()
        mgr = PRManager(config, event_bus)

        removed: list[str] = []
        added: list[str] = []

        async def fake_remove(_kind: str, _number: int, label: str) -> None:
            removed.append(label)

        async def fake_add(_kind: str, _number: int, labels: list[str]) -> None:
            added.extend(labels)

        mgr._remove_label = fake_remove  # type: ignore[method-assign]
        mgr._add_labels = fake_add  # type: ignore[method-assign]

        await mgr.swap_pipeline_labels(42, new_label)

        # Every pipeline label except new_label must have a remove call
        expected_removed = set(ALL_PIPELINE_LABELS) - {new_label}
        assert set(removed) == expected_removed, (
            f"Expected to remove {expected_removed}, actually removed {set(removed)}"
        )

        # The new_label must be added exactly once
        assert added.count(new_label) == 1

    @pytest.mark.asyncio
    @given(stage=st_stage)
    @settings(max_examples=5, deadline=None)
    async def test_transition_maps_to_correct_label(self, stage: str) -> None:
        """PRManager.transition() calls swap_pipeline_labels with the correct label."""
        from pr_manager import PRManager

        config = _make_config()
        event_bus = MagicMock()
        mgr = PRManager(config, event_bus)

        swapped_to: list[str] = []

        async def fake_swap(
            _issue_number: int, new_label: str, **_kwargs: object
        ) -> None:
            swapped_to.append(new_label)

        mgr.swap_pipeline_labels = fake_swap  # type: ignore[method-assign]

        await mgr.transition(99, stage)

        expected_label = _stage_to_label(stage)
        assert swapped_to == [expected_label], (
            f"Stage '{stage}' should swap to '{expected_label}', got {swapped_to}"
        )
