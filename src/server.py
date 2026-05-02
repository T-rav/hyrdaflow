"""HydraFlow server entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from pathlib import Path

from config import HydraFlowConfig, build_credentials
from log import setup_logging
from runtime_config import DEFAULT_LOG_FILE, load_runtime_config

logger = logging.getLogger("hydraflow.server")


def _init_sentry() -> None:
    """Initialize Sentry SDK if SENTRY_DSN is configured."""
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return

    import re  # noqa: PLC0415

    import sentry_sdk  # noqa: PLC0415
    from sentry_sdk.integrations.fastapi import FastApiIntegration  # noqa: PLC0415
    from sentry_sdk.integrations.logging import LoggingIntegration  # noqa: PLC0415

    _SENSITIVE_RE = re.compile(
        r"(ghp_[a-zA-Z0-9]{36}|gho_[a-zA-Z0-9]{36}|github_pat_[a-zA-Z0-9_]{82}|"
        r"sk-[a-zA-Z0-9]{48}|Bearer\s+[a-zA-Z0-9._-]+)",
        re.IGNORECASE,
    )

    def _scrub(obj):
        if isinstance(obj, str):
            return _SENSITIVE_RE.sub("[REDACTED]", obj)
        if isinstance(obj, dict):
            return {k: _scrub(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [_scrub(v) for v in obj]
        return obj

    # Exception types that indicate real code bugs (not transient infra errors)
    _BUG_TYPES = (
        TypeError,
        KeyError,
        AttributeError,
        ValueError,
        IndexError,
        NotImplementedError,
    )

    def _before_send(event, hint):  # type: ignore[no-untyped-def]
        """Drop transient errors, fingerprint bugs, scrub credentials."""
        exc_info = hint.get("exc_info")
        if exc_info:
            exc_type = exc_info[0]
            if exc_type and not issubclass(exc_type, _BUG_TYPES):
                return None  # Drop transient errors (network, auth, Docker, etc.)
            # Fingerprint by exception type + module to collapse duplicates
            exc_name = exc_type.__name__ if exc_type else "Unknown"
            module = getattr(exc_info[1], "__module__", "") or ""
            event["fingerprint"] = [exc_name, module]

        # Check log-record events (from LoggingIntegration)
        log_record = hint.get("log_record")
        if log_record and not exc_info:
            record_exc = getattr(log_record, "exc_info", None)
            if (
                record_exc
                and record_exc[0]
                and not issubclass(record_exc[0], _BUG_TYPES)
            ):
                return None  # Drop transient errors logged via logger.exception()

        return _scrub(event)

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("HYDRAFLOW_ENV", "development"),
        traces_sample_rate=float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        profiles_sample_rate=float(
            os.environ.get("SENTRY_PROFILES_SAMPLE_RATE", "0.0")
        ),
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
            LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
        ],
        before_send=_before_send,  # type: ignore[arg-type]
        before_send_transaction=lambda event, hint: _scrub(event),  # type: ignore[arg-type]
    )


def _detect_submodule_parent(hydraflow_root: Path) -> Path | None:
    """Return the parent repo path if HydraFlow is a git submodule, else None."""
    git_path = hydraflow_root / ".git"
    if not git_path.is_file():
        return None  # .git is a directory — standalone repo, not a submodule
    parent = hydraflow_root.parent
    if (parent / ".git").exists():
        return parent
    return None


async def _detect_remote_slug(repo_path: Path) -> str | None:
    """Detect GitHub slug (owner/repo) from git remote origin URL."""
    try:
        import re  # noqa: PLC0415

        from subprocess_util import run_subprocess  # noqa: PLC0415

        url = await run_subprocess("git", "remote", "get-url", "origin", cwd=repo_path)
        url = url.strip()
        # Parse: https://github.com/owner/repo.git or git@github.com:owner/repo.git
        match = re.search(r"[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        return match.group(1) if match else None
    except (RuntimeError, OSError):
        return None


async def _run_with_dashboard(config: HydraFlowConfig) -> None:
    from dashboard import HydraFlowDashboard  # noqa: PLC0415
    from events import EventBus, EventLog, EventType, HydraFlowEvent  # noqa: PLC0415
    from models import Phase  # noqa: PLC0415
    from repo_runtime import RepoRuntimeRegistry  # noqa: PLC0415
    from repo_store import RepoRecord, RepoRegistryStore  # noqa: PLC0415
    from service_registry import build_state_tracker  # noqa: PLC0415

    event_log = EventLog(config.event_log_path)
    bus = EventBus(event_log=event_log)
    await bus.rotate_log(
        config.event_log_max_size_mb * 1024 * 1024,
        config.event_log_retention_days,
    )
    await bus.load_history_from_disk()
    state = build_state_tracker(config)

    repo_store = RepoRegistryStore(config.data_root)
    registry = RepoRuntimeRegistry()

    # Restore previously registered repos into the runtime registry.
    # The repo store persists to disk, but the registry is in-memory —
    # without this, added repos are lost on restart and their play
    # buttons return 404.
    for record in repo_store.list():
        if not record.path:
            continue
        repo_path = Path(record.path)
        if not repo_path.is_dir():
            logger.warning(
                "Skipping stored repo %s — path %s not found", record.slug, record.path
            )
            continue
        try:
            repo_cfg = load_runtime_config(
                overrides={
                    "repo_root": str(repo_path),
                    **({"repo": record.repo} if record.repo else {}),
                }
            )
            await registry.register(repo_cfg)
            logger.info("Restored registered repo %r from store", record.slug)
        except Exception:
            logger.warning("Failed to restore repo %s", record.slug, exc_info=True)

    # Auto-register parent repo when running as a git submodule
    hydraflow_root = Path(__file__).resolve().parent.parent
    submodule_parent = _detect_submodule_parent(hydraflow_root)
    if submodule_parent is not None:
        try:
            parent_slug = await _detect_remote_slug(submodule_parent)
            if parent_slug and parent_slug not in registry:
                repo_cfg = load_runtime_config(
                    overrides={
                        "repo_root": str(submodule_parent),
                        "repo": parent_slug,
                    }
                )
                await registry.register(repo_cfg)
                repo_store.upsert(
                    RepoRecord(
                        slug=parent_slug, repo=parent_slug, path=str(submodule_parent)
                    )
                )
                logger.info(
                    "Auto-registered parent repo %s (submodule detected)", parent_slug
                )
        except Exception:
            logger.debug("Submodule auto-registration failed", exc_info=True)

    async def _register_repo(
        repo_path: Path, slug: str | None
    ) -> tuple[RepoRecord, HydraFlowConfig]:
        from runtime_config import load_runtime_config  # noqa: PLC0415

        repo_cfg = load_runtime_config(
            overrides={
                "repo_root": str(repo_path),
                **({"repo": slug} if slug else {}),
            }
        )
        # Use the GitHub slug (owner/repo) for the record, not the
        # filesystem-safe repo_slug (owner-repo).
        github_slug = slug or repo_cfg.repo
        record = repo_store.upsert(
            RepoRecord(
                slug=github_slug,
                repo=github_slug,
                path=str(repo_path),
            )
        )
        if record.slug not in registry:
            await registry.register(repo_cfg)
        return record, repo_cfg

    async def _remove_repo(slug: str) -> bool:
        rt = registry.remove(slug)
        if rt is not None:
            await rt.stop()
        return repo_store.remove(slug)

    credentials = build_credentials(config)

    dashboard = HydraFlowDashboard(
        config=config,
        event_bus=bus,
        state=state,
        registry=registry,
        repo_store=repo_store,
        register_repo_cb=_register_repo,
        remove_repo_cb=_remove_repo,
        list_repos_cb=repo_store.list,
        credentials=credentials,
    )
    await dashboard.start()

    await bus.publish(
        HydraFlowEvent(
            type=EventType.PHASE_CHANGE,
            data={"phase": Phase.IDLE.value},
        )
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    try:
        await stop_event.wait()
    finally:
        if dashboard._orchestrator and dashboard._orchestrator.running:
            await dashboard._orchestrator.stop()
        await dashboard.stop()


async def _run_headless(config: HydraFlowConfig) -> None:
    from repo_runtime import RepoRuntime  # noqa: PLC0415

    runtime = await RepoRuntime.create(config)

    # Strong refs + done-callback for shutdown tasks (#6513) so the GC can't
    # collect the Task before ``runtime.stop()`` completes and exceptions are
    # surfaced instead of silently swallowed by the event loop.
    shutdown_tasks: set[asyncio.Task[None]] = set()

    def _on_shutdown_done(t: asyncio.Task[None]) -> None:
        shutdown_tasks.discard(t)
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        if exc is not None:
            logger.warning("runtime.stop() task failed", exc_info=exc)

    def _schedule_stop() -> None:
        task = asyncio.create_task(runtime.stop())
        shutdown_tasks.add(task)
        task.add_done_callback(_on_shutdown_done)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _schedule_stop)

    await runtime.run()


async def _run_preflight(config: HydraFlowConfig) -> bool:
    """Run preflight checks; return True if startup should proceed."""
    from preflight import log_preflight_results, run_preflight_checks  # noqa: PLC0415

    if config.skip_preflight:
        logger.info("Preflight checks skipped (skip_preflight=True)")
        return True
    results = await run_preflight_checks(config)
    healthy = log_preflight_results(results)
    if not healthy:
        logger.error("Preflight checks failed — aborting startup")
    return healthy


async def _run(config: HydraFlowConfig) -> None:
    # NOTE: Tests patch _run_with_dashboard / _run_headless (private names)
    # because these are heavyweight server-starting functions that bind ports
    # and block forever.  Extracting them as injectable dependencies would be
    # over-engineering for a two-branch dispatch function.
    if not await _run_preflight(config):
        return
    if config.dashboard_enabled:
        await _run_with_dashboard(config)
    else:
        await _run_headless(config)


def main() -> None:
    from dotenv import load_dotenv  # noqa: PLC0415

    load_dotenv()

    # Initialize Sentry (no-op if SENTRY_DSN is empty/unset)
    _init_sentry()

    verbose = os.environ.get("HYDRAFLOW_VERBOSE_LOGS", "").strip() not in {
        "",
        "0",
        "false",
        "False",
    }
    log_path = os.environ.get("HYDRAFLOW_LOG_FILE", str(DEFAULT_LOG_FILE))
    level = logging.DEBUG if verbose else logging.INFO
    setup_logging(level=level, json_output=not verbose, log_file=log_path)

    config = load_runtime_config()
    logging.getLogger("hydraflow.server").info(
        "Starting HydraFlow server (dashboard=%s)", config.dashboard_enabled
    )
    asyncio.run(_run(config))


if __name__ == "__main__":
    main()
