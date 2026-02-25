"""HydraFlow application version helpers."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

_PACKAGE_NAME = "hydraflow"
_FALLBACK_VERSION = "0.9.0+dev"


def get_app_version() -> str:
    """Return the installed HydraFlow package version."""
    try:
        return version(_PACKAGE_NAME)
    except PackageNotFoundError:
        return _FALLBACK_VERSION
