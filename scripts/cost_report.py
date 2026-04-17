"""Print HydraFlow API spend breakdown from prompt telemetry.

Reads ``.hydraflow/metrics/prompt/pr_stats.json`` for lifetime and per-source
aggregates and, when available, ``inferences.jsonl`` for a per-(source, model)
breakdown that exposes where Opus vs Sonnet cost actually lands.

Usage:
    python scripts/cost_report.py
    python scripts/cost_report.py --data-root /custom/.hydraflow
    python scripts/cost_report.py --top 20
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        print(f"error: {path} not found", file=sys.stderr)
        sys.exit(1)
    with path.open() as f:
        return json.load(f)


def _iter_jsonl(path: Path):
    if not path.is_file():
        return
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _fmt_money(x: float) -> str:
    return f"${x:>10,.2f}"


def _fmt_int(x: int) -> str:
    return f"{x:>10,}"


def _print_lifetime(lifetime: dict[str, Any]) -> None:
    print("=" * 72)
    print("LIFETIME TOTALS")
    print("=" * 72)
    cost = float(lifetime.get("estimated_cost_usd", 0.0) or 0.0)
    calls = int(lifetime.get("inference_calls", 0) or 0)
    tokens = int(lifetime.get("total_tokens", 0) or 0)
    cache_hits = int(lifetime.get("cache_hits", 0) or 0)
    cache_misses = int(lifetime.get("cache_misses", 0) or 0)
    cache_total = cache_hits + cache_misses
    hit_rate = (cache_hits / cache_total * 100) if cache_total else 0.0
    print(f"  total spend         {_fmt_money(cost)}")
    print(f"  inference calls     {_fmt_int(calls)}")
    print(f"  total tokens        {_fmt_int(tokens)}")
    print(
        f"  cache hit rate      {hit_rate:>9.1f}%  ({cache_hits:,} hits / {cache_misses:,} misses)"
    )
    if calls:
        print(f"  avg $/call          ${cost / calls:>9.4f}")
    print()


def _print_sources(sources: dict[str, Any], top: int) -> None:
    print("=" * 72)
    print(f"COST BY SOURCE (top {top})")
    print("=" * 72)
    rows = []
    total_cost = 0.0
    for name, payload in sources.items():
        if not isinstance(payload, dict):
            continue
        cost = float(payload.get("estimated_cost_usd", 0.0) or 0.0)
        calls = int(payload.get("inference_calls", 0) or 0)
        rows.append((name, cost, calls))
        total_cost += cost
    rows.sort(key=lambda r: -r[1])
    print(
        f"  {'source':<22} {'cost':>12} {'% of total':>11} {'calls':>10} {'$/call':>10}"
    )
    print(f"  {'-' * 22} {'-' * 12} {'-' * 11} {'-' * 10} {'-' * 10}")
    for name, cost, calls in rows[:top]:
        pct = (cost / total_cost * 100) if total_cost else 0.0
        per_call = (cost / calls) if calls else 0.0
        print(
            f"  {name:<22} {_fmt_money(cost)} {pct:>10.1f}% {_fmt_int(calls)} ${per_call:>9.4f}"
        )
    print()


def _print_source_model_breakdown(inferences_path: Path, top: int) -> None:
    if not inferences_path.is_file():
        print(f"note: {inferences_path} not found — skipping per-model breakdown\n")
        return
    agg: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"cost": 0.0, "calls": 0, "tokens": 0, "prompt_chars": 0}
    )
    for record in _iter_jsonl(inferences_path):
        source = str(record.get("source", "?"))
        model = str(record.get("model", "?"))
        key = (source, model)
        agg[key]["cost"] += float(record.get("estimated_cost_usd") or 0.0)
        agg[key]["calls"] += 1
        agg[key]["tokens"] += int(record.get("total_tokens") or 0)
        agg[key]["prompt_chars"] += int(record.get("prompt_chars") or 0)

    rows = [
        (
            source,
            model,
            v["cost"],
            int(v["calls"]),
            int(v["prompt_chars"]),
        )
        for (source, model), v in agg.items()
    ]
    rows.sort(key=lambda r: -r[2])

    print("=" * 72)
    print(f"COST BY SOURCE x MODEL (top {top})")
    print("=" * 72)
    print(
        f"  {'source':<22} {'model':<14} {'cost':>12} {'calls':>8} "
        f"{'$/call':>10} {'avg chars':>11}"
    )
    print(f"  {'-' * 22} {'-' * 14} {'-' * 12} {'-' * 8} {'-' * 10} {'-' * 11}")
    for source, model, cost, calls, chars in rows[:top]:
        per_call = (cost / calls) if calls else 0.0
        avg_chars = (chars // calls) if calls else 0
        print(
            f"  {source:<22} {model:<14} {_fmt_money(cost)} "
            f"{_fmt_int(calls).strip():>8} ${per_call:>9.4f} {avg_chars:>11,}"
        )
    print()


def _default_data_root() -> Path:
    return Path.cwd() / ".hydraflow"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print HydraFlow API spend breakdown from prompt telemetry."
    )
    parser.add_argument(
        "--data-root",
        type=Path,
        default=_default_data_root(),
        help="HydraFlow data root (defaults to ./.hydraflow)",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=15,
        help="Rows to show in each breakdown table",
    )
    args = parser.parse_args()

    stats_path = args.data_root / "metrics" / "prompt" / "pr_stats.json"
    inferences_path = args.data_root / "metrics" / "prompt" / "inferences.jsonl"

    data = _load_json(stats_path)
    updated = data.get("updated_at") or "unknown"
    print(f"\nhydraflow cost report — stats as of {updated}\n")

    lifetime = data.get("lifetime", {})
    if isinstance(lifetime, dict):
        _print_lifetime(lifetime)

    sources = data.get("sources", {})
    if isinstance(sources, dict) and sources:
        _print_sources(sources, args.top)

    _print_source_model_breakdown(inferences_path, args.top)


if __name__ == "__main__":
    main()
