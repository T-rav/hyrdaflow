"""One-off: scan tests/ and emit the initial grandfather YAML.

Delete this file after the initial PR lands.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from _mock_spec_detector import detect_violations  # noqa: E402


def main() -> None:
    tests_root = REPO_ROOT / "tests"
    entries = []
    for path in sorted(tests_root.rglob("test_*.py")):
        # Skip our own meta fixtures — they're synthetic and tested separately.
        if "_mock_spec_fixtures" in path.parts:
            continue
        for v in detect_violations(path):
            entries.append(
                {
                    "path": str(v.path.relative_to(REPO_ROOT)),
                    "line": v.lineno,
                    "reason": "grandfathered at initial scan 2026-05-07",
                }
            )
    out = {
        "comment": (
            "Mock-spec discipline ratchet. Generated 2026-05-07. "
            "MAY shrink (cleanup welcome). MUST NOT grow (CI fails on growth)."
        ),
        "entries": entries,
    }
    target = REPO_ROOT / "tests" / "_mock_spec_grandfathered.yaml"
    target.write_text(yaml.safe_dump(out, sort_keys=False, width=120))
    print(f"wrote {len(entries)} entries to {target}")


if __name__ == "__main__":
    main()
