"""Tests for dx/hydraflow/config.py — Env var overrides."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import get_args

import pytest

# conftest.py already inserts the hydraflow package directory into sys.path
from config import (
    _ENV_BOOL_OVERRIDES,
    _ENV_FLOAT_OVERRIDES,
    _ENV_INT_OVERRIDES,
    _ENV_LITERAL_OVERRIDES,
    _ENV_STR_OVERRIDES,
    HydraFlowConfig,
)

# ---------------------------------------------------------------------------
# Data-driven env-var override table validation
# ---------------------------------------------------------------------------


class TestEnvVarOverrideTable:
    """Tests for the _ENV_INT_OVERRIDES and _ENV_STR_OVERRIDES tables."""

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Each int override should apply when the field is at its default."""
        override_value = default + 1
        monkeypatch.setenv(env_key, str(override_value))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == override_value

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Explicit values should take precedence over env var overrides."""
        # Use default + 1 to stay within Pydantic field constraints
        explicit = default + 1
        monkeypatch.setenv(env_key, str(default + 2))
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == explicit

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_INT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_INT_OVERRIDES],
    )
    def test_env_int_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: int,
    ) -> None:
        """Non-numeric env var values should be silently ignored."""
        monkeypatch.setenv(env_key, "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == default

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_STR_OVERRIDES,
        ids=[entry[0] for entry in _ENV_STR_OVERRIDES],
    )
    def test_env_str_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: str,
    ) -> None:
        """Each str override should apply when the field is at its default."""
        monkeypatch.setenv(env_key, "custom-value")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        result = getattr(cfg, field)
        assert str(result) == "custom-value"

    # Valid non-default explicit values for Literal-typed string fields.
    # Generic tests can't use arbitrary strings for these fields.
    _EXPLICIT_VALUES: dict[str, str] = {
        "execution_mode": "docker",
    }

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_STR_OVERRIDES,
        ids=[entry[0] for entry in _ENV_STR_OVERRIDES],
    )
    def test_env_str_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: str,
    ) -> None:
        """Explicit values should take precedence over str env var overrides."""
        explicit = self._EXPLICIT_VALUES.get(field, "explicit-value")
        monkeypatch.setenv(env_key, "env-value")
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert str(getattr(cfg, field)) == explicit

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Each float override should apply when the field is at its default."""
        override_value = default + 1.0
        monkeypatch.setenv(env_key, str(override_value))
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(override_value)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Explicit values should take precedence over float env var overrides."""
        explicit = default + 0.5
        monkeypatch.setenv(env_key, str(default + 1.0))
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(explicit)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_FLOAT_OVERRIDES,
        ids=[entry[0] for entry in _ENV_FLOAT_OVERRIDES],
    )
    def test_env_float_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: float,
    ) -> None:
        """Non-numeric float env var values should be silently ignored."""
        monkeypatch.setenv(env_key, "not-a-number")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == pytest.approx(default)

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Each bool override should apply when the field is at its default."""
        monkeypatch.setenv(env_key, "false")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) is False

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_truthy_values(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Bool overrides should treat '1', 'true', 'yes' as True."""
        for truthy in ("1", "true", "yes", "True", "YES"):
            monkeypatch.setenv(env_key, truthy)
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
            assert getattr(cfg, field) is True, f"'{truthy}' should parse as True"

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_falsy_variants(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Bool overrides should treat '0', 'false', 'no' as False."""
        for falsy in ("0", "false", "no", "False", "NO"):
            monkeypatch.setenv(env_key, falsy)
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
            assert getattr(cfg, field) is False, f"'{falsy}' should parse as False"

    @pytest.mark.parametrize(
        ("field", "env_key", "default"),
        _ENV_BOOL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_BOOL_OVERRIDES],
    )
    def test_env_bool_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
        default: bool,
    ) -> None:
        """Explicit values should take precedence over bool env var overrides."""
        explicit = not default
        monkeypatch.setenv(
            env_key, str(default).lower()
        )  # env tries to revert to default
        cfg = HydraFlowConfig(
            **{field: explicit},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) is explicit

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_applies_when_at_default(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
    ) -> None:
        """Each Literal override should apply when the field is at its default."""
        allowed = get_args(HydraFlowConfig.model_fields[field].annotation)
        default = HydraFlowConfig.model_fields[field].default
        # Pick a non-default value from the allowed values
        non_default = next(v for v in allowed if v != default)
        monkeypatch.setenv(env_key, non_default)
        # execution_mode="docker" triggers _validate_docker which needs shutil.which
        if field == "execution_mode":
            import shutil

            monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == non_default

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_ignored_when_explicit_value_set(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        env_key: str,
    ) -> None:
        """Explicit values should take precedence over Literal env var overrides."""
        allowed = get_args(HydraFlowConfig.model_fields[field].annotation)
        default = HydraFlowConfig.model_fields[field].default
        non_default = next(v for v in allowed if v != default)
        # Pass non-default explicitly, set env var to default
        monkeypatch.setenv(env_key, default)
        # execution_mode="docker" triggers _validate_docker which needs shutil.which
        if field == "execution_mode":
            import shutil

            monkeypatch.setattr(shutil, "which", lambda _: "/usr/bin/docker")
        cfg = HydraFlowConfig(
            **{field: non_default},  # type: ignore[arg-type]
            repo_root=tmp_path,
            worktree_base=tmp_path / "wt",
            state_file=tmp_path / "s.json",
        )
        assert getattr(cfg, field) == non_default

    @pytest.mark.parametrize(
        ("field", "env_key"),
        _ENV_LITERAL_OVERRIDES,
        ids=[entry[0] for entry in _ENV_LITERAL_OVERRIDES],
    )
    def test_env_literal_override_invalid_value_ignored(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        field: str,
        env_key: str,
    ) -> None:
        """Invalid Literal env var values should be rejected and field stays at default."""
        default = HydraFlowConfig.model_fields[field].default
        monkeypatch.setenv(env_key, "bogus")
        with caplog.at_level(logging.WARNING, logger="hydraflow.config"):
            cfg = HydraFlowConfig(
                repo_root=tmp_path,
                worktree_base=tmp_path / "wt",
                state_file=tmp_path / "s.json",
            )
        assert getattr(cfg, field) == default
        assert env_key in caplog.text, "Expected warning to name the invalid env var"
        assert "bogus" in caplog.text, "Expected warning to include the invalid value"

    def test_override_table_field_names_are_valid(self) -> None:
        """Every field in the override tables should be a real HydraFlowConfig attribute."""
        all_fields = (
            {f for f, _, _ in _ENV_INT_OVERRIDES}
            | {f for f, _, _ in _ENV_STR_OVERRIDES}
            | {f for f, _, _ in _ENV_FLOAT_OVERRIDES}
            | {f for f, _, _ in _ENV_BOOL_OVERRIDES}
            | {f for f, _ in _ENV_LITERAL_OVERRIDES}
        )
        config_fields = set(HydraFlowConfig.model_fields.keys())
        invalid = all_fields - config_fields
        assert not invalid, f"Invalid field names in override tables: {invalid}"
        # Every field in _ENV_LITERAL_OVERRIDES must actually have a Literal annotation
        # so that get_args() returns allowed values instead of an empty tuple.
        for field, _ in _ENV_LITERAL_OVERRIDES:
            field_info = HydraFlowConfig.model_fields[field]
            args = get_args(field_info.annotation)
            assert args, (
                f"Field '{field}' in _ENV_LITERAL_OVERRIDES has no Literal args "
                f"(annotation={field_info.annotation!r}); "
                "all env var overrides for this field would be silently rejected"
            )
            # Every field must have at least one non-default allowed value so that
            # next(v for v in allowed if v != default) in the parametrized tests
            # never raises StopIteration.
            default = field_info.default
            non_defaults = [v for v in args if v != default]
            assert non_defaults, (
                f"Field '{field}' in _ENV_LITERAL_OVERRIDES has no non-default Literal "
                f"value (default={default!r}, allowed={args}); "
                "test_env_literal_override_applies_when_at_default would raise StopIteration"
            )

    def test_override_table_defaults_match_field_defaults(self) -> None:
        """Default values in the override tables must match HydraFlowConfig field defaults.

        This prevents silent drift when a field default is changed without updating
        the corresponding entry in _ENV_INT_OVERRIDES or _ENV_STR_OVERRIDES.
        """
        # Arrange
        model_fields = HydraFlowConfig.model_fields

        # Act / Assert — int overrides
        for field, _env_key, table_default in _ENV_INT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_INT_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )

        # Act / Assert — str overrides
        for field, _env_key, table_default in _ENV_STR_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert str(pydantic_default) == table_default, (
                f"_ENV_STR_OVERRIDES entry for '{field}' has default={table_default!r}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default!r}"
            )

        # Act / Assert — float overrides
        for field, _env_key, table_default in _ENV_FLOAT_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_FLOAT_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )

        # Act / Assert — bool overrides
        for field, _env_key, table_default in _ENV_BOOL_OVERRIDES:
            pydantic_default = model_fields[field].default
            assert pydantic_default == table_default, (
                f"_ENV_BOOL_OVERRIDES entry for '{field}' has default={table_default}, "
                f"but HydraFlowConfig.{field} default is {pydantic_default}"
            )
