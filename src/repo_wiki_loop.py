"""Background worker loop — repo wiki lint, compilation, and maintenance."""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from auto_pr import open_automated_pr_async
from base_background_loop import BaseBackgroundLoop, LoopDeps
from config import Credentials, HydraFlowConfig
from events import EventType, HydraFlowEvent
from knowledge_metrics import metrics as _metrics
from repo_wiki import DEFAULT_TOPICS, RepoWikiStore, WikiEntry, active_lint_tracked
from staleness import evaluate as evaluate_staleness
from subprocess_util import run_subprocess
from wiki_maint_queue import MaintenanceQueue

if TYPE_CHECKING:
    from events import EventBus
    from state import StateTracker
    from tribal_wiki import TribalWikiStore
    from wiki_compiler import WikiCompiler

logger = logging.getLogger("hydraflow.repo_wiki_loop")

# Terminal outcome types — issues with these outcomes are considered closed.
_TERMINAL_OUTCOMES = frozenset({"merged", "hitl_closed", "failed", "manual_close"})


@dataclass
class GeneralizationPassResult:
    promoted: int = 0
    considered_pairs: int = 0


async def run_generalization_pass(
    *,
    per_repo: RepoWikiStore,
    tribal: TribalWikiStore,
    compiler: WikiCompiler,
    event_bus: EventBus | None = None,
) -> GeneralizationPassResult:
    """Scan per-repo wikis, promote matching principles to tribal store.

    For each topic, gather current entries across all repos. For any
    cross-repo pair, ask the compiler to judge; if ``same_principle`` and
    ``confidence`` is high or medium, write to tribal and mark per-repo
    copies superseded. Publishes a ``TRIBAL_PROMOTION`` event per
    promotion when an ``event_bus`` is provided.

    Conservative by design: each pair only considered once; promotion is
    skipped if confidence is "low".
    """
    result = GeneralizationPassResult()
    now = datetime.now(UTC)

    for topic in DEFAULT_TOPICS:
        per_topic_entries: list[tuple[str, WikiEntry]] = []
        for repo in per_repo.list_repos():
            topic_path = per_repo.repo_dir(repo) / f"{topic}.md"
            if not topic_path.exists():
                continue
            for e in per_repo.load_topic_entries(topic_path):
                if evaluate_staleness(e, now=now) == "current":
                    per_topic_entries.append((repo, e))

        # Consider cross-repo pairs only. Avoid re-judging the same pair.
        seen_pair_ids: set[tuple[str, str]] = set()
        for i, (repo_a, ent_a) in enumerate(per_topic_entries):
            for repo_b, ent_b in per_topic_entries[i + 1 :]:
                if repo_a == repo_b:
                    continue
                pair_key = tuple(sorted((ent_a.id, ent_b.id)))
                if pair_key in seen_pair_ids:
                    continue
                seen_pair_ids.add(pair_key)  # type: ignore[arg-type]
                result.considered_pairs += 1

                check = await compiler.generalize_pair(
                    entry_a=ent_a,
                    entry_b=ent_b,
                    topic=topic,
                )
                if not check.same_principle or check.confidence == "low":
                    continue

                tribal_entry = WikiEntry(
                    title=check.generalized_title,
                    content=check.generalized_body,
                    source_type="librarian",
                    topic=topic,
                    source_repo="global",
                    confidence=check.confidence,
                )
                tribal.ingest([tribal_entry])
                for repo_x, ent_x in ((repo_a, ent_a), (repo_b, ent_b)):
                    per_repo.mark_superseded(
                        repo_x,
                        entry_id=ent_x.id,
                        superseded_by=tribal_entry.id,
                        reason="promoted to tribal wiki",
                    )
                result.promoted += 1
                _metrics.increment("tribal_promotions")

                if event_bus is not None:
                    event = HydraFlowEvent(
                        type=EventType.TRIBAL_PROMOTION,
                        data={
                            "repo_a": repo_a,
                            "repo_b": repo_b,
                            "tribal_id": tribal_entry.id,
                            "topic": topic,
                        },
                    )
                    try:
                        await event_bus.publish(event)
                    except Exception:  # noqa: BLE001
                        logger.debug("tribal promotion event publish failed")
    return result


