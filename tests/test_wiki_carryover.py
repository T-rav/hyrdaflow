"""Tests for ``src.wiki_carryover`` — shipped-with-known-gap detection
and wiki entry rendering for the adversarial pipeline.

Covers:
* ``detect_shipped_with_known_gaps`` returns ``[]`` on an empty state.
* Unresolved pending concerns survive to become "known gaps".
* Concerns whose ``id`` matches an ``addressed_concerns[].concern_id`` are
  excluded.
* ``build_wiki_entry`` returns an empty string when there are no concerns.
* ``build_wiki_entry`` renders Markdown + ``json:entry`` block including
  the severity, id, concern text, and PR number.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from src.pending_concerns import (
    AdversarialState,
    Concern,
    ConcernResolution,
)
from src.wiki_carryover import build_wiki_entry, detect_shipped_with_known_gaps


def _make_concern(
    cid: str = "C-1",
    severity: str = "HIGH",
    concern: str = "missing edge case",
) -> Concern:
    return Concern(
        id=cid,
        raised_in_phase="plan",
        raised_in_stage="plan_council",
        severity=severity,
        concern=concern,
        raised_at=datetime.now(UTC),
        must_address_by="implement",
    )


def _make_resolution(
    concern_id: str, kind: str = "addressed-in-code"
) -> ConcernResolution:
    return ConcernResolution(
        concern_id=concern_id,
        addressed_in_stage="implement",
        resolution="fixed",
        addressed_at=datetime.now(UTC),
        resolution_kind=kind,
    )


# ---------------------------------------------------------------------------
# detect_shipped_with_known_gaps
# ---------------------------------------------------------------------------


def test_no_pending_concerns_returns_empty():
    state = AdversarialState(
        phase="post_merge", pending_concerns=[], addressed_concerns=[]
    )
    assert detect_shipped_with_known_gaps(state) == []


def test_unresolved_concerns_become_known_gaps():
    c1 = _make_concern(cid="C-1", concern="no test for empty input")
    c2 = _make_concern(cid="C-2", severity="MEDIUM", concern="race in handler")
    state = AdversarialState(
        phase="post_merge",
        pending_concerns=[c1, c2],
        addressed_concerns=[],
    )
    surviving = detect_shipped_with_known_gaps(state)
    assert [c.id for c in surviving] == ["C-1", "C-2"]


def test_addressed_concerns_are_excluded():
    c1 = _make_concern(cid="C-1")
    c2 = _make_concern(cid="C-2")
    c3 = _make_concern(cid="C-3")
    state = AdversarialState(
        phase="post_merge",
        pending_concerns=[c1, c2, c3],
        addressed_concerns=[
            _make_resolution("C-1"),
            _make_resolution("C-3", kind="addressed-in-test"),
        ],
    )
    surviving = detect_shipped_with_known_gaps(state)
    assert [c.id for c in surviving] == ["C-2"]


# ---------------------------------------------------------------------------
# build_wiki_entry
# ---------------------------------------------------------------------------


def test_build_wiki_entry_empty_returns_empty_string():
    assert build_wiki_entry([], pr_number=123) == ""


def test_build_wiki_entry_renders_markdown_and_json_block():
    c1 = _make_concern(cid="C-1", severity="HIGH", concern="no test for empty input")
    c2 = _make_concern(cid="C-2", severity="MEDIUM", concern="race in handler")

    rendered = build_wiki_entry([c1, c2], pr_number=4242)

    # Markdown body contains a heading and references each concern + the PR.
    assert "# " in rendered  # markdown heading present
    assert "PR #4242" in rendered
    assert "C-1" in rendered
    assert "C-2" in rendered
    assert "HIGH" in rendered
    assert "MEDIUM" in rendered
    assert "no test for empty input" in rendered
    assert "race in handler" in rendered

    # json:entry block is present and parses to JSON with the expected
    # bookkeeping fields (id, title, source_type/topic + pr_number).
    match = re.search(r"```json:entry\n(\{.*?\})\n```", rendered, flags=re.DOTALL)
    assert match is not None, f"expected ```json:entry block in:\n{rendered}"
    payload = json.loads(match.group(1))
    assert "id" in payload
    assert "title" in payload
    assert payload.get("source_type")
    # pr_number is the load-bearing back-reference; either inlined as a
    # field or embedded in the title is fine — assert it surfaces.
    assert str(4242) in json.dumps(payload)
