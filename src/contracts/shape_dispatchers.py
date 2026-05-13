"""Shape-validating dispatchers for LiveCorpusReplayLoop (Phase 5 of #8786).

The first dispatcher to populate ``LiveCorpusReplayLoop``'s registry. Rather
than mirror every gh call shape through a per-method ``FakeGitHub`` invocation
(needs careful state seeding to be meaningful), this dispatcher validates the
sampled stdout against the matching Pydantic shape from
``contracts.shapes``. A validation failure IS the drift signal — gh changed a
field, removed one, or returned a new enum value.

Why this is useful before per-method dispatchers exist:

- Shape drift is the *highest-frequency* drift in practice. New gh versions
  add fields; removed fields break downstream parsers. Catching that at
  shadow-corpus replay time means we hear about it within one tick
  (~15 min), not when a production loop crashes parsing the new shape.
- Zero state-seeding required. The dispatcher is purely defensive against
  upstream changes, not a fake-correctness check.
- Adding per-method value-comparison dispatchers later doesn't conflict —
  they'd register under different ``(adapter, command)`` keys or the same
  key with a richer body that still validates first.

The dispatcher returns ``None`` when validation succeeds (sample matches the
shape — no drift). On validation failure it returns a dict that surfaces the
expected shape vs the sampled payload, which the loop diffs to produce the
drift signature. The signature is stable across reruns of the same drift.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from pydantic import BaseModel, ValidationError

from contracts.shapes import (
    GhCheckRun,
    GhIssueSummary,
    GhPRDetail,
    GhPRSummary,
)

if TYPE_CHECKING:
    from contracts.shadow import ShadowSample

logger = logging.getLogger("hydraflow.contracts.shape_dispatchers")

# Map ``(command0_after_gh, shape_keyword)`` → Pydantic model.
# Detection is heuristic on args — the dispatcher inspects ``--json
# FIELDS`` for tell-tale fields and chooses the most-specific shape.
# Unrecognized shapes return None (no opinion = loop skips).


def _pick_shape_for_pr(args: list[str]) -> type[BaseModel] | None:
    """``gh pr ...`` shape selection. Detect summary vs detail by which
    detail-only fields are requested in ``--json FIELDS``."""
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    detail_signals = {
        "headRefName",
        "baseRefName",
        "headRefOid",
        "mergeable",
        "isDraft",
    }
    if fields & detail_signals:
        return GhPRDetail
    return GhPRSummary


def _pick_shape_for_issue(args: list[str]) -> type[BaseModel] | None:
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    return GhIssueSummary


def _pick_shape_for_checks(args: list[str]) -> type[BaseModel] | None:
    fields = _extract_json_fields(args)
    if fields is None:
        return None
    return GhCheckRun


def _extract_json_fields(args: list[str]) -> frozenset[str] | None:
    """Return the set of fields requested via ``--json A,B,C``.

    Returns None when no ``--json`` flag is present — the call isn't
    asking for a JSON payload, so shape validation is meaningless.
    """
    try:
        idx = args.index("--json")
    except ValueError:
        return None
    if idx + 1 >= len(args):
        return None
    return frozenset(args[idx + 1].split(","))


def _gh_subcommand(args: list[str]) -> str | None:
    """Return the gh subcommand pair, e.g. ``"pr-view"``, or None."""
    if len(args) < 2:
        return None
    return f"{args[0]}-{args[1]}"


async def gh_shape_validator(sample: ShadowSample) -> dict[str, object] | None:  # noqa: PLR0911
    """Dispatcher: validate ``sample.stdout`` against the matching shape.

    Returns:
        - ``None`` if the sample's stdout validates cleanly — no drift.
        - A diff-payload dict if validation fails — the loop fingerprints
          this to file a single drift issue per signature.
        - ``None`` for samples this dispatcher has no opinion on
          (unknown subcommand, no ``--json`` flag, empty stdout, etc.) —
          the loop treats those as "skipped, no opinion".
    """
    if sample.adapter != "github" or sample.command != "gh":
        return None
    if not sample.stdout.strip():
        return None
    subcommand = _gh_subcommand(sample.args)
    if subcommand is None:
        return None

    shape_cls: type[BaseModel] | None = None
    if subcommand in ("pr-view", "pr-list"):
        shape_cls = _pick_shape_for_pr(sample.args)
    elif subcommand in ("issue-view", "issue-list"):
        shape_cls = _pick_shape_for_issue(sample.args)
    elif subcommand == "pr-checks":
        shape_cls = _pick_shape_for_checks(sample.args)
    if shape_cls is None:
        return None

    try:
        parsed_payload = json.loads(sample.stdout)
    except json.JSONDecodeError as exc:
        logger.debug("gh_shape_validator: stdout for %s not JSON: %s", subcommand, exc)
        return None

    # gh --json sometimes returns a single object, sometimes a list of
    # them. Validate each element when it's a list.
    candidates = (
        parsed_payload if isinstance(parsed_payload, list) else [parsed_payload]
    )
    failures: list[dict[str, object]] = []
    for i, item in enumerate(candidates):
        try:
            shape_cls.model_validate(item)
        except ValidationError as exc:
            failures.append(
                {
                    "index": i,
                    "shape": shape_cls.__name__,
                    "errors": _summarize_errors(exc),
                }
            )
    if not failures:
        return None
    return {
        "shape_validation_failed": True,
        "shape": shape_cls.__name__,
        "subcommand": subcommand,
        "failure_count": len(failures),
        "failures": failures[:5],  # cap body length
    }


def _summarize_errors(exc: ValidationError) -> list[dict[str, str]]:
    """Compact error report — one entry per offending field/value."""
    out: list[dict[str, str]] = []
    for err in exc.errors()[:10]:
        out.append(
            {
                "loc": ".".join(str(p) for p in err.get("loc", ())),
                "type": str(err.get("type", "")),
                "msg": str(err.get("msg", ""))[:200],
            }
        )
    return out
