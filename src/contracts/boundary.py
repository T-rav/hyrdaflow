"""I/O-boundary validation helper for adapter call sites (Phase 7 of #8786).

The Pydantic shapes in ``contracts.shapes`` catch drift at the call site —
but only if call sites actually validate. This module provides the small,
non-intrusive helper that lets ``PRManager``, ``FakeGitHub``, and friends
opt in without changing their return type or breaking on novel inputs.

Contract:

- ``parse_with_shape(json_str, model)`` returns a typed
  :class:`BoundaryParseResult[T]` where ``T`` is the model class supplied
  at the call site. ``payload`` is always populated when the JSON parsed
  at all; ``model_instance`` is the validated Pydantic model (typed as
  ``T``) when validation succeeded, else None; ``validation_error``
  carries a compact diagnostic on failure.
- The helper NEVER raises on validation failure — it logs at WARNING and
  returns a partial result. Call sites that want strict behaviour check
  ``model_instance is None`` and raise themselves.
- JSON parse failures (truly malformed input) DO raise ``ValueError`` so
  callers don't silently fall back to a stale value.
- ``field_or(result, attr, default, dict_key=None)`` is the canonical
  accessor for the lenient pattern — pulls the field from the typed
  model when available, else falls back to dict access on the raw
  payload. Hides the dual-path boilerplate at every call site.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger("hydraflow.contracts.boundary")

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class BoundaryValidationError:
    """Compact, log-friendly diagnostic for a single failed validation."""

    shape: str
    failure_count: int
    sample: list[dict[str, str]]  # up to N errors, one per offending field


@dataclass(frozen=True)
class BoundaryParseResult(Generic[T]):
    """Outcome of a call-site validation.

    Generic over the Pydantic model class ``T`` so callers can access
    ``result.model_instance.<attr>`` with full type information.

    ``payload`` is typed ``Any`` because JSON can decode to any value; in
    the validated path it's always a dict/list of dicts, but in the
    lenient fallback we want simple ``.get`` access without a cast at
    every call site.
    """

    payload: Any
    model_instance: T | None
    validation_error: BoundaryValidationError | None

    @property
    def ok(self) -> bool:
        """True iff JSON parsed AND the shape validated."""
        return self.model_instance is not None and self.validation_error is None


def _build_error_diag(
    model: type[BaseModel], exc: ValidationError
) -> BoundaryValidationError:
    """Compact a ValidationError into a log-friendly diagnostic."""
    return BoundaryValidationError(
        shape=model.__name__,
        failure_count=len(exc.errors()),
        sample=[
            {
                "loc": ".".join(str(p) for p in e.get("loc", ())),
                "type": str(e.get("type", "")),
                "msg": str(e.get("msg", ""))[:200],
            }
            for e in exc.errors()[:10]
        ],
    )


def parse_with_shape(json_str: str, model: type[T]) -> BoundaryParseResult[T]:
    """Parse *json_str* and validate it against *model*.

    Returns a BoundaryParseResult capturing all three possible outcomes:
    parse OK + validation OK, parse OK + validation fail, parse fail
    (raises ValueError so the caller can't silently fall back).
    """
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError as exc:
        msg = f"could not parse JSON at boundary: {exc}"
        raise ValueError(msg) from exc

    try:
        instance = model.model_validate(payload)
    except ValidationError as exc:
        diag = _build_error_diag(model, exc)
        logger.warning(
            "boundary validation failed for %s (count=%d): %s",
            model.__name__,
            diag.failure_count,
            diag.sample[0] if diag.sample else "no detail",
        )
        return BoundaryParseResult(
            payload=payload, model_instance=None, validation_error=diag
        )

    return BoundaryParseResult(
        payload=payload, model_instance=instance, validation_error=None
    )


def parse_list_with_shape(
    json_str: str, model: type[T]
) -> list[BoundaryParseResult[T]]:
    """Parse *json_str* as a list and validate each element against *model*.

    Returns one BoundaryParseResult per list element. Element-level
    failures don't poison sibling elements — each carries its own
    validation outcome.
    """
    try:
        payload = json.loads(json_str)
    except json.JSONDecodeError as exc:
        msg = f"could not parse JSON list at boundary: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(payload, list):
        msg = (
            f"expected JSON list at boundary, got {type(payload).__name__}: {payload!r}"
        )
        raise ValueError(msg)

    out: list[BoundaryParseResult[T]] = []
    for i, item in enumerate(payload):
        try:
            instance = model.model_validate(item)
        except ValidationError as exc:
            diag = _build_error_diag(model, exc)
            logger.warning(
                "boundary validation failed for %s[%d]: %s",
                model.__name__,
                i,
                diag.sample[0] if diag.sample else "no detail",
            )
            out.append(
                BoundaryParseResult(
                    payload=item, model_instance=None, validation_error=diag
                )
            )
        else:
            out.append(
                BoundaryParseResult(
                    payload=item, model_instance=instance, validation_error=None
                )
            )
    return out


def field_or(
    result: BoundaryParseResult[T],
    attr: str,
    default: Any,
    *,
    dict_key: str | None = None,
) -> Any:
    """Pull ``attr`` from the typed model when valid, else from the raw dict.

    Hides the lenient-pattern boilerplate at every call site. Returns
    ``default`` when the dict path also has no value (e.g. payload is
    not a dict, key absent, or value is None).

    ``dict_key`` defaults to ``attr`` — pass it when the gh/REST JSON
    field name differs from the Python attribute name (camelCase vs
    snake_case). Most callers can omit it because the Pydantic models
    use ``populate_by_name`` with the camelCase alias, so the raw dict
    key matches the Python attribute snake_case... only when the
    payload is a Pydantic-aliased model field, which is exactly the
    drift case we're worried about. Be explicit when in doubt.
    """
    if result.model_instance is not None:
        value = getattr(result.model_instance, attr, None)
        return default if value is None else value
    payload = result.payload if isinstance(result.payload, dict) else {}
    value = payload.get(dict_key or attr)
    return default if value is None else value
