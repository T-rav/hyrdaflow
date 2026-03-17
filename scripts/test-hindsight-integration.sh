#!/usr/bin/env bash
# Integration test for Hindsight semantic memory.
#
# Prerequisites:
#   1. HINDSIGHT_LLM_API_KEY set in .env (OpenAI key)
#   2. Docker running
#
# Usage:
#   ./scripts/test-hindsight-integration.sh
#
# This script:
#   1. Starts the Hindsight container
#   2. Waits for health check
#   3. Retains a test memory
#   4. Recalls it
#   5. Verifies the round-trip
#   6. Cleans up (stops container)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

# Load .env
if [[ -f .env ]]; then
    set -a; source .env; set +a
fi

HINDSIGHT_URL="${HINDSIGHT_URL:-http://localhost:8888}"
BANK="integration-test"

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RESET='\033[0m'

info() { echo -e "${BLUE}[INFO]${RESET} $*"; }
pass() { echo -e "${GREEN}[PASS]${RESET} $*"; }
fail() { echo -e "${RED}[FAIL]${RESET} $*"; exit 1; }

cleanup() {
    info "Stopping Hindsight container..."
    docker compose down --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

# 1. Start Hindsight
info "Starting Hindsight..."
docker compose up -d hindsight

# 2. Wait for health
info "Waiting for Hindsight to become healthy (up to 60s)..."
for i in $(seq 1 60); do
    if curl -fsS "$HINDSIGHT_URL/health" > /dev/null 2>&1; then
        pass "Hindsight healthy after ${i}s"
        break
    fi
    if [[ $i -eq 60 ]]; then
        fail "Hindsight failed to start within 60s"
    fi
    sleep 1
done

# 3. Retain a test memory
info "Retaining test memory..."
RETAIN_RESP=$(curl -fsS -X POST "$HINDSIGHT_URL/v1/default/banks/$BANK/memories/retain" \
    -H "Content-Type: application/json" \
    -d '{
        "items": [{
            "content": "HydraFlow integration test: always run make quality before committing",
            "context": "CI best practices",
            "metadata": {"source": "integration-test"}
        }]
    }')
echo "  Retain response: $RETAIN_RESP"
pass "Memory retained"

# 4. Wait for indexing (Hindsight needs a moment to process)
info "Waiting 5s for indexing..."
sleep 5

# 5. Recall
info "Recalling memories about CI..."
RECALL_RESP=$(curl -fsS -X POST "$HINDSIGHT_URL/v1/default/banks/$BANK/memories/recall" \
    -H "Content-Type: application/json" \
    -d '{"query": "What should I do before committing code?"}')
echo "  Recall response: $RECALL_RESP"

# 6. Verify
if echo "$RECALL_RESP" | python3 -c "
import sys, json
data = json.load(sys.stdin)
results = data.get('results', [])
if not results:
    print('No results returned')
    sys.exit(1)
found = any('quality' in r.get('text', '').lower() or 'commit' in r.get('text', '').lower() for r in results)
if found:
    print(f'Found {len(results)} result(s) — memory recalled successfully')
    sys.exit(0)
else:
    print(f'Got {len(results)} result(s) but none matched expected content')
    for r in results:
        print(f'  - {r.get(\"text\", \"\")[:100]}')
    sys.exit(1)
" 2>&1; then
    pass "Round-trip retain → recall verified!"
else
    fail "Recall did not return expected memory"
fi

# 7. Test via Python client
info "Testing Python HindsightClient..."
cd "$SCRIPT_DIR"
PYTHONPATH=src uv run python3 -c "
import asyncio
from hindsight import HindsightClient, Bank

async def test():
    client = HindsightClient('$HINDSIGHT_URL')

    # Health
    healthy = await client.health_check()
    assert healthy, 'Health check failed'
    print('  Health check: OK')

    # Retain
    result = await client.retain(
        Bank.LEARNINGS,
        'Python client test: always check types with pyright',
        context='type safety',
    )
    print(f'  Retain: {result}')

    # Wait for indexing
    await asyncio.sleep(3)

    # Recall
    memories = await client.recall(Bank.LEARNINGS, 'type checking best practices')
    print(f'  Recall: {len(memories)} memories')
    for m in memories[:3]:
        print(f'    - {m.display_text[:80]}')

    assert len(memories) > 0, 'No memories recalled'
    await client.close()
    print('  Python client: ALL TESTS PASSED')

asyncio.run(test())
"

pass "All integration tests passed!"
