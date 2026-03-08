"""Repo store utilities — config cloning for multi-repo setups.

Centralizes the logic for deriving a per-repo ``HydraFlowConfig`` from a
base/template config.  All callers (CLI auto-register, dashboard add-repo,
``load_saved``) should use :func:`clone_config_for_repo` to avoid
duplicating config-derivation logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import HydraFlowConfig


def clone_config_for_repo(
    base_config: HydraFlowConfig,
    *,
    repo: str,
    repo_root: Path,
) -> HydraFlowConfig:
    """Create a per-repo config by overriding repo identity fields.

    Copies *base_config* and replaces ``repo`` and ``repo_root`` while
    keeping all other settings (worker counts, models, poll intervals,
    etc.) from the base.  Path fields that are derived from ``repo_root``
    (like ``state_file``, ``event_log_path``) are re-resolved by the
    config model's validators.
    """
    from config import HydraFlowConfig  # noqa: PLC0415

    # Use model_copy to produce a shallow clone, then override identity fields.
    # We pass through the validator by reconstructing so derived paths resolve.
    base_dict = base_config.model_dump()
    base_dict["repo"] = repo
    base_dict["repo_root"] = repo_root
    # Let the model re-derive path fields from the new repo_root.
    # Remove derived paths so validators recompute them.
    for key in ("state_file", "event_log_path", "config_file"):
        base_dict.pop(key, None)
    return HydraFlowConfig(**base_dict)
