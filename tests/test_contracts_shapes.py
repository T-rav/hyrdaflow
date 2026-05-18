"""Unit tests for ``contracts.shapes`` — gh JSON I/O boundary models (#8786 Phase 1).

Each test parses a representative ``gh --json`` payload through the model
and asserts the round-trip + enum pinning + alias handling. Drift tests
prove that a removed/renamed/typed-wrong field actually trips
``ValidationError`` — the whole point of the shape-typed boundary.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from contracts.shapes import (
    GhCheckRun,
    GhIssueSummary,
    GhLabel,
    GhPRDetail,
    GhPRSummary,
)

# ---------------------------------------------------------------------------
# GhLabel
# ---------------------------------------------------------------------------


def test_label_parses_full_shape() -> None:
    raw = {"name": "in-progress", "color": "ededed", "description": "active"}
    label = GhLabel.model_validate(raw)
    assert label.name == "in-progress"
    assert label.color == "ededed"


def test_label_tolerates_missing_optional_fields() -> None:
    """gh --json name without color/description is a common minimal payload."""
    label = GhLabel.model_validate({"name": "bug"})
    assert label.color is None
    assert label.description is None


def test_label_rejects_missing_name() -> None:
    """name is the contract — a label without a name is a shape drift."""
    with pytest.raises(ValidationError):
        GhLabel.model_validate({"color": "ededed"})


# ---------------------------------------------------------------------------
# GhCheckRun
# ---------------------------------------------------------------------------


def test_check_run_parses_alias_detailsUrl() -> None:
    """gh emits camelCase; the model accepts camelCase via alias."""
    raw = {
        "name": "Lint & Format",
        "state": "COMPLETED",
        "conclusion": "SUCCESS",
        "detailsUrl": "https://github.com/x/y/actions/runs/1",
    }
    cr = GhCheckRun.model_validate(raw)
    assert cr.details_url == "https://github.com/x/y/actions/runs/1"


def test_check_run_rejects_unknown_state() -> None:
    """A new state value from a gh upgrade trips the model — that's the
    shape-drift signal we want."""
    with pytest.raises(ValidationError):
        GhCheckRun.model_validate({"name": "x", "state": "WARP_DRIVE"})


def test_check_run_rejects_unknown_conclusion() -> None:
    with pytest.raises(ValidationError):
        GhCheckRun.model_validate(
            {"name": "x", "state": "COMPLETED", "conclusion": "MAYBE"}
        )


# ---------------------------------------------------------------------------
# GhPRSummary
# ---------------------------------------------------------------------------


def test_pr_summary_parses_typical_list_payload() -> None:
    raw = {
        "number": 42,
        "title": "feat: x",
        "state": "OPEN",
        "labels": [{"name": "in-progress"}],
        "updatedAt": "2026-05-13T01:00:00Z",
    }
    s = GhPRSummary.model_validate(raw)
    assert s.number == 42
    assert s.state == "OPEN"
    assert s.updated_at == "2026-05-13T01:00:00Z"
    assert len(s.labels) == 1
    assert s.labels[0].name == "in-progress"


def test_pr_summary_pins_state_enum() -> None:
    """A drifted state ('MERGE_QUEUED' etc) trips validation."""
    raw = {"number": 1, "title": "x", "state": "MERGE_QUEUED"}
    with pytest.raises(ValidationError):
        GhPRSummary.model_validate(raw)


def test_pr_summary_ignores_unknown_fields() -> None:
    """Unknown fields (new gh output) are silently ignored — they don't
    break shape compatibility for existing fields."""
    raw = {
        "number": 1,
        "title": "x",
        "state": "OPEN",
        "futureUnknownField": "ignored",
    }
    s = GhPRSummary.model_validate(raw)
    assert s.number == 1


# ---------------------------------------------------------------------------
# GhPRDetail
# ---------------------------------------------------------------------------


def test_pr_detail_parses_full_shape() -> None:
    raw = {
        "number": 42,
        "url": "https://github.com/x/y/pull/42",
        "headRefName": "feat/x",
        "baseRefName": "staging",
        "headRefOid": "1a2b3c4d5e6f7g8h",
        "labels": [{"name": "in-progress"}, {"name": "hydraflow-ready"}],
        "mergeable": "MERGEABLE",
        "isDraft": False,
    }
    d = GhPRDetail.model_validate(raw)
    assert d.head_ref_name == "feat/x"
    assert d.base_ref_name == "staging"
    assert d.head_ref_oid == "1a2b3c4d5e6f7g8h"
    assert d.mergeable == "MERGEABLE"
    assert d.is_draft is False
    assert len(d.labels) == 2


def test_pr_detail_pins_mergeable_enum() -> None:
    raw = {"number": 1, "mergeable": "PROBABLY"}
    with pytest.raises(ValidationError):
        GhPRDetail.model_validate(raw)


def test_pr_detail_round_trips_json_dump() -> None:
    """``model_dump_json`` produces output that's reparseable — important
    for the eventual replay loop persisting these via the shadow corpus."""
    raw = {"number": 1, "headRefName": "b", "mergeable": "CONFLICTING"}
    d = GhPRDetail.model_validate(raw)
    payload = json.loads(d.model_dump_json(by_alias=True))
    again = GhPRDetail.model_validate(payload)
    assert again == d


# ---------------------------------------------------------------------------
# GhIssueSummary
# ---------------------------------------------------------------------------


def test_issue_summary_parses_typical_payload() -> None:
    raw = {
        "number": 7,
        "state": "OPEN",
        "title": "Find: cassette drift",
        "body": "details…",
        "labels": [{"name": "hydraflow-find"}],
        "updatedAt": "2026-05-13T01:00:00Z",
    }
    i = GhIssueSummary.model_validate(raw)
    assert i.number == 7
    assert i.state == "OPEN"
    assert i.title == "Find: cassette drift"
    assert i.labels[0].name == "hydraflow-find"


def test_issue_summary_includes_state_reason() -> None:
    """gh reports stateReason='completed'|'not_planned' for closed issues."""
    raw = {"number": 7, "state": "CLOSED", "stateReason": "completed"}
    i = GhIssueSummary.model_validate(raw)
    assert i.state == "CLOSED"
    assert i.state_reason == "completed"


def test_issue_summary_pins_state_enum() -> None:
    raw = {"number": 1, "state": "REOPENED"}
    with pytest.raises(ValidationError):
        GhIssueSummary.model_validate(raw)


# ---------------------------------------------------------------------------
# Validator helper — the call-site contract
# ---------------------------------------------------------------------------


def test_models_validate_real_json_strings() -> None:
    """The most common call pattern: gh returns a JSON string; the call
    site validates it through the model. ``model_validate_json`` covers it."""
    raw = '{"number":1,"title":"x","state":"OPEN"}'
    s = GhPRSummary.model_validate_json(raw)
    assert s.number == 1
