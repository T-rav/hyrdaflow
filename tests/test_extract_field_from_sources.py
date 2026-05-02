"""Tests for _extract_field_from_sources and _parse_compat_json_object helpers."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes._common import (
    _extract_field_from_sources,
    _parse_compat_json_object,
)
from dashboard_routes._routes import (
    _extract_repo_path,
    _extract_repo_slug,
)


class TestParseCompatJsonObject:
    def test_returns_none_for_none(self) -> None:
        assert _parse_compat_json_object(None) is None

    def test_returns_none_for_non_string(self) -> None:
        assert _parse_compat_json_object(42) is None  # type: ignore[arg-type]

    def test_returns_none_for_empty_string(self) -> None:
        assert _parse_compat_json_object("") is None

    def test_returns_none_for_whitespace(self) -> None:
        assert _parse_compat_json_object("   ") is None

    def test_returns_none_for_invalid_json(self) -> None:
        assert _parse_compat_json_object("{bad json") is None

    def test_returns_none_for_json_array(self) -> None:
        assert _parse_compat_json_object("[1, 2]") is None

    def test_returns_none_for_json_string(self) -> None:
        assert _parse_compat_json_object('"hello"') is None

    def test_returns_dict_for_valid_json_object(self) -> None:
        result = _parse_compat_json_object('{"key": "value"}')
        assert result == {"key": "value"}

    def test_strips_whitespace_before_parsing(self) -> None:
        result = _parse_compat_json_object('  {"k": 1}  ')
        assert result == {"k": 1}


class TestExtractFieldFromSources:
    # --- Basic extraction from query params ---

    def test_extracts_from_primary_query_param(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"), None, None, ("my-slug", None)
        )
        assert result == "my-slug"

    def test_extracts_from_alias_query_param(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"), None, None, (None, "my-repo")
        )
        assert result == "my-repo"

    # --- Basic extraction from body dict ---

    def test_extracts_from_body_primary_field(self) -> None:
        result = _extract_field_from_sources(
            ("path", "repo_path"), {"path": "/tmp/repo"}, None, (None, None)
        )
        assert result == "/tmp/repo"

    def test_extracts_from_body_alias_field(self) -> None:
        result = _extract_field_from_sources(
            ("path", "repo_path"), {"repo_path": "/tmp/repo"}, None, (None, None)
        )
        assert result == "/tmp/repo"

    def test_extracts_from_nested_req_in_body(self) -> None:
        body = {"req": {"slug": "nested-slug"}}
        result = _extract_field_from_sources(("slug", "repo"), body, None, (None, None))
        assert result == "nested-slug"

    # --- Extraction from JSON query string ---

    def test_extracts_from_json_query_string(self) -> None:
        query = json.dumps({"slug": "from-query"})
        result = _extract_field_from_sources(
            ("slug", "repo"), None, query, (None, None)
        )
        assert result == "from-query"

    def test_extracts_from_nested_req_in_json_query(self) -> None:
        query = json.dumps({"req": {"path": "/from/query"}})
        result = _extract_field_from_sources(
            ("path", "repo_path"), None, query, (None, None)
        )
        assert result == "/from/query"

    def test_raw_req_query_used_when_not_json(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"), None, "plain-string", (None, None)
        )
        assert result == "plain-string"

    # --- Priority / ordering with query_params_first=True (slug behavior) ---

    def test_query_params_first_prefers_query_over_body(self) -> None:
        body = {"slug": "from-body"}
        result = _extract_field_from_sources(
            ("slug", "repo"),
            body,
            None,
            ("from-query-param", None),
            query_params_first=True,
        )
        assert result == "from-query-param"

    def test_query_params_first_falls_back_to_body(self) -> None:
        body = {"slug": "from-body"}
        result = _extract_field_from_sources(
            ("slug", "repo"),
            body,
            None,
            (None, None),
            query_params_first=True,
        )
        assert result == "from-body"

    # --- Priority / ordering with query_params_first=False (path behavior) ---

    def test_body_first_prefers_body_over_query_params(self) -> None:
        body = {"path": "/from-body"}
        result = _extract_field_from_sources(
            ("path", "repo_path"),
            body,
            None,
            ("/from-query-param", None),
            query_params_first=False,
        )
        assert result == "/from-body"

    def test_body_first_falls_back_to_query_params(self) -> None:
        result = _extract_field_from_sources(
            ("path", "repo_path"),
            None,
            None,
            ("/from-query-param", None),
            query_params_first=False,
        )
        assert result == "/from-query-param"

    # --- Edge cases ---

    def test_returns_empty_string_when_no_sources(self) -> None:
        result = _extract_field_from_sources(("slug", "repo"), None, None, (None, None))
        assert result == ""

    def test_ignores_whitespace_only_values(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"), {"slug": "   "}, None, (None, None)
        )
        assert result == ""

    def test_strips_whitespace_from_values(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"), {"slug": "  trimmed  "}, None, (None, None)
        )
        assert result == "trimmed"

    def test_ignores_non_string_values(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"), {"slug": 42}, None, (None, None)
        )
        assert result == ""

    def test_ignores_non_dict_body(self) -> None:
        result = _extract_field_from_sources(
            ("slug", "repo"),
            "not-a-dict",
            None,
            (None, None),  # type: ignore[arg-type]
        )
        assert result == ""

    def test_ignores_non_dict_nested_req(self) -> None:
        body = {"req": "not-a-dict"}
        result = _extract_field_from_sources(("slug", "repo"), body, None, (None, None))
        assert result == ""

    def test_primary_field_preferred_over_alias_in_body(self) -> None:
        body = {"slug": "primary", "repo": "alias"}
        result = _extract_field_from_sources(("slug", "repo"), body, None, (None, None))
        assert result == "primary"

    def test_alias_field_resolved_from_nested_req(self) -> None:
        body = {"req": {"repo": "alias-in-nested"}}
        result = _extract_field_from_sources(("slug", "repo"), body, None, (None, None))
        assert result == "alias-in-nested"

    def test_body_wins_over_json_req_query_when_query_params_first(self) -> None:
        body = {"slug": "from-body"}
        query = json.dumps({"slug": "from-json"})
        result = _extract_field_from_sources(
            ("slug", "repo"),
            body,
            query,
            (None, None),
            query_params_first=True,
        )
        assert result == "from-body"


class TestExtractRepoSlug:
    def test_slug_from_query_param(self) -> None:
        assert _extract_repo_slug(None, None, "owner/repo", None) == "owner/repo"

    def test_slug_from_repo_query_param(self) -> None:
        assert _extract_repo_slug(None, None, None, "owner/repo") == "owner/repo"

    def test_slug_from_body(self) -> None:
        assert (
            _extract_repo_slug({"slug": "owner/repo"}, None, None, None) == "owner/repo"
        )

    def test_slug_from_body_repo_key(self) -> None:
        assert (
            _extract_repo_slug({"repo": "owner/repo"}, None, None, None) == "owner/repo"
        )

    def test_slug_from_nested_body(self) -> None:
        assert (
            _extract_repo_slug({"req": {"slug": "nested"}}, None, None, None)
            == "nested"
        )

    def test_slug_from_nested_body_repo_alias(self) -> None:
        assert (
            _extract_repo_slug({"req": {"repo": "nested-alias"}}, None, None, None)
            == "nested-alias"
        )

    def test_slug_body_wins_over_json_req_query(self) -> None:
        q = json.dumps({"slug": "from-json"})
        assert _extract_repo_slug({"slug": "from-body"}, q, None, None) == "from-body"

    def test_slug_from_json_query(self) -> None:
        q = json.dumps({"slug": "from-json"})
        assert _extract_repo_slug(None, q, None, None) == "from-json"

    def test_slug_query_param_wins_over_body(self) -> None:
        assert _extract_repo_slug({"slug": "body"}, None, "query", None) == "query"

    def test_slug_query_param_wins_over_json_req_query(self) -> None:
        q = json.dumps({"slug": "from-json"})
        assert _extract_repo_slug(None, q, "from-qp", None) == "from-qp"

    def test_raw_req_query_used_when_not_json(self) -> None:
        assert _extract_repo_slug(None, "plain-slug", None, None) == "plain-slug"

    def test_empty_when_nothing_provided(self) -> None:
        assert _extract_repo_slug(None, None, None, None) == ""


class TestExtractRepoPath:
    def test_path_from_body(self) -> None:
        assert _extract_repo_path({"path": "/tmp/r"}, None, None, None) == "/tmp/r"

    def test_path_from_body_repo_path_key(self) -> None:
        assert _extract_repo_path({"repo_path": "/tmp/r"}, None, None, None) == "/tmp/r"

    def test_path_from_nested_body(self) -> None:
        assert (
            _extract_repo_path({"req": {"path": "/nested"}}, None, None, None)
            == "/nested"
        )

    def test_path_from_nested_body_repo_path_alias(self) -> None:
        assert (
            _extract_repo_path(
                {"req": {"repo_path": "/nested-alias"}}, None, None, None
            )
            == "/nested-alias"
        )

    def test_path_from_json_query(self) -> None:
        q = json.dumps({"path": "/from-json"})
        assert _extract_repo_path(None, q, None, None) == "/from-json"

    def test_path_from_query_param(self) -> None:
        assert _extract_repo_path(None, None, "/from-qp", None) == "/from-qp"

    def test_body_wins_over_query_param(self) -> None:
        assert _extract_repo_path({"path": "/body"}, None, "/query", None) == "/body"

    def test_path_from_repo_path_query_param(self) -> None:
        assert (
            _extract_repo_path(None, None, None, "/from-alias-qp") == "/from-alias-qp"
        )

    def test_empty_when_nothing_provided(self) -> None:
        assert _extract_repo_path(None, None, None, None) == ""