class RepoWikiLoop(BaseBackgroundLoop):
    """Periodically lints and compiles all per-repo wikis.

    Each cycle:
    1. **Active lint** — marks stale entries for closed issues, prunes
       old stale entries, rebuilds index.
    2. **Compile** — if a WikiCompiler is available, runs LLM synthesis
       on any topic with 5+ entries to deduplicate and cross-reference.
    """

    def __init__(
        self,
        config: HydraFlowConfig,
        wiki_store: RepoWikiStore,
        deps: LoopDeps,
        wiki_compiler: WikiCompiler | None = None,
        state: StateTracker | None = None,
        credentials: Credentials | None = None,
        maintenance_queue: MaintenanceQueue | None = None,
        tribal_store: TribalWikiStore | None = None,
    ) -> None:
        super().__init__(worker_name="repo_wiki", config=config, deps=deps)
        self._wiki_store = wiki_store
        self._wiki_compiler = wiki_compiler
        self._state = state
        self._credentials = credentials
        self._tribal_store = tribal_store
        # Queue lives under the gitignored data path — single-host only
        # in Phase 4 (multi-host coordination is an open question in the
        # design doc).  ``maintenance_queue`` is injectable so tests can
        # swap in a tmp-path queue without touching real state.
        self._queue = maintenance_queue or MaintenanceQueue(
            path=Path(config.data_path("wiki_maint_queue.json"))
        )
        # Tracks the currently-open maintenance PR so subsequent ticks
        # can coalesce (append commits to the same branch) when
        # ``repo_wiki_maintenance_pr_coalesce`` is True.
        self._open_pr_branch: str | None = None
        self._open_pr_url: str | None = None

    def _get_default_interval(self) -> int:
        return self._config.repo_wiki_interval

    def _get_closed_issues(self) -> set[int]:
        """Derive closed issue numbers from StateTracker outcomes."""
        if self._state is None:
            return set()
        outcomes = self._state.get_all_outcomes()
        return {int(k) for k, v in outcomes.items() if v.outcome in _TERMINAL_OUTCOMES}

    async def _do_work(self) -> dict[str, Any] | None:
        # Drain console-triggered admin tasks up front — admin actions
        # may target repos the store does not yet see (e.g. rebuild-index
        # of a freshly migrated repo), so draining before the list_repos
        # early-return keeps them from piling up in the queue.
        drained = self._queue.drain()
        if drained:
            logger.info(
                "Wiki maintenance queue drained %d tasks: %s",
                len(drained),
                [t.kind for t in drained],
            )

        repos = self._wiki_store.list_repos()

        # Phase 7: when git-backed is on, lint the tracked per-entry
        # layout under ``config.repo_root / config.repo_wiki_path``.  In
        # that mode the store's ``active_lint`` still runs against the
        # legacy gitignored layout — harmless read — but stale-flag
        # writes only land on the tracked layout so they surface as
        # uncommitted diffs for the maintenance PR.  Compute
        # ``tracked_root`` and merge tracked repos in BEFORE the
        # no-repos early-return — a freshly migrated repo may only
        # exist in the tracked location.
        tracked_root: Path | None = None
        if self._config.repo_wiki_git_backed:
            tracked_root = (
                Path(self._config.repo_root) / self._config.repo_wiki_path
            ).resolve()
            for slug in _list_tracked_repos(tracked_root):
                if slug not in repos:
                    repos.append(slug)

        if not repos:
            return {
                "repos": 0,
                "total_entries": 0,
                "queue_drained": len(drained),
            }

        closed_issues = self._get_closed_issues()

        total_stale = 0
        total_orphans = 0
        total_entries = 0
        total_marked_stale = 0
        total_pruned = 0
        total_compiled = 0
        empty_topics: list[str] = []

        for slug in repos:
            # Phase 1: Active lint — self-healing pass
            result = self._wiki_store.active_lint(slug, closed_issues=closed_issues)
            total_stale += result.stale_entries
            total_orphans += result.orphan_entries
            total_entries += result.total_entries
            total_marked_stale += result.entries_marked_stale
            total_pruned += result.orphans_pruned
            empty_topics.extend(f"{slug}:{t}" for t in result.empty_topics)

            if tracked_root is not None:
                tracked = await asyncio.to_thread(
                    active_lint_tracked,
                    tracked_root,
                    slug,
                    closed_issues,
                )
                # Tracked stats are additive — they observe a different
                # set of files (per-entry markdown vs. legacy topic
                # pages) so summing avoids double-counting of the same
                # actions.
                total_stale += tracked.stale_entries
                total_entries += tracked.total_entries
                total_marked_stale += tracked.entries_marked_stale
                total_pruned += tracked.orphans_pruned

            # Phase 2: LLM compilation — synthesize topics with many entries
            if self._wiki_compiler is not None:
                for topic in DEFAULT_TOPICS:
                    topic_path = self._wiki_store._repo_dir(slug) / f"{topic}.md"
                    entries = self._wiki_store._load_topic_entries(topic_path)
                    # Compile at 5+ entries (not 2) to avoid burning LLM
                    # calls on small topics where synthesis adds little value.
                    if len(entries) >= 5:
                        try:
                            after = await self._wiki_compiler.compile_topic(
                                self._wiki_store, slug, topic
                            )
                            if after < len(entries):
                                total_compiled += len(entries) - after
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "Wiki compile failed for %s/%s",
                                slug,
                                topic,
                                exc_info=True,
                            )

                # Phase 8: tracked-layout compilation — produces
                # ``source_phase: synthesis`` per-entry files and marks
                # their sources ``superseded`` under
                # ``{repo_root}/{repo_wiki_path}/{slug}/{topic}/``.  When
                # the layout has ≥ 5 active entries, LLM synthesis runs
                # and its diffs surface in the next maintenance PR.
                if tracked_root is not None:
                    for topic in DEFAULT_TOPICS:
                        topic_dir = tracked_root / slug / topic
                        active_count = sum(
                            1 for _ in _iter_tracked_active_files(topic_dir)
                        )
                        if active_count < 5:
                            continue
                        try:
                            synthesized = (
                                await self._wiki_compiler.compile_topic_tracked(
                                    tracked_root, slug, topic
                                )
                            )
                            # Report the post-synthesis count — matches the
                            # legacy ``compile_topic`` semantic and keeps
                            # ``total_compiled`` comparable across legacy
                            # and tracked ticks.  Using ``active_count``
                            # here (pre-synthesis) would inflate the stat
                            # roughly 5-10× because synthesis typically
                            # collapses many entries into one or two.
                            if synthesized:
                                total_compiled += synthesized
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "Wiki compile_tracked failed for %s/%s",
                                slug,
                                topic,
                                exc_info=True,
                            )

        stats = {
            "repos": len(repos),
            "total_entries": total_entries,
            "stale_entries": total_stale,
            "orphan_entries": total_orphans,
            "entries_marked_stale": total_marked_stale,
            "entries_pruned": total_pruned,
            "entries_compiled": total_compiled,
            "empty_topics": len(empty_topics),
        }

        if total_marked_stale or total_pruned or total_compiled:
            logger.info(
                "Wiki maintenance: %d marked stale, %d pruned, %d compiled across %d repos",
                total_marked_stale,
                total_pruned,
                total_compiled,
                len(repos),
            )

        # Record the up-front queue drain, poll any open maintenance PR
        # for CI-green → review + merge, then attempt to open a new one
        # if the tracked layout has changes.  The open-then-poll order
        # lets a single tick do both: merge the last cycle's PR (if
        # ready) and emit this cycle's PR.  Phase 4 does not yet teach
        # ``active_lint`` / ``compile_topic`` to write into
        # ``repo_root / repo_wiki/`` — those edits still land on the
        # legacy gitignored store — so the open path stays dormant
        # until Phase 5 ports them.
        stats["queue_drained"] = len(drained)
        await self._poll_and_merge_open_pr(stats)
        await self._maybe_open_maintenance_pr(stats)

        tribal_store = getattr(self, "_tribal_store", None)
        if tribal_store is not None and self._wiki_compiler is not None:
            try:
                await run_generalization_pass(
                    per_repo=self._wiki_store,
                    tribal=tribal_store,
                    compiler=self._wiki_compiler,
                    event_bus=getattr(self, "_bus", None),
                )
            except Exception:  # noqa: BLE001
                logger.warning("generalization pass failed", exc_info=True)

        return stats

    async def _maybe_open_maintenance_pr(self, stats: dict[str, Any]) -> None:
        """Open or coalesce a maintenance PR if the tracked wiki layout
        has uncommitted changes.

        Silently no-ops when:
        - credentials are absent (no ``gh_token`` to push with)
        - ``git status --porcelain {repo_wiki_path}`` is empty (no diffs)
        - the repo root is not a git repo (defensive)
        """
        if self._credentials is None or not self._credentials.gh_token:
            logger.debug("Wiki maintenance PR skipped: no gh_token available")
            return

        repo_root = Path(self._config.repo_root).resolve()
        if not (repo_root / ".git").exists():
            logger.debug("Wiki maintenance PR skipped: %s is not a git repo", repo_root)
            return

        path_prefix = self._config.repo_wiki_path
        try:
            diff_files = await asyncio.to_thread(
                _porcelain_paths, repo_root, path_prefix
            )
        except subprocess.CalledProcessError as exc:
            logger.warning(
                "Wiki maintenance git status failed (stderr=%s)",
                exc.stderr,
            )
            return

        if not diff_files:
            return

        if (
            self._open_pr_branch is not None
            and self._config.repo_wiki_maintenance_pr_coalesce
        ):
            logger.info(
                "Wiki maintenance PR %s is already open; Phase 5 will append",
                self._open_pr_url,
            )
            stats["maintenance_pr"] = self._open_pr_url
            return

        timestamp = datetime.now(UTC).strftime("%Y%m%d%H%M%S")
        branch = f"hydraflow/wiki-maint-{timestamp}"
        today = datetime.now(UTC).date().isoformat()
        title = f"chore(wiki): maintenance {today}"
        body = _maintenance_pr_body(stats, diff_files)

        result = await open_automated_pr_async(
            repo_root=repo_root,
            branch=branch,
            files=[repo_root / p for p in diff_files],
            pr_title=title,
            pr_body=body,
            base=self._config.base_branch(),
            # Auto-merge is disabled — the loop polls CI on subsequent
            # ticks and calls ``gh pr review --approve`` + ``gh pr merge``
            # itself once CI is green.  The label is how operators (and
            # future factory loops) identify these PRs.
            auto_merge=False,
            labels=["hydraflow-wiki-maintenance"],
            gh_token=self._credentials.gh_token,
            raise_on_failure=False,
            commit_author_name=self._config.git_user_name,
            commit_author_email=self._config.git_user_email,
        )

        if result.status == "opened":
            self._open_pr_branch = branch
            self._open_pr_url = result.pr_url
            stats["maintenance_pr"] = result.pr_url
            logger.info(
                "Wiki maintenance PR opened: %s (%d files)",
                result.pr_url,
                len(diff_files),
            )
        elif result.status == "failed":
            logger.warning(
                "Wiki maintenance PR failed for %s: %s",
                branch,
                result.error,
            )

    async def _poll_and_merge_open_pr(  # noqa: PLR0911 — linear state-machine guards
        self, stats: dict[str, Any]
    ) -> None:
        """Review + merge the currently-open maintenance PR when CI is green.

        Runs every tick.  No-op when no PR is being tracked.  State
        transitions handled:

        - Remote state ``MERGED`` / ``CLOSED`` → clear tracked state
          and record the outcome on ``stats``.
        - Remote state ``OPEN``, CI green, not yet approved →
          ``gh pr review --approve`` with an automation comment.
        - Remote state ``OPEN``, CI green, already approved →
          ``gh pr merge --squash``, then clear tracked state.
        - Remote state ``OPEN``, CI pending / red → log and leave
          for a future tick (red CI surfaces on the PR for humans).

        Always fail-soft so a transient ``gh`` error doesn't crash
        the loop or strand the PR's tracked state — the next tick
        re-polls.
        """
        if self._open_pr_url is None or self._credentials is None:
            return
        gh_token = self._credentials.gh_token
        if not gh_token:
            return

        pr_url = self._open_pr_url
        try:
            view_stdout = await run_subprocess(
                "gh",
                "pr",
                "view",
                pr_url,
                "--json",
                "state,reviewDecision,statusCheckRollup",
                gh_token=gh_token,
            )
            view = json.loads(view_stdout)
        except (RuntimeError, json.JSONDecodeError) as exc:
            logger.warning("Wiki maintenance PR poll failed for %s: %s", pr_url, exc)
            return

        state = str(view.get("state", "")).upper()
        if state in {"MERGED", "CLOSED"}:
            logger.info(
                "Wiki maintenance PR %s is %s; clearing tracked state",
                pr_url,
                state,
            )
            self._open_pr_url = None
            self._open_pr_branch = None
            stats["maintenance_pr_state"] = state
            return

        ci_state = _ci_rollup_state(view.get("statusCheckRollup") or [])
        stats["maintenance_pr_ci"] = ci_state

        if ci_state != "success":
            logger.debug(
                "Wiki maintenance PR %s CI=%s — skipping review/merge",
                pr_url,
                ci_state,
            )
            return

        review_decision = str(view.get("reviewDecision") or "").upper()
        if review_decision != "APPROVED":
            try:
                await run_subprocess(
                    "gh",
                    "pr",
                    "review",
                    pr_url,
                    "--approve",
                    "-b",
                    "Automated approval — RepoWikiLoop wrote these maintenance "
                    "edits and CI is green.",
                    gh_token=gh_token,
                )
                logger.info("Wiki maintenance PR %s approved", pr_url)
            except RuntimeError as exc:
                logger.warning(
                    "Wiki maintenance PR approve failed for %s: %s", pr_url, exc
                )
                return

        try:
            await run_subprocess(
                "gh",
                "pr",
                "merge",
                pr_url,
                "--squash",
                gh_token=gh_token,
            )
        except RuntimeError as exc:
            logger.warning("Wiki maintenance PR merge failed for %s: %s", pr_url, exc)
            return

        logger.info("Wiki maintenance PR %s merged", pr_url)
        self._open_pr_url = None
        self._open_pr_branch = None
        stats["maintenance_pr_state"] = "MERGED"


