"""Pydantic shapes for the gh-CLI JSON I/O boundary (Phase 1 of #8786).

Each model corresponds to a real ``gh ... --json FIELDS`` invocation used by
HydraFlow's production code. Validating both the real-adapter response AND
the fake-adapter return at the same model catches shape drift at the call
site — without needing a cassette recorder or replay tick. Loop A (#8786)
detects *value-level* drift via the shadow corpus; these models catch
*shape-level* drift (fields appearing, disappearing, or changing type).

Design notes:

- ``Pydantic v2`` with ``ConfigDict(extra="ignore")``. New optional fields
  from gh upgrades are silently dropped; missing required fields or
  type-mismatched fields raise ``ValidationError``. That's the signal we
  want — shape drift breaks loudly at the call site.

- Where gh returns a string-typed enum (``state``, ``mergeable``,
  ``conclusion``), we use ``Literal`` to pin the known values. A new
  state value from gh trips validation immediately rather than flowing
  through to call sites that branch on the old set.

- Optional fields are typed ``X | None = None``. Some gh commands return
  the field, some omit it depending on ``--json FIELDS``. The model is
  a superset; callers select which fields they need.

- ``GhLabel`` and ``GhCheckRun`` are nested types reused across the
  parent shapes — they're contracts in their own right.

The matching contract-test live in ``tests/test_contracts_shapes.py``.
Wiring the real ``PRManager`` and ``FakeGitHub`` to validate through
these models is the *next* PR — this one ships the shapes + validation
contract, the wiring is parallelizable.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

_GhIssueState = Literal["OPEN", "CLOSED"]
_GhPRState = Literal["OPEN", "CLOSED", "MERGED"]
_GhMergeable = Literal["MERGEABLE", "CONFLICTING", "UNKNOWN"]
_GhCheckState = Literal["QUEUED", "IN_PROGRESS", "COMPLETED", "PENDING", "WAITING"]
_GhCheckConclusion = Literal[
    "SUCCESS",
    "FAILURE",
    "NEUTRAL",
    "CANCELLED",
    "TIMED_OUT",
    "ACTION_REQUIRED",
    "STALE",
    "SKIPPED",
    "STARTUP_FAILURE",
]


class GhLabel(BaseModel):
    """One label as returned by ``gh ... --json labels``."""

    model_config = ConfigDict(extra="ignore")

    name: str
    color: str | None = None
    description: str | None = None


class GhCheckRun(BaseModel):
    """One CI check as returned by ``gh pr checks --json``."""

    model_config = ConfigDict(extra="ignore")

    name: str
    state: _GhCheckState | None = None
    conclusion: _GhCheckConclusion | None = None
    details_url: str | None = Field(default=None, alias="detailsUrl")


class GhPRSummary(BaseModel):
    """List-shape: ``gh pr list --json number,title,state[,labels,updatedAt]``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: int
    title: str
    state: _GhPRState
    body: str | None = None
    labels: list[GhLabel] = Field(default_factory=list)
    updated_at: str | None = Field(default=None, alias="updatedAt")


class GhPRDetail(BaseModel):
    """Detail-shape: ``gh pr view N --json number,headRefName,baseRefName,labels,mergeable,isDraft,url[,headRefOid]``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: int
    url: str | None = None
    head_ref_name: str | None = Field(default=None, alias="headRefName")
    base_ref_name: str | None = Field(default=None, alias="baseRefName")
    head_ref_oid: str | None = Field(default=None, alias="headRefOid")
    labels: list[GhLabel] = Field(default_factory=list)
    mergeable: _GhMergeable | None = None
    is_draft: bool | None = Field(default=None, alias="isDraft")


class GhIssueSummary(BaseModel):
    """``gh issue view N --json number,state[,title,body,labels,updatedAt,stateReason]``."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: int
    state: _GhIssueState
    state_reason: str | None = Field(default=None, alias="stateReason")
    title: str | None = None
    body: str | None = None
    labels: list[GhLabel] = Field(default_factory=list)
    updated_at: str | None = Field(default=None, alias="updatedAt")


class GhIssueListItem(BaseModel):
    """``gh issue list --json number,title,body,updatedAt`` element shape.

    Narrower than :class:`GhIssueSummary` — list invocations typically
    omit ``state`` (the filter is already applied by ``--state open|closed``)
    and ``labels``. A separate shape so the broader summary keeps its
    drift-detection bite on view invocations.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: int
    title: str
    body: str | None = None
    updated_at: str | None = Field(default=None, alias="updatedAt")


class GhPromotionPR(BaseModel):
    """``gh api repos/.../pulls`` element after the custom ``--jq`` filter
    used by :meth:`PRManager.list_recent_promotion_prs`.

    Shape: ``{number, branch, merged, closed_at, url}``. Not directly
    produced by any ``gh ... --json FIELDS`` invocation — this is the
    HydraFlow-defined projection over the GitHub REST PR payload.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    number: int
    branch: str
    merged: bool
    closed_at: str | None = None
    url: str | None = None


_GhReviewState = Literal[
    "APPROVED",
    "CHANGES_REQUESTED",
    "COMMENTED",
    "DISMISSED",
    "PENDING",
]


class GhReviewAuthor(BaseModel):
    """Reviewer identity. ``login`` is the GitHub username."""

    model_config = ConfigDict(extra="ignore")

    login: str = ""


class GhReview(BaseModel):
    """One PR review as returned by ``gh pr view N --json reviews`` (each
    element of the ``reviews`` array) or the underlying GitHub REST
    ``/pulls/N/reviews`` endpoint."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    state: _GhReviewState
    author: GhReviewAuthor | None = None
    submitted_at: str | None = Field(default=None, alias="submittedAt")
    commit_id: str | None = Field(default=None, alias="commitId")


class GhPRReviewsResponse(BaseModel):
    """Wrapper for ``gh pr view N --json reviews`` — the outer object
    carries a single ``reviews`` array."""

    model_config = ConfigDict(extra="ignore")

    reviews: list[GhReview] = Field(default_factory=list)
