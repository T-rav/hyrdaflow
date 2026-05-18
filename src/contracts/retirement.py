"""Cassette retirement audit (Phase 6 of #8786).

A baseline cassette becomes a retirement candidate once a
``LiveCorpusReplayLoop`` dispatcher covers the same ``(adapter, command)``
shape AND the dispatcher exercises that shape meaningfully (i.e. returns
non-None for matching samples). For the first wave (the shape dispatcher
from Phase 5), "meaningfully" means: the cassette's command shape would
be picked up — currently any github ``gh`` call.

This module ships the audit as a pure function so it can be invoked from
``FakeCoverageAuditorLoop``, a one-off CLI, or a future check in
``trust_fleet_sanity_loop``. The integration into a running loop is a
deliberate follow-up so the audit's noise level can be tuned before it
files issues.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger("hydraflow.contracts.retirement")


@dataclass(frozen=True)
class RetirementCandidate:
    """One cassette eligible for retirement.

    ``reason`` is a short machine-readable tag. ``dispatcher_key`` is the
    ``(adapter, command)`` tuple that covers this cassette's shape.
    """

    path: Path
    adapter: str
    interaction: str
    dispatcher_key: tuple[str, str]
    reason: str


def find_retirement_candidates(
    cassettes_root: Path,
    dispatcher_keys: set[tuple[str, str]],
) -> list[RetirementCandidate]:
    """Return baseline cassettes whose (adapter, command) is dispatcher-covered.

    Iterates every ``*.yaml`` under ``cassettes_root/<adapter>/`` that has
    ``baseline_only: true`` and a ``input.command`` matching one of the
    registered dispatcher keys. Malformed cassettes are skipped with a
    warning (the audit must not crash on bad files).
    """
    if not cassettes_root.is_dir():
        return []

    candidates: list[RetirementCandidate] = []
    for adapter_dir in sorted(cassettes_root.iterdir()):
        if not adapter_dir.is_dir():
            continue
        adapter = adapter_dir.name
        for yaml_path in sorted(adapter_dir.glob("*.yaml")):
            try:
                raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                logger.warning(
                    "retirement audit: could not load %s: %s", yaml_path, exc
                )
                continue
            if not raw.get("baseline_only"):
                continue
            cassette_adapter = str(raw.get("adapter") or adapter)
            cmd = str((raw.get("input") or {}).get("command") or "")
            if not cmd:
                continue
            # Match either the exact (adapter, command) key or an adapter
            # wildcard. The Phase 5 shape dispatcher uses
            # ("github", "gh") — that's an exact match for every github
            # cassette whose ``command`` happens to also be "gh" (the
            # convention for the existing hand-authored corpus uses the
            # FakeGitHub method name, not "gh", so most github cassettes
            # won't trigger today — by design).
            key = (cassette_adapter, cmd)
            if key in dispatcher_keys:
                candidates.append(
                    RetirementCandidate(
                        path=yaml_path,
                        adapter=cassette_adapter,
                        interaction=str(raw.get("interaction") or ""),
                        dispatcher_key=key,
                        reason="dispatcher_covers_shape",
                    )
                )
    return candidates


def format_candidates_for_issue(
    candidates: list[RetirementCandidate],
) -> str:
    """Render a candidate list as a markdown body for an audit issue."""
    if not candidates:
        return "No retirement candidates."
    lines = [
        "## Cassette retirement candidates",
        "",
        "The following baseline cassettes are covered by a live",
        "``LiveCorpusReplayLoop`` dispatcher and may be retired:",
        "",
        "| Cassette | Adapter | Interaction | Dispatcher |",
        "|---|---|---|---|",
    ]
    for c in candidates:
        lines.append(
            f"| `{c.path.name}` | {c.adapter} | {c.interaction} | "
            f"{c.dispatcher_key[0]}/{c.dispatcher_key[1]} |"
        )
    lines.extend(
        [
            "",
            "Retirement is a one-PR cleanup: verify the live dispatcher",
            "covers the same drift signal these cassettes catch, then",
            "delete the cassette files and the matching dispatcher entry",
            "in ``_invoke_fake_<adapter>``.",
        ]
    )
    return "\n".join(lines)
