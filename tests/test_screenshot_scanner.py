"""Tests for the screenshot secret scanner."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from screenshot_scanner import scan_base64_for_secrets


class TestScanBase64ForSecrets:
    """Tests for scan_base64_for_secrets."""

    def test_clean_payload_returns_empty(self) -> None:
        """A payload with no secrets returns an empty list."""
        result = scan_base64_for_secrets("iVBORw0KGgoAAAANSUhEUgAA")
        assert result == []

    def test_github_pat_classic_detected(self) -> None:
        """A GitHub PAT (classic) pattern is detected."""
        payload = "some data ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl more data"
        result = scan_base64_for_secrets(payload)
        assert "GitHub PAT (classic)" in result

    def test_github_pat_fine_grained_detected(self) -> None:
        """A fine-grained GitHub PAT is detected."""
        payload = "github_pat_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnop more"
        result = scan_base64_for_secrets(payload)
        assert "GitHub PAT (fine-grained)" in result

    def test_aws_access_key_detected(self) -> None:
        """An AWS access key is detected."""
        payload = "AKIAIOSFODNN7EXAMPLE more"
        result = scan_base64_for_secrets(payload)
        assert "AWS access key" in result

    def test_slack_token_detected(self) -> None:
        """A Slack token is detected."""
        payload = "xoxb-123456789-abcdefghijk more"
        result = scan_base64_for_secrets(payload)
        assert "Slack token" in result

    def test_anthropic_api_key_detected(self) -> None:
        """An Anthropic API key is detected."""
        payload = "sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX more"
        result = scan_base64_for_secrets(payload)
        assert "Anthropic API key" in result

    def test_openai_api_key_detected(self) -> None:
        """An OpenAI API key is detected."""
        payload = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZabcd more"
        result = scan_base64_for_secrets(payload)
        assert "OpenAI API key" in result

    def test_private_key_header_detected(self) -> None:
        """A PEM private key header is detected."""
        payload = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIB more"
        result = scan_base64_for_secrets(payload)
        assert "Generic private key" in result

    def test_generic_secret_assignment_detected(self) -> None:
        """A generic secret assignment pattern is detected."""
        payload = 'secret: "my_super_secret_value"'
        result = scan_base64_for_secrets(payload)
        assert "Generic secret assignment" in result

    def test_multiple_secrets_returns_all(self) -> None:
        """Multiple different secret types in the same payload are all reported."""
        payload = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl AKIAIOSFODNN7EXAMPLE"
        result = scan_base64_for_secrets(payload)
        assert len(result) >= 2
        assert "GitHub PAT (classic)" in result
        assert "AWS access key" in result

    def test_empty_string_returns_empty(self) -> None:
        """An empty string returns an empty list."""
        result = scan_base64_for_secrets("")
        assert result == []

    def test_github_oauth_token_detected(self) -> None:
        """GitHub OAuth token pattern is detected."""
        payload = "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"
        result = scan_base64_for_secrets(payload)
        assert "GitHub OAuth token" in result

    def test_github_app_token_detected(self) -> None:
        """GitHub App user-to-server token is detected."""
        payload = "ghu_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"
        result = scan_base64_for_secrets(payload)
        assert "GitHub App token" in result

    def test_github_app_installation_token_detected(self) -> None:
        """GitHub App installation token is detected."""
        payload = "ghs_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"
        result = scan_base64_for_secrets(payload)
        assert "GitHub App installation" in result

    def test_github_refresh_token_detected(self) -> None:
        """GitHub refresh token is detected."""
        payload = "ghr_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijkl"
        result = scan_base64_for_secrets(payload)
        assert "GitHub refresh token" in result

    def test_openssh_private_key_detected(self) -> None:
        """An OpenSSH private key header is detected."""
        payload = "-----BEGIN OPENSSH PRIVATE KEY-----\nbase64data"
        result = scan_base64_for_secrets(payload)
        assert "Generic private key" in result

    def test_case_insensitive_secret_assignment(self) -> None:
        """Secret assignment detection is case-insensitive."""
        payload = 'PASSWORD="supersecretpassword1"'
        result = scan_base64_for_secrets(payload)
        assert "Generic secret assignment" in result
