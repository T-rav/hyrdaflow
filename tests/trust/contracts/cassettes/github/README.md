# GitHub cassette corpus

Every cassette in this directory is a **hand-authored baseline** — they are
not refreshed by `ContractRefreshLoop` against a live `gh` CLI. Identifiable
by `recorder_sha: "00000000"` in the YAML header.

## Why hand-authored?

The call shapes a `gh`-backed `FakeGitHub` must contract-test against are
predominantly *mutating* — `gh pr create`, `gh pr merge`, `gh issue create`,
`gh issue close`, `gh label create`, `gh issue edit --add-label`, etc.
Refreshing those live every week would pollute the shared sandbox repo
(`T-rav-Hydra-Ops/hydraflow-contracts-sandbox`) with throwaway PRs and
issues, and the refresh PR would carry irreversible side effects.

The sibling adapters (git/docker/claude) record live because their fakes
contract-test against read-only ops (`git commit` is "mutating" but lives
in a tmp dir that's destroyed after recording — no shared state). See
`src/contract_recording.py::record_git` / `record_docker` /
`record_claude_stream` for the live-recording pattern.

## How baselines stay accurate

Two safeguards keep the hand-authored baselines from drifting silently:

1. **Replay gate**: every cassette must be replayable through `FakeGitHub`
   via `_invoke_fake_github` in
   `tests/trust/contracts/test_fake_github_contract.py`. A fake
   implementation change that diverges from the cassette breaks the test
   in CI — the cassette is the contract.
2. **FakeCoverageAuditorLoop** (ADR-0045): scans `FakeGitHub` for public
   methods without a cassette and files `fake-coverage-gap` issues.
   Adding a method without a baseline is detected, not silent.

## When to add a cassette here

- A new `FakeGitHub` method that emulates a real `gh` call is added.
- A real `gh` call shape is added to production code paths via
  `subprocess_util.run_subprocess` and a corresponding fake method exists
  (or is being added in the same PR).

Always add the dispatcher entry in `_invoke_fake_github` in the same PR
so the replay test exercises the new cassette end-to-end.

## When NOT to add a cassette here

- A `gh` call shape that isn't backed by a fake method — there's nothing
  to contract-test. Add the fake method first.
- An adapter-internal helper (`_run_gh`, `_maybe_rate_limit`) — the
  contract is at the public method level, not the helper.

## Current corpus

The committed corpus is auto-discovered by
`tests/trust/contracts/test_fake_github_contract.py` (parametrized over
`list_cassettes(_CASSETTE_DIR)`). To enumerate it locally:

```bash
ls tests/trust/contracts/cassettes/github/*.yaml
```

Each cassette must have a matching dispatcher entry in
`_invoke_fake_github`. The reverse is also true — a dispatcher entry
without a cassette (e.g. the historical `merge_pr` orphan) is dead code
and a fake-coverage signal.

## Future work

Implementing live read-only github recording (a real replacement for the
no-op `record_github`) needs:

1. A reliably-provisioned sandbox repo accessible from CI and dev hosts.
2. Shape-alignment between gh JSON output and fake method return types
   (e.g., `gh pr list --json …` returns dicts with different fields than
   `FakeGitHub.list_open_prs`'s `PRListItem` objects).
3. Per-call normalizers for issue/PR numbers, timestamps, label IDs.

Tracked separately.
