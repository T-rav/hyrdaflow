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

Future agents working in any HydraFlow-format project inherit it via this
document.

## What "tractable + reversible" means

| Class | Examples | Action |
|---|---|---|
| **Tractable + reversible** — act, then report | Run `make arch-regen` and push when CI fails on stale arch artifacts. Run `make lint-fix` and push on lint-formatting failures. Retarget a PR's base branch when a ruleset change broke the merge target. Add `Skip-ADR:` to a PR body when touchpoints are implementation-level (decorator-add, kwarg-add, import-path) not decision-changing. File a `hydraflow-find` issue for a recurring CI pattern that should be automated. Pull a stale branch and rebase onto its target. | **Act, then report what you did.** Don't ask first. |
| **High blast radius** — still requires explicit consent | Force-push to the default branch. Delete a branch with un-merged work. Drop persisted data. Modify repo permissions, branch-protection rulesets, or repo-level settings. Send messages on behalf of the user (Slack, email, GitHub mentions). Merge a PR that the human operator hasn't approved AND the orchestrator's reviewer hasn't approved. | **Confirm before acting.** Surface the proposal, get explicit OK. |
| **Authorial / scope** — needs alignment, not permission | New features, refactors, architectural changes. | **Brainstorm → spec → plan → TDD execute** per the existing workflow skills (`superpowers:brainstorming`, `writing-plans`, `subagent-driven-development`). Permission is implicit once the spec is approved; iteration on the plan does not need re-approval. |

## How to act under the directive

1. **Narrate before you act** — one short sentence stating the action and why.
   Example: "Retargeting this PR to the integration branch since the default
   branch now requires release-candidate head refs under the two-tier ruleset."
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
those rules — it doesn't replace them. "Never commit to the default branch"
still means never commit to the default branch, even with full autonomy.

## Discoverability

This standard lives at three load-bearing surfaces in any HydraFlow-format repo:

- This document — the canonical reference
- `CLAUDE.md` Quick Rules → indexed via the Knowledge Lookup table
- `docs/wiki/dark-factory.md` — the broader dark-factory operating contract

Future agents reading `CLAUDE.md` find the index entry, click through here,
inherit the directive. That's the propagation mechanism.

## Why this standard exists

Two consistent patterns surface in any factory-style codebase:

1. **Mechanical CI failures the bot could auto-fix in seconds** — stale
   auto-regenerated artifacts, lint formatting, base-branch targeting after a
   ruleset change. These have no judgment call. An agent asking
   "should I run `make arch-regen` and push?" wastes the operator's
   attention on what the factory was designed to handle.

2. **Recurring patterns that deserve a caretaker loop** — when the same kind
   of fix shows up three times across different PRs, it's a candidate for
   automation. The agent that recognizes the pattern should file a
   `hydraflow-find` so it lands in the factory's input queue, instead of
   privately handling each instance.

The directive turns those two patterns into explicit policy, so agents
don't have to re-derive the right behavior every session.
