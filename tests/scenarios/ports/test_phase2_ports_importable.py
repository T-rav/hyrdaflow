"""Phase 2 port smoke test."""

from __future__ import annotations

import pytest

from tests.scenarios.ports import DockerPort, FSPort, GitPort, HTTPPort


@pytest.mark.parametrize("port", [DockerPort, FSPort, GitPort, HTTPPort])
def test_port_is_runtime_checkable(port: type) -> None:
    assert getattr(port, "_is_runtime_protocol", False), (
        f"{port.__name__} must be @runtime_checkable"
    )
