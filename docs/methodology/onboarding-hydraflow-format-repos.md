# Onboarding HydraFlow-Format Repos

**Status:** Methodology proposal (informed by two reference bootstraps)
**Last updated:** 2026-05-16
**Cross-references:**
- [`factory_operation`](../standards/factory_operation/README.md) — what the format actually is
- [`branch_protection`](../standards/branch_protection/README.md) — protection ruleset shape
- [`testing`](../standards/testing/README.md) — the three-layer pyramid that bootstraps depend on
- [`factory_autonomy`](../standards/factory_autonomy/README.md) — when agents act vs ask during onboarding
- [`self-documenting-architecture`](self-documenting-architecture.md) — sister methodology doc

---

## What this document is

A pattern + interface design for **standing up a new HydraFlow-format target repo** the way an IDE handles "File → New Project": the operator clicks a button, answers a handful of questions in a wizard, and lands on a project dashboard with a green-CI repo, provisioned branches + labels + protection, a design spec, an implementation plan, and the first batch of `hydraflow-find` issues queued for the factory.

It exists because we did this process twice in close succession (amplifier, then harvestd) and the second pass cost noticeably less than the first. The deltas tell us which pieces are stable (and belong in a template the backend stamps out), which are one-knob choices (and belong in the wizard form), which are genuinely creative work (and belong in an embedded AI design dialogue), and which are friction the interface should absorb so the operator never sees them. All of this is reachable from a UI, with no Claude Code CLI dependency on the operator side.

If you are about to bootstrap a third HydraFlow-format repo by hand: this doc tells you what's invariant, what's a knob, where the friction lives, and what a UI-driven onboarding surface that absorbs the friction should look like.

---

## What we built (the two reference bootstraps)

| Repo | Domain | UI in V1? | Domain safety guard | Plan 01 tasks |
|---|---|---|---|---|
| `amplifier` | AI-native content amplification | No (deferred) | None | 15 |
| `harvestd` | AI-assisted portfolio operating system | Yes (Next.js scaffold) | `decimal-purity` AST guard on money paths | 17 |

Both repos followed the same arc (today, executed by hand through Claude Code):

```
Brainstorming skill (design)
  → Design spec written to docs/superpowers/specs/
  → User approves spec
  → Plan 01 (Bootstrap) written to docs/superpowers/plans/
  → Subagent-driven execution of Plan 01
  → Plan 02 + ROADMAP for remaining plans
  → 12-15 GitHub issues filed with hydraflow-find label
  → RC promotion PR (staging → main)
```

By the end of each bootstrap, the repo had:

- A private GitHub repo with `main` + `staging` branches
- CI workflow `quality` running on every PR
- HydraFlow lifecycle labels provisioned
- Plan 02 issues ready for HydraFlow's `DiscoverLoop` to pick up

The proposal in this doc takes that exact arc and puts it behind a "New Project" button.

---

## The 10-file invariant kernel

Across both repos, the following files were **structurally identical** (modulo project-name substitution):

| Layer | File | Substitution variables |
|---|---|---|
| Code | `src/<pkg>/__init__.py` | `<pkg>` |
| Code | `src/<pkg>/cli.py` | `<pkg>` |
| Code | `tests/unit/test_smoke.py` | `<pkg>` |
| Config | `pyproject.toml` | `<pkg>`, `<description>`, `<cli_entry>`, `<coverage_floor>` |
| Config | `.gitignore` | none |
| Config | `.env.example` | domain-specific block at top |
| Config | `Makefile` | `<pkg>`, `<coverage_floor>`, optional `decimal-purity` + `ui-*` targets |
| Config | `.github/workflows/quality.yml` | `<coverage_floor>`, conditional UI block |
| Doc | `CLAUDE.md` | `<pkg>`, domain safety rules block, glossary |
| Doc | `README.md` | `<pkg>`, architecture table, domain narrative |
| Doc | `docs/standards/**` | none (direct copy from HydraFlow) |
| Doc | `docs/adr/README.md` | none (one-line ADR-0001 entry varies) |
| Doc | `docs/adr/0001-<title>.md` | domain decision |
| Doc | `docs/wiki/index.md` | none |
| Doc | `.github/ISSUE_TEMPLATE/{bug,feature}.md` | `hydraflow-find` label (canonical) |
| Doc | `.github/PULL_REQUEST_TEMPLATE.md` | optional domain safety checklist |
| Script | `scripts/prep.py` | 1-line docstring only |
| Script | `scripts/setup_branch_protection.py` | none (classic-API version) |
| Script | `scripts/__init__.py` | none |

