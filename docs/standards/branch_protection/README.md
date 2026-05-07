# HydraFlow Standard — Branch Protection (ADR-0042)

Canonical, version-controlled GitHub ruleset configurations for the
two-tier branch model. Any HydraFlow-format repo applies these via
`scripts/setup_branch_protection.py` to encode the ADR-0042 decision in
GitHub itself rather than by convention alone.

## Files

| File | Applies to | What it enforces |
|---|---|---|
| `main_ruleset.json` | the default branch (`~DEFAULT_BRANCH`, normally `main`) | Merge-commit only (no squash); 15 required checks including the RC promotion + MockWorld + e2e gate (`Resolve RC PR`, `Browser Scenarios`, `Trust Gate`, `Sandbox (rc/* promotion PR full suite)`); no deletion; no force-push; PR required. |
| `staging_ruleset.json` | `refs/heads/staging` | Squash or merge allowed; **3 required checks** (`ADR gate`, `Detect Changes`, `discover-projects` — the always-on baseline). No deletion; no force-push; PR required. **Why only 3?** GitHub's required-status-checks treat path-filtered SKIPPED as "not passed", so any check that's job-conditional on touched paths would block docs-only PRs forever. The heavy CI jobs (`Tests`, `Lint`, `Type Check`, `Smoke Tests`, etc.) still RUN on code PRs — failures are visible in the rollup and reviewers/CI catch them — but they're not ruleset-required. **Future work:** add a single umbrella "Quality Gate" job (`if: always()`, depends on all conditional jobs, aggregates) and require only that — gives strict gating with path-filter compatibility. |

Both rulesets also enforce CodeQL `high_or_higher` and code-quality severity `errors`.

## Apply to a repo

```bash
# Dry-run (show what would change, no writes)
python scripts/setup_branch_protection.py --repo owner/name

# Apply
python scripts/setup_branch_protection.py --repo owner/name --apply

# Apply to the current repo (auto-detects from git remote)
python scripts/setup_branch_protection.py --apply
```

The script is idempotent: it `PUT`s the existing ruleset by name if it already exists,
`POST`s a new one otherwise. Running twice is a no-op when configs match.

## Audit drift

```bash
# Compare a repo's live rulesets against the canonical configs
python scripts/setup_branch_protection.py --repo owner/name --audit
```

`--audit` exits non-zero if any field on the live ruleset diverges from the canonical JSON.
Wire this into a periodic CI job (or a HydraFlow caretaker loop) to catch silent drift.

## Rationale

See [ADR-0042 §Enforcement](../../adr/0042-two-tier-branch-release-promotion.md#enforcement)
and [`docs/wiki/patterns.md`](../../wiki/patterns.md) "Branch protection — rulesets that
enforce the two-tier model" for the why and the operator reference.
