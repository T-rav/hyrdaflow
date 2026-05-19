"""MockWorldSeed — serializable initial state for a sandbox scenario.

A scenario module's `seed()` function returns this dataclass. The host-side
harness serializes via `to_json()` and writes the result to a file that
the docker container's `mockworld.sandbox_main` entrypoint reads on boot.

Pure data; no methods that take a live FakeGitHub. The Fake adapters'
own `from_seed(seed)` classmethods construct themselves from this payload.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MockWorldSeed:
    """Serializable initial state for a MockWorld run."""

    # List of (slug, path) pairs registered into RepoRegistryStore.
    repos: list[tuple[str, str]] = field(default_factory=list)

    # Each issue is a dict with keys: number, title, body, labels[].
    issues: list[dict[str, Any]] = field(default_factory=list)

    # Each PR is a dict with keys: number, issue_number, branch,
    # ci_status, merged, labels[].
    prs: list[dict[str, Any]] = field(default_factory=list)

    # Per-phase scripted LLM responses. Outer key is phase name
    # ("triage", "plan", "implement", "review", "fix_ci"); inner key is
    # issue number; value is a list of result dicts that get popped per
    # invocation.
    scripts: dict[str, dict[int, list[Any]]] = field(default_factory=dict)

    # Per-(issue, role) scripted advisor responses. Outer key is issue
    # number; inner key is the advisor role (``"pre_flight"`` /
    # ``"mid_flight"`` / ``"post_verify"``); value is a list of payloads
    # (typically JSON strings shaped like ``PostVerifyResult`` /
    # ``ReviewPlan``) that get popped per advisor invocation.
    #
    # Lives in its own field instead of ``scripts`` because the FakeLLM
    # advisor runner is keyed by a compound (issue, role) — the 2-arg
    # ``script_<phase>(issue, results)`` shape used by the loader for
    # ``scripts`` can't carry the role axis. Default empty for
    # back-compat with every existing seed payload.
    advisor_scripts: dict[int, dict[str, list[Any]]] = field(default_factory=dict)

    # How many ticks each enabled loop fires before assertions run.
    cycles_to_run: int = 4

    # Subset of loops to enable. None = all registered loops.
    loops_enabled: list[str] | None = None

    # (conclusion, url) for the main-branch CI status returned by
    # FakeGitHub.get_latest_ci_status().  Defaults to green so all existing
    # scenarios are unaffected.  CIMonitorLoop sandbox scenarios set this to
    # ("failure", "<run_url>") to drive the red-CI path.
    main_branch_ci_status: tuple[str, str] = ("success", "")

    def to_json(self) -> str:
        """Serialize to JSON for cross-process transfer."""
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, raw: str) -> MockWorldSeed:
        """Deserialize from JSON string."""
        data = json.loads(raw)
        # asdict() converts tuples to lists; coerce repos and ci status back.
        if "repos" in data:
            data["repos"] = [tuple(r) for r in data["repos"]]
        if "main_branch_ci_status" in data:
            data["main_branch_ci_status"] = tuple(data["main_branch_ci_status"])
        # JSON keys are strings; coerce script issue keys back to int.
        if "scripts" in data:
            data["scripts"] = {
                phase: {int(k): v for k, v in by_issue.items()}
                for phase, by_issue in data["scripts"].items()
            }
        # Same coercion for advisor_scripts (issue is the OUTER key here).
        if "advisor_scripts" in data:
            data["advisor_scripts"] = {
                int(issue): by_role
                for issue, by_role in data["advisor_scripts"].items()
            }
        return cls(**data)
