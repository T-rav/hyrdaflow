"""RepoRuntime — per-repo lifecycle boundary for orchestrator + state + events.

Each ``RepoRuntime`` encapsulates the full mutable runtime for a single
repository: config, event bus, state tracker, and orchestrator.  The
``RepoRuntimeRegistry`` manages multiple runtimes by slug.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from config import HydraFlowConfig
from events import EventBus, EventLog
from orchestrator import HydraFlowOrchestrator
from state import StateTracker

logger = logging.getLogger("hydraflow.repo_runtime")


class RepoRuntime:
    """Isolated runtime boundary for a single repository.

    Owns the event bus, state tracker, and orchestrator.  Call
    :meth:`start` to begin the orchestrator loop and :meth:`stop` to
    shut it down gracefully.
    """

    def __init__(self, config: HydraFlowConfig) -> None:
        self._config = config
        self._slug = config.repo.replace("/", "-") or config.repo_root.name
        event_log = EventLog(config.event_log_path)
        self._event_bus = EventBus(event_log=event_log)
        self._state = StateTracker(config.state_file)
        self._orchestrator = HydraFlowOrchestrator(
            config,
            event_bus=self._event_bus,
            state=self._state,
        )
        self._task: asyncio.Task[None] | None = None

    @classmethod
    async def create(cls, config: HydraFlowConfig) -> RepoRuntime:
        """Construct a runtime and perform async initialization.

        Rotates the event log and loads persisted event history before
        returning the ready-to-start runtime.
        """
        runtime = cls(config)
        await runtime._event_bus.rotate_log(
            config.event_log_max_size_mb * 1024 * 1024,
            config.event_log_retention_days,
        )
        await runtime._event_bus.load_history_from_disk()
        return runtime

    # --- Properties ---

    @property
    def slug(self) -> str:
        """Repo slug derived from config (e.g. ``owner-repo``)."""
        return self._slug

    @property
    def config(self) -> HydraFlowConfig:
        return self._config

    @property
    def event_bus(self) -> EventBus:
        return self._event_bus

    @property
    def state(self) -> StateTracker:
        return self._state

    @property
    def orchestrator(self) -> HydraFlowOrchestrator:
        return self._orchestrator

    @property
    def running(self) -> bool:
        return self._orchestrator.running

    # --- Lifecycle ---

    async def start(self) -> None:
        """Start the orchestrator loop as a background task."""
        if self._task and not self._task.done():
            logger.warning("Runtime %r already running", self._slug)
            return
        logger.info("Starting runtime for %r", self._slug)
        self._task = asyncio.create_task(
            self._orchestrator.run(), name=f"runtime-{self._slug}"
        )

    async def run(self) -> None:
        """Run the orchestrator loop in the foreground (blocks until stopped)."""
        logger.info("Running runtime for %r", self._slug)
        await self._orchestrator.run()

    async def stop(self) -> None:
        """Stop the orchestrator and wait for the loop task to complete."""
        logger.info("Stopping runtime for %r", self._slug)
        await self._orchestrator.stop()
        if self._task and not self._task.done():
            try:
                await asyncio.wait_for(self._task, timeout=30)
            except (TimeoutError, asyncio.CancelledError):
                logger.warning("Runtime %r did not stop within timeout", self._slug)

    def __repr__(self) -> str:
        status = "running" if self.running else "stopped"
        return f"<RepoRuntime slug={self._slug!r} status={status}>"


class RepoRuntimeRegistry:
    """Manages multiple :class:`RepoRuntime` instances by slug.

    Provides lookup, lifecycle management, persistence, and graceful
    shutdown ordering.

    Parameters
    ----------
    data_root:
        Directory where ``repos.json`` is stored for persistence across
        restarts.  When ``None``, persistence is disabled (in-memory only).
    """

    def __init__(self, data_root: Path | None = None) -> None:
        self._runtimes: dict[str, RepoRuntime] = {}
        self._data_root = data_root

    @property
    def _repos_path(self) -> Path | None:
        """Path to the ``repos.json`` persistence file, or ``None``."""
        if self._data_root is None:
            return None
        return self._data_root / "repos.json"

    # --- Persistence ---

    def _save(self) -> None:
        """Persist the current set of registered repos to ``repos.json``."""
        path = self._repos_path
        if path is None:
            return
        entries = []
        for rt in self._runtimes.values():
            entries.append(
                {
                    "slug": rt.slug,
                    "repo": rt.config.repo,
                    "repo_root": str(rt.config.repo_root),
                }
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"repos": entries}, indent=2) + "\n")
        tmp.replace(path)
        logger.debug("Saved %d repo(s) to %s", len(entries), path)

    def _load(self) -> list[dict[str, str]]:
        """Load saved repo entries from ``repos.json``.

        Returns a list of dicts with ``slug``, ``repo``, and ``repo_root``
        keys.  Returns an empty list when the file is missing or malformed.
        """
        path = self._repos_path
        if path is None or not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return []
        if not isinstance(data, dict):
            logger.warning("Invalid repos.json format (expected object)")
            return []
        repos = data.get("repos")
        if not isinstance(repos, list):
            logger.warning("Invalid repos.json: missing 'repos' list")
            return []
        return [e for e in repos if isinstance(e, dict) and "repo_root" in e]

    async def load_saved(self) -> list[RepoRuntime]:
        """Re-register repos persisted in ``repos.json``.

        Skips entries whose ``repo_root`` no longer exists or that are
        already registered.  Returns the list of newly registered runtimes.
        """
        entries = self._load()
        registered: list[RepoRuntime] = []
        for entry in entries:
            repo_root = Path(entry["repo_root"])
            if not repo_root.is_dir():
                logger.warning(
                    "Skipping saved repo %s: directory %s not found",
                    entry.get("slug", "?"),
                    repo_root,
                )
                continue
            slug = entry.get("slug", "")
            if slug and slug in self._runtimes:
                logger.debug("Skipping already-registered repo %s", slug)
                continue
            try:
                cfg = HydraFlowConfig(
                    repo_root=repo_root,
                    repo=entry.get("repo", ""),
                )
                rt = await self.register(cfg)
                registered.append(rt)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "Failed to re-register saved repo %s",
                    entry.get("slug", "?"),
                    exc_info=True,
                )
        return registered

    # --- Registration ---

    async def register(self, config: HydraFlowConfig) -> RepoRuntime:
        """Create and register a runtime for the given config.

        Raises ``ValueError`` if a runtime with the same slug already exists.
        """
        runtime = await RepoRuntime.create(config)
        if runtime.slug in self._runtimes:
            msg = f"Runtime already registered for slug {runtime.slug!r}"
            raise ValueError(msg)
        self._runtimes[runtime.slug] = runtime
        logger.info("Registered runtime %r", runtime.slug)
        self._save()
        return runtime

    def get(self, slug: str) -> RepoRuntime | None:
        """Look up a runtime by slug."""
        return self._runtimes.get(slug)

    def remove(self, slug: str) -> RepoRuntime | None:
        """Remove and return a runtime (does not stop it)."""
        rt = self._runtimes.pop(slug, None)
        if rt is not None:
            self._save()
        return rt

    @property
    def slugs(self) -> list[str]:
        """Return all registered slug names."""
        return list(self._runtimes)

    @property
    def all(self) -> list[RepoRuntime]:
        """Return all registered runtimes."""
        return list(self._runtimes.values())

    async def start_all(self) -> None:
        """Start all registered runtimes as background tasks."""
        for runtime in self._runtimes.values():
            await runtime.start()

    async def stop_all(self) -> None:
        """Stop all registered runtimes gracefully."""
        tasks = [runtime.stop() for runtime in self._runtimes.values()]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def __len__(self) -> int:
        return len(self._runtimes)

    def __contains__(self, slug: str) -> bool:
        return slug in self._runtimes

    def __repr__(self) -> str:
        return f"<RepoRuntimeRegistry runtimes={len(self._runtimes)}>"
