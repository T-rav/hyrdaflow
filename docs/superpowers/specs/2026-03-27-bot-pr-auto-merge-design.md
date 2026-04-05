# Bot PR Auto-Merge — Design Spec

## Problem

Dependabot, Renovate, Snyk, and other bots create dependency update PRs that sit open until a human reviews and merges them. HydraFlow already has CI checking and merge infrastructure but no way to automatically handle bot-authored PRs. Teams want a "set it and forget it" toggle that auto-merges safe dependency updates.

## Solution

A new `bot_pr` background worker that discovers bot-authored PRs from the local GitHub cache, waits for CI, and either auto-merges or escalates based on user-configured settings. All configuration is done from the dashboard UI — no `.env` changes required.

## Architecture

### Approach: Standalone Background Loop

The bot PR worker is a standalone `BaseBackgroundLoop` subclass, same pattern as `pr_unsticker_loop.py` and `memory_sync_loop.py`. It does not touch the triage → plan → implement pipeline. Bot PRs have no associated issues — they enter at the PR level and either merge or escalate.

### Why Not Review Phase?

Bot PRs are fundamentally different from human PRs:
- No issue lifecycle (no triage, plan, implement)
- No worktree needed
- Simpler decision tree (CI green → merge)
- Different failure strategies (close PR is valid for bots, never for humans)

Coupling bot logic into `review_phase.py` (already 1800+ lines) would add complexity with no reuse benefit.

## Components

### 1. `src/bot_pr_loop.py` — Background Worker

Extends `BaseBackgroundLoop` with `worker_name="bot_pr"`.

**`_do_work()` cycle:**

1. Read open PRs from `GitHubDataCache.get_open_prs()` — zero API calls
2. Filter to PRs where `author` is in the enabled bot author list
3. Skip PRs already in `bot_pr_processed` state set
4. For each bot PR:
   - Check CI status via `PRManager.get_ci_status()`
   - If CI pending → skip, pick up next cycle
   - If CI green → apply review mode:
     - `ci_only` → approve + squash merge
     - `llm_review` → run `ReviewRunner` against repo root with PR diff context, merge if APPROVE, apply failure strategy if REQUEST_CHANGES
   - If CI red → apply failure strategy:
     - `skip` → leave PR open, do not track as processed (retry next cycle)
     - `hitl` → apply `hydraflow-hitl` label + post comment explaining CI failure
     - `close` → close PR with comment ("CI failed on dependency update, closing. The bot will recreate when a new version is available.")
5. Track processed PR numbers in state
6. Publish `BACKGROUND_WORKER_STATUS` event with cycle stats

**`_get_default_interval():`** Returns `config.bot_pr_interval` (default 3600s).

**LLM review mode:** When `review_mode == "llm_review"`, the worker calls `ReviewRunner` with the PR diff injected into the prompt. The reviewer runs against repo root (read-only, no worktree). If the reviewer returns APPROVE → merge. If REQUEST_CHANGES → apply the configured failure strategy.

### 2. `src/models.py` — PRListItem Author Field

Add `author: str = ""` to `PRListItem`. This is populated during the regular `GitHubCacheLoop` poll cycle, making bot PR discovery a pure local filter.

### 3. `src/github_cache_loop.py` — Enrich PR Fetch

Update the `gh pr list` query in the cache poll to include `author` in the JSON fields. Map `author.login` to `PRListItem.author`.

### 4. `src/config.py` — Config Fields

```
bot_pr_interval: int = 3600    (env: HYDRAFLOW_BOT_PR_INTERVAL)
bot_pr_enabled: bool = False   (env: HYDRAFLOW_BOT_PR_ENABLED)
```

Worker starts **disabled by default** — user opts in from the dashboard.

### 5. `src/state.py` — Persisted Settings

New state fields under `bot_pr_settings`:

```json
{
  "bot_pr_settings": {
    "authors": ["dependabot[bot]"],
    "failure_strategy": "skip",
    "review_mode": "ci_only"
  },
  "bot_pr_processed": [101, 102, 105]
}
```

- `authors` — list of enabled bot usernames. Default: `["dependabot[bot]"]`
- `failure_strategy` — one of `"skip"`, `"hitl"`, `"close"`. Default: `"skip"`
- `review_mode` — one of `"ci_only"`, `"llm_review"`. Default: `"ci_only"`
- `bot_pr_processed` — set of PR numbers already handled (prevents re-processing). A PR is added to this set when merged, closed, or escalated to HITL. PRs that are skipped (CI pending or `failure_strategy == "skip"` with CI red) are NOT added — they get retried next cycle.

### 6. `src/service_registry.py` — Wiring

Instantiate `BotPRLoop` in `build_services()` with dependencies:
- `config`
- `GitHubDataCache` (for `get_open_prs()`)
- `PRManager` (for CI check, approve, merge, close, comment)
- `ReviewRunner` (for LLM review mode)
- `StateTracker` (for settings and processed tracking)
- `LoopDeps` (standard background loop deps)

Add `bot_pr_loop: BotPRLoop` to `ServiceRegistry` dataclass.

### 7. `src/orchestrator.py` — Registration

Add to `bg_loop_registry`:
```python
"bot_pr": svc.bot_pr_loop,
```

