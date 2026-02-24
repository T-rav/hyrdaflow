"""Entry point module for the `hf` console script."""

from __future__ import annotations

import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

from cli import main as hydraflow_main

from .init_cmd import run_init
from .supervisor_client import add_repo, list_repos, remove_repo
from .supervisor_manager import ensure_running

_FLAG_COMMANDS = {
    "prep": "--prep",
    "scaffold": "--scaffold",
    "audit": "--audit",
    "clean": "--clean",
    "dry-run": "--dry-run",
}


def _parse_repo_argument(
    rest: Sequence[str],
    *,
    require_path: bool,
    allow_slug: bool,
) -> tuple[Path | None, str | None]:
    if rest:
        candidate = Path(rest[0]).expanduser()
        if candidate.exists():
            return candidate.resolve(), None
        if require_path or not allow_slug:
            raise SystemExit(f"Path not found: {candidate}")
        return None, rest[0]
    if require_path:
        return Path.cwd(), None
    return Path.cwd(), None


def _dispatch_flag_command(flag: str, rest: Iterable[str]) -> None:
    hydraflow_main([flag, *rest])


def _handle_run(rest: Sequence[str]) -> None:
    ensure_running()
    repo_path, _ = _parse_repo_argument(rest, require_path=True, allow_slug=False)
    if repo_path is None:
        raise SystemExit("Repository path is required")
    try:
        info = add_repo(repo_path)
    except RuntimeError as exc:
        print(f"Failed to register repo {repo_path}: {exc}")
        print("Use `hf view` to inspect supervisor status or tail the log file above.")
        raise SystemExit(1) from exc
    url = info.get("dashboard_url")
    print(f"Registered repo {repo_path} with hf supervisor")
    if not info.get("started", True):
        print("  (already running)")
    if url:
        print(f"Dashboard: {url}")
    if info.get("log_file"):
        print(f"Logs: {info['log_file']}")


def _handle_view(rest: Sequence[str]) -> None:
    slug_filter = rest[0] if rest else None
    repos = list_repos()
    if not repos:
        print("No repos registered. Run `hf run` inside a repo first.")
        return
    if slug_filter:
        repos = [repo for repo in repos if repo.get("slug") == slug_filter]
        if not repos:
            print(f"No repo with slug '{slug_filter}' registered.")
            return
    print("Registered repos:")
    for repo in repos:
        path = repo.get("path")
        url = repo.get("dashboard_url")
        port = repo.get("port")
        slug = repo.get("slug")
        log_file = repo.get("log_file")
        running = repo.get("running", False)
        status = "RUNNING" if running else "STOPPED"
        line = f"- {path} [{status}]"
        if slug:
            line += f" slug={slug}"
        if port:
            line += f" port={port}"
        if url:
            line += f" -> {url}"
        print(line)
        if log_file:
            print(f"    logs: {log_file}")


def _handle_stop(rest: Sequence[str]) -> None:
    repo_path, slug = _parse_repo_argument(rest, require_path=False, allow_slug=True)
    try:
        remove_repo(repo_path, slug=slug)
        target = slug or repo_path
        print(f"Removed repo {target} from hf supervisor")
    except RuntimeError as exc:
        print(f"{exc}")


def entrypoint(argv: Sequence[str] | None = None) -> None:
    args = list(argv) if argv is not None else []
    if not args:
        hydraflow_main(None)
        return

    cmd, rest = args[0], args[1:]
    if cmd in ("-h", "--help"):
        hydraflow_main([cmd, *rest])
        return

    if cmd == "init":
        raise SystemExit(run_init(rest))

    command_map = {
        "view": lambda: _handle_view(rest),
        "status": lambda: _handle_view(rest),
        "stop": lambda: _handle_stop(rest),
        "run": lambda: _handle_run(rest),
        "start": lambda: hydraflow_main(rest),
    }
    if cmd in command_map:
        command_map[cmd]()
        return

    if cmd in _FLAG_COMMANDS:
        _dispatch_flag_command(_FLAG_COMMANDS[cmd], rest)
        return

    hydraflow_main(args)


if __name__ == "__main__":
    entrypoint(sys.argv[1:])
