#!/usr/bin/env python3
"""One-shot fleet sync for implement-phase + pr_unsticker drift.

Modes:
  --mode issue-side  (default) — issues at hydraflow-ready whose PR exists
                                 with commits → swap both to hydraflow-review.
  --mode pr-side                — PRs at hydraflow-ready that have commits →
                                 swap PR to hydraflow-review (issue is left
                                 at whatever the operator put it at).
  --mode all                    — both modes in sequence.

Idempotent: re-running is a no-op once the fleet is reconciled.

Usage:
    python scripts/sync_implement_state.py --repo T-rav/hydraflow [--mode all] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class StuckPair:
    issue: int
    pr: int
    pr_commits: int


@dataclass
class StuckPR:
    pr: int
    pr_commits: int


def _gh(repo: str, *args: str) -> str:
    return subprocess.run(
        ["gh", *args, "--repo", repo],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def find_stuck_issues(repo: str) -> list[StuckPair]:
    issues_json = _gh(
        repo,
        "issue",
        "list",
        "--state",
        "open",
        "--label",
        "hydraflow-ready",
        "--limit",
        "200",
        "--json",
        "number",
    )
    issues = [i["number"] for i in json.loads(issues_json)]
    out: list[StuckPair] = []
    for n in issues:
        prs_json = _gh(
            repo,
            "pr",
            "list",
            "--head",
            f"agent/issue-{n}",
            "--state",
            "open",
            "--json",
            "number,isDraft,commits",
        )
        prs = json.loads(prs_json)
        if not prs:
            continue
        pr = prs[0]
        commits = len(pr.get("commits") or [])
        if pr["isDraft"] or commits == 0:
            continue
        out.append(StuckPair(issue=n, pr=pr["number"], pr_commits=commits))
    return out


def find_stuck_prs(repo: str) -> list[StuckPR]:
    # GraphQL aggregate-node limit is hit if we ask for `commits` across all
    # matching PRs at once. Fetch the lightweight (number, isDraft) shape
    # first, then resolve commits per PR.
    prs_json = _gh(
        repo,
        "pr",
        "list",
        "--state",
        "open",
        "--label",
        "hydraflow-ready",
        "--limit",
        "200",
        "--json",
        "number,isDraft",
    )
    prs = json.loads(prs_json)
    out: list[StuckPR] = []
    for pr in prs:
        if pr["isDraft"]:
            continue
        try:
            view_json = _gh(repo, "pr", "view", str(pr["number"]), "--json", "commits")
        except subprocess.CalledProcessError:
            continue
        commits = len(json.loads(view_json).get("commits") or [])
        if commits == 0:
            continue
        out.append(StuckPR(pr=pr["number"], pr_commits=commits))
    return out


def reconcile_pair(repo: str, p: StuckPair, *, dry_run: bool) -> None:
    if dry_run:
        print(
            f"[dry-run] swap #{p.issue} ready→review (PR #{p.pr}, {p.pr_commits} commits)"
        )
        return
    for kind, num in (("issue", p.issue), ("pr", p.pr)):
        _gh(repo, kind, "edit", str(num), "--add-label", "hydraflow-review")
        _gh(repo, kind, "edit", str(num), "--remove-label", "hydraflow-ready")
    print(f"[ok] swapped #{p.issue} ↔ PR #{p.pr} → review")


def reconcile_pr(repo: str, p: StuckPR, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[dry-run] swap PR #{p.pr} ready→review ({p.pr_commits} commits)")
        return
    _gh(repo, "pr", "edit", str(p.pr), "--add-label", "hydraflow-review")
    _gh(repo, "pr", "edit", str(p.pr), "--remove-label", "hydraflow-ready")
    print(f"[ok] swapped PR #{p.pr} → review")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument(
        "--mode", choices=["issue-side", "pr-side", "all"], default="issue-side"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if shutil.which("gh") is None:
        print("error: gh CLI not on PATH", file=sys.stderr)
        return 2

    issue_pairs: list[StuckPair] = []
    pr_only: list[StuckPR] = []

    if args.mode in ("issue-side", "all"):
        issue_pairs = find_stuck_issues(args.repo)
    if args.mode in ("pr-side", "all"):
        pr_only = find_stuck_prs(args.repo)

    if not issue_pairs and not pr_only:
        print("fleet is clean — no drift found")
        return 0

    print(f"found {len(issue_pairs)} issue-side pair(s), {len(pr_only)} PR-side")
    for p in issue_pairs:
        print(f"  issue #{p.issue} ↔ PR #{p.pr} ({p.pr_commits} commits)")
    for p in pr_only:
        print(f"  PR #{p.pr} alone ({p.pr_commits} commits)")

    if args.dry_run:
        print("\nrun without --dry-run to apply.")
        return 0

    for p in issue_pairs:
        try:
            reconcile_pair(args.repo, p, dry_run=False)
        except subprocess.CalledProcessError as e:
            print(f"  [fail] #{p.issue}: {e.stderr.strip()}", file=sys.stderr)
    for p in pr_only:
        try:
            reconcile_pr(args.repo, p, dry_run=False)
        except subprocess.CalledProcessError as e:
            print(f"  [fail] PR #{p.pr}: {e.stderr.strip()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
