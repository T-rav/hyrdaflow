"""Regression tests for the EC2 deploy helper script."""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
SCRIPT_PATH = REPO_ROOT / "deploy" / "ec2" / "deploy-hydraflow.sh"


def _prepare_doctor_environment(
    tmp_path: Path, *, include_env_file: bool = True
) -> dict[str, str]:
    """Create a fake repo + PATH so the doctor command can run in CI."""
    repo_root = tmp_path / "hydraflow"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()

    env_file = repo_root / ".env"
    if include_env_file:
        env_file.write_text("HYDRAFLOW_GH_TOKEN=test-token\n")

    home_dir = tmp_path / "home"
    home_dir.mkdir()
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    systemd_dir = tmp_path / "systemd"
    systemd_dir.mkdir()
    service_path = systemd_dir / "hf-test.service"
    service_path.write_text("[Unit]\nDescription=HydraFlow test service\n")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("git", "make", "uv"):
        fake = bin_dir / name
        fake.write_text("#!/usr/bin/env bash\nexit 0\n")
        fake.chmod(0o755)

    env = os.environ.copy()
    original_path = env.get("PATH", "")
    env.update(
        {
            "HYDRAFLOW_ROOT": str(repo_root),
            "HYDRAFLOW_HOME_DIR": str(home_dir),
            "HYDRAFLOW_LOG_DIR": str(log_dir),
            "ENV_FILE": str(env_file),
            "SYSTEMD_DIR": str(systemd_dir),
            "SERVICE_NAME": "hf-test",
            "UV_BIN": "uv",
            "PATH": f"{bin_dir}:{original_path}",
        }
    )
    return env


def _write_fake_curl(response: str) -> Path:
    """Create a fake curl binary under the repo root so it can execute."""
    fd, path = tempfile.mkstemp(prefix="fake-curl-", suffix=".sh", dir=REPO_ROOT)
    fake = Path(path)
    with os.fdopen(fd, "w") as fh:
        fh.write(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'if [[ -n "${CURL_CALL_LOG:-}" ]]; then\n'
            '  printf "%s\\n" "$*" >> "${CURL_CALL_LOG}"\n'
            "fi\n"
            "cat <<'JSON'\n"
            f"{response}\n"
            "JSON\n"
        )
    fake.chmod(0o755)
    return fake


def _write_sequence_curl(
    responses: list[str], tmp_path: Path
) -> tuple[Path, Path, Path]:
    """Create a fake curl binary that steps through multiple responses."""
    responses_file = tmp_path / "curl-responses.txt"
    responses_file.write_text("\n".join(responses))
    counter_file = tmp_path / "curl-counter.txt"
    fd, path = tempfile.mkstemp(prefix="fake-seq-curl-", suffix=".sh", dir=REPO_ROOT)
    os.close(fd)
    script_path = Path(path)
    script_path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'if [[ -n "${CURL_CALL_LOG:-}" ]]; then\n'
        '  printf "%s\\n" "$*" >> "${CURL_CALL_LOG}"\n'
        "fi\n"
        'responses_file="${FAKE_CURL_RESPONSES_FILE:?}"\n'
        'counter_file="${FAKE_CURL_COUNTER_FILE:?}"\n'
        "count=0\n"
        'if [[ -f "${counter_file}" ]]; then\n'
        '  count="$(<"${counter_file}")"\n'
        "fi\n"
        'mapfile -t responses < "${responses_file}"\n'
        'total="${#responses[@]}"\n'
        "if (( total == 0 )); then\n"
        "  printf '{}'\n"
        "  exit 0\n"
        "fi\n"
        "if (( count >= total )); then\n"
        "  count=$((total - 1))\n"
        "fi\n"
        'printf "%s\\n" "${responses[count]}"\n'
        'echo $((count + 1)) > "${counter_file}"\n'
    )
    script_path.chmod(0o755)
    return script_path, responses_file, counter_file


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