Concrete evidence: `diff scripts/setup_branch_protection.py` between the two repos returns zero output. `diff scripts/prep.py` returns a single-line difference (the module docstring's first line). `diff -rq docs/standards/testing` returns zero output. The standards corpus is byte-for-byte identical.

**Implication for the UI:** this entire kernel is the **payload** the onboarding backend writes to disk after the wizard collects the few substitution variables. The operator never sees these files during onboarding — they appear in the new repo on GitHub after the "Create" button is pressed.

---

## Customization knobs (what genuinely varies → wizard inputs)

### Domain-driven (requires design dialogue; AI assistant in the UI)

| Knob | Amplifier | Harvestd | Where it lives |
|---|---|---|---|
| Module layout | `ingest/`, `extract/`, `index/`, `generate/`, `review/`, `voice/`, `topics/` | `policy/`, `exchange/`, `strategies/`, `portfolio/`, `candles/`, `backtest/`, `approvals/`, `ai/` | Plan 01 file map |
| Safety guards | none | `decimal-purity` AST scanner | `scripts/`, `Makefile` target |
| Safety test tier | none | `tests/safety/` directory | `Makefile`, CI workflow |
| Mode discipline | n/a | three-mode contract (backtest/paper/live) | `README.md`, `CLAUDE.md`, ADR-0001 |
| Domain-specific deps | `kuzu`, `trafilatura` | `coinbase-advanced-py`, `pandas`, `sqlalchemy`, `apscheduler` | `pyproject.toml` |
| Critical invariants surfaced in CLAUDE.md | "posting safety is load-bearing" | "no float in money paths" + "paper-only V1" | `CLAUDE.md` Quick Rules |

### Operator-choice (one binary or small-set decision → wizard form fields)

| Knob | Amplifier | Harvestd | Wizard control |
|---|---|---|---|
| UI scaffold | No | Yes (Next.js) | Radio: None / Next.js / Other |
| Repo visibility | Private | Private | Radio: Private / Public |
| Coverage floor | 80% | 85% | Slider 70–95% |
| Initial test scope (script tests?) | Yes (post-friction) | No | Checkbox |
| GitHub plan tier | Free (deferred) | Free (succeeded) | Auto-detect at runtime, fall back |

### Tooling drift (transparent to operator; backend pins versions)

| What drifted | Why | Fix |
|---|---|---|
| Next.js 16 instead of 15 | `npx create-next-app@latest` resolves to latest stable | Backend pins the version in the scaffolding step |
| Pyright 1.1.380 → 1.1.409 hint | Pyright self-updates | Pinned in `dev` extras (already done) |

---

## Friction catalog (what the UI must absorb)

Each friction below cost real time on amplifier. Most were absorbed into harvestd's plan before execution; all of them are candidates for the UI to handle silently.

### F1 — Pyright IDE phantom imports

**Symptom:** Fresh `__init__.py` + `cli.py` show "unresolved import" squiggles in the IDE even though `uv run pyright src` returns 0 errors.

**Cause:** IDE's pyright LSP runs outside the venv and cannot find the installed package without `venvPath`/`venv` config.

**Resolution:** Add `venvPath = "."` + `venv = ".venv"` to `[tool.pyright]` in `pyproject.toml`.

**Prevent in UI:** The backend's `pyproject.toml` template ships with these settings. Operator never sees the issue.

### F2 — GitHub branch protection 403 on free-tier private repos

**Symptom:** `gh api .../rulesets` returns HTTP 403 on private repos under GitHub free plan. Modern Rulesets API requires Pro.

**Cause:** GitHub gates the Rulesets API behind paid plans for private repos. HydraFlow's own `setup_branch_protection.py` uses Rulesets because HydraFlow is public.

**Resolution:** Rewrite the script to use GitHub's classic protection API (`PUT /repos/.../branches/{branch}/protection`), which works on all plans. Canonical ruleset JSONs in `docs/standards/branch_protection/` stay as the source of truth; the script derives the required-check list from them.

**Prevent in UI:** The backend tries Rulesets first, automatically falls back to classic on 403, and reports the actual tier to the operator on the project dashboard (badge: "Branch protection: classic API — upgrade to Pro for Rulesets"). The operator never has to know there's a script.

**Unexplained variance:** amplifier hit 403; harvestd succeeded with the same script on the same account days later. The UI should treat success as a happy surprise, not the expected case.

### F3 — Label name drift (`find` → `hydraflow-find`)

**Symptom:** Issues filed with the `find` label invisible to HydraFlow's `DiscoverLoop`, which watches `hydraflow-find` (canonical prefix in `hydraflow/src/config.py`).

**Cause:** Plan did not specify the label naming convention; implementer used bare names.

**Resolution:** Renamed all 14 labels to `hydraflow-*` prefix in `prep.py`; relabeled 13 already-filed issues via `gh`; updated issue templates.

**Prevent in UI:** Backend's `prep.py` template ships with `hydraflow-*` prefix from day one. Issue templates default to `labels: hydraflow-find`. The label set is a load-bearing contract with the factory's loop, not a project choice.

### F4 — Next.js version drift

**Symptom:** Plan specified Next.js 15; `npx create-next-app@latest` pulled Next.js 16. Commit message contradicts package.json.

**Cause:** `@latest` is always the latest stable; no version pin in the scaffold command.

**Resolution:** Accepted 16 in place (no behavioral regression at scaffold-only stage).

**Prevent in UI:** Backend pins the major version in the scaffolding step. Wizard's "UI scaffold" dropdown shows the exact version that will be installed.

### F5 — Ruff unsafe-fixes required manual intervention

**Symptom:** After porting scripts in harvestd, `make lint` failed on RUF005 and UP038 without offering to fix. `--unsafe-fixes` was required.

**Cause:** Ruff classifies these as unsafe because they change semantics in edge cases; the default `--fix` skips them.

**Resolution:** Manual `ruff check --fix --unsafe-fixes` once, then committed.

**Prevent in UI:** Backend pre-formats all scripts with `--unsafe-fixes` applied before committing. Operator never sees a red `make quality`.

### F6 — Empty test commit on `main` from BP smoke test

**Symptom:** Empty commit `test: should fail to push to main directly` landed on `main` because the BP smoke test wasn't cleaned up.

**Cause:** Smoke test creates a direct-push commit to verify protection rejects it; the cleanup step was not executed.

**Resolution:** Left in place on amplifier; needs to be done explicitly on harvestd.

**Prevent in UI:** Backend skips the smoke test — it trusts its own configuration. If the operator wants to verify, the project dashboard has a "Verify branch protection" button that runs the smoke against a throwaway branch.

### F7 — Repeated mechanical work across bootstraps

**Symptom:** Two repos, ~80% identical scaffolding, but 15+ subagent dispatches each to materialize the files piece by piece.

**Cause:** No template; every file is freshly written each time. Implementer agents do mechanical work the UI could absorb.

**Prevent in UI:** The 10-file invariant kernel is generated by the backend in one operation (~seconds). The creative work (design spec, Plan 02 task content) is what the AI assistant in the UI helps with.

### F8 — Spec → plan → issues handoff is bespoke

**Symptom:** Each bootstrap requires hand-composing Plan 01 + Plan 02 + filing N issues. The flow is mechanical but not yet templatized.

**Cause:** No unified "new project" surface. The brainstorming + writing-plans + subagent-driven-development skills exist but are composed by hand each time.

**Prevent in UI:** The wizard composes them under one flow. The operator clicks Next → Next → Create, and the spec + Plan 01 + initial issues all materialize via the backend.

---

## Mechanical vs creative work

The bootstrap split into two distinct phases. Each maps to a different surface in the UI.

### Creative (requires design dialogue with the operator)

These live in the UI as either form fields or an embedded AI assistant:

- The product concept (what the system does, for whom, why) → **AI chat** with structured-output handoff to spec
- The domain module structure (what belongs in `src/<pkg>/`) → **AI chat** + template suggestions
- The safety load-bearing constraints (CLAUDE.md Quick Rules block) → **AI chat** + checkbox library of common patterns
- Domain-specific safety guards → **checkbox library** (decimal-purity, posting-approval, future ones) + AI suggestions
- The architecture decision recorded in ADR-0001 → **AI chat** outputs draft; operator edits inline
- Plan 02+ task content (domain operations, not factory plumbing) → **AI chat** + operator edits
- Issue descriptions → **AI generates from Plan 02**; operator reviews

### Mechanical (the backend does it; no operator visibility needed)

These happen server-side after "Create" is clicked:

- All 10+ files in the invariant kernel
- Copying the HydraFlow standards corpus
- `prep.py --create-labels` against the new repo
- `gh repo create --private --source=. --remote=origin --push`
- `git checkout -b staging && git push -u origin staging`
- `setup_branch_protection.py --apply` (with tier fallback)
- Filing N GitHub issues from Plan 02 with `gh issue create --label hydraflow-find`
- RC promotion PR creation on first publish

### The flow composes inside the UI

```
[Wizard form]                       [Backend (invisible)]
basics + tech stack + safety   →    pick template files + variables
                               →    generate invariant kernel
                                    
[Embedded AI design chat]      →    write design spec
                               →    write Plan 01
                               →    write Plan 02 + ROADMAP
                                    
[Review screens]               →    operator reviews spec + plans (inline edit)
                                    
[Click Create]                 →    gh repo create + push
                               →    apply branch protection
                               →    provision labels
                               →    file Plan 02 issues
                               →    register repo with factory
                                    
[Project dashboard]            →    operator lands here; CI green; factory ready
```

---

## Proposed onboarding interface — UI-driven

### Anti-pattern this design rejects

An earlier draft proposed a separate "HydraFlow Studio" surface with its own home, its own project dashboard, its own everything. After mockup review with the operator, that was wrong: HydraFlow already has a working React dashboard (`src/ui/`) with `RepoSelector`, `RegisterRepoDialog`, `PipelineStatus`, `EventLog`, `Livestream`, and friends. **The right design extends that surface, not builds a parallel one.** Onboarding is a feature inside the existing dashboard, not a separate app.

### The integration is one menu item

The entire entry point is a new option in the existing "All repos" picker at the top-left of the HydraFlow dashboard:

```
All repos ▾
├── Existing
│   ├── All repos
│   ├── T-rav/amplifier
│   ├── T-rav/harvestd
│   └── T-rav/hydraflow
└── Onboard
    ├── + New project…              ← NEW: opens the bootstrap wizard
    └── ⌕ Register existing repo…   ← existing RegisterRepoDialog flow
```

Two related actions, sibling menu items. `Register existing repo…` already exists (wraps `RegisterRepoDialog`). `+ New project…` is the addition — it opens a multi-step wizard as a **modal/drawer overlay** on the dashboard. The factory model (pipeline, livestream, intent input) is untouched. No new tabs, no new panes, no navigation away.

### The wizard — design first, save locally, push later

Four steps, in this order (design-first, materialize-second, push-deliberate):

| # | Step | What happens |
|---|---|---|
| 1 | **Describe** | AI chat. Operator talks about what they're building. Form fields auto-fill in a sidebar as Claude surfaces them (name, backend, UI, visibility, safety guards). |
| 2 | **Spec** | Auto-drafted design spec. Inline edit; AI revises on request. |
| 3 | **Plan 01** | Auto-drafted bootstrap plan (15-17 tasks, derived from harvestd as the template). Review checklist; tweak if needed. |
| 4 | **Materialize locally** | Creates directory, runs scaffolding, `git init`, `make quality`, commits the bootstrap + spec + plan. **No GitHub push yet.** |

Then — **outside the wizard, on the project view** — the operator gets a single one-click action:

- **[ Push to GitHub ]** runs `gh repo create --private --push` → branch protection (with tier-fallback) → label provisioning → Plan 02 issue filing → factory registration · ~30s total.

This local-first split is deliberate. The operator can run the new repo locally, iterate on the spec or the plan, hit `make quality` a few times, abandon the project if it's wrong — all with **zero GitHub state created**. Push happens when ready, not at the end of a wizard.

### Step 1 — Describe (the key UX shift)

The earlier draft had Step 1 as a form. Wrong: the form is something the AI fills out *for* the operator while they're talking about what they want. Conceptually:

- **Left/main pane**: chat with Claude. "Tell me what you're building."
- **Right sidebar**: auto-extracted fields appearing as the conversation surfaces them (Name: agentwatch · Backend: Python 3.11 · UI: Next.js · Safety guards: ☑ Token redaction · …)
- **Bottom-right**: "Edit manually" override if the AI gets something wrong
- **Footer**: "Save draft" (conversation persists) · "Draft spec →" (proceed to Step 2)

The operator never fills out a form unless they want to. The chat IS the form.

### Step 4 — Materialize (quiet ops)

Earlier draft showed every step of the pipeline streaming in the operator's face. Wrong: the operator cares about *did it work*, not the 14-step play-by-play. The validated pattern:

- **Big outcome at the top**: ✓ "agentwatch is ready locally" + `make quality` timing
- **One amber line**: "Local-only. Push to GitHub from the project view when ready."
- **Activity log** (`▸ Activity log · 15 steps`) — **collapsed by default**, click to expand

Same pattern applies to the Push action on the project view: compact one-line status + single CTA · ops details live in the expandable activity log · no noise in the face.

The activity log becomes the **one** place ops live — collapsed, click to expand, persists across operations. Same component family as HydraFlow's existing `EventLog` / `Livestream`, just scoped per-project. Once the repo is pushed and registered with the factory, the activity log can hook into the existing dashboard's livestream surface so all activity (bootstrap + push + factory pipeline) shows up in one stream.

### Project view — local-only state

After Step 4 closes the wizard, the new repo appears in the existing sidebar with an **amber "○ local only" badge** so the state is unmistakable. The center pane (Work Stream tab) shows:

- **Amber status block** at the top: "Local only · ~/Documents/projects/agentwatch · make quality green" + **[ Push to GitHub ]** button
- **Local commands** block: `make quality`, `uv run agentwatch`, `cd ui && npm run dev` with last-run status
- **Activity log** at the bottom (collapsed): bootstrap timeline · click to expand

On click of **Push to GitHub**:
- The amber block flips green: "Pushing to GitHub… ⠋ filing Plan 02 issues" + progress bar
- Activity log updates live (still expandable, not in-the-face)
- Operator can close the tab; push continues server-side
- On completion: amber badge → green ●; status flips to "registered with factory"; regular pipeline view takes over (DiscoverLoop picks up issues, etc.)

### What the operator does NOT do

- Run `gh repo create` manually
- Edit `pyproject.toml`, `Makefile`, `CLAUDE.md`, `.github/workflows/quality.yml` by hand
- Know what "branch protection rulesets" are
- Know that `hydraflow-find` is the canonical label prefix
- Install Claude Code
- Open a terminal
- See an ops-step play-by-play unless they explicitly expand the activity log

### What the operator DOES do

- Click "+ New project…" in the existing repo picker
- Talk to the AI assistant about what they're building (form fills itself in the sidebar)
- Skim the auto-drafted spec + plan; inline-edit if needed
- Click "Materialize" → wizard closes; operator is back in the dashboard with the new repo selected
- Run the project locally; iterate
- When ready: click "Push to GitHub" on the project view
- Land back in the regular HydraFlow dashboard, now showing the new repo's pipeline activity

### Reference mockups

The validated UI mockups live in `.superpowers/brainstorm/` from the mockup-review session that produced this doc. They're gitignored (per the superpowers brainstorming visual companion pattern) but persist locally for reference. Key files:

- `00-frame.html` — superseded by `01-corrected-architecture.html` (Studio framing was wrong)
- `01-corrected-architecture.html` — onboarding inside existing dashboard with right-pane fleet view (also superseded — fleet pane was overkill)
- `02-dropdown-integration.html` — **kept**: one menu item in the All repos picker is the entire integration
- `03-wizard-step1-basics.html` — superseded by `04` (form-first was wrong)
- `04-wizard-flipped-flow.html` — **kept**: 4-step flow with Describe (chat) first, Materialize (no push) last
- `05-materialize-then-push.html` — superseded by `06` (too much ops noise in the project view)
- `06-quiet-ops.html` — **kept**: show outcome, collapse activity log by default

The supersession history is itself part of the design rationale: each iteration removed scope from the proposal in response to operator feedback. The final design is smaller than the initial draft on every axis (fewer panes, fewer steps visible, fewer ops in the face).

### Behind the UI — backend services

The UI is the surface; the work happens in three backend services:

| Service | Responsibility |
|---|---|
| **Templating service** | Owns the invariant kernel + variable substitution. Given `(name, tech_stack, safety_guards)`, returns a fully-written directory tree ready to commit. |
| **Provisioning service** | Wraps `gh` CLI + git + scripts. Creates GitHub repos, applies branch protection (with tier-fallback), provisions labels, files issues, pushes branches. Streams progress events to the UI via SSE/WebSockets. |
| **Design AI service** | Wraps Anthropic Claude API. Stateful conversation per project; structured outputs for spec + Plan 01 + Plan 02 outlines. The operator never sees an API key. |

These compose:

```
[Browser (Next.js)]
        │ HTTPS + WebSocket
        ▼
[Onboarding API (FastAPI)]
        ├──► Templating service ──► writes to working directory
        ├──► Design AI service ──► drafts spec/plan content
        └──► Provisioning service
                 ├──► gh CLI
                 ├──► git
                 ├──► scripts (prep.py, setup_branch_protection.py)
                 └──► HydraFlow factory registry (records the new repo)
```

The simplest deployment is **single-binary, self-hosted alongside the existing HydraFlow daemon**: the same `hydraflow serve` process gains a `/studio` web UI + a few new API endpoints. The operator runs HydraFlow locally, opens `localhost:5555/studio`, and sees their projects.

### Authentication model

Two credentials needed:

| Credential | Provided how | Stored where |
|---|---|---|
| GitHub OAuth token (for `gh` calls) | Operator clicks "Connect GitHub" on first use; OAuth device flow | Locally; encrypted at rest; never sent to the templating/design services |
| Anthropic API key (for design dialogue) | Operator pastes in Settings once; or uses an already-configured `ANTHROPIC_API_KEY` env var | Locally; same encryption as GitHub token |

Self-hosted multi-tenant deployments would need standard SSO + per-tenant secret stores, but that's a deferred concern. V1 is single-operator self-hosted.

### What the operator does NOT do

- Run `gh repo create` manually
- Edit `pyproject.toml`, `Makefile`, `CLAUDE.md`, `.github/workflows/quality.yml` by hand
- Know what "branch protection rulesets" are
- Know that `hydraflow-find` is the canonical label prefix
- Install Claude Code
- Open a terminal

### What the operator DOES do

- Click "New Project"
- Fill in name + description + a few checkboxes
- Talk to the AI assistant in a chat (or skip and use defaults)
- Review the generated spec + plan (inline edit if desired)
- Click "Create"
- Land on a dashboard showing the live state of their new project

### Comparison vs the CLI-driven path

| Concern | CLI-driven (hypothetical alternative) | UI-driven (this proposal) |
|---|---|---|
| Operator setup | Install Claude Code + uv + gh + Node | Open the existing HydraFlow dashboard |
| Operator skill required | Familiarity with git, gh, scripts, skills | Click "+ New project…", talk to chat |
| Friction visibility | Operator hits issues, sees errors | Backend absorbs friction silently; activity log on demand |
| Customization at creation | Edit text files | AI chat → fields auto-fill in sidebar |
| Time to local-ready | 30-60 min hand-driven | ~3 min wizard + materialize |
| Time to GitHub-published | Same | + ~30s push step on operator's deliberate click |
| Failure mode | Mid-stream halt; operator debugs | Local steps atomic; push retries with progress visible |
| Reuse | Each bootstrap is bespoke | Templated; consistent across bootstraps |
| Ops visibility | Inline output by default | Outcome only; activity log expandable on demand |

The CLI surface still exists for power users + CI automation, but the **primary surface is the existing HydraFlow dashboard**. CLI is the optional escape hatch, not the default path.

---

## Implementation roadmap

This work itself becomes a HydraFlow project, executed via HydraFlow's own factory pattern (eat your own dog food). Suggested phasing:

### Phase 1 — Templating service + headless API

Backend-only first; no UI yet. Validates that the materialization works.

1. New module `hydraflow/src/onboarding/templating.py` — accepts a `BootstrapSpec` (name, tech, guards, etc.) + writes a directory tree using harvestd's bootstrap as the source-of-truth template
2. Endpoints under `/api/onboarding/`:
   - `POST /api/onboarding/projects` — accepts a spec, returns a draft ID
   - `POST /api/onboarding/projects/{id}/materialize` — runs the full provisioning pipeline (gh + git + scripts), streams progress via SSE
3. Provisioning service (`hydraflow/src/onboarding/provisioning.py`) — wraps gh + git + scripts, handles BP tier-fallback
4. Test against a real third bootstrap (a small project like a personal-finance tracker or observability tool); confirm the API can produce a green-CI private repo in <5 min
5. Headless API is usable on its own: a curl + JSON workflow for ops people who don't want a browser

End state: HTTP-driven onboarding works. UI is the next layer.

### Phase 2 — Wizard UI inside the existing dashboard (no separate Studio)

Layers the wizard onto HydraFlow's existing React dashboard (`src/ui/`). No parallel app.

1. New "+ New project…" entry in the existing `RepoSelector` / `GitHubRepoPicker` menu (sibling to the existing `RegisterRepoDialog` invocation)
2. New `BootstrapWizard.jsx` component — modal/drawer overlay rendered above the existing dashboard
3. Four-step flow: Describe (chat placeholder until Phase 3) · Spec (auto-drafted, inline edit) · Plan 01 (auto-drafted checklist) · Materialize (calls Phase-1 API; activity log collapsed)
4. New `ProjectView.jsx` block that renders when a `local-only` repo is selected: amber status + **[ Push to GitHub ]** button + collapsed activity log
5. Authentication: reuse HydraFlow's existing GitHub auth path (`gh` token already configured for the daemon)
6. Live progress streaming via WebSocket/SSE during materialize + push (reuses existing `Livestream` / `EventLog` plumbing)

End state: operator opens the existing dashboard at `localhost:5555`, clicks "+ New project…", has a local-ready repo in ~3 minutes, pushes to GitHub on a deliberate second click.

### Phase 3 — Design AI service (the chat in Step 1)

Adds Claude-backed dialogue + spec/plan generation in the wizard.

1. New module `hydraflow/src/onboarding/design_ai.py` — wraps Anthropic API with structured outputs
2. Persistent conversation per project draft (stored in HydraFlow's SQLite)
3. Templates for spec sections + Plan 01 + Plan 02 outlines
4. Streaming responses in the wizard's Step 1 chat
5. **Form auto-fill** — Claude returns structured field updates (name, backend, UI, safety guards) alongside its chat replies; sidebar updates in real time
6. Inline-edit support: AI generates a draft section, operator edits, AI revises on next turn
7. Optional "Skip chat" path with sensible defaults (for operators who already know what they want; lets them fill the sidebar by hand)
8. Manual override per field: operator clicks "Edit manually" on any auto-filled sidebar entry to take control

End state: the whole arc — describe → spec → plan → materialize — completes inside the wizard. The chat IS the form.

### Phase 4 — Plan execution + factory registry integration

The existing dashboard becomes the operator's home for managing the factory across all onboarded repos.

1. Plan 02+ work surfaces on the existing dashboard (issue queue, PR status, CI runs) — already mostly present; just needs per-repo scoping
2. "Continue to next plan" workflow: when Plan N is done, generate Plan N+1 outline (via Phase-3 AI service) → operator reviews → file issues with `hydraflow-find` label
3. Repo-level metrics: factory throughput, time-to-merge per task, friction reports — add to existing `MetricsPanel`
4. Cross-repo view: extend `RepoSelector` to show health summary per managed repo

End state: onboarding is a feature inside HydraFlow's existing dashboard, not a separate product. The factory's own state (across all onboarded repos) is visible and operable from one browser tab.

---

## Open questions

- **How does the templating service stay in sync with the HydraFlow standards corpus?** When `docs/standards/factory_operation/README.md` updates upstream, do existing onboarded repos pick up the change? Options: (a) periodic backend sync that opens PRs against managed repos, (b) "upgrade format" button on the project view, (c) document manual steps. Lean toward (b) initially.
- **Where do design AI conversations live across sessions?** Operator pauses mid-design, comes back tomorrow — the AI context needs to persist. Per-project SQLite table is the simplest answer.
- **Self-hosted single-operator vs hosted multi-tenant?** V1 is single-operator self-hosted (matches existing HydraFlow deployment model). Multi-tenant SaaS adds auth, secret isolation, billing — defer until there's demand.
- **Plan 02 generation: AI-drafted or operator-edited?** Currently in the reference bootstraps, Claude wrote Plan 02 inline. In the wizard, should this be auto-generated and presented for review, or should it be a separate step? Lean toward "generated as outline; operator fleshes out each task in a per-task chat with the AI from the project view, after push, not in the wizard." Keeps the wizard tight at 4 steps.
- **What happens to Plans 03-08?** Same project-view "Continue to next plan" pattern, or a different surface? Probably the same — but each plan's complexity grows, so the AI assistance scales with it.
- **When does the local working directory get created?** Wizard's Step 4 (Materialize) writes to `~/Documents/projects/<name>/` by default. Operator can override the path; daemon needs filesystem access there. For headless / containerized HydraFlow deployments, the directory lives in a configured `HYDRAFLOW_WORKSPACE_DIR`.
- **What if the operator wants to bootstrap from an existing local directory?** (e.g. an empty repo they've already `git init`'d.) Probably a Step 0 "Use existing directory" toggle in the wizard, defaulting to "Create new directory at default path." Defer until someone asks.

---

## Quick reference — bootstrap a HydraFlow-format repo today (manual, pre-wizard)

Until the UI lands, here is the manual procedure that produced amplifier + harvestd:

1. Brainstorm + write design spec via the `superpowers:brainstorming` skill
2. Write `Plan 01 (Bootstrap)` task-by-task via `superpowers:writing-plans` skill
   - Use harvestd's Plan 01 as a starting template; remove decimal-purity + UI tasks if not needed
3. Execute Plan 01 via `superpowers:subagent-driven-development` skill
   - Tasks 1-13: local scaffolding (pyproject, Makefile, smoke, README, CLAUDE.md, standards copy, ADR, scripts, decimal-purity if any, UI if any, CI workflow, run make quality green)
   - Task 14: `gh repo create <name> --private --source=. --remote=origin --push` + `staging` branch
   - Task 15: `setup_branch_protection.py --apply`
   - Task 16: `prep.py --create-labels`
   - Task 17: final verification + handoff summary
4. Write Plan 02 + ROADMAP for the remaining 5-7 plans
5. File 12-15 GitHub issues for Plan 02 tasks with `gh issue create --label hydraflow-find`
6. RC promote staging → main via `gh pr create --base main --head staging --title "rc/..." && gh pr merge --merge`
7. Register the new repo with HydraFlow (separate operator action)

Plan-01 task count target: 15-17 depending on UI yes/no + safety guards. Domain plan 02 task count: 12-15.

This procedure is what the wizard will absorb. When Phase 2 lands, this section gets a "Deprecated" note pointing to the "+ New project…" entry in the HydraFlow dashboard's repo picker.

---

## Acknowledgments

This methodology synthesizes lessons from two bootstraps:

- `amplifier` — `https://github.com/T-rav/amplifier` (private)
- `harvestd` — `https://github.com/T-rav/harvestd` (private)

The detailed research log informing this doc is preserved in the conversation that produced both repos.
