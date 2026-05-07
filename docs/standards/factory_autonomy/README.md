# HydraFlow Standard — Factory Autonomy

HydraFlow is a self-fixing factory. The human operator is the bottleneck the
factory exists to eliminate. Agents (human or LLM) acting inside the factory
should act on tractable + reversible fixes and report results — they should
not bottleneck on permission for things the factory's whole reason for being
is to handle automatically.

This standard codifies the autonomy directive so it lives in the repo
(durable, applies to every future agent that reads this codebase) rather
than in any single agent's per-session memory.

## The directive

> **For tractable + reversible fixes that align with the dark-factory pattern,
> act first and report results. Do not bottleneck on permission.**

The user explicitly delegated this on 2026-05-07. Future agents working in
HydraFlow inherit it via this document.

## What "tractable + reversible" means

| Class | Examples | Action |
|---|---|---|
| **Tractable + reversible** — act, then report | Run `make arch-regen` and push when CI fails on stale artifacts. Run `make lint-fix` and push on lint failures. Retarget a PR's base branch when a ruleset change broke the merge target. Add `Skip-ADR:` to a PR body when touchpoints are implementation-level (decorator-add, kwarg-add, import-path) not decision-changing. File a `hydraflow-find` issue for a recurring CI pattern that should be automated. Pull a stale branch + rebase onto target. | **Act, then report what you did.** Don't ask first. |
| **High blast radius** — still requires explicit consent | Force-push to `main`. Delete a branch with un-merged work. Drop persisted data. Modify repo permissions, branch protection rulesets, or repo-level settings. Send messages on behalf of the user (Slack, email, GitHub mentions). Merge a PR that the human operator hasn't approved AND the orchestrator's reviewer hasn't approved. | **Confirm before acting.** Surface the proposal, get explicit OK. |
| **Authorial / scope** — needs alignment, not permission | New features, refactors, architectural changes. | **Brainstorm → spec → plan → TDD execute** per the existing workflow skills (`superpowers:brainstorming`, `writing-plans`, `subagent-driven-development`). Permission is implicit once the spec is approved; iteration on the plan does not need re-approval. |

## How to act under the directive

1. **Narrate before you act** — one short sentence stating the action and why.
   Example: "Retargeting #8478 to staging since main now requires rc/* head
   refs under ADR-0042's main protect ruleset."
2. **Act**.
3. **Report what changed** — concrete file paths, commits, PR/issue numbers.
4. **Surface the underlying gap** when the fix is the same kind of fix you've
   already applied — file a `hydraflow-find` issue. Recurring manual fixes
   ARE the dark-factory's input signal.

## When in doubt, escalate

If the action's blast radius is uncertain, lean toward asking. The cost of
a 30-second confirmation is much smaller than the cost of an irreversible
mistake. The directive trusts you with tractable + reversible. It does
NOT trust you with the bet-the-repo class.

Specifically: never apply this directive to override an existing project
rule (e.g. CLAUDE.md "Quick rules"). The autonomy directive composes WITH
those rules — it doesn't replace them. "Never commit to main" still means
never commit to main, even with full autonomy.

## Discoverability

This standard lives at three load-bearing surfaces:

- This document — the canonical reference
- `CLAUDE.md` Quick Rules → indexed via the "Wiki topic index" / Knowledge Lookup table
- `docs/wiki/dark-factory.md` — the broader dark-factory operating contract

Future agents reading `CLAUDE.md` find the index entry, click through here,
inherit the directive. That's the propagation mechanism.

## How this standard came to exist

This document was written 2026-05-07 after a session that demonstrated the
need: rebase-on-conflict (PR #8482) shipped without scenario+sandbox tests,
then PR #8478 sat broken with mechanical CI failures the bot could fix in
seconds, then I (the agent) repeatedly asked the user "should I retarget /
should I run arch-regen / should I push the fix?" — burning attention the
factory was supposed to save.

The user's response — "hydra is the factory, you help me build it, I want
you to make more of these decisions without me going forward" — is the
seed of this standard.

Don't make the user repeat that.
