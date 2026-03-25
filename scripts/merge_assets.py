"""Namespace-aware asset merge for HydraFlow.

Merges HydraFlow's hf.* / hf-* namespaced assets into a target repo
alongside existing user files, instead of rm -rf-ing everything.

Tracks installed files in .hydraflow/assets.json so subsequent runs
can clean up stale files before installing new ones.
"""

from __future__ import annotations

import argparse
import json
import shutil
import stat
from datetime import UTC, datetime
from pathlib import Path

CHAIN_START = "# --- HydraFlow hook chain (do not edit) ---"
CHAIN_END = "# --- End HydraFlow hook chain ---"

HOOK_NAMES = ("pre-commit", "pre-push")

SETTINGS_FILES = ("settings.json", "settings.local.json")


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def load_manifest(path: Path) -> dict:
    """Return manifest dict from JSON file, or empty manifest if missing."""
    if path.exists():
        return json.loads(path.read_text())
    return {"files": []}


def save_manifest(path: Path, files: list[str]) -> None:
    """Write manifest with version, timestamp, and sorted file list."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "installed_at": datetime.now(UTC).isoformat(),
        "files": sorted(files),
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# File copying
# ---------------------------------------------------------------------------


def copy_namespaced_files(
    source_dir: Path, target_dir: Path, subdir: str, prefix: str
) -> list[str]:
    """Copy files (or dirs for .codex/skills/) matching *prefix* into target.

    Returns list of relative paths like '.claude/commands/hf.adr.md'.
    """
    src = source_dir / subdir
    if not src.is_dir():
        return []

    dst = target_dir / subdir
    dst.mkdir(parents=True, exist_ok=True)
    installed = []

    is_dir_copy = subdir == ".codex/skills"

    for entry in sorted(src.iterdir()):
        if not entry.name.startswith(prefix):
            continue

        target_entry = dst / entry.name
        rel = f"{subdir}/{entry.name}"

        if is_dir_copy and entry.is_dir():
            if target_entry.exists():
                shutil.rmtree(target_entry)
            shutil.copytree(entry, target_entry)
            installed.append(rel)
        elif entry.is_file():
            shutil.copy2(entry, target_entry)
            installed.append(rel)

    return installed


# ---------------------------------------------------------------------------
# Git hook chaining
# ---------------------------------------------------------------------------


def _chain_block(hook_name: str) -> str:
    """Return the chain block for a given hook name."""
    return (
        f"{CHAIN_START}\n"
        f'if [ -x "$(dirname "$0")/hf-{hook_name}" ]; then\n'
        f'  "$(dirname "$0")/hf-{hook_name}" || exit $?\n'
        f"fi\n"
        f"{CHAIN_END}"
    )


def _make_executable(path: Path) -> None:
    """Add executable bits to a file."""
    st = path.stat()
    path.chmod(st.st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def chain_hooks(source_hooks_dir: Path, target_hooks_dir: Path) -> list[str]:
    """Chain HydraFlow hooks into existing hooks via marker blocks.

    Returns list of relative paths created/modified.
    """
    if not source_hooks_dir.is_dir():
        return []

    target_hooks_dir.mkdir(parents=True, exist_ok=True)
    installed = []

    for hook_file in sorted(source_hooks_dir.iterdir()):
        if not hook_file.is_file():
            continue
        name = hook_file.name

        # Copy as hf-{name}
        hf_dest = target_hooks_dir / f"hf-{name}"
        shutil.copy2(hook_file, hf_dest)
        _make_executable(hf_dest)
        installed.append(f".githooks/hf-{name}")

        target_hook = target_hooks_dir / name
        block = _chain_block(name)

        if not target_hook.exists():
            # Create a dispatcher script
            dispatcher = f"#!/bin/bash\n{block}\n"
            target_hook.write_text(dispatcher)
            _make_executable(target_hook)
            installed.append(f".githooks/{name}")
        else:
            content = target_hook.read_text()
            if CHAIN_START in content:
                # Replace existing block (idempotent)
                start = content.index(CHAIN_START)
                end = content.index(CHAIN_END) + len(CHAIN_END)
                # Consume trailing newline if present
                if end < len(content) and content[end] == "\n":
                    end += 1
                content = content[:start] + block + "\n" + content[end:]
            else:
                # Append chain block
                if not content.endswith("\n"):
                    content += "\n"
                content += block + "\n"
            target_hook.write_text(content)
            _make_executable(target_hook)
            installed.append(f".githooks/{name}")

    return installed


# ---------------------------------------------------------------------------
# Settings merge
# ---------------------------------------------------------------------------


def _is_hf_entry(matcher_entry: dict) -> bool:
    """Check if a matcher entry contains any HydraFlow-tagged hooks."""
    return any(hook.get("_hydraflow") for hook in matcher_entry.get("hooks", []))


def _has_hf_hooks(hook_list: list) -> bool:
    """Check if any hook in the list is HydraFlow-tagged."""
    return any(h.get("_hydraflow") for h in hook_list)


def merge_settings_file(source_path: Path, target_path: Path) -> None:
    """Deep-merge HydraFlow-tagged entries into existing Claude settings."""
    if not source_path.exists():
        return

    source = json.loads(source_path.read_text())

    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(source, indent=2) + "\n")
        return

    target = json.loads(target_path.read_text())

    # Merge hooks
    src_hooks = source.get("hooks", {})
    tgt_hooks = target.setdefault("hooks", {})

    for category, src_entries in src_hooks.items():
        tgt_entries = tgt_hooks.setdefault(category, [])

        # Build a map of source HF entries by matcher
        src_by_matcher = {}
        for entry in src_entries:
            if _is_hf_entry(entry):
                matcher = entry["matcher"]
                src_by_matcher.setdefault(matcher, []).extend(
                    h for h in entry["hooks"] if h.get("_hydraflow")
                )

        # For each matcher in source, merge into target
        for matcher, src_hf_hooks in src_by_matcher.items():
            # Find existing target entry for this matcher
            tgt_entry = None
            for e in tgt_entries:
                if e["matcher"] == matcher:
                    tgt_entry = e
                    break

            if tgt_entry is None:
                # No existing entry — add a new one with HF hooks only
                tgt_entries.append({"matcher": matcher, "hooks": list(src_hf_hooks)})
            else:
                # Remove old HF hooks, then append new ones
                tgt_entry["hooks"] = [
                    h for h in tgt_entry["hooks"] if not h.get("_hydraflow")
                ] + list(src_hf_hooks)

        # Also add any source entries for matchers not in src_by_matcher
        # (non-HF entries from source are not merged — only HF-tagged ones)

    # Merge permissions
    src_perms = source.get("permissions", {})
    tgt_perms = target.setdefault("permissions", {})
    for key in ("allow", "deny"):
        if key in src_perms:
            existing = set(tgt_perms.get(key, []))
            merged = list(tgt_perms.get(key, []))
            for pattern in src_perms[key]:
                if pattern not in existing:
                    merged.append(pattern)
            tgt_perms[key] = merged

    target_path.write_text(json.dumps(target, indent=2) + "\n")


def _remove_hf_entries_from_settings(settings_path: Path) -> None:
    """Remove HydraFlow-tagged entries from a settings file."""
    if not settings_path.exists():
        return

    data = json.loads(settings_path.read_text())
    modified = False

    hooks = data.get("hooks", {})
    for category in list(hooks.keys()):
        entries = hooks[category]
        new_entries = []
        for entry in entries:
            # Remove HF hooks from each entry
            new_hooks = [h for h in entry.get("hooks", []) if not h.get("_hydraflow")]
            if new_hooks:
                entry["hooks"] = new_hooks
                new_entries.append(entry)
            elif not _is_hf_entry(entry):
                new_entries.append(entry)
            else:
                modified = True
        if new_entries != entries:
            modified = True
        hooks[category] = new_entries

    if modified:
        data["hooks"] = hooks
        settings_path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def merge_assets(source: Path, target: Path) -> None:
    """Full namespace-aware merge of HydraFlow assets into target repo."""
    manifest_path = target / ".hydraflow" / "assets.json"
    old_manifest = load_manifest(manifest_path)

    # Remove previously installed files
    for rel in old_manifest["files"]:
        old_file = target / rel
        if old_file.is_dir():
            shutil.rmtree(old_file)
        elif old_file.is_file():
            old_file.unlink()

    # Copy namespaced files
    installed = []
    installed.extend(copy_namespaced_files(source, target, ".claude/commands", "hf."))
    installed.extend(copy_namespaced_files(source, target, ".claude/hooks", "hf."))
    installed.extend(copy_namespaced_files(source, target, ".claude/agents", "hf."))
    installed.extend(copy_namespaced_files(source, target, ".codex/skills", "hf."))
    installed.extend(copy_namespaced_files(source, target, ".pi/skills", "hf-"))

    # Chain hooks
    source_hooks = source / ".githooks"
    target_hooks = target / ".githooks"
    installed.extend(chain_hooks(source_hooks, target_hooks))

    # Merge settings files
    for settings_name in SETTINGS_FILES:
        src_settings = source / ".claude" / settings_name
        tgt_settings = target / ".claude" / settings_name
        if src_settings.exists():
            merge_settings_file(src_settings, tgt_settings)

    # Save updated manifest
    save_manifest(manifest_path, installed)


def clean_assets(target: Path) -> None:
    """Remove all HydraFlow-managed assets from target repo."""
    manifest_path = target / ".hydraflow" / "assets.json"
    manifest = load_manifest(manifest_path)

    # Remove all tracked files
    for rel in manifest["files"]:
        full = target / rel
        if full.is_dir():
            shutil.rmtree(full)
        elif full.is_file():
            full.unlink()

        # Clean up empty parent directories
        parent = full.parent
        while parent != target:
            try:
                if parent.is_dir() and not any(parent.iterdir()):
                    parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    # Remove HF entries from settings files
    for settings_name in SETTINGS_FILES:
        _remove_hf_entries_from_settings(target / ".claude" / settings_name)

    # Remove hook chain blocks
    for hook_name in HOOK_NAMES:
        hook_path = target / ".githooks" / hook_name
        if not hook_path.exists():
            continue
        content = hook_path.read_text()
        if CHAIN_START in content:
            start = content.index(CHAIN_START)
            end = content.index(CHAIN_END) + len(CHAIN_END)
            if end < len(content) and content[end] == "\n":
                end += 1
            content = content[:start] + content[end:]
            if content.strip():
                hook_path.write_text(content)
            else:
                hook_path.unlink()

    # Remove the manifest itself
    if manifest_path.exists():
        manifest_path.unlink()
        # Clean up .hydraflow dir if empty
        hf_dir = manifest_path.parent
        try:
            if hf_dir.is_dir() and not any(hf_dir.iterdir()):
                hf_dir.rmdir()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Namespace-aware asset merge for HydraFlow"
    )
    parser.add_argument("--source", type=Path, help="HydraFlow project root")
    parser.add_argument("--target", type=Path, required=True, help="Target repo root")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Remove HydraFlow assets instead of merging",
    )
    args = parser.parse_args()

    if args.clean:
        clean_assets(args.target)
    else:
        if not args.source:
            parser.error("--source is required when not using --clean")
        merge_assets(args.source, args.target)


if __name__ == "__main__":
    main()
