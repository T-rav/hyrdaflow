"""Regression tests for the EC2 deploy helper script."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "deploy" / "ec2" / "deploy-hydraflow.sh"


def _run_install(env_overrides: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update(env_overrides)
    subprocess.run(
        ["bash", str(SCRIPT_PATH), "install"],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )


def test_install_action_copies_unit_into_custom_directory(tmp_path):
    """The install verb should copy the unit file into SYSTEMD_DIR."""
    systemd_dir = tmp_path / "systemd"
    _run_install({"SYSTEMD_DIR": str(systemd_dir)})

    unit_path = systemd_dir / "hydraflow.service"
    assert unit_path.exists(), "Expected hydraflow.service to be installed"
    contents = unit_path.read_text()
    assert "deploy/ec2/deploy-hydraflow.sh run" in contents


def test_install_action_invokes_systemctl_when_allowed(tmp_path):
    """When permitted, install should call systemctl enable/daemon-reload."""
    systemd_dir = tmp_path / "units"
    log_file = tmp_path / "systemctl.log"
    with tempfile.NamedTemporaryFile(
        "w",
        dir=REPO_ROOT,
        delete=False,
        prefix="fake-systemctl-",
    ) as fake_fd:
        fake_fd.write(
            '#!/usr/bin/env bash\nset -euo pipefail\necho "$*" >> "${SYSTEMCTL_LOG}"\n'
        )
        fake_path = Path(fake_fd.name)
    fake_path.chmod(0o755)

    try:
        _run_install(
            {
                "SYSTEMD_DIR": str(systemd_dir),
                "SERVICE_NAME": "hf-prod",
                "SYSTEMCTL_BIN": str(fake_path),
                "SYSTEMCTL_ALLOW_USER": "1",
                "SYSTEMCTL_LOG": str(log_file),
            }
        )
    finally:
        fake_path.unlink(missing_ok=True)

    unit_path = systemd_dir / "hf-prod.service"
    assert unit_path.exists()
    commands = log_file.read_text().strip().splitlines()
    # The helper should reload units then enable/start the service.
    assert commands == [
        "daemon-reload",
        "enable --now hf-prod.service",
    ]
