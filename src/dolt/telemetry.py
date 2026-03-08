"""Repositories for inference tracking and model pricing."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from dolt.connection import DoltConnection


class InferenceRepository:
    """Append/load the ``inferences`` table; stats via ``inference_stats``."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def append(self, inference: dict) -> None:
        """Insert a new inference record."""
        self.db.execute(
            "INSERT INTO inferences (inference_json) VALUES (%s)",
            (json.dumps(inference),),
        )

    def load(self, limit: int = 100) -> list[dict[str, Any]]:
        """Return recent inference records."""
        rows = self.db.fetchall(
            "SELECT id, inference_json, created_at "
            "FROM inferences ORDER BY id DESC LIMIT %s",
            (limit,),
        )
        return [
            {
                "id": r[0],
                "inference": json.loads(r[1]) if r[1] else {},
                "created_at": r[2],
            }
            for r in rows
        ]

    def update_stats(self, stats: dict) -> None:
        """Upsert aggregated inference statistics."""
        self.db.execute(
            "REPLACE INTO inference_stats (id, stats_json) VALUES (1, %s)",
            (json.dumps(stats),),
        )

    def get_stats(self) -> dict | None:
        """Return the current inference stats."""
        row = self.db.fetchone(
            "SELECT stats_json FROM inference_stats WHERE id = 1"
        )
        return json.loads(row[0]) if row else None


class ModelPricingRepository:
    """CRUD on the ``model_pricing`` table."""

    def __init__(self, db: DoltConnection) -> None:
        self.db = db

    def upsert(self, model: str, pricing: dict) -> None:
        """Insert or replace pricing for a model."""
        self.db.execute(
            "REPLACE INTO model_pricing (model_name, pricing_json) VALUES (%s, %s)",
            (model, json.dumps(pricing)),
        )

    def get(self, model: str) -> dict | None:
        """Return pricing for a model, or ``None``."""
        row = self.db.fetchone(
            "SELECT pricing_json FROM model_pricing WHERE model_name = %s",
            (model,),
        )
        return json.loads(row[0]) if row else None

    def get_all(self) -> dict[str, dict]:
        """Return all model pricing as ``{model: pricing}``."""
        rows = self.db.fetchall(
            "SELECT model_name, pricing_json FROM model_pricing"
        )
        return {r[0]: json.loads(r[1]) for r in rows}

    def delete(self, model: str) -> None:
        """Remove pricing for a model."""
        self.db.execute(
            "DELETE FROM model_pricing WHERE model_name = %s", (model,)
        )
