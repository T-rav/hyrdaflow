"""Backfill the zero-usage-anomaly guard onto historical telemetry records.

Rewrites ``.hydraflow/metrics/prompt/inferences.jsonl`` so that any record
matching the zero-usage anomaly signature (success=True, zero actual tokens,
usage_available=False, prompt_chars > threshold) is reclassified as
status="failed", estimated_cost_usd=0.0, and tagged with
usage_anomaly="zero_usage_with_prompt".

Then rebuilds ``pr_stats.json`` from the cleaned record stream so lifetime,
per-PR, per-issue, per-session, and per-source rollups reflect honest spend.

Idempotent: records already tagged ``usage_anomaly`` are left alone. The
original files are copied to ``inferences.jsonl.bak`` / ``pr_stats.json.bak``
before rewriting.

Usage:
    python scripts/cleanup_phantom_cost.py                # dry-run report
    python scripts/cleanup_phantom_cost.py --apply        # rewrite files
    python scripts/cleanup_phantom_cost.py --path <jsonl> # custom location
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

# Must match src/prompt_telemetry.py::_ZERO_USAGE_PROMPT_THRESHOLD
_ZERO_USAGE_PROMPT_THRESHOLD = 500


def _is_anomaly(record: dict[str, object]) -> bool:
    """Match the same signature as the runtime guard in PromptTelemetry.record."""
    if record.get("usage_anomaly"):
        return False  # already cleaned
    if record.get("status") != "success":
        return False
    if record.get("usage_available"):
        return False
    if _as_int(record.get("input_tokens")) + _as_int(record.get("output_tokens")) > 0:
        return False
    return _as_int(record.get("prompt_chars")) > _ZERO_USAGE_PROMPT_THRESHOLD


def _reclassify(record: dict[str, object]) -> dict[str, object]:
    fixed = dict(record)
    fixed["status"] = "failed"
    fixed["estimated_cost_usd"] = 0.0
    fixed["usage_anomaly"] = "zero_usage_with_prompt"
    return fixed


def _as_int(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _as_float(value: object) -> float:
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _new_counter() -> dict[str, object]:
    # Must match src/prompt_telemetry.py::_new_counter exactly — notably
    # estimated_cost_usd is NOT seeded here; it appears only on first
    # non-zero contribution, matching production counter shape.
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
        "usage_unavailable_calls": 0,
        "pruned_chars_total": 0,
        "last_updated": "",
    }


def _accumulate(target: dict[str, object], record: dict[str, object]) -> None:
    """Mirror PromptTelemetry._accumulate_counter exactly."""
    target["inference_calls"] = _as_int(target.get("inference_calls", 0)) + 1
    for key in (
        "prompt_est_tokens",
        "total_est_tokens",
        "total_tokens",
        "history_chars_saved",
        "context_chars_saved",
        "cache_hits",
        "cache_misses",
        "pruned_chars_total",
    ):
        target[key] = _as_int(target.get(key, 0)) + _as_int(record.get(key, 0))
    if record.get("token_source") == "actual":
        target["actual_usage_calls"] = _as_int(target.get("actual_usage_calls", 0)) + 1
    if record.get("usage_status") == "unavailable":
        target["usage_unavailable_calls"] = (
            _as_int(target.get("usage_unavailable_calls", 0)) + 1
        )
    record_cost = record.get("estimated_cost_usd")
    if isinstance(record_cost, int | float) and record_cost > 0:
        target["estimated_cost_usd"] = round(
            _as_float(target.get("estimated_cost_usd", 0.0)) + float(record_cost),
            6,
        )
    target["last_updated"] = str(record.get("timestamp", ""))


def _rebuild_rollup(records: list[dict[str, object]]) -> dict[str, object]:
    """Reconstruct pr_stats.json from a clean record stream."""
    data: dict[str, object] = {
        "lifetime": _new_counter(),
        "sessions": {},
        "prs": {},
        "issues": {},
        "sources": {},
    }
    for rec in records:
        _accumulate(data["lifetime"], rec)  # type: ignore[arg-type]
        session_id = str(rec.get("session_id", "")).strip()
        if session_id:
            sessions = data["sessions"]
            assert isinstance(sessions, dict)
            sessions.setdefault(session_id, _new_counter())
            _accumulate(sessions[session_id], rec)
        pr_number = rec.get("pr_number")
        if isinstance(pr_number, int) and pr_number > 0:
            prs = data["prs"]
            assert isinstance(prs, dict)
            key = str(pr_number)
            prs.setdefault(key, _new_counter())
            _accumulate(prs[key], rec)
        issue_number = rec.get("issue_number")
        if isinstance(issue_number, int) and issue_number > 0:
            issues = data["issues"]
            assert isinstance(issues, dict)
            key = str(issue_number)
            issues.setdefault(key, _new_counter())
            _accumulate(issues[key], rec)
        source = str(rec.get("source", "")).strip()
        if source:
            sources = data["sources"]
            assert isinstance(sources, dict)
            sources.setdefault(source, _new_counter())
            _accumulate(sources[source], rec)
    if records:
        data["updated_at"] = str(records[-1].get("timestamp", ""))
    return data


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    with path.open() as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                rec = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(rec, dict):
                records.append(rec)
    return records


def _write_jsonl_atomic(path: Path, records: list[dict[str, object]]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        for rec in records:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
    tmp.replace(path)


def run(jsonl_path: Path, *, apply: bool) -> int:
    if not jsonl_path.is_file():
        print(f"error: {jsonl_path} not found", file=sys.stderr)
        return 1
    pr_stats_path = jsonl_path.parent / "pr_stats.json"

    records = _load_jsonl(jsonl_path)
    total = len(records)
    scanned, reclassified, phantom_cost = 0, 0, 0.0
    cleaned: list[dict[str, object]] = []
    for rec in records:
        scanned += 1
        if _is_anomaly(rec):
            reclassified += 1
            phantom_cost += _as_float(rec.get("estimated_cost_usd"))
            cleaned.append(_reclassify(rec))
        else:
            cleaned.append(rec)

    print(f"scanned:        {scanned}/{total}")
    print(f"reclassified:   {reclassified}")
    print(f"phantom cost:   ${phantom_cost:.4f} removed")

    if not apply:
        print("\nDRY-RUN — rerun with --apply to write changes.")
        return 0

    if reclassified == 0:
        print("\nno changes to apply.")
        return 0

    bak = jsonl_path.with_suffix(jsonl_path.suffix + ".bak")
    shutil.copy2(jsonl_path, bak)
    print(f"\nbacked up:      {bak}")
    _write_jsonl_atomic(jsonl_path, cleaned)
    print(f"rewrote:        {jsonl_path} ({len(cleaned)} records)")

    if pr_stats_path.is_file():
        pr_bak = pr_stats_path.with_suffix(pr_stats_path.suffix + ".bak")
        shutil.copy2(pr_stats_path, pr_bak)
        print(f"backed up:      {pr_bak}")

    rebuilt = _rebuild_rollup(cleaned)
    pr_stats_path.write_text(json.dumps(rebuilt, indent=2, sort_keys=True))
    print(f"rebuilt rollup: {pr_stats_path}")
    lifetime = rebuilt["lifetime"]
    assert isinstance(lifetime, dict)
    print(f"lifetime cost:  ${_as_float(lifetime.get('estimated_cost_usd')):.4f}")
    return 0


def main() -> int:
    default_path = (
        Path(__file__).resolve().parent.parent
        / ".hydraflow"
        / "metrics"
        / "prompt"
        / "inferences.jsonl"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=default_path,
        help="Path to inferences.jsonl (default: repo-local .hydraflow)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually rewrite files; otherwise prints a dry-run report.",
    )
    args = parser.parse_args()
    return run(args.path, apply=args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
