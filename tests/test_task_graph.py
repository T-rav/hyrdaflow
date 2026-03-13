"""Tests for task_graph.py — Task Graph parsing and extraction."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from task_graph import (
    TaskGraphPhase,
    extract_impl_step_texts,
    extract_phases,
    has_task_graph,
    topological_sort,
)

# ---------------------------------------------------------------------------
# has_task_graph
# ---------------------------------------------------------------------------


class TestHasTaskGraph:
    def test_detects_task_graph_header(self):
        assert has_task_graph("## Task Graph\nSome content")

    def test_case_insensitive(self):
        assert has_task_graph("## task graph\nSome content")

    def test_returns_false_when_absent(self):
        assert not has_task_graph("## Implementation Steps\n1. Do stuff")

    def test_partial_match_rejected(self):
        assert not has_task_graph("## Task Graphs Are Great")


# ---------------------------------------------------------------------------
# extract_phases
# ---------------------------------------------------------------------------


class TestExtractPhases:
    def test_parses_valid_two_phase_graph(self):
        body = (
            "### P1 \u2014 Data Model\n"
            "**Files:** src/models.py (modify), migrations/001.py (create)\n"
            "**Tests:**\n"
            "- Creating a Widget persists and returns an id\n"
            "- Duplicate name raises IntegrityError\n"
            "**Depends on:** (none)\n\n"
            "### P2 \u2014 Service Layer\n"
            "**Files:** src/service.py (create)\n"
            "**Tests:**\n"
            "- Service.create() with valid input returns a Widget\n"
            "**Depends on:** P1\n"
        )
        phases = extract_phases(body)
        assert len(phases) == 2
        assert isinstance(phases[0], TaskGraphPhase)

        assert phases[0].id == "P1"
        assert phases[0].name == "P1 \u2014 Data Model"
        assert "src/models.py" in phases[0].files
        assert len(phases[0].tests) == 2
        assert phases[0].depends_on == []

        assert phases[1].id == "P2"
        assert phases[1].depends_on == ["P1"]

    def test_returns_empty_for_no_headers(self):
        assert extract_phases("Just some text without phases") == []

    def test_returns_empty_for_empty_string(self):
        assert extract_phases("") == []

    def test_single_phase(self):
        body = (
            "### P1 \u2014 Quick Fix\n"
            "**Files:** src/main.py\n"
            "**Tests:**\n"
            "- App starts without error\n"
            "**Depends on:** (none)\n"
        )
        phases = extract_phases(body)
        assert len(phases) == 1
        assert phases[0].id == "P1"

    def test_dash_separator_works(self):
        body = (
            "### P1 - Data Model\n"
            "**Files:** src/models.py\n"
            "**Tests:**\n"
            "- Model validates input\n"
            "**Depends on:** (none)\n"
        )
        phases = extract_phases(body)
        assert len(phases) == 1
        assert phases[0].name == "P1 \u2014 Data Model"

    def test_multiple_dependencies(self):
        body = (
            "### P1 \u2014 Base\n"
            "**Files:** src/base.py\n"
            "**Tests:**\n"
            "- Base works\n"
            "**Depends on:** (none)\n\n"
            "### P2 \u2014 Mid\n"
            "**Files:** src/mid.py\n"
            "**Tests:**\n"
            "- Mid works\n"
            "**Depends on:** (none)\n\n"
            "### P3 \u2014 Top\n"
            "**Files:** src/top.py\n"
            "**Tests:**\n"
            "- Top works\n"
            "**Depends on:** P1, P2\n"
        )
        phases = extract_phases(body)
        assert len(phases) == 3
        assert phases[2].depends_on == ["P1", "P2"]

    def test_phase_without_tests_returns_empty_tests_list(self):
        body = (
            "### P1 \u2014 No Tests\n**Files:** src/main.py\n**Depends on:** (none)\n"
        )
        phases = extract_phases(body)
        assert len(phases) == 1
        assert phases[0].tests == []

    def test_phase_without_files_returns_empty_files_list(self):
        body = (
            "### P1 \u2014 No Files\n"
            "**Tests:**\n"
            "- Something works\n"
            "**Depends on:** (none)\n"
        )
        phases = extract_phases(body)
        assert len(phases) == 1
        assert phases[0].files == []


# ---------------------------------------------------------------------------
# extract_impl_step_texts
# ---------------------------------------------------------------------------


class TestExtractImplStepTexts:
    def test_extracts_numbered_steps(self):
        body = "1. Add the model\n2. Update the config\n3. Write tests\n"
        steps = extract_impl_step_texts(body)
        assert len(steps) == 3
        assert "Add the model" in steps[0]

    def test_extracts_bulleted_steps(self):
        body = "- Add the model\n- Update the config\n"
        steps = extract_impl_step_texts(body)
        assert len(steps) == 2

    def test_extracts_checkbox_steps(self):
        body = "[ ] Add the model\n[x] Update the config\n"
        steps = extract_impl_step_texts(body)
        assert len(steps) == 2

    def test_extracts_heading_steps(self):
        body = "## Step 1: Add the model\n## Step 2: Write tests\n"
        steps = extract_impl_step_texts(body)
        assert len(steps) == 2

    def test_returns_empty_for_no_steps(self):
        body = "Just some prose without any list items."
        steps = extract_impl_step_texts(body)
        assert steps == []

    def test_returns_empty_for_empty_string(self):
        steps = extract_impl_step_texts("")
        assert steps == []

    def test_filters_empty_strings(self):
        body = "1. Good step\n2.  \n3. Another step\n"
        steps = extract_impl_step_texts(body)
        assert all(s.strip() for s in steps)


# ---------------------------------------------------------------------------
# topological_sort
# ---------------------------------------------------------------------------


class TestTopologicalSort:
    def test_no_deps(self):
        phases = [
            TaskGraphPhase(id="P1", name="P1 — A", files=[], tests=[], depends_on=[]),
            TaskGraphPhase(id="P2", name="P2 — B", files=[], tests=[], depends_on=[]),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1", "P2"]

    def test_respects_deps(self):
        phases = [
            TaskGraphPhase(
                id="P2", name="P2 — B", files=[], tests=[], depends_on=["P1"]
            ),
            TaskGraphPhase(id="P1", name="P1 — A", files=[], tests=[], depends_on=[]),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1", "P2"]

    def test_cycle_returns_original_order(self):
        phases = [
            TaskGraphPhase(
                id="P1", name="P1 — A", files=[], tests=[], depends_on=["P2"]
            ),
            TaskGraphPhase(
                id="P2", name="P2 — B", files=[], tests=[], depends_on=["P1"]
            ),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1", "P2"]

    def test_missing_dep_skipped(self):
        phases = [
            TaskGraphPhase(
                id="P1", name="P1 — A", files=[], tests=[], depends_on=["P99"]
            ),
        ]
        result = topological_sort(phases)
        assert [p.id for p in result] == ["P1"]

    def test_diamond_deps(self):
        phases = [
            TaskGraphPhase(id="P1", name="P1", files=[], tests=[], depends_on=[]),
            TaskGraphPhase(id="P2", name="P2", files=[], tests=[], depends_on=["P1"]),
            TaskGraphPhase(id="P3", name="P3", files=[], tests=[], depends_on=["P1"]),
            TaskGraphPhase(
                id="P4", name="P4", files=[], tests=[], depends_on=["P2", "P3"]
            ),
        ]
        result = topological_sort(phases)
        ids = [p.id for p in result]
        assert ids.index("P1") < ids.index("P2")
        assert ids.index("P1") < ids.index("P3")
        assert ids.index("P2") < ids.index("P4")
        assert ids.index("P3") < ids.index("P4")
