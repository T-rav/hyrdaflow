"""Dashboard route handlers — package wrapper.

This package replaces the former ``dashboard_routes.py`` flat module.
All public (and test-accessed) symbols are re-exported here so that
existing ``from dashboard_routes import X`` statements continue to work.
"""

from __future__ import annotations

# Re-export shared constants and helpers from _common
from dashboard_routes._common import (
    _EPIC_INTERNAL_LABELS,
    _FRONTEND_STAGE_TO_LABEL_FIELD,
    _HISTORY_STATUSES,
    _INFERENCE_COUNTER_KEYS,
    _INTERVAL_BOUNDS,
    _SAFE_SLUG_COMPONENT,
    _STAGE_NAME_MAP,
    _coerce_history_status,
    _coerce_int,
    _extract_field_from_sources,
    _is_timestamp_in_range,
    _parse_compat_json_object,
    _parse_iso_or_none,
    _status_rank,
    _status_sort_key,
)

# Re-export route-level symbols from _routes
from dashboard_routes._routes import (
    _DONE_STATUS_MAP,
    _STATUS_DRIVEN_TYPES,
    RouteContext,
    _extract_issue_number,
    _extract_repo_path,
    _extract_repo_slug,
    _is_likely_disconnect,
    _log_ws_error,
    _normalise_event_status,
    _parse_metrics_lines,
    _replay_ws_history,
    _validate_repo_request_types,
    create_router,
)

__all__ = [
    # _common
    "_EPIC_INTERNAL_LABELS",
    "_FRONTEND_STAGE_TO_LABEL_FIELD",
    "_HISTORY_STATUSES",
    "_INFERENCE_COUNTER_KEYS",
    "_INTERVAL_BOUNDS",
    "_SAFE_SLUG_COMPONENT",
    "_STAGE_NAME_MAP",
    "_coerce_history_status",
    "_coerce_int",
    "_extract_field_from_sources",
    "_is_timestamp_in_range",
    "_parse_compat_json_object",
    "_parse_iso_or_none",
    "_status_rank",
    "_status_sort_key",
    # _routes
    "_DONE_STATUS_MAP",
    "_STATUS_DRIVEN_TYPES",
    "RouteContext",
    "_extract_issue_number",
    "_extract_repo_path",
    "_extract_repo_slug",
    "_is_likely_disconnect",
    "_log_ws_error",
    "_normalise_event_status",
    "_parse_metrics_lines",
    "_replay_ws_history",
    "_validate_repo_request_types",
    "create_router",
]
