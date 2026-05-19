"""Wiki carryover for the adversarial pipeline.

When a PR merges with one or more pending concerns that survived all
adversarial stages without a matching ``ConcernResolution``, the
factory has "shipped with a known gap". Those gaps are load-bearing
context for future runs: the next planner / reviewer needs to see them
so the gap is not forgotten.

This module provides two pure functions:

* :func:`detect_shipped_with_known_gaps` — scans an
  :class:`AdversarialState` and returns the unresolved
  :class:`Concern` objects.
* :func:`build_wiki_entry` — renders those concerns as a Markdown body
  + ``json:entry`` machine block, following the per-repo wiki format
  used elsewhere in ``docs/wiki/``.

Pure, no I/O. The post-merge hook + ``RepoWikiLoop`` subscriber
compose these with the actual filesystem write (see
``post_merge_handler.PostMergeHandler`` and ``repo_wiki_loop`` for the
wiring).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from src.pending_concerns import AdversarialState, Concern


def detect_shipped_with_known_gaps(state: AdversarialState) -> list[Concern]:
    """Return pending concerns whose id is not in ``addressed_concerns``.

    A "shipped with known gap" is a :class:`Concern` raised earlier in
    the adversarial pipeline (discover / shape / plan / implement) that
    never received a matching :class:`ConcernResolution` by post-merge.
    The next run of this issue (or related work) needs to know about
    these so the gap is visible rather than buried in old state files.

    Pure: takes a snapshot of state, returns a list. Preserves the
    order of ``pending_concerns`` so downstream rendering is
    deterministic.
    """
    addressed_ids = {res.concern_id for res in state.addressed_concerns}
    return [c for c in state.pending_concerns if c.id not in addressed_ids]


def build_wiki_entry(concerns: list[Concern], pr_number: int) -> str:
    """Render a wiki entry for shipped-with-known-gap concerns.

    Returns an empty string when ``concerns`` is empty — callers should
    skip writing in that case.

    Output format mirrors the existing per-repo wiki entries under
    ``docs/wiki/`` (Markdown heading + body + a ``json:entry`` machine
    block). The id is a deterministic ULID-shaped string derived from
    the PR number so re-renders are idempotent; the ``source_type`` is
    ``shipped-with-known-gap`` and the ``topic`` is ``gotchas`` — that
    is where future planners / reviewers look for "things we know
    aren't fixed yet". The PR number is carried in both the body and
    the JSON payload for back-reference.
    """
    if not concerns:
        return ""

    title = f"Shipped with known gap — PR #{pr_number}"
    now = datetime.now(UTC).isoformat()

    body_lines: list[str] = [
        f"# {title}",
        "",
        (
            f"PR #{pr_number} merged with {len(concerns)} unresolved "
            "adversarial concern(s) that survived all gates without an "
            "explicit ConcernResolution. Future planners / reviewers "
            "should treat these as known gaps until either addressed "
            "in a follow-up PR or explicitly accepted."
        ),
        "",
        "## Unresolved concerns",
        "",
    ]
    for c in concerns:
        body_lines.append(
            f"- **{c.severity}** `{c.id}` (raised in "
            f"`{c.raised_in_phase}` / `{c.raised_in_stage}`): {c.concern}"
        )
        if c.must_address_by:
            body_lines.append(f"  - _must_address_by_: `{c.must_address_by}`")
    body_lines.append("")

    # json:entry machine block — same shape as the entries already in
    # docs/wiki/*.md so downstream readers (RepoWikiLoop lint, wiki
    # query) parse it the same way.
    payload: dict[str, object] = {
        "id": f"shipped-with-known-gap-pr-{pr_number}",
        "title": title,
        "topic": "gotchas",
        "source_type": "shipped-with-known-gap",
        "source_issue": None,
        "source_repo": None,
        "pr_number": pr_number,
        "created_at": now,
        "updated_at": now,
        "valid_to": None,
        "superseded_by": None,
        "superseded_reason": None,
        "confidence": "high",
        "stale": False,
        "corroborations": 1,
        "concerns": [
            {
                "id": c.id,
                "severity": c.severity,
                "concern": c.concern,
                "raised_in_phase": c.raised_in_phase,
                "raised_in_stage": c.raised_in_stage,
                "must_address_by": c.must_address_by,
            }
            for c in concerns
        ],
    }

    body_lines.append("```json:entry")
    body_lines.append(json.dumps(payload))
    body_lines.append("```")
    body_lines.append("")

    return "\n".join(body_lines)
