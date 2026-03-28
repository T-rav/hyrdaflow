# Capture Session Learnings as Memory Suggestions

Scan the current conversation for architectural decisions, bug root causes, configuration choices, codebase patterns, and workflow preferences. Write each as a memory item to the local JSONL store for ingestion by the memory sync worker.

## Usage

```
/hf.memory
/hf.memory review model decisions
```

`$ARGUMENTS` optionally filters extraction to a specific topic. If empty, scan the full conversation.

## Instructions

### Phase 0: Resolve Configuration

Before doing anything else, resolve these values:

1. **REPO**: Run `echo "$HYDRAFLOW_GITHUB_REPO"`. If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
2. **DATA_ROOT**: The HydraFlow data directory. Check `echo "$HYDRAFLOW_DATA_ROOT"`. If empty, default to `.hydraflow/<repo_slug>/` relative to repo root (where `/` in the slug is replaced with `-`).

### Phase 1: Fetch Existing Memories for Dedup

Load existing memory items from the local JSONL store to avoid duplicates:

```bash
cat "$DATA_ROOT/memory/items.jsonl" 2>/dev/null | jq -r '.title' | sort -u
```

Keep these titles in mind — skip any learning that substantially overlaps with an existing item.

### Phase 2: Extract Learnings from Conversation

Scan the full conversation history (or filter to `$ARGUMENTS` topic if provided). Look for these categories:

1. **Architectural decisions** — choices about how the system is structured
2. **Bug root causes and fixes** — what broke, why, and how it was fixed
3. **Configuration insights** — what settings mean and why they're set that way
4. **Codebase patterns** — recurring patterns that future agents should follow
5. **Workflow preferences** — how the developer wants things done

For each learning, formulate:
- **title**: Short description (under 60 chars)
- **learning**: What was learned and why it matters (1-3 sentences)
- **context**: How it was discovered — reference specific issues, PRs, files, or conversation topics
- **memory_type**: One of `knowledge`, `config`, `instruction`, `code`

### Phase 3: Filter and Deduplicate

For each extracted learning:
1. Compare against existing memory items fetched in Phase 1
2. Skip if the title or learning substantially overlaps with an existing item
3. Skip trivial or session-specific items (e.g., "we ran make test" is not a memory)
4. Keep only durable insights that would help future agent runs

### Phase 4: Write Memory Items to JSONL

For each unique learning, append a JSON object to the local items file:

```bash
ITEMS_FILE="$DATA_ROOT/memory/items.jsonl"
mkdir -p "$(dirname "$ITEMS_FILE")"

ITEM_ID="mem-$(uuidgen | tr '[:upper:]' '[:lower:]' | cut -c1-8)"
TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"

printf '%s\n' "$(jq -n \
  --arg id "$ITEM_ID" \
  --arg title "<title>" \
  --arg learning "<learning text>" \
  --arg context "<context text>" \
  --arg memory_type "knowledge" \
  --arg source "interactive" \
  --arg reference "<conversation topic or issue references>" \
  --arg created_at "$TIMESTAMP" \
  '{id: $id, title: $title, learning: $learning, context: $context, memory_type: $memory_type, source: $source, reference: $reference, created_at: $created_at}')" \
  >> "$ITEMS_FILE"
```

**CRITICAL**: The JSONL format MUST match what `memory.py:file_memory_suggestion()` produces.

### Phase 5: Report Back

Show the user:
- Total learnings extracted vs. filed (after dedup)
- For each filed item: the ID and a one-line summary
- Any learnings skipped due to existing duplicates
