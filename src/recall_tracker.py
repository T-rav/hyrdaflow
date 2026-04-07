"""Recall instrumentation for tribal memory.

Logs every Hindsight recall to ``data/memory/recall_history.jsonl`` so
that downstream eviction logic (#6083) can decay items that are stored
but never recalled. This module is the *data collection* half only —
the eviction half is deferred until enough recall data has accumulated
to set meaningful thresholds.

Schema (one JSON object per line):
    {
        "timestamp": "2026-04-07T20:00:00+00:00",
        "bank": "hydraflow-tribal",
        "query": "<truncated query, max 500 chars>",
        "item_count": 3,
        "item_ids": ["mem-aaaa", "mem-bbbb", "mem-cccc"],
        "source": "base_runner | shape_phase | ..."
    }

Item IDs come from the metadata Hindsight returns; if not present they
are omitted from the entry. ``query`` is truncated so the log file does
not grow unbounded for long context dumps.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from hindsight_types import HindsightMemory

logger = logging.getLogger("hydraflow.recall_tracker")

_QUERY_TRUNCATE_CHARS = 500


def log_recall(
    config: HydraFlowConfig,
    *,
    bank: str,
    query: str,
    memories: list[HindsightMemory],
    source: str,
) -> None:
    """Append a recall record to ``data/memory/recall_history.jsonl``.

    Never raises — failures log a warning and the recall continues.
    Empty recalls (zero memories returned) are also logged so we can
    distinguish "memory bank cold" from "queries are running."
    """
    try:
        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "bank": str(bank),
            "query": query[:_QUERY_TRUNCATE_CHARS],
            "item_count": len(memories),
            "item_ids": [
                mem.metadata.get("id", "")
                for mem in memories
                if mem.metadata and mem.metadata.get("id")
            ],
            "source": source,
        }
        path = config.data_path("memory", "recall_history.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except OSError:
        logger.warning("Failed to write recall_history.jsonl", exc_info=True)
    except Exception:  # noqa: BLE001
        logger.warning("Unexpected failure logging recall", exc_info=True)
