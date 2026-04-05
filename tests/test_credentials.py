"""Tests for the Credentials model and build_credentials() factory."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config import Credentials, build_credentials
from tests.helpers import ConfigFactory, CredentialsFactory


class TestCredentialsModel:
    """Credentials model field defaults and immutability."""

    def test_defaults_are_empty_strings(self) -> None:
        creds = Credentials()
        assert creds.gh_token == ""
        assert creds.hindsight_url == ""
        assert creds.hindsight_api_key == ""
        assert creds.sentry_auth_token == ""
        assert creds.whatsapp_token == ""
        assert creds.whatsapp_phone_id == ""
        assert creds.whatsapp_recipient == ""
        assert creds.whatsapp_verify_token == ""

    def test_frozen_rejects_mutation(self) -> None:
        creds = Credentials(gh_token="tok")
        with pytest.raises(ValidationError):
            creds.gh_token = "other"  # type: ignore[misc]

    def test_explicit_values_stored(self) -> None:
        creds = Credentials(
            gh_token="gh-tok",
            hindsight_url="http://h",
            sentry_auth_token="sntryu_x",
        )
        assert creds.gh_token == "gh-tok"
        assert creds.hindsight_url == "http://h"
        assert creds.sentry_auth_token == "sntryu_x"


class TestCredentialsFactory:
    """CredentialsFactory test helper produces valid instances."""

    def test_factory_defaults(self) -> None:
        creds = CredentialsFactory.create()
        assert isinstance(creds, Credentials)
        assert creds.gh_token == ""

    def test_factory_overrides(self) -> None:
        creds = CredentialsFactory.create(gh_token="tok", hindsight_url="http://x")
        assert creds.gh_token == "tok"
        assert creds.hindsight_url == "http://x"


class TestBuildCredentials:
    """build_credentials() resolves tokens from env vars."""

    _CLEARED_ENV = {
        "HYDRAFLOW_GH_TOKEN": "",
        "GH_TOKEN": "",
        "GITHUB_TOKEN": "",
        "HYDRAFLOW_HINDSIGHT_URL": "",
        "HYDRAFLOW_HINDSIGHT_API_KEY": "",
        "SENTRY_AUTH_TOKEN": "",
        "HYDRAFLOW_WHATSAPP_TOKEN": "",
        "HYDRAFLOW_WHATSAPP_PHONE_ID": "",
        "HYDRAFLOW_WHATSAPP_RECIPIENT": "",
        "HYDRAFLOW_WHATSAPP_VERIFY_TOKEN": "",
    }

    def test_gh_token_priority_hydraflow(self, tmp_path: Path) -> None:
        """HYDRAFLOW_GH_TOKEN wins over GH_TOKEN and GITHUB_TOKEN."""
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "HYDRAFLOW_GH_TOKEN": "hf", "GH_TOKEN": "gh"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == "hf"

    def test_gh_token_priority_gh_token(self, tmp_path: Path) -> None:
        """GH_TOKEN is used when HYDRAFLOW_GH_TOKEN is empty."""
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "GH_TOKEN": "gh"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == "gh"

    def test_gh_token_priority_github_token(self, tmp_path: Path) -> None:
        """GITHUB_TOKEN is used when higher-priority vars are empty."""
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "GITHUB_TOKEN": "gha"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == "gha"

    def test_gh_token_empty_when_no_env(self, tmp_path: Path) -> None:
        """gh_token is empty when no env vars set and no .env file."""
        config = ConfigFactory.create(repo_root=tmp_path)
        with patch.dict(os.environ, self._CLEARED_ENV, clear=False):
            creds = build_credentials(config)
        assert creds.gh_token == ""

    def test_reads_sentry_auth_token(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {**self._CLEARED_ENV, "SENTRY_AUTH_TOKEN": "sntryu_abc"}
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.sentry_auth_token == "sntryu_abc"

    def test_reads_hindsight_fields(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {
            **self._CLEARED_ENV,
            "HYDRAFLOW_HINDSIGHT_URL": "http://h",
            "HYDRAFLOW_HINDSIGHT_API_KEY": "key123",
        }
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.hindsight_url == "http://h"
        assert creds.hindsight_api_key == "key123"

    def test_reads_whatsapp_fields(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        env = {
            **self._CLEARED_ENV,
            "HYDRAFLOW_WHATSAPP_TOKEN": "wa-tok",
            "HYDRAFLOW_WHATSAPP_PHONE_ID": "12345",
            "HYDRAFLOW_WHATSAPP_RECIPIENT": "+1999",
            "HYDRAFLOW_WHATSAPP_VERIFY_TOKEN": "vfy",
        }
        with patch.dict(os.environ, env, clear=False):
            creds = build_credentials(config)
        assert creds.whatsapp_token == "wa-tok"
        assert creds.whatsapp_phone_id == "12345"
        assert creds.whatsapp_recipient == "+1999"
        assert creds.whatsapp_verify_token == "vfy"


class TestHydraFlowConfigExcludesCredentials:
    """HydraFlowConfig no longer carries credential fields."""

    def test_model_dump_has_no_credential_keys(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path)
        dumped = config.model_dump()
        credential_keys = {
            "gh_token",
            "hindsight_url",
            "hindsight_api_key",
            "sentry_auth_token",
            "whatsapp_token",
            "whatsapp_phone_id",
            "whatsapp_recipient",
            "whatsapp_verify_token",
        }
        leaked = credential_keys & set(dumped.keys())
        assert not leaked, f"Credential fields still on HydraFlowConfig: {leaked}"
