#!/usr/bin/env bash
# docker-smoke-test.sh — Verify all required tools are present in the agent image.
#
# Usage: docker run --rm ghcr.io/t-rav/hydraflow-agent:latest bash /opt/hydraflow/docker-smoke-test.sh

set -euo pipefail

PASS=0
FAIL=0

check() {
    local label="$1"
    shift
    if "$@" >/dev/null 2>&1; then
        echo "  [PASS] $label"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $label"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Hydra Agent Image Smoke Test ==="
echo ""

# Tool availability
echo "--- Tool Versions ---"
check "claude --version"    claude --version
check "git --version"       git --version
check "gh --version"        gh --version
check "python3 --version"   python3 --version
check "node --version"      node --version
check "make --version"      make --version
check "uv --version"        uv --version
check "ruff --version"      ruff --version
check "pyright --version"   pyright --version
check "pytest --version"    pytest --version

echo ""
echo "--- Version Details ---"
echo "  claude:  $(claude --version 2>/dev/null || echo 'N/A')"
echo "  git:     $(git --version 2>/dev/null || echo 'N/A')"
echo "  gh:      $(gh --version 2>/dev/null | head -1 || echo 'N/A')"
echo "  python:  $(python3 --version 2>/dev/null || echo 'N/A')"
echo "  node:    $(node --version 2>/dev/null || echo 'N/A')"
echo "  make:    $(make --version 2>/dev/null | head -1 || echo 'N/A')"
echo "  uv:      $(uv --version 2>/dev/null || echo 'N/A')"
echo "  ruff:    $(ruff --version 2>/dev/null || echo 'N/A')"
echo "  pyright: $(pyright --version 2>/dev/null || echo 'N/A')"
echo "  pytest:  $(pytest --version 2>/dev/null || echo 'N/A')"

# Non-root user check
echo ""
echo "--- User & Permissions ---"
CURRENT_USER=$(whoami)
if [ "$CURRENT_USER" = "hydraflow" ]; then
    echo "  [PASS] Running as user: hydraflow"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] Expected user 'hydraflow', got '$CURRENT_USER'"
    FAIL=$((FAIL + 1))
fi

CURRENT_UID=$(id -u)
if [ "$CURRENT_UID" = "1000" ]; then
    echo "  [PASS] UID is 1000"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] Expected UID 1000, got $CURRENT_UID"
    FAIL=$((FAIL + 1))
fi

# Directory checks
if [ -d /workspace ]; then
    echo "  [PASS] /workspace exists"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] /workspace does not exist"
    FAIL=$((FAIL + 1))
fi

if touch /workspace/.smoke-test-write 2>/dev/null; then
    rm -f /workspace/.smoke-test-write
    echo "  [PASS] /workspace is writable"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] /workspace is not writable"
    FAIL=$((FAIL + 1))
fi

if touch /tmp/.smoke-test-write 2>/dev/null; then
    rm -f /tmp/.smoke-test-write
    echo "  [PASS] /tmp is writable"
    PASS=$((PASS + 1))
else
    echo "  [FAIL] /tmp is not writable"
    FAIL=$((FAIL + 1))
fi

# Summary
echo ""
echo "=== Results: $PASS passed, $FAIL failed ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi

echo "All checks passed!"