Add to `loop_factories`:
```python
("bot_pr", self._svc.bot_pr_loop.run),
```

### 8. `src/dashboard_routes/_routes.py` — Settings API

**`GET /api/bot-pr/settings`**
Returns current bot PR settings from state.

**`POST /api/bot-pr/settings`**
Updates any combination of `authors`, `failure_strategy`, `review_mode`. Validates:
- `failure_strategy` must be one of `skip`, `hitl`, `close`
- `review_mode` must be one of `ci_only`, `llm_review`
- `authors` must be a non-empty list of strings

### 9. `src/ui/src/constants.js` — Dashboard Constants

Add to `BACKGROUND_WORKERS`:
```javascript
{
  key: 'bot_pr',
  label: 'Bot PR Manager',
  description: 'Auto-merges dependency update PRs from configured bots after CI passes.',
  color: theme.green
}
```

Add `'bot_pr'` to `EDITABLE_INTERVAL_WORKERS`.

Add presets:
```javascript
BOT_PR_PRESETS: [
  { label: '1 hour', value: 3600 },
  { label: '2 hours', value: 7200 },
  { label: '6 hours', value: 21600 },
  { label: '12 hours', value: 43200 },
  { label: '24 hours', value: 86400 },
]
```

Add to `SYSTEM_WORKER_INTERVALS`:
```javascript
bot_pr: 3600
```

### 10. Dashboard UI — Settings Panel

A collapsible settings section within the Bot PR Manager worker card (same pattern as `MemoryAutoApproveToggle` on the `memory_sync` card).

**Bot author checklist:**
- `dependabot[bot]` — checked by default
- `renovate[bot]` — unchecked
- `snyk-bot` — unchecked
- Text input to add custom bot usernames

**Failure strategy** — radio group:
- Skip (leave open, retry next cycle)
- Escalate to HITL
- Close PR

**Review mode** — radio group:
- CI Only (fast, no tokens)
- LLM Review (thorough, costs tokens)

Settings save instantly on change via `POST /api/bot-pr/settings` — no submit button.

### 11. Observability

**Events:**
- Standard `BACKGROUND_WORKER_STATUS` from `BaseBackgroundLoop` — cycle summary with `{processed, merged, skipped, escalated, closed}`

**Sentry breadcrumb:**
- `bot_pr.processed` — per PR: `{pr_number, author, action, review_mode}`

**Dashboard:**
- Worker card shows status dot, last run, and detail stats (processed/merged counts)
- Event log shows individual PR actions

## Data Flow

```
GitHubCacheLoop (existing, polls every ~60s)
    │
    ├─ Fetches open PRs with author field
    └─ Stores in GitHubDataCache (in-memory + disk)

BotPRLoop (new, polls every 1hr default)
    │
    ├─ Reads from GitHubDataCache.get_open_prs()  ← zero API calls
    ├─ Filters by enabled bot authors from state settings
    ├─ Skips already-processed PRs
    │
    └─ For each unprocessed bot PR:
        ├─ PRManager.get_ci_status()  ← 1 API call per PR
        │
        ├─ CI green + ci_only → PRManager.approve() + PRManager.merge_pr()
        ├─ CI green + llm_review → ReviewRunner → merge or failure strategy
        ├─ CI red + skip → do nothing
        ├─ CI red + hitl → PRManager.add_labels() + PRManager.post_comment()
        └─ CI red + close → PRManager.close_pr() + PRManager.post_comment()
```

## Testing Strategy

- **Unit tests:** `tests/test_bot_pr_loop.py` — mock `GitHubDataCache`, `PRManager`, `ReviewRunner`, `StateTracker`. Test each decision branch (CI green/red × failure strategy × review mode).
- **Settings API tests:** Mock state, verify GET/POST validation and persistence.
- **Dashboard tests:** Add to `constants.test.js` for new worker entry. Add to `SystemPanel.test.jsx` for settings panel rendering.
- **Integration:** Bot PR loop with real `GitHubDataCache` returning mock PR data, verify end-to-end flow.

## Files Changed

| File | Action | What |
|------|--------|------|
| `src/bot_pr_loop.py` | Create | New background loop |
| `src/models.py` | Modify | Add `author` to `PRListItem` |
| `src/github_cache_loop.py` | Modify | Include `author` in PR fetch |
| `src/config.py` | Modify | Add `bot_pr_interval`, `bot_pr_enabled` |
| `src/state.py` | Modify | Add `bot_pr_settings`, `bot_pr_processed` |
| `src/service_registry.py` | Modify | Wire `BotPRLoop` |
| `src/orchestrator.py` | Modify | Register in loop registry + factories |
| `src/dashboard_routes/_routes.py` | Modify | Add settings GET/POST endpoints |
| `src/ui/src/constants.js` | Modify | Add worker + presets |
| `src/ui/src/components/SystemPanel.jsx` | Modify | Add settings panel |
| `tests/test_bot_pr_loop.py` | Create | Unit tests |
| `tests/test_bot_pr_settings_api.py` | Create | API tests |

## Out of Scope

- Auto-rebasing bot PRs when they have merge conflicts
- Dependency vulnerability scoring (Dependabot already handles severity)
- Batch merging multiple bot PRs in a single cycle
- Custom merge strategies per bot (always squash merge)
