"""Model pricing loader — reads per-model token costs from a managed JSON asset."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("hydraflow.model_pricing")

_ASSET_PATH = Path(__file__).parent / "assets" / "model_pricing.json"

_REQUIRED_COST_FIELDS = frozenset({"input_cost_per_million", "output_cost_per_million"})


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Per-model token pricing rates (USD per million tokens)."""

    input_cost_per_million: float
    output_cost_per_million: float
    cache_write_cost_per_million: float
    cache_read_cost_per_million: float

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Return estimated cost in USD for the given token counts."""
        return (
            self.input_cost_per_million * input_tokens
            + self.output_cost_per_million * output_tokens
            + self.cache_write_cost_per_million * cache_write_tokens
            + self.cache_read_cost_per_million * cache_read_tokens
        ) / 1_000_000


class ModelPricingTable:
    """Loads and resolves model pricing from the managed JSON asset."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _ASSET_PATH
        self._rates: dict[str, ModelRate] = {}
        self._aliases: dict[str, str] = {}
        self._loaded = False

    def _load(self) -> None:
        """Parse the pricing JSON and build lookup tables."""
        if self._loaded:
            return
        self._loaded = True
        if not self._path.is_file():
            logger.warning("Model pricing asset not found: %s", self._path)
            return
        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Failed to load model pricing from %s", self._path, exc_info=True
            )
            return
        if not isinstance(raw, dict):
            return
        models = raw.get("models", {})
        if not isinstance(models, dict):
            return
        for model_id, entry in models.items():
            if not isinstance(entry, dict):
                continue
            if not _REQUIRED_COST_FIELDS.issubset(entry):
                logger.warning(
                    "Skipping model %r — missing required cost fields", model_id
                )
                continue
            rate = ModelRate(
                input_cost_per_million=float(entry["input_cost_per_million"]),
                output_cost_per_million=float(entry["output_cost_per_million"]),
                cache_write_cost_per_million=float(
                    entry.get("cache_write_cost_per_million", 0.0)
                ),
                cache_read_cost_per_million=float(
                    entry.get("cache_read_cost_per_million", 0.0)
                ),
            )
            self._rates[model_id] = rate
            for alias in entry.get("aliases", []):
                if isinstance(alias, str):
                    self._aliases[alias.lower()] = model_id

    def get_rate(self, model: str) -> ModelRate | None:
        """Look up pricing for *model* by exact ID or alias."""
        self._load()
        model_l = model.lower().strip()
        if model_l in self._rates:
            return self._rates[model_l]
        canonical = self._aliases.get(model_l)
        if canonical:
            return self._rates.get(canonical)
        # Fuzzy match: check if any alias is a substring of the model string
        for alias, canonical_id in self._aliases.items():
            if alias in model_l:
                return self._rates.get(canonical_id)
        return None

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float | None:
        """Return estimated cost in USD, or None if model is unknown."""
        rate = self.get_rate(model)
        if rate is None:
            return None
        return rate.estimate_cost(
            input_tokens, output_tokens, cache_write_tokens, cache_read_tokens
        )

    @property
    def model_ids(self) -> list[str]:
        """Return all loaded model IDs."""
        self._load()
        return list(self._rates)

    def validate(self) -> list[str]:
        """Return a list of validation errors (empty if valid)."""
        self._load()
        errors: list[str] = []
        if not self._rates:
            errors.append("No models loaded from pricing asset")
        for model_id, rate in self._rates.items():
            if rate.input_cost_per_million < 0:
                errors.append(f"{model_id}: negative input cost")
            if rate.output_cost_per_million < 0:
                errors.append(f"{model_id}: negative output cost")
        return errors


def load_pricing(path: Path | None = None) -> ModelPricingTable:
    """Load the model pricing table from the default or given path."""
    return ModelPricingTable(path)


def validate_pricing_asset(raw: dict[str, Any]) -> list[str]:
    """Validate raw pricing JSON structure without loading from disk."""
    errors: list[str] = []
    if not isinstance(raw, dict):
        return ["Root must be a JSON object"]
    if "schema_version" not in raw:
        errors.append("Missing schema_version")
    models = raw.get("models")
    if not isinstance(models, dict):
        errors.append("Missing or invalid 'models' key")
        return errors
    for model_id, entry in models.items():
        if not isinstance(entry, dict):
            errors.append(f"{model_id}: entry must be an object")
            continue
        for field in _REQUIRED_COST_FIELDS:
            if field not in entry:
                errors.append(f"{model_id}: missing {field}")
            elif not isinstance(entry[field], int | float):
                errors.append(f"{model_id}: {field} must be numeric")
    return errors