def _list_tracked_repos(tracked_root: Path) -> list[str]:
    """Return ``owner/repo`` slugs found directly under the tracked wiki
    root, or an empty list when the root does not exist yet.

    Mirrors ``RepoWikiStore.list_repos``' ``index.md`` / ``index.json``
    gate so the tracked-layout enumeration and the legacy-layout
    enumeration agree on what counts as a wiki-bearing repo.
    """
    if not tracked_root.is_dir():
        return []
    slugs: list[str] = []
    for owner_dir in sorted(tracked_root.iterdir()):
        if not owner_dir.is_dir():
            continue
        for repo_dir in sorted(owner_dir.iterdir()):
            if not repo_dir.is_dir():
                continue
            if (repo_dir / "index.md").exists() or (repo_dir / "index.json").exists():
                slugs.append(f"{owner_dir.name}/{repo_dir.name}")
    return slugs


def _iter_tracked_active_files(topic_dir: Path):
    """Yield per-entry file paths whose frontmatter ``status`` is
    ``active``.  Used to count active entries before deciding to run
    ``compile_topic_tracked`` — LLM calls are expensive, so we cap the
    work at topics with a meaningful backlog.
    """
    if not topic_dir.is_dir():
        return
    for path in topic_dir.glob("*.md"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if not text.startswith("---\n"):
            continue
        try:
            end = text.index("\n---\n", 4)
        except ValueError:
            continue
        block = text[4:end]
        status = "active"
        for line in block.splitlines():
            if line.startswith("status:"):
                status = line.split(":", 1)[1].strip() or "active"
                break
        if status == "active":
            yield path


def _ci_rollup_state(rollup: list[dict[str, Any]]) -> str:
    """Collapse ``gh pr view --json statusCheckRollup`` into a single state.

    - ``success`` — every check succeeded
    - ``failure`` — at least one failed / errored / action-required
    - ``pending`` — otherwise (queued, in-progress, or empty)
    """
    if not rollup:
        return "pending"
    statuses: list[str] = []
    for check in rollup:
        conclusion = check.get("conclusion") or check.get("state") or ""
        statuses.append(str(conclusion).lower())
    if any(s in {"failure", "error", "action_required", "cancelled"} for s in statuses):
        return "failure"
    if all(s in {"success", "neutral", "skipped"} for s in statuses):
        return "success"
    return "pending"


def _porcelain_paths(repo_root: Path, path_prefix: str) -> list[str]:
    """Return relative paths under ``path_prefix`` with uncommitted changes.

    Runs ``git status --porcelain`` scoped to ``path_prefix`` and parses
    each entry.  Renamed entries take the destination path.  Empty
    result means nothing to commit.
    """
    proc = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "status",
            "--porcelain",
            "--",
            path_prefix,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        # Porcelain format: XY<space>path  (rename is XY<space>oldpath -> newpath)
        payload = line[3:]
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        paths.append(payload.strip().strip('"'))
    return paths


def _maintenance_pr_body(stats: dict[str, Any], diff_files: list[str]) -> str:
    """Render the PR body with a short action summary + changed files."""
    lines = [
        "Automated wiki maintenance PR opened by `RepoWikiLoop`.",
        "",
        "## Actions",
        "",
        f"- {stats.get('entries_marked_stale', 0)} entries marked stale",
        f"- {stats.get('entries_pruned', 0)} entries pruned",
        f"- {stats.get('entries_compiled', 0)} entries compiled / synthesized",
        f"- {stats.get('queue_drained', 0)} console-triggered tasks drained",
        "",
        "## Files changed",
        "",
    ]
    lines.extend(f"- `{p}`" for p in sorted(diff_files))
    lines.append("")
    lines.append(
        "Auto-merge is enabled when CI is green; if CI fails, the PR "
        "stays open and subsequent ticks will append commits instead of "
        "opening a new PR."
    )
    return "\n".join(lines)
