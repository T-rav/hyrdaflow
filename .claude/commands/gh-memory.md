# Capture Session Learnings as Memory Suggestions

Scan the current conversation for architectural decisions, bug root causes, configuration choices, codebase patterns, and workflow preferences. File each as a memory suggestion issue that enters the HITL review pipeline and eventually syncs into the agent memory digest.

## Usage

```
/gh-memory
/gh-memory review model decisions
```

`$ARGUMENTS` optionally filters extraction to a specific topic. If empty, scan the full conversation.

## Instructions

### Phase 0: Resolve Configuration

Before doing anything else, resolve these values:

1. **REPO**: Run `echo "$HYDRAFLOW_GITHUB_REPO"`. If empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
2. **ASSIGNEE**: Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"`. If empty, extract the owner from the repo slug (the part before `/`).
3. **IMPROVE_LABEL**: Run `echo "$HYDRAFLOW_LABEL_IMPROVE"`. If empty, default to `hydraflow-improve`.
4. **HITL_LABEL**: Run `echo "$HYDRAFLOW_LABEL_HITL"`. If empty, default to `hydraflow-hitl`.

### Phase 1: Fetch Existing Memories for Dedup

Before extracting anything, fetch existing memory and improvement issues to avoid duplicates:

```bash
gh issue list --repo $REPO --label hydraflow-memory --state open --limit 100 --json title,body
gh issue list --repo $REPO --label hydraflow-improve --state open --limit 100 --json title,body
```

Keep these titles and bodies in mind — skip any learning that substantially overlaps with an existing issue.

### Phase 2: Extract Learnings from Conversation

Scan the full conversation history (or filter to `$ARGUMENTS` topic if provided). Look for these categories:

1. **Architectural decisions** — choices about how the system is structured
   - Example: "use sonnet for review agents, opus for planning"
   - Example: "triage processes issues sequentially, no concurrency"

2. **Bug root causes and fixes** — what broke, why, and how it was fixed
   - Example: "merged state disappears because /api/prs only returns open PRs"
   - Example: "Makefile REVIEW_MODEL overrides config.py default"

3. **Configuration insights** — what settings mean and why they're set that way
   - Example: "max_reviewers=5 allows parallel review, max_planners=1 is intentional"

4. **Codebase patterns** — recurring patterns that future agents should follow
   - Example: "worker concurrency uses asyncio.Semaphore pattern in phase modules"
   - Example: "all label fields need config.py + cli.py + Makefile + ensure-labels"

5. **Workflow preferences** — how the developer wants things done
   - Example: "always run make quality before committing"
   - Example: "issue titles should start with TRAV: when requested"

For each learning, formulate:
- **title**: Short description (under 60 chars)
- **learning**: What was learned and why it matters (1-3 sentences)
- **context**: How it was discovered — reference specific issues, PRs, files, or conversation topics

### Phase 3: Filter and Deduplicate

For each extracted learning:
1. Compare against existing memory/improve issues fetched in Phase 1
2. Skip if the title or learning substantially overlaps with an existing issue
3. Skip trivial or session-specific items (e.g., "we ran make test" is not a memory)
4. Keep only durable insights that would help future agent runs

### Phase 4: Create Memory Issues

For each unique learning, create a GitHub issue using `--body-file` to avoid shell escaping issues:

```bash
BODY_FILE=$(mktemp)
cat > "$BODY_FILE" <<'MEMORY_EOF'
## Memory Suggestion

**Learning:** <learning text>

**Context:** <context text>

**Source:** interactive session during <conversation topic or issue references>
MEMORY_EOF

gh issue create --repo $REPO \
  --assignee $ASSIGNEE \
  --label "$IMPROVE_LABEL,$HITL_LABEL" \
  --title "[Memory] <title>" \
  --body-file "$BODY_FILE"

rm -f "$BODY_FILE"
```

**CRITICAL**: The body format MUST match `memory.py:build_memory_issue_body()` exactly:
```
## Memory Suggestion

**Learning:** <text>

**Context:** <text>

**Source:** <source> during <reference>
```

This ensures the `MemorySyncWorker._extract_learning()` regex can parse it when the issue is approved.

### Phase 5: Report Back

Show the user:
- Total learnings extracted vs. filed (after dedup)
- For each filed issue: the URL and a one-line summary
- Any learnings skipped due to existing duplicates

Example output:
```
Extracted 5 learnings, filed 3 (2 already existed):

- #450 — Review model is sonnet, planning model is opus
- #451 — Merged state needs client-side persistence (server returns open PRs only)
- #452 — Worker concurrency follows asyncio.Semaphore pattern in phase modules

Skipped (already filed):
- "Always run make quality before committing" — matches #401
- "Label fields need config + CLI + Makefile" — matches #437
```