def test_health_command_uses_curl_and_prints_payload(tmp_path: Path) -> None:
    """`health` should hit the configured URL and surface the JSON payload."""
    fake_curl = _write_fake_curl('{"ready": true, "status": "ok"}')
    log_file = tmp_path / "curl.log"
    env = os.environ.copy()
    env.update(
        {
            "CURL_BIN": str(fake_curl),
            "CURL_CALL_LOG": str(log_file),
            "HEALTHCHECK_URL": "http://internal/healthz",
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "health"],
            cwd=REPO_ROOT,
            env=env,
            check=True,
            text=True,
            capture_output=True,
        )
    finally:
        fake_curl.unlink(missing_ok=True)

    assert '"ready": true' in result.stdout
    assert "ready=true" in result.stdout
    assert log_file.read_text().strip() == "-fsS http://internal/healthz"


def test_health_command_can_fail_when_not_ready(tmp_path: Path) -> None:
    """When readiness is enforced, non-ready payloads should exit non-zero."""
    fake_curl = _write_fake_curl('{"ready": false, "status": "degraded"}')
    env = os.environ.copy()
    env.update(
        {
            "CURL_BIN": str(fake_curl),
            "HEALTHCHECK_URL": "http://internal/healthz",
            "HEALTHCHECK_REQUIRE_READY": "1",
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "health"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_curl.unlink(missing_ok=True)

    assert result.returncode != 0
    assert "Service is not ready" in result.stdout


def test_wait_ready_polls_until_ready(tmp_path: Path) -> None:
    """wait-ready should retry until the payload reports ready=true."""
    fake_curl, responses_file, counter_file = _write_sequence_curl(
        [
            '{"ready": false, "status": "starting"}',
            '{"ready": false, "status": "warming"}',
            '{"ready": true, "status": "ok"}',
        ],
        tmp_path,
    )
    log_file = tmp_path / "curl.log"
    env = os.environ.copy()
    env.update(
        {
            "CURL_BIN": str(fake_curl),
            "FAKE_CURL_RESPONSES_FILE": str(responses_file),
            "FAKE_CURL_COUNTER_FILE": str(counter_file),
            "CURL_CALL_LOG": str(log_file),
            "HEALTHCHECK_URL": "http://internal/healthz",
            "HEALTHCHECK_WAIT_TIMEOUT_SECONDS": "5",
            "HEALTHCHECK_WAIT_INTERVAL_SECONDS": "0",
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "wait-ready"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
    finally:
        fake_curl.unlink(missing_ok=True)

    assert '"ready": true' in result.stdout
    commands = [line for line in log_file.read_text().splitlines() if line]
    assert len(commands) == 4, "Expected three probes plus the final payload dump"


def test_wait_ready_times_out_when_service_never_ready(tmp_path: Path) -> None:
    """wait-ready should exit non-zero when ready never flips to true."""
    fake_curl, responses_file, counter_file = _write_sequence_curl(
        [
            '{"ready": false, "status": "starting"}',
            '{"ready": false, "status": "starting"}',
        ],
        tmp_path,
    )
    env = os.environ.copy()
    env.update(
        {
            "CURL_BIN": str(fake_curl),
            "FAKE_CURL_RESPONSES_FILE": str(responses_file),
            "FAKE_CURL_COUNTER_FILE": str(counter_file),
            "HEALTHCHECK_URL": "http://internal/healthz",
            "HEALTHCHECK_WAIT_TIMEOUT_SECONDS": "1",
            "HEALTHCHECK_WAIT_INTERVAL_SECONDS": "0",
        }
    )

    try:
        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "wait-ready"],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        fake_curl.unlink(missing_ok=True)

    assert result.returncode != 0
    assert "Timed out waiting for ready" in result.stdout


def test_doctor_passes_when_environment_ready(tmp_path: Path) -> None:
    """doctor should succeed when repo, env, and directories exist."""
    env = _prepare_doctor_environment(tmp_path)
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "doctor"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Doctor checks passed" in result.stdout


def test_doctor_fails_when_env_file_missing(tmp_path: Path) -> None:
    """doctor should fail fast when the env file is absent."""
    env = _prepare_doctor_environment(tmp_path, include_env_file=False)
    result = subprocess.run(
        ["bash", str(SCRIPT_PATH), "doctor"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "missing env file" in result.stdout.lower()
