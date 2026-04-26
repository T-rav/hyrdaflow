"""Pure-function helpers for PricingRefreshLoop.

No IO, no logging, no external state. All functions deterministic and
trivially testable. Importing this module must not trigger any side
effects.
"""

from __future__ import annotations

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
