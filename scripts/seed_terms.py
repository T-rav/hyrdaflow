"""One-shot script to author the 9 seed term files for the ubiquitous-language slice.

Anchors verified against build_symbol_index. WorktreeManager deferred — no such
class exists in src/ at the time of authoring (workspace lifecycle is split
between src/workspace.py and src/bg_worker_manager.py). See commit message.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from ubiquitous_language import (  # noqa: E402
    BoundedContext,
    Term,
    TermKind,
    TermStore,
)

ROOT = Path(__file__).parent.parent
TERMS_DIR = ROOT / "docs" / "wiki" / "terms"

SEEDS: list[Term] = [
    Term(
        id="01KQV37D10M06PGF32CF77W6K2",
        name="HydraFlowConfig",
        kind=TermKind.AGGREGATE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "Pydantic-validated runtime configuration aggregate for the HydraFlow "
            "orchestrator. Bundles issue selection (ready labels, batch size, repo), "
            "per-phase concurrency caps (max_workers, max_planners, max_reviewers, "
            "max_triagers, max_hitl_workers), required-plugin manifests, language "
            "plugins, and per-phase skill whitelists into a single object passed to "
            "every loop and runner. Edited via the dashboard or config JSON file, "
            "not environment variables."
        ),
        invariants=[
            "Worker concurrency fields default to 1 and are bounded by ge=1, le=10 "
            "(max_hitl_workers le=5).",
            "batch_size is bounded ge=1, le=50.",
            "repo is auto-detected from the git remote when left empty.",
        ],
        code_anchor="src/config.py:HydraFlowConfig",
        aliases=["hydraflow config", "config aggregate", "orchestrator config"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K3",
        name="EventBus",
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "Async pub/sub bus that fans HydraFlowEvent objects out to subscriber "
            "asyncio.Queues, retains a bounded in-memory history for replay, and "
            "optionally persists every event through an EventLog. Auto-injects the "
            "active session_id and repo slug onto outbound events so downstream "
            "consumers always see a fully tagged event stream."
        ),
        invariants=[
            "History length is capped at max_history (default 5000); oldest entries "
            "are evicted when full.",
            "Slow subscribers do not block the publisher: a full subscriber queue "
            "drops its oldest entry before the new event is enqueued.",
            "History mutation is serialized through an asyncio.Lock.",
        ],
        code_anchor="src/events.py:EventBus",
        aliases=["event bus", "pub/sub bus", "hydraflow event bus"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K4",
        name="StateTracker",
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "JSON-file backed state service for crash recovery. Composes ~30 "
            "domain mixins (issue, workspace, HITL, review, route-back, epic, "
            "session, worker, principles audit, sentry, trust fleet, ...) into a "
            "single facade that writes <repo_root>/.hydraflow/state.json after "
            "every mutation and rotates timestamped backups so a corrupt primary "
            "file can be restored from .bak."
        ),
        invariants=[
            "Every mutating method persists state to disk before returning.",
            "Issue/PR/epic numbers are stored as string keys; helpers convert to "
            "int on read.",
            "On corrupt primary file, load() falls back to the most recent .bak "
            "before defaulting to an empty StateData.",
        ],
        code_anchor="src/state/__init__.py:StateTracker",
        aliases=["state tracker", "state facade", "state mixin facade"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K5",
        name="BaseBackgroundLoop",
        kind=TermKind.LOOP,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "Abstract base class for every concurrent worker loop in the "
            "HydraFlow orchestrator (ADR-0001, ADR-0029). Owns the run-loop "
            "skeleton — enabled-check, interval management, status callbacks, "
            "BACKGROUND_WORKER_STATUS event publishing, error reporting, and "
            "trigger-based early wake-up — leaving subclasses to implement only "
            "the domain-specific _do_work and _get_default_interval hooks."
        ),
        invariants=[
            "Subclasses must implement abstract methods _do_work and "
            "_get_default_interval.",
            "AuthenticationError, AuthenticationRetryError, and "
            "CreditExhaustedError propagate; all other exceptions are logged and "
            "the loop retries on the next cycle.",
            "Shared dependencies (event_bus, stop_event, status_cb, enabled_cb, "
            "sleep_fn, interval_cb) are bundled into a LoopDeps record passed to "
            "__init__.",
        ],
        code_anchor="src/base_background_loop.py:BaseBackgroundLoop",
        aliases=["base background loop", "background loop", "loop base class"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K6",
        name="RepoWikiStore",
        kind=TermKind.SERVICE,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "File-based per-repo wiki manager (ADR-0032). Owns the on-disk layout "
            "for both the self-repo wiki (flattened directly under wiki_root so it "
            "can live at docs/wiki/ alongside code) and managed-repo wikis "
            "(nested under wiki_root/owner/repo). Provides ingest, lookup, "
            "indexing, lint, and append-only operation logging across the topic "
            "pages and structured WikiIndex."
        ),
        invariants=[
            "Self-repo pages live directly under wiki_root; every other slug is "
            "nested under wiki_root/owner/repo.",
            "ingest() updates topic pages, refreshes index.json/index.md, and "
            "appends to log.jsonl in a single operation.",
            "When a tracked_root with per-entry layout is configured, reads "
            "prefer it and fall back to the legacy topic-page layout.",
        ],
        code_anchor="src/repo_wiki.py:RepoWikiStore",
        aliases=["repo wiki store", "wiki store", "per-repo wiki"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K7",
        name="PRPort",
        kind=TermKind.PORT,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "Hexagonal port for GitHub PR, label, and CI operations — branch "
            "push, PR creation/merge, RC-branch creation, and the related label "
            "manipulations consumed by domain phases and background loops. "
            "Implemented by pr_manager.PRManager; signatures are kept identical "
            "to the concrete class to enable structural subtype checks."
        ),
        invariants=[
            "Pure Protocol — no implementation, no state.",
            "Method signatures must match pr_manager.PRManager exactly so "
            "structural subtype checks in tests/test_ports.py pass.",
        ],
        code_anchor="src/ports.py:PRPort",
        aliases=["pr port", "pull request port", "github pr port"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K8",
        name="WorkspacePort",
        kind=TermKind.PORT,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "Hexagonal port for git workspace lifecycle operations — create and "
            "destroy isolated worktrees per issue, merge main into a worktree, "
            "list conflicting files, hard-reset to origin/main, abort an "
            "in-progress merge, and run post-work cleanup. Implemented by "
            "workspace.WorkspaceManager; the abstraction is what lets phases "
            "stay agnostic to the concrete worktree machinery."
        ),
        invariants=[
            "Pure Protocol — no implementation, no state.",
            "Each managed worktree is keyed by issue_number; create() returns "
            "the worktree path used for subsequent calls.",
        ],
        code_anchor="src/ports.py:WorkspacePort",
        aliases=["workspace port", "worktree port", "git workspace port"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6K9",
        name="IssueStorePort",
        kind=TermKind.PORT,
        bounded_context=BoundedContext.SHARED_KERNEL,
        definition=(
            "Hexagonal port for the in-memory issue work-queue — exposes only "
            "the queue accessors that domain code (phases, background loops, "
            "phase utilities) actually uses (get_triageable, get_plannable, "
            "get_implementable, get_reviewable, ...). Implemented by "
            "issue_store.IssueStore; orchestrator-only and dashboard-only "
            "methods stay on the concrete class to keep the domain surface "
            "narrow."
        ),
        invariants=[
            "Pure Protocol — no implementation, no state.",
            "Only domain-consumed methods are declared; orchestrator and "
            "dashboard methods deliberately stay off the port.",
        ],
        code_anchor="src/ports.py:IssueStorePort",
        aliases=["issue store port", "issue queue port", "work queue port"],
        confidence="accepted",
    ),
    Term(
        id="01KQV37D10M06PGF32CF77W6KA",
        name="AgentRunner",
        kind=TermKind.RUNNER,
        bounded_context=BoundedContext.BUILDER,
        definition=(
            "Subprocess runner for the implement phase: launches a `claude -p` "
            "process inside an isolated git worktree to implement a GitHub "
            "issue. Builds the agent's self-check checklist (extended by recent "
            "review escalations), spec-match guidance, and requirements-gap "
            "context, then commits the agent's changes locally. Pushing the "
            "branch and creating the PR are deliberately left to other phases."
        ),
        invariants=[
            "Phase name is fixed: _phase_name == 'implement'.",
            "The runner commits inside the worktree but never pushes or opens "
            "a PR — that work belongs to downstream phases.",
            "Self-check checklist is dynamically extended with checklist items "
            "from recurring review escalations.",
        ],
        code_anchor="src/agent.py:AgentRunner",
        aliases=["agent runner", "implement runner", "claude agent runner"],
        confidence="accepted",
    ),
]


def main() -> None:
    store = TermStore(TERMS_DIR)
    for term in SEEDS:
        path = store.write(term)
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
