#!/usr/bin/env bash
set -euo pipefail

ACTION="${1:-deploy}"
if (($# > 0)); then
  shift
fi
EXTRA_ARGS=("$@")

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT_DEFAULT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
HYDRAFLOW_ROOT="${HYDRAFLOW_ROOT:-${REPO_ROOT_DEFAULT}}"
VENV_DIR="${VENV_DIR:-${HYDRAFLOW_ROOT}/.venv}"
UV_CACHE_DIR="${UV_CACHE_DIR:-${HYDRAFLOW_ROOT}/.uv-cache}"
HYDRAFLOW_HOME_DIR="${HYDRAFLOW_HOME_DIR:-/var/lib/hydraflow}"
LOG_DIR="${HYDRAFLOW_LOG_DIR:-/var/log/hydraflow}"
UV_BIN="${UV_BIN:-uv}"
CURL_BIN="${CURL_BIN:-curl}"
GIT_REMOTE="${GIT_REMOTE:-origin}"
GIT_BRANCH="${GIT_BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-hydraflow}"
ENV_FILE="${ENV_FILE:-${HYDRAFLOW_ROOT}/.env}"
RUNTIME_ENV_FILE="${RUNTIME_ENV_FILE:-/etc/hydraflow.env}"
SYSTEMD_DIR="${SYSTEMD_DIR:-/etc/systemd/system}"
SYSTEMCTL_BIN="${SYSTEMCTL_BIN:-systemctl}"
SYSTEMCTL_ALLOW_USER="${SYSTEMCTL_ALLOW_USER:-0}"
SERVICE_DESCRIPTION="${SERVICE_DESCRIPTION:-HydraFlow orchestrator and dashboard}"
SERVICE_USER="${SERVICE_USER:-hydraflow}"
SERVICE_GROUP="${SERVICE_GROUP:-${SERVICE_USER}}"
SERVICE_RUNTIME_DIR="${SERVICE_RUNTIME_DIR:-hydraflow}"
SERVICE_WORK_DIR="${SERVICE_WORK_DIR:-${HYDRAFLOW_ROOT}}"
SERVICE_LOG_FILE="${SERVICE_LOG_FILE:-${LOG_DIR}/orchestrator.log}"
SERVICE_EXEC_START="${SERVICE_EXEC_START:-${HYDRAFLOW_ROOT}/deploy/ec2/deploy-hydraflow.sh run}"
UNIT_TEMPLATE="${UNIT_TEMPLATE:-${SCRIPT_DIR}/hydraflow.service}"
HEALTHCHECK_URL="${HEALTHCHECK_URL:-}"
HEALTHCHECK_REQUIRE_READY="${HEALTHCHECK_REQUIRE_READY:-0}"
HEALTH_PROBE_LAST_CODE=""
HEALTH_PROBE_LAST_MESSAGE=""

log() {
  printf '[%s] %s\n' "$(date --iso-8601=seconds 2>/dev/null || date)" "$*"
}

fatal() {
  log "ERROR: $*"
  exit 1
}

ensure_dir() {
  local dir="$1"
  if [[ -d "${dir}" ]]; then
    return
  fi
  if mkdir -p "${dir}"; then
    log "Created ${dir}"
  else
    log "WARNING: Unable to create ${dir}; check permissions"
  fi
}

ensure_repo() {
  if [[ ! -d "${HYDRAFLOW_ROOT}/.git" ]]; then
    fatal "HYDRAFLOW_ROOT (${HYDRAFLOW_ROOT}) does not contain a .git directory"
  fi
}

escape_sed_replacement() {
  sed -e 's/[\\/|&]/\\&/g' <<<"$1"
}

render_systemd_unit() {
  local template="$1"
  local dest="$2"
  if [[ ! -f "${template}" ]]; then
    fatal "Missing systemd unit template at ${template}"
  fi
  local tmp
  tmp="$(mktemp)"
  sed \
    -e "s|@SERVICE_DESCRIPTION@|$(escape_sed_replacement "${SERVICE_DESCRIPTION}")|g" \
    -e "s|@SERVICE_USER@|$(escape_sed_replacement "${SERVICE_USER}")|g" \
    -e "s|@SERVICE_GROUP@|$(escape_sed_replacement "${SERVICE_GROUP}")|g" \
    -e "s|@WORKING_DIRECTORY@|$(escape_sed_replacement "${SERVICE_WORK_DIR}")|g" \
    -e "s|@ENV_FILE@|$(escape_sed_replacement "${RUNTIME_ENV_FILE}")|g" \
    -e "s|@HYDRAFLOW_HOME_DIR@|$(escape_sed_replacement "${HYDRAFLOW_HOME_DIR}")|g" \
    -e "s|@RUNTIME_DIRECTORY@|$(escape_sed_replacement "${SERVICE_RUNTIME_DIR}")|g" \
    -e "s|@EXEC_START@|$(escape_sed_replacement "${SERVICE_EXEC_START}")|g" \
    -e "s|@LOG_PATH@|$(escape_sed_replacement "${SERVICE_LOG_FILE}")|g" \
    "${template}" >"${tmp}"
  mv "${tmp}" "${dest}"
  chmod 0644 "${dest}"
}

uv_env_cmd() {
  (cd "${HYDRAFLOW_ROOT}" && \
    VIRTUAL_ENV="${VENV_DIR}" \
    UV_CACHE_DIR="${UV_CACHE_DIR}" \
    "${UV_BIN}" "$@")
}

check_requirements() {
  if ! require_commands git make "${UV_BIN}"; then
    fatal "Install the missing commands and re-run the script"
  fi
}

require_commands() {
  local missing=0
  for cmd in "$@"; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      log "Missing required command: ${cmd}"
      missing=1
    fi
  done
  return ${missing}
}

sync_git() {
  ensure_repo
  log "Syncing repository at ${HYDRAFLOW_ROOT}"
  git -C "${HYDRAFLOW_ROOT}" fetch --prune
  git -C "${HYDRAFLOW_ROOT}" checkout "${GIT_BRANCH}"
  git -C "${HYDRAFLOW_ROOT}" pull --ff-only "${GIT_REMOTE}" "${GIT_BRANCH}"
  git -C "${HYDRAFLOW_ROOT}" submodule update --init --recursive
}

ensure_env_file() {
  if [[ ! -f "${ENV_FILE}" && -f "${HYDRAFLOW_ROOT}/.env.sample" ]]; then
    log "Seeding ${ENV_FILE} from .env.sample"
    cp "${HYDRAFLOW_ROOT}/.env.sample" "${ENV_FILE}"
  fi
}

load_runtime_env() {
  local env_file="$1"
  if [[ -z "${env_file}" || ! -f "${env_file}" ]]; then
    return
  fi
  log "Loading runtime environment from ${env_file}"
  # shellcheck disable=SC1090
  set -a
  source "${env_file}"
  set +a
}

build_artifacts() {
  log "Syncing Python dependencies via uv"
  uv_env_cmd sync --all-extras
  log "Building dashboard assets"
  (cd "${HYDRAFLOW_ROOT}" && make ui >/dev/null)
}

maybe_restart_service() {
  if ! command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    log "${SYSTEMCTL_BIN} not available; skipping service restart"
    return
  fi
  if [[ ${EUID} -ne 0 && "${SYSTEMCTL_ALLOW_USER}" != "1" ]]; then
    log "Not running as root; skipping systemd restart"
    return
  fi
  if [[ ! -f "${SYSTEMD_DIR}/${SERVICE_NAME}.service" ]]; then
    log "${SERVICE_NAME}.service not installed under ${SYSTEMD_DIR}; skipping restart"
    return
  fi
  log "Reloading systemd units"
  "${SYSTEMCTL_BIN}" daemon-reload
  log "Restarting ${SERVICE_NAME}.service"
  "${SYSTEMCTL_BIN}" restart "${SERVICE_NAME}.service"
}

install_systemd_unit() {
  local src="${UNIT_TEMPLATE}"
  local dest="${SYSTEMD_DIR}/${SERVICE_NAME}.service"

  ensure_dir "${SYSTEMD_DIR}"
  ensure_dir "$(dirname "${SERVICE_LOG_FILE}")"
  render_systemd_unit "${src}" "${dest}"
  log "Rendered ${SERVICE_NAME}.service to ${dest}"

  if ! command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
    log "${SYSTEMCTL_BIN} not available; skipping systemd enable"
    return
  fi
  if [[ ${EUID} -ne 0 && "${SYSTEMCTL_ALLOW_USER}" != "1" ]]; then
    log "Not running as root; skipping systemd enable; run sudo ${SYSTEMCTL_BIN} enable --now ${SERVICE_NAME}.service"
    return
  fi

  log "Reloading systemd units"
  "${SYSTEMCTL_BIN}" daemon-reload
  log "Enabling and starting ${SERVICE_NAME}.service"
  "${SYSTEMCTL_BIN}" enable --now "${SERVICE_NAME}.service"
}

run_cli() {
  ensure_repo
  load_runtime_env "${RUNTIME_ENV_FILE}"
  log "Starting HydraFlow via uv run"
  (cd "${HYDRAFLOW_ROOT}" && \
    VIRTUAL_ENV="${VENV_DIR}" \
    UV_CACHE_DIR="${UV_CACHE_DIR}" \
    HYDRAFLOW_HOME="${HYDRAFLOW_HOME:-${HYDRAFLOW_HOME_DIR}}" \
    PYTHONPATH="src" \
    "${UV_BIN}" run --active python -m cli "${EXTRA_ARGS[@]}")
}

extract_health_field() {
  local key="$1"
  python3 -c '
import json
import sys

payload = json.load(sys.stdin)
key = sys.argv[1]
value = payload.get(key)
if isinstance(value, bool):
    print("true" if value else "false")
elif value is None:
    print()
else:
    print(value)
' "${key}"
}

health_probe() {
  local quiet=0
  if [[ "${1:-}" == "--quiet" ]]; then
    quiet=1
    shift
  fi
  HEALTH_PROBE_LAST_CODE=""
  HEALTH_PROBE_LAST_MESSAGE=""
  local override_url="${1:-}"
  load_runtime_env "${RUNTIME_ENV_FILE}"
  local host="${HYDRAFLOW_DASHBOARD_HOST:-127.0.0.1}"
  local port="${HYDRAFLOW_DASHBOARD_PORT:-5555}"
  local url="${override_url:-${HEALTHCHECK_URL:-}}"
  if [[ -z "${url}" ]]; then
    url="http://${host}:${port}/healthz"
  fi
  local curl_cmd="${CURL_BIN}"
  if [[ "${curl_cmd}" == */* ]]; then
    if [[ ! -x "${curl_cmd}" ]]; then
      HEALTH_PROBE_LAST_CODE="missing_binary"
      HEALTH_PROBE_LAST_MESSAGE="Missing curl implementation: ${curl_cmd}"
      return 2
    fi
  else
    if ! curl_cmd="$(command -v "${curl_cmd}")"; then
      HEALTH_PROBE_LAST_CODE="missing_binary"
      HEALTH_PROBE_LAST_MESSAGE="Missing curl implementation: ${curl_cmd}"
      return 2
    fi
  fi
  log "Checking health endpoint at ${url}"
  local response ready status
  if ! response="$(${curl_cmd} -fsS "${url}")"; then
    HEALTH_PROBE_LAST_CODE="curl_error"
    HEALTH_PROBE_LAST_MESSAGE="Failed to fetch ${url}"
    return 2
  fi
  ready="$(printf '%s\n' "${response}" | extract_health_field ready)"
  status="$(printf '%s\n' "${response}" | extract_health_field status)"
  log "Health status=${status:-unknown} ready=${ready:-unknown}"
  if [[ ${quiet} -eq 0 ]]; then
    printf '%s\n' "${response}"
  fi
  local require_ready="${HEALTHCHECK_REQUIRE_READY,,}"
  if [[ "${require_ready}" =~ ^(1|true|yes)$ && "${ready}" != "true" ]]; then
    HEALTH_PROBE_LAST_CODE="not_ready"
    HEALTH_PROBE_LAST_MESSAGE="Service is not ready (ready=${ready:-unset})"
    return 1
  fi
  return 0
}

health_check() {
  if ! health_probe "$@"; then
    fatal "${HEALTH_PROBE_LAST_MESSAGE:-Health check failed}"
  fi
}

wait_for_health_ready() {
  local override_url="${1:-}"
  local timeout="${HEALTHCHECK_WAIT_TIMEOUT_SECONDS:-180}"
  local interval="${HEALTHCHECK_WAIT_INTERVAL_SECONDS:-5}"
  if ! [[ "${timeout}" =~ ^[0-9]+$ ]]; then
    fatal "HEALTHCHECK_WAIT_TIMEOUT_SECONDS must be an integer"
  fi
  if ! [[ "${interval}" =~ ^[0-9]+$ ]]; then
    fatal "HEALTHCHECK_WAIT_INTERVAL_SECONDS must be an integer"
  fi
  local deadline=$((SECONDS + timeout))
  log "Waiting up to ${timeout}s for HydraFlow readiness"
  while ((SECONDS < deadline)); do
    if HEALTHCHECK_REQUIRE_READY=1 health_probe --quiet "${override_url}"; then
      log "HydraFlow dashboard reports ready"
      HEALTHCHECK_REQUIRE_READY=1 health_probe "${override_url}"
      return 0
    fi
    if [[ "${HEALTH_PROBE_LAST_CODE}" != "not_ready" ]]; then
      fatal "${HEALTH_PROBE_LAST_MESSAGE:-Health probe failed}"
    fi
    sleep "${interval}"
  done
  fatal "Timed out waiting for ready=true after ${timeout}s (${HEALTH_PROBE_LAST_MESSAGE:-last probe failed})"
}

maybe_wait_for_ready() {
  local wait_flag="${HEALTHCHECK_WAIT_FOR_READY,,}"
  if [[ "${wait_flag}" =~ ^(1|true|yes)$ ]]; then
    wait_for_health_ready
  fi
}

doctor() {
  log "Running HydraFlow EC2 doctor checks"
  local failures=0

  if require_commands git make "${UV_BIN}"; then
    log "Doctor: required commands located (git, make, ${UV_BIN})"
  else
    log "Doctor: required commands missing (see messages above)"
    failures=1
  fi

  if [[ -d "${HYDRAFLOW_ROOT}/.git" ]]; then
    log "Doctor: git checkout detected at ${HYDRAFLOW_ROOT}"
  else
    log "Doctor: missing .git directory under ${HYDRAFLOW_ROOT}"
    failures=1
  fi

  if [[ -f "${ENV_FILE}" ]]; then
    log "Doctor: env file present at ${ENV_FILE}"
  else
    log "Doctor: missing env file at ${ENV_FILE}"
    failures=1
  fi

  if [[ -d "${HYDRAFLOW_HOME_DIR}" ]]; then
    log "Doctor: HYDRAFLOW_HOME_DIR exists (${HYDRAFLOW_HOME_DIR})"
  else
    log "Doctor: HYDRAFLOW_HOME_DIR missing (${HYDRAFLOW_HOME_DIR}); create it to persist agent state"
  fi

  if [[ -d "${LOG_DIR}" ]]; then
    log "Doctor: log directory exists (${LOG_DIR})"
  else
    log "Doctor: log directory missing (${LOG_DIR}); create it so journalctl tails are mirrored to disk"
  fi

  local unit_path="${SYSTEMD_DIR}/${SERVICE_NAME}.service"
  if [[ -f "${unit_path}" ]]; then
    log "Doctor: systemd unit installed at ${unit_path}"
  else
    log "Doctor: systemd unit not found at ${unit_path}; run install once bootstrap completes"
  fi

  if ((failures > 0)); then
    log "Doctor detected ${failures} blocking issue(s). Fix them and re-run doctor."
    return 1
  fi

  log "Doctor checks passed; host is ready for hydraflow deploys."
}

case "${ACTION}" in
  bootstrap)
    check_requirements
    ensure_repo
    ensure_env_file
    ensure_dir "${HYDRAFLOW_HOME_DIR}"
    ensure_dir "${HYDRAFLOW_ROOT}/.hydraflow/logs"
    ensure_dir "${LOG_DIR}"
    sync_git
    build_artifacts
    log "Bootstrap complete. Customize ${ENV_FILE} and install the systemd unit."
    ;;
  deploy)
    check_requirements
    sync_git
    build_artifacts
    maybe_restart_service
    maybe_wait_for_ready
    log "Deploy step finished."
    ;;
  run)
    run_cli
    ;;
  status)
    if command -v "${SYSTEMCTL_BIN}" >/dev/null 2>&1; then
      "${SYSTEMCTL_BIN}" status "${SERVICE_NAME}.service"
    else
      fatal "${SYSTEMCTL_BIN} is not available on this host"
    fi
    ;;
  health)
    health_check "${EXTRA_ARGS[@]:-}"
    ;;
  wait-ready)
    wait_for_health_ready "${EXTRA_ARGS[@]:-}"
    ;;
  install)
    install_systemd_unit
    ;;
  doctor)
    doctor
    ;;
  *)
    cat <<USAGE
Usage: ${0##*/} [bootstrap|deploy|run|status|health|wait-ready|install|doctor] [-- additional cli args]

bootstrap : Prepare dependencies, copy .env.sample, and build UI assets.
deploy    : Update git checkout, rebuild assets, and restart the systemd unit.
run       : Execute python -m cli with the provided arguments.
status    : Show the hydraflow systemd unit status.
health    : Query /healthz (optionally fail when not ready).
wait-ready: Poll /healthz until ready=true (with timeout controls).
install   : Copy the systemd unit into ${SYSTEMD_DIR} and enable it.
doctor    : Verify prerequisites: commands, repo checkout, env file, and directories.
USAGE
    exit 1
    ;;
esac
