"""Subprocess entry for scripts/check_arch.py.

Contract:
  argv[1] = repo path
  stdout: one JSON object per violation
  stderr: human-readable status / errors
  exit 0: success (pass or skipped)
  exit 1: violations reported
  exit 2: loader / extractor error
"""

from __future__ import annotations

import json
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

from arch.loader import LoaderError, load_rule_module
from arch.validator import validate


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python -m arch.subprocess_entry <repo>", file=sys.stderr)
        return 2
    repo = Path(argv[1]).resolve()
    rule_path = repo / ".hydraflow" / "arch_rules.py"
    if not rule_path.is_file():
        print(f"SKIPPED: no .hydraflow/arch_rules.py at {repo}", file=sys.stderr)
        return 0
    try:
        rules = load_rule_module(rule_path)
    except LoaderError as e:
        print(f"LOADER_ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
    try:
        graph = rules.extractor(str(repo))
    except Exception as e:  # noqa: BLE001
        print(f"EXTRACTOR_ERROR: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 2
    violations = validate(graph, rules, repo_root=repo)
    for v in violations:
        print(json.dumps(asdict(v), sort_keys=True))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
