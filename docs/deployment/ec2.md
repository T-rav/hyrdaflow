# EC2 Deployment Guide

This guide shows how to run HydraFlow as a long-lived service on Ubuntu-based EC2 hosts. It ships three building blocks:

- `deploy/ec2/deploy-hydraflow.sh` — bootstrap, update, and run helper
- `deploy/ec2/hydraflow.service` — systemd unit template
- `GET /healthz` — FastAPI health-check endpoint suitable for load balancers or uptime monitors
- `/etc/hydraflow.env` — optional runtime environment file automatically sourced before HydraFlow starts (override with `RUNTIME_ENV_FILE`)

Follow the steps below to install everything under `/opt/hydraflow`, expose the dashboard, and keep the instance healthy.

## 1. Prerequisites

```bash
sudo apt-get update
sudo apt-get install -y git make python3.11 python3.11-venv build-essential curl
curl -LsSf https://astral.sh/uv/install.sh | sh                    # installs uv into ~/.local/bin
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -  # Node 22 (for dashboard assets)
sudo apt-get install -y nodejs
```

Create a dedicated user and directories for persistent state and logs:

```bash
sudo useradd --system --create-home --shell /bin/bash hydraflow || true
sudo mkdir -p /opt/hydraflow /var/lib/hydraflow /var/log/hydraflow
sudo chown -R hydraflow:hydraflow /opt/hydraflow /var/lib/hydraflow /var/log/hydraflow
```

Clone the repository as that user:

```bash
sudo -u hydraflow git clone https://github.com/hydraflow-ai/hydraflow.git /opt/hydraflow
```

### Quick readiness check (doctor)

Before bootstrapping, run the built-in doctor to confirm the host has everything it needs:

```bash
cd /opt/hydraflow
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh doctor
```

The doctor exits non-zero when required commands (`git`, `make`, `uv`) are missing, when `/opt/hydraflow` is not a git checkout, or when `.env` has not been created yet. It also warns if `/var/lib/hydraflow`, `/var/log/hydraflow`, or the rendered `hydraflow.service` are absent so you can fix the filesystem layout before touching systemd.

## 2. Bootstrap the runtime

Run the helper script once to install Python deps, build the dashboard, and seed `.env`:

```bash
cd /opt/hydraflow
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh bootstrap
```

The script will:

1. Verify `git`, `uv`, and `make` are available.
2. Copy `.env.sample` to `.env` if one is missing.
3. Sync the git branch (`GIT_BRANCH`/`GIT_REMOTE` can be overridden) and update submodules.
4. Create `/var/lib/hydraflow`, `.hydraflow/logs`, and `/var/log/hydraflow` when writable.
5. Run `uv sync --all-extras` and `make ui` so FastAPI can serve the compiled React dashboard.

Re-run the script with `deploy` any time you need to pull new commits and restart the service:

```bash
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh deploy
```

To launch HydraFlow manually (for smoke tests), call:

```bash
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh run --dashboard-port 5555
```

## 3. Bind the dashboard to a public interface

HydraFlow now exposes a `HYDRAFLOW_DASHBOARD_HOST` knob inside `HydraFlowConfig`. Set it to `0.0.0.0` (all IPv4 interfaces) or an explicit IP if you want to reach the dashboard from outside the host:

```bash
cat <<'ENV' | sudo tee /etc/hydraflow.env
HYDRAFLOW_GH_TOKEN=ghp_xxx                 # required for GitHub automation
HYDRAFLOW_READY_LABEL=hydraflow-ready
HYDRAFLOW_DASHBOARD_HOST=0.0.0.0           # bind on all interfaces for EC2
HYDRAFLOW_DASHBOARD_PORT=5555              # optional override
ENV
```

`deploy/ec2/deploy-hydraflow.sh` automatically sources `/etc/hydraflow.env` before starting HydraFlow, so manual `run` invocations match the systemd unit’s environment. Override the path with `RUNTIME_ENV_FILE=/custom/file deploy/ec2/deploy-hydraflow.sh run`.

> **Security note:** Opening the dashboard publicly is equivalent to exposing your automation kernel. Always restrict the EC2 security group to the IPs/VPCs that actually need access, and prefer a TLS-terminating proxy (ALB, CloudFront, Nginx, etc.) in front of port 5555.

You can also override the host on demand via CLI: `deploy/ec2/deploy-hydraflow.sh run --dashboard-host 0.0.0.0`.

## 4. Install the systemd unit

Let the helper script handle copying and enabling the unit:

```bash
cd /opt/hydraflow
sudo deploy/ec2/deploy-hydraflow.sh install
```

By default the unit is written to `/etc/systemd/system/hydraflow.service`; override this or the service name via `SYSTEMD_DIR=/custom/path deploy/ec2/deploy-hydraflow.sh install` and/or `SERVICE_NAME=my-hydraflow`.

The installer renders the template with a handful of environment overrides so you rarely have to edit the unit by hand:

- `SERVICE_USER` / `SERVICE_GROUP` — user/group that owns the process (default: `hydraflow`)
- `SERVICE_WORK_DIR` — checkout path HydraFlow runs from (default: `HYDRAFLOW_ROOT`)
- `SERVICE_LOG_FILE` — file used for both stdout/stderr (default: `${HYDRAFLOW_LOG_DIR:-/var/log/hydraflow}/orchestrator.log`)
- `SERVICE_RUNTIME_DIR` — name for the systemd runtime dir (`RuntimeDirectory=`; default: `hydraflow`)
- `RUNTIME_ENV_FILE` — EnvironmentFile path sourced before the service starts (default: `/etc/hydraflow.env`)
- `SERVICE_EXEC_START` — command systemd executes (default: `<repo>/deploy/ec2/deploy-hydraflow.sh run`)

