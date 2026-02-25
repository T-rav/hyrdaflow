"""Prompt/inference telemetry for ROI tracking and token-efficiency analysis."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from config import HydraFlowConfig
from file_util import atomic_write

logger = logging.getLogger("hydraflow.prompt_telemetry")


def _estimate_tokens(chars: int) -> int:
    """Estimate token count from character count (approx. 4 chars/token)."""
    if chars <= 0:
        return 0
    return max(1, round(chars / 4))


class PromptTelemetry:
    """Writes prompt/inference metrics to filesystem-backed JSON artifacts."""

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._dir = config.data_path("metrics", "prompt")
        self._inferences_file = self._dir / "inferences.jsonl"
        self._pr_stats_file = self._dir / "pr_stats.json"

    def record(
        self,
        *,
        source: str,
        tool: str,
        model: str,
        issue_number: int | None,
        pr_number: int | None,
        session_id: str | None,
        prompt_chars: int,
        transcript_chars: int,
        duration_seconds: float,
        success: bool,
        stats: dict[str, int] | None = None,
    ) -> None:
        """Append one inference record and update aggregate per-PR stats."""
        st = stats or {}

        history_before = max(0, int(st.get("history_chars_before", 0)))
        history_after = max(0, int(st.get("history_chars_after", 0)))
        context_before = max(0, int(st.get("context_chars_before", 0)))
        context_after = max(0, int(st.get("context_chars_after", 0)))
        cache_hits = max(0, int(st.get("cache_hits", 0)))
        cache_misses = max(0, int(st.get("cache_misses", 0)))
        actual_input_tokens = max(0, int(st.get("input_tokens", 0)))
        actual_output_tokens = max(0, int(st.get("output_tokens", 0)))
        actual_cache_creation_tokens = max(
            0, int(st.get("cache_creation_input_tokens", 0))
        )
        actual_cache_read_tokens = max(0, int(st.get("cache_read_input_tokens", 0)))
        actual_total_tokens = max(0, int(st.get("total_tokens", 0)))

        history_saved = max(0, history_before - history_after)
        context_saved = max(0, context_before - context_after)

        prompt_tokens = _estimate_tokens(prompt_chars)
        transcript_tokens = _estimate_tokens(transcript_chars)
        estimated_total_tokens = prompt_tokens + transcript_tokens
        if actual_total_tokens <= 0 and (actual_input_tokens or actual_output_tokens):
            actual_total_tokens = actual_input_tokens + actual_output_tokens
        token_source = "actual" if actual_total_tokens > 0 else "estimated"
        effective_total_tokens = (
            actual_total_tokens if actual_total_tokens > 0 else estimated_total_tokens
        )

        record = {
            "timestamp": datetime.now(UTC).isoformat(),
            "source": source,
            "tool": tool,
            "model": model,
            "issue_number": issue_number,
            "pr_number": pr_number,
            "session_id": session_id or "",
            "prompt_chars": prompt_chars,
            "prompt_est_tokens": prompt_tokens,
            "transcript_chars": transcript_chars,
            "transcript_est_tokens": transcript_tokens,
            "total_est_tokens": estimated_total_tokens,
            "input_tokens": actual_input_tokens,
            "output_tokens": actual_output_tokens,
            "cache_creation_input_tokens": actual_cache_creation_tokens,
            "cache_read_input_tokens": actual_cache_read_tokens,
            "total_tokens": effective_total_tokens,
            "token_source": token_source,
            "duration_seconds": round(duration_seconds, 3),
            "status": "success" if success else "failed",
            "history_chars_before": history_before,
            "history_chars_after": history_after,
            "history_chars_saved": history_saved,
            "history_prune_roi": (
                round(history_saved / history_before, 4) if history_before else 0.0
            ),
            "context_chars_before": context_before,
            "context_chars_after": context_after,
            "context_chars_saved": context_saved,
            "context_prune_roi": (
                round(context_saved / context_before, 4) if context_before else 0.0
            ),
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "cache_hit_rate": (
                round(cache_hits / (cache_hits + cache_misses), 4)
                if (cache_hits + cache_misses)
                else 0.0
            ),
        }

        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            with open(self._inferences_file, "a") as f:
                f.write(json.dumps(record, sort_keys=True) + "\n")
                f.flush()
        except OSError:
            logger.warning(
                "Could not append prompt telemetry to %s",
                self._inferences_file,
                exc_info=True,
            )

        self._update_pr_stats(record)

    def _update_pr_stats(self, record: dict[str, object]) -> None:
        data = self._load_pr_stats()
        lifetime = _get_or_init_dict(data, "lifetime", _new_counter())
        self._accumulate_counter(lifetime, record)

        sessions = _get_or_init_dict(data, "sessions", {})
        session_id = str(record.get("session_id", "")).strip()
        if session_id:
            sess_entry = _get_or_init_dict(sessions, session_id, _new_counter())
            self._accumulate_counter(sess_entry, record)

        prs = _get_or_init_dict(data, "prs", {})
        pr_number = record.get("pr_number")
        if isinstance(pr_number, int) and pr_number > 0:
            entry = _get_or_init_dict(prs, str(pr_number), _new_counter())
            self._accumulate_counter(entry, record)

        data["updated_at"] = str(record.get("timestamp", ""))

        try:
            atomic_write(
                self._pr_stats_file, json.dumps(data, indent=2, sort_keys=True)
            )
        except OSError:
            logger.warning(
                "Could not write per-PR prompt stats to %s",
                self._pr_stats_file,
                exc_info=True,
            )

    def _load_pr_stats(self) -> dict[str, object]:
        if not self._pr_stats_file.is_file():
            return {}
        try:
            raw = self._pr_stats_file.read_text()
        except OSError:
            return {}
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Per-PR stats file is corrupt, rebuilding")
            return {}
        return parsed if isinstance(parsed, dict) else {}

    @staticmethod
    def _accumulate_counter(
        target: dict[str, object], record: dict[str, object]
    ) -> None:
        target["inference_calls"] = _as_int(target.get("inference_calls", 0)) + 1
        target["prompt_est_tokens"] = _as_int(
            target.get("prompt_est_tokens", 0)
        ) + _as_int(record.get("prompt_est_tokens", 0))
        target["total_est_tokens"] = _as_int(
            target.get("total_est_tokens", 0)
        ) + _as_int(record.get("total_est_tokens", 0))
        target["total_tokens"] = _as_int(target.get("total_tokens", 0)) + _as_int(
            record.get("total_tokens", 0)
        )
        target["history_chars_saved"] = _as_int(
            target.get("history_chars_saved", 0)
        ) + _as_int(record.get("history_chars_saved", 0))
        target["context_chars_saved"] = _as_int(
            target.get("context_chars_saved", 0)
        ) + _as_int(record.get("context_chars_saved", 0))
        target["cache_hits"] = _as_int(target.get("cache_hits", 0)) + _as_int(
            record.get("cache_hits", 0)
        )
        target["cache_misses"] = _as_int(target.get("cache_misses", 0)) + _as_int(
            record.get("cache_misses", 0)
        )
        target["actual_usage_calls"] = _as_int(target.get("actual_usage_calls", 0))
        if record.get("token_source") == "actual":
            target["actual_usage_calls"] = _as_int(target["actual_usage_calls"]) + 1
        target["last_updated"] = str(record.get("timestamp", ""))

    def get_pr_totals(self, pr_number: int) -> dict[str, int] | None:
        """Return aggregate telemetry totals for a PR, or None if missing."""
        data = self._load_pr_stats()
        prs = data.get("prs", {})
        if not isinstance(prs, dict):
            return None
        entry = prs.get(str(pr_number))
        if not isinstance(entry, dict):
            return None
        return {k: int(v) for k, v in entry.items() if isinstance(v, int)}

    def get_lifetime_totals(self) -> dict[str, int]:
        """Return aggregate telemetry totals across all sessions."""
        data = self._load_pr_stats()
        lifetime = data.get("lifetime", {})
        if not isinstance(lifetime, dict):
            return {}
        return {k: int(v) for k, v in lifetime.items() if isinstance(v, int)}

    def get_session_totals(self, session_id: str) -> dict[str, int]:
        """Return aggregate telemetry totals for a single session ID."""
        if not session_id:
            return {}
        data = self._load_pr_stats()
        sessions = data.get("sessions", {})
        if not isinstance(sessions, dict):
            return {}
        entry = sessions.get(session_id, {})
        if not isinstance(entry, dict):
            return {}
        return {k: int(v) for k, v in entry.items() if isinstance(v, int)}


def parse_command_tool_model(cmd: list[str]) -> tuple[str, str]:
    """Extract ``(tool, model)`` from an agent command list."""
    tool = cmd[0] if cmd else "unknown"
    model = ""
    for i, part in enumerate(cmd):
        if part == "--model" and i + 1 < len(cmd):
            model = cmd[i + 1]
            break
    return tool, model


def _new_counter() -> dict[str, object]:
    """Create a fresh aggregate counter payload."""
    return {
        "inference_calls": 0,
        "prompt_est_tokens": 0,
        "total_est_tokens": 0,
        "total_tokens": 0,
        "history_chars_saved": 0,
        "context_chars_saved": 0,
        "cache_hits": 0,
        "cache_misses": 0,
        "actual_usage_calls": 0,
        "last_updated": "",
    }


def _as_int(value: object) -> int:
    """Best-effort integer conversion for telemetry counters."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _get_or_init_dict(
    parent: dict[str, object], key: str, default: dict[str, object]
) -> dict[str, object]:
    """Get a nested dict value or initialize it with *default*."""
    current = parent.get(key)
    if isinstance(current, dict):
        return current
    parent[key] = default
    return default
