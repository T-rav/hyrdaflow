"""Tests for conftest factory None-sentinel defaults."""

from __future__ import annotations

from events import EventType
from models import AnalysisVerdict, GitHubIssueState, ReviewVerdict
from tests.conftest import (
    AnalysisResultFactory,
    EventFactory,
    IssueFactory,
    ReviewResultFactory,
    TaskFactory,
    TestScaffoldResultFactory,
    TriageResultFactory,
)


class TestIssueFactoryNoneSentinels:
    """IssueFactory optional params use None sentinel, not truthy checks."""

    def test_default_labels_applied(self):
        issue = IssueFactory.create()
        assert issue.labels == ["ready"]

    def test_explicit_empty_labels_preserved(self):
        issue = IssueFactory.create(labels=[])
        assert issue.labels == []

    def test_default_comments_applied(self):
        issue = IssueFactory.create()
        assert issue.comments == []

    def test_explicit_empty_comments_preserved(self):
        issue = IssueFactory.create(comments=[])
        assert issue.comments == []

    def test_default_url_generated(self):
        issue = IssueFactory.create(number=99)
        assert str(issue.url) == "https://github.com/test-org/test-repo/issues/99"

    def test_explicit_empty_url_preserved(self):
        issue = IssueFactory.create(url="")
        assert str(issue.url) == ""

    def test_explicit_url_used(self):
        issue = IssueFactory.create(url="https://example.com/issues/1")
        assert str(issue.url) == "https://example.com/issues/1"

    def test_default_state_is_open(self):
        issue = IssueFactory.create()
        assert issue.state == GitHubIssueState.OPEN

    def test_explicit_state_closed(self):
        issue = IssueFactory.create(state=GitHubIssueState.CLOSED)
        assert issue.state == GitHubIssueState.CLOSED

    def test_explicit_state_open(self):
        issue = IssueFactory.create(state=GitHubIssueState.OPEN)
        assert issue.state == GitHubIssueState.OPEN


class TestTaskFactoryNoneSentinels:
    """TaskFactory optional params use None sentinel, not truthy checks."""

    def test_default_tags_applied(self):
        task = TaskFactory.create()
        assert task.tags == ["ready"]

    def test_explicit_empty_tags_preserved(self):
        task = TaskFactory.create(tags=[])
        assert task.tags == []

    def test_default_comments_applied(self):
        task = TaskFactory.create()
        assert task.comments == []

    def test_explicit_empty_comments_preserved(self):
        task = TaskFactory.create(comments=[])
        assert task.comments == []

    def test_default_source_url_generated(self):
        task = TaskFactory.create(id=77)
        assert str(task.source_url) == "https://github.com/test-org/test-repo/issues/77"

    def test_explicit_empty_source_url_preserved(self):
        task = TaskFactory.create(source_url="")
        assert str(task.source_url) == ""


class TestEventFactoryNoneSentinels:
    """EventFactory optional params use None sentinel, not truthy checks."""

    def test_default_timestamp_is_empty(self):
        event = EventFactory.create()
        assert event.timestamp == ""

    def test_explicit_empty_timestamp_preserved(self):
        event = EventFactory.create(timestamp="")
        assert event.timestamp == ""

    def test_explicit_timestamp_used(self):
        event = EventFactory.create(timestamp="2026-01-01T00:00:00Z")
        assert event.timestamp == "2026-01-01T00:00:00Z"

    def test_default_type_is_phase_change(self):
        event = EventFactory.create()
        assert event.type == EventType.PHASE_CHANGE

    def test_default_data_is_empty_dict(self):
        event = EventFactory.create()
        assert event.data == {}

    def test_explicit_empty_data_preserved(self):
        event = EventFactory.create(data={})
        assert event.data == {}


class TestTriageResultFactoryNoneSentinels:
    """TriageResultFactory optional params use None sentinel, not truthy checks."""

    def test_default_reasons_is_empty_list(self):
        result = TriageResultFactory.create()
        assert result.reasons == []

    def test_explicit_empty_reasons_preserved(self):
        result = TriageResultFactory.create(reasons=[])
        assert result.reasons == []

    def test_explicit_reasons_used(self):
        result = TriageResultFactory.create(reasons=["reason1"])
        assert result.reasons == ["reason1"]


class TestAnalysisResultFactoryNoneSentinels:
    """AnalysisResultFactory.create_section uses None sentinel, not truthy checks."""

    def test_default_details_is_empty_list(self):
        section = AnalysisResultFactory.create_section()
        assert section.details == []

    def test_explicit_empty_details_preserved(self):
        section = AnalysisResultFactory.create_section(details=[])
        assert section.details == []

    def test_explicit_details_used(self):
        section = AnalysisResultFactory.create_section(details=["detail1"])
        assert section.details == ["detail1"]

    def test_default_verdict_is_pass(self):
        section = AnalysisResultFactory.create_section()
        assert section.verdict == AnalysisVerdict.PASS

    def test_explicit_verdict_used(self):
        section = AnalysisResultFactory.create_section(verdict=AnalysisVerdict.WARN)
        assert section.verdict == AnalysisVerdict.WARN


class TestScaffoldResultFactoryNoneSentinels:
    """TestScaffoldResultFactory optional params use None sentinel, not truthy checks."""

    def test_default_created_dirs_is_empty_list(self):
        result = TestScaffoldResultFactory.create()
        assert result.created_dirs == []

    def test_explicit_empty_created_dirs_preserved(self):
        result = TestScaffoldResultFactory.create(created_dirs=[])
        assert result.created_dirs == []

    def test_default_created_files_is_empty_list(self):
        result = TestScaffoldResultFactory.create()
        assert result.created_files == []

    def test_explicit_empty_created_files_preserved(self):
        result = TestScaffoldResultFactory.create(created_files=[])
        assert result.created_files == []

    def test_default_modified_files_is_empty_list(self):
        result = TestScaffoldResultFactory.create()
        assert result.modified_files == []

    def test_explicit_empty_modified_files_preserved(self):
        result = TestScaffoldResultFactory.create(modified_files=[])
        assert result.modified_files == []


class TestReviewResultFactoryFieldCoverage:
    """ReviewResultFactory must support all ReviewResult fields."""

    def test_success_true_produces_success_true(self):
        result = ReviewResultFactory.create(success=True)
        assert result.success is True
        assert result.verdict == ReviewVerdict.APPROVE

    def test_success_false_produces_success_false(self):
        result = ReviewResultFactory.create(success=False)
        assert result.success is False

    def test_default_success_is_false(self):
        result = ReviewResultFactory.create()
        assert result.success is False

    def test_visual_passed_true(self):
        result = ReviewResultFactory.create(visual_passed=True)
        assert result.visual_passed is True

    def test_visual_passed_false(self):
        result = ReviewResultFactory.create(visual_passed=False)
        assert result.visual_passed is False

    def test_visual_passed_default_is_none(self):
        result = ReviewResultFactory.create()
        assert result.visual_passed is None

    def test_files_changed_explicit(self):
        result = ReviewResultFactory.create(files_changed=["src/a.py"])
        assert result.files_changed == ["src/a.py"]

    def test_files_changed_default_is_empty(self):
        result = ReviewResultFactory.create()
        assert result.files_changed == []

    def test_use_defaults_preserves_success(self):
        result = ReviewResultFactory.create(use_defaults=True, success=True)
        assert result.success is True

    def test_use_defaults_preserves_visual_passed(self):
        result = ReviewResultFactory.create(use_defaults=True, visual_passed=True)
        assert result.visual_passed is True