Example for a non-root install under `/srv/hf`:

```bash
sudo SYSTEMD_DIR=/etc/systemd/system \
     SERVICE_USER=ubuntu \
     SERVICE_GROUP=ubuntu \
     SERVICE_WORK_DIR=/srv/hf \
     SERVICE_LOG_FILE=/srv/hf/logs/orchestrator.log \
     deploy/ec2/deploy-hydraflow.sh install
```

The unit calls the deploy script’s `run` verb, so it inherits all of the script’s environment handling. Runtime environment is loaded from `/etc/hydraflow.env` (see Step 3). Logs are written to `/var/log/hydraflow/orchestrator.log`; watch them with:

```bash
sudo journalctl -u hydraflow -f
```

## 5. Health checks and monitoring

FastAPI now exposes `GET /healthz`, which reports the orchestrator status, worker health, and dashboard binding. Example:

```bash
curl -s http://SERVER_IP:5555/healthz | jq
{
  "status": "ok",
  "ready": true,
  "version": "1.12.0",
  "session_started_at": "2026-03-07T12:29:56+00:00",
  "uptime_seconds": 960,
  "orchestrator_running": true,
  "active_issue_count": 0,
  "active_worktrees": 0,
  "worker_count": 6,
  "worker_errors": [],
  "dashboard": {"host": "0.0.0.0", "port": 5555},
  "checks": {
    "orchestrator": {
      "status": "running",
      "running": true,
      "session_started_at": "2026-03-07T12:29:56+00:00"
    },
    "workers": {"status": "ok", "count": 6, "errors": []},
    "dashboard": {"status": "ok", "host": "0.0.0.0", "port": 5555, "public": true}
  },
  "timestamp": "2026-03-07T12:34:56+00:00"
}
```

You can run the same check locally with the deploy helper:

```bash
# Loads HYDRAFLOW_DASHBOARD_HOST/HYDRAFLOW_DASHBOARD_PORT from /etc/hydraflow.env
deploy/ec2/deploy-hydraflow.sh health

# Fail the command when ready=false (perfect for cron or ALB health checks)
HEALTHCHECK_REQUIRE_READY=1 deploy/ec2/deploy-hydraflow.sh health

# Override the target URL or curl binary if needed
deploy/ec2/deploy-hydraflow.sh health https://hydraflow.example.com/healthz
HEALTHCHECK_URL=https://internal-lb/healthz CURL_BIN=/usr/local/bin/curl deploy/ec2/deploy-hydraflow.sh health
```

To gate restarts or CI rollouts on readiness, either run the dedicated waiter or set a flag before `deploy`:

```bash
# Block interactively until /healthz returns ready=true (default timeout: 180s)
deploy/ec2/deploy-hydraflow.sh wait-ready

# Make the deploy action wait automatically after the systemd restart
HEALTHCHECK_WAIT_FOR_READY=1 \
HEALTHCHECK_WAIT_TIMEOUT_SECONDS=300 \
sudo deploy/ec2/deploy-hydraflow.sh deploy
```

`HEALTHCHECK_WAIT_TIMEOUT_SECONDS` (default `180`) and `HEALTHCHECK_WAIT_INTERVAL_SECONDS` (default `5`) control how long the waiter polls `/healthz`. The helper fails fast when the endpoint is unreachable, and it only busy-waits when the payload explicitly reports `ready=false`.

`ready` flips to `false` whenever the orchestrator is missing/idle or any worker reports `degraded`, making it trivial for an ALB or uptime monitor to gate traffic without parsing internal details. `checks.dashboard.public` is `true` when `HYDRAFLOW_DASHBOARD_HOST` is not localhost/127.0.0.1, which is a quick sanity check that you actually bound to a public interface.

The endpoint still returns `200 OK` for “starting/idle/degraded” states, so you can point an ALB, Route 53 health check, or uptime monitor at `/healthz` without needing an auth token. Alert when `ready=false` or when `worker_errors` is non-empty.

`session_started_at` mirrors the orchestrator session boot time, while `uptime_seconds` is a wall-clock counter you can alert on if it resets unexpectedly.

## 6. Updates

Each deploy only requires one command:

```bash
sudo systemctl stop hydraflow
sudo -u hydraflow deploy/ec2/deploy-hydraflow.sh deploy
sudo systemctl start hydraflow
```

Or let the script restart the service automatically (it calls `systemctl restart` when run as root and the unit is installed):

```bash
HEALTHCHECK_WAIT_FOR_READY=1 sudo deploy/ec2/deploy-hydraflow.sh deploy
```

The script honours `GIT_BRANCH`, `GIT_REMOTE`, `UV_BIN`, and `HYDRAFLOW_HOME_DIR` env vars, so you can pin to a release branch or custom fork by exporting those variables before running it.

## 7. Troubleshooting checklist

- `deploy/ec2/deploy-hydraflow.sh status` — shows the live systemd state.
- `journalctl -u hydraflow -b` — inspect the last boot’s logs.
- `curl http://127.0.0.1:5555/healthz` — verify FastAPI is responsive even if the ALB is failing.
- Ensure `/var/log/hydraflow` and `/var/lib/hydraflow` are writable by the `hydraflow` user.
- Open TCP port 5555 (or your configured port) in the EC2 security group to whichever CIDR blocks need dashboard access.

With these assets in place you can treat HydraFlow as any other continuously-running service: deploy updates with one command, monitor `/healthz`, and expose the dashboard safely.
