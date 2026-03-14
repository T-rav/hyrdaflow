"""HydraFlow server entry point."""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from config import HydraFlowConfig
from log import setup_logging
from runtime_config import DEFAULT_LOG_FILE, load_runtime_config


async def _run_with_dashboard(config: HydraFlowConfig) -> None:
    from dashboard import HydraFlowDashboard  # noqa: PLC0415
    from events import EventBus, EventLog, EventType, HydraFlowEvent  # noqa: PLC0415
    from models import Phase  # noqa: PLC0415
    from state import StateTracker  # noqa: PLC0415

    event_log = EventLog(config.event_log_path)
    bus = EventBus(event_log=event_log)
    await bus.rotate_log(
        config.event_log_max_size_mb * 1024 * 1024,
        config.event_log_retention_days,
    )
    await bus.load_history_from_disk()
    state = StateTracker(config.state_file)

    dashboard = HydraFlowDashboard(
        config=config,
        event_bus=bus,
        state=state,
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

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(runtime.stop()))

    await runtime.run()


async def _run(config: HydraFlowConfig) -> None:
    # NOTE: Tests patch _run_with_dashboard / _run_headless (private names)
    # because these are heavyweight server-starting functions that bind ports
    # and block forever.  Extracting them as injectable dependencies would be
    # over-engineering for a two-branch dispatch function.
    if config.dashboard_enabled:
        await _run_with_dashboard(config)
    else:
        await _run_headless(config)


def main() -> None:
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
