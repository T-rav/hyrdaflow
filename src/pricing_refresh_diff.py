"""Pure-function helpers for PricingRefreshLoop.

No IO, no logging, no external state. All functions deterministic and
trivially testable. Importing this module must not trigger any side
effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_BEDROCK_PREFIX = "anthropic."
_V1_ZERO_SUFFIX = "-v1:0"


def normalize_litellm_key(key: str) -> str:
    """Strip Bedrock-style prefixes/suffixes so a LiteLLM key matches our local naming.

    LiteLLM publishes both bare canonical keys (``claude-haiku-4-5-20251001``)
    and Bedrock-prefixed variants (``anthropic.claude-haiku-4-5-20251001-v1:0``,
    ``anthropic.claude-haiku-4-5@20251001``). All three normalize to the same
    canonical form.
    """
    out = key
    if out.startswith(_BEDROCK_PREFIX):
        out = out[len(_BEDROCK_PREFIX) :]
    # The "@YYYYMMDD" convention is treated as "-YYYYMMDD" for our naming.
    out = out.replace("@", "-")
    if out.endswith(_V1_ZERO_SUFFIX):
        out = out[: -len(_V1_ZERO_SUFFIX)]
    return out


def filter_anthropic_entries(
    raw: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Keep only entries whose ``litellm_provider`` is ``"anthropic"``.

    Returns a NEW dict keyed by :func:`normalize_litellm_key` of the original.
    Entries without a ``litellm_provider`` field are skipped.
    """
    out: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        if entry.get("litellm_provider") != "anthropic":
            continue
        out[normalize_litellm_key(key)] = entry
    return out


def map_litellm_to_local_costs(upstream: dict[str, Any]) -> dict[str, float]:
    """Map LiteLLM per-token costs to our per-million-tokens shape.

    Required upstream keys: ``input_cost_per_token``, ``output_cost_per_token``.
    Cache fields (``cache_creation_input_token_cost``, ``cache_read_input_token_cost``)
    default to 0 when absent. All output values rounded to 6 decimals.

    Raises:
        KeyError: a required field is missing.
    """
    return {
        "input_cost_per_million": round(
            float(upstream["input_cost_per_token"]) * 1e6, 6
        ),
        "output_cost_per_million": round(
            float(upstream["output_cost_per_token"]) * 1e6, 6
        ),
        "cache_write_cost_per_million": round(
            float(upstream.get("cache_creation_input_token_cost", 0.0)) * 1e6, 6
        ),
        "cache_read_cost_per_million": round(
            float(upstream.get("cache_read_input_token_cost", 0.0)) * 1e6, 6
        ),
    }


_COST_FIELDS = (
    "input_cost_per_million",
    "output_cost_per_million",
    "cache_write_cost_per_million",
    "cache_read_cost_per_million",
)
_BOUNDS_UPPER = 2.0  # ≤ +100% allowed
_BOUNDS_LOWER = 0.5  # ≥ -50% allowed


@dataclass(frozen=True)
class BoundsViolation:
    """Single field rejected by the bounds guard."""

    model: str
    field: str
    old: float
    new: float

    @property
    def ratio(self) -> float:
        return self.new / self.old if self.old != 0 else float("inf")


@dataclass
class PricingDiff:
    """Result of comparing local pricing.json to mapped upstream entries.

    ``updated``: model → mapped-cost dict, only for models where every cost
    field passed the bounds guard.
    ``added``: model → fresh entry (with empty aliases) for upstream-only
    models. Bounds guard does not apply to additions.
    ``bounds_violations``: per (model, field) rejections — the entire
    update for a model is rejected if any of its fields violate.
    """

    updated: dict[str, dict[str, float]] = field(default_factory=dict)
    added: dict[str, dict[str, Any]] = field(default_factory=dict)
    bounds_violations: list[BoundsViolation] = field(default_factory=list)


def _within_bounds(old: float, new: float) -> bool:
    if old == 0:
        return True  # zero-baseline can move freely; no infinite-ratio paradox
    ratio = new / old
    return _BOUNDS_LOWER <= ratio <= _BOUNDS_UPPER


def compute_pricing_diff(
    *,
    local: dict[str, dict[str, Any]],
    upstream: dict[str, dict[str, Any]],
) -> PricingDiff:
    """Diff local pricing entries against mapped upstream values.

    ``upstream`` is the raw LiteLLM dict (already filtered to anthropic-
    provider entries via :func:`filter_anthropic_entries`); this function
    re-maps each upstream value via :func:`map_litellm_to_local_costs`.

    Local-only entries are preserved (return type doesn't list them; the
    caller merges added/updated against local).
    """
    diff = PricingDiff()
    for model, upstream_entry in upstream.items():
        try:
            mapped = map_litellm_to_local_costs(upstream_entry)
        except KeyError:
            continue  # skip upstream entries missing required fields

        local_entry = local.get(model)
        if local_entry is None:
            diff.added[model] = {
                "provider": "anthropic",
                "aliases": [],
                **mapped,
            }
            continue

        # All cost fields equal? → no change.
        changed_fields = {
            f: mapped[f] for f in _COST_FIELDS if mapped[f] != local_entry.get(f, 0.0)
        }
        if not changed_fields:
            continue

        # Bounds guard: reject the WHOLE update if any field violates.
        violations: list[BoundsViolation] = []
        for f, new in changed_fields.items():
            old = float(local_entry.get(f, 0.0))
            if not _within_bounds(old, new):
                violations.append(
                    BoundsViolation(model=model, field=f, old=old, new=new)
                )
        if violations:
            diff.bounds_violations.extend(violations)
            continue

        diff.updated[model] = changed_fields
    return diff
