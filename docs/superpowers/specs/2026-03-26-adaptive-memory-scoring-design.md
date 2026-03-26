# Adaptive Memory Scoring Design

**Date:** 2026-03-26
**Status:** Draft
**Beads:** ops-audit-fixes-0lm, 6l1, 1cz, 1sx, arn, o06, 0n1, btn, du2, vo3, f8c

## Problem

HydraFlow's memory system captures learnings but never evaluates whether they help. Memories accumulate without scoring, demotion, or eviction based on outcomes. A memory that consistently correlates with failed attempts persists identically to one that drives first-pass merges. Seven of eight observation channels are partially or fully open loops — data is captured but never fed back into agent behavior.

## Goal

Close the feedback loop: track outcomes, score memory items by correlation with success/failure, decay stale knowledge, and evict items that don't help. Also close the 7 open loops identified in the memory audit so all observation channels feed back into agent behavior.

## Design Principles (from RL/knowledge system research)

1. **Noise handling** — failures may be unrelated to the memory content. Use memory-type x failure-category filtering to avoid false attribution.
2. **Temporal decay** — what was good advice 100 issues ago may be stale. Scores drift toward neutral without recent positive evidence.
3. **Minimum observation threshold** — don't evict items without enough data. At least 5 appearances before acting on a score.
4. **Surprise flagging** — outcomes that diverge from predictions are the most informative. Highlight them during compaction.
5. **Informed compaction** — the model that compacts the digest should see score trails, not just text. Keep/rephrase/evict decisions should be evidence-based.

---

## Part 1: Outcome Tracking

**Bead:** ops-audit-fixes-0lm (P0)

### Terminal States

| Outcome | Score | Where recorded | Condition |
|---------|-------|----------------|-----------|
| First-pass merge | +1.0 | `post_merge_handler.py` | quality_fix_rounds == 0 AND review cycles <= 1 |
| Merged after iteration | +0.5 | `post_merge_handler.py` | quality_fix_rounds > 0 OR review cycles > 1 |
| HITL escalation | -1.0 | `review_phase.py` | Label swapped to hydraflow-hitl |
| Max attempts exceeded | -1.0 | `implement_phase.py` | max_issue_attempts reached |

Record once per issue at its terminal state. No double-counting.

### Storage

File: `.hydraflow/memory/outcomes.jsonl`

```json
{
  "issue_id": 42,
  "outcome": "success",
  "score": 1.0,
  "digest_hash": "a1b2c3d4",
  "failure_category": null,
  "summary": "PR merged first-pass, added auth middleware",
  "timestamp": "2026-03-26T10:00:00Z"
}
```

`digest_hash` is SHA-256 of `digest.md` content at the time the issue entered the implement phase. This associates the outcome with the knowledge state that was active.

`failure_category` is populated from `harness_insights.FailureCategory` for non-success outcomes (e.g., `"quality_gate"`, `"review_rejection"`, `"ci_failure"`).

### New function: `record_outcome()`

In `src/memory.py` (or a new `src/memory_scoring.py`):

```python
def record_outcome(
    issue_id: int,
    outcome: Literal["success", "partial", "failure"],
    score: float,
    digest_hash: str,
    failure_category: str | None,
    summary: str,
) -> None:
    """Append an outcome record to outcomes.jsonl."""
```

### Call sites

- `post_merge_handler.py:handle_approved()` — after successful merge, compute score from quality_fix_rounds and review cycles
- `review_phase.py:_escalate_to_hitl()` — record failure with the escalation cause
- `implement_phase.py:_run_implementation()` — when max_issue_attempts is exceeded

### Digest hash capture

In `implement_phase.py`, before calling the agent, read and hash `digest.md`:

```python
digest_path = config.memory_dir / "digest.md"
digest_hash = hashlib.sha256(digest_path.read_bytes()).hexdigest()[:16] if digest_path.exists() else ""
```

Store in state tracker so post-merge handler can retrieve it later.

---

## Part 2: Item Confidence with Score Trail

**Bead:** ops-audit-fixes-6l1 (P0)

### Per-item scoring model

File: `.hydraflow/memory/item_scores.json`

```json
{
  "items": {
    "42": {
      "score": 0.72,
      "appearances": 8,
      "last_updated": "2026-03-26T10:00:00Z",
      "trail": [
        {
          "issue": 101,
          "outcome": "success",
          "delta": 0.1,
          "summary": "PR merged first-pass, implemented auth middleware",
          "surprising": false,
          "timestamp": "2026-03-26T09:00:00Z"
        },
        {
          "issue": 115,
          "outcome": "failure",
          "delta": -0.1,
          "summary": "HITL escalation, merge conflict in config.py",
          "surprising": false,
          "timestamp": "2026-03-26T10:00:00Z"
        }
      ]
    }
  }
}
```

### Scoring rules

- **New item:** starts at `score = 0.5` (neutral)
- **Success:** `delta = +0.1`
- **Partial:** `delta = +0.05`
- **Failure:** `delta = -0.1`
- **Score bounds:** clamp to `[0.0, 1.0]`
- **Surprise flag:** set when `score > 0.7 AND outcome == failure` or `score < 0.3 AND outcome == success`

### Temporal decay

During each compaction cycle (called from `_compact_digest`):

```python
for item in scores["items"].values():
    item["score"] = item["score"] * 0.95 + 0.5 * 0.05
```

Half-life of ~14 compaction cycles. Items without recent positive evidence drift toward 0.5 (neutral).

### Trail management

Keep the last 10 trail entries per item. When exceeding 10, condense the oldest entries into a single summary:

```json
{"condensed": true, "successes": 5, "failures": 1, "partials": 2, "period": "issues #80-#110"}
```

### New class: `MemoryScorer`

```python
class MemoryScorer:
    def __init__(self, memory_dir: Path): ...
    def update_scores(self, outcome: OutcomeRecord, active_item_ids: list[int]) -> None: ...
    def get_item_score(self, item_id: int) -> float: ...
    def apply_temporal_decay(self) -> None: ...
    def get_eviction_candidates(self, min_appearances: int = 5, threshold: float = 0.3) -> list[int]: ...
    def get_score_trail(self, item_id: int) -> list[dict]: ...
```

---

## Part 3: Outcome-Type Awareness (Noise Filtering)

**Bead:** ops-audit-fixes-1cz (P0)

### Memory type x failure category matrix

Not all failures are relevant to all memory types. Skip score updates when the failure category is unrelated:

| Memory Type | Scored on these failure categories | Ignored |
|-------------|-----------------------------------|---------|
| `code` | quality_gate, review_rejection, implementation_error | ci_failure, plan_validation, hitl_escalation |
| `config` | ci_failure, quality_gate | review_rejection, plan_validation |
| `instruction` | ALL categories | (none — instructions are general) |
| `knowledge` | plan_validation, review_rejection | quality_gate, ci_failure |

### Implementation

In `MemoryScorer.update_scores()`:

```python
RELEVANCE_MATRIX = {
    MemoryType.CODE: {"quality_gate", "review_rejection", "implementation_error"},
    MemoryType.CONFIG: {"ci_failure", "quality_gate"},
    MemoryType.INSTRUCTION: None,  # scored on everything
    MemoryType.KNOWLEDGE: {"plan_validation", "review_rejection"},
}

def _is_relevant(self, item_type: MemoryType, failure_category: str | None) -> bool:
    if failure_category is None:  # success — always relevant
        return True
    relevant = RELEVANCE_MATRIX.get(item_type)
    if relevant is None:  # instruction type — always relevant
        return True
    return failure_category in relevant
```

When not relevant, the item's score is not updated but `appearances` still increments (it was present, just not judged).

---

## Part 4: Informed Compaction

**Bead:** ops-audit-fixes-1sx (P0)

### Change to `_compact_digest()`

Currently compaction uses keyword-overlap dedup + a cheap model call to summarize. Add score-informed curation as a third step between dedup and summarization.

### Curation prompt

For items below the eviction threshold OR with `surprising: true` in recent trail:

```
You are curating a memory digest for an AI coding agent.

The following memory item has a confidence score of {score} after {appearances} appearances.

Content: {item_content}

Score trail (most recent):
{formatted_trail}

Based on the evidence:
- If the failures are unrelated to this memory's content → KEEP
- If the memory's advice is sound but agents aren't following it → REPHRASE (suggest better wording)
- If the memory is genuinely unhelpful or outdated → EVICT

Respond with exactly one of: KEEP, REPHRASE: <new text>, or EVICT
```

### Eviction rules

1. `score < 0.3 AND appearances >= 5` → send to curation prompt
2. `score < 0.15 AND appearances >= 10` → auto-evict (confidently useless, skip model call)
3. `surprising: true` in last 3 trail entries → send to curation prompt regardless of score
4. `appearances < 5` → never evict (insufficient data)

### Rephrased items

When the model returns `REPHRASE: <new text>`:
1. Replace the item content in the digest
2. Reset score to 0.5 (fresh start for the new wording)
3. Keep the trail (provenance of why it was rephrased)
4. Add a trail entry: `{"outcome": "rephrased", "delta": 0, "summary": "Compaction rephrased due to low score"}`

---

## Part 5: Harness Insights Auto-File

**Bead:** ops-audit-fixes-arn (P1)

### Current state

`generate_suggestions()` produces `ImprovementSuggestion` objects but they're only surfaced on the dashboard.

### Change

After `generate_suggestions()` in the harness insights sync path, file each new suggestion as a GitHub issue:

```python
for suggestion in suggestions:
    if suggestion.id not in filed_suggestions:
        issue_number = await prs.create_issue(
            f"[Harness Insight] {suggestion.title}",
            suggestion.body,
            labels=list(config.improve_label),
        )
        filed_suggestions.add(suggestion.id)
```

Track filed suggestions in `.hydraflow/memory/filed_harness_suggestions.json` (dedup set, same pattern as `filed_patterns.json`).

### Where to wire

Add to `harness_insights.py` or call from the background loop that already aggregates harness data. The `_do_work` method in the metrics sync loop already has access to harness insights — extend it.

---

## Part 6: Hindsight Recall All 5 Banks

**Bead:** ops-audit-fixes-o06 (P1)

### Current state

Only `Bank.LEARNINGS` is recalled. Four other banks (`RETROSPECTIVES`, `REVIEW_INSIGHTS`, `HARNESS_INSIGHTS`, `TROUBLESHOOTING`) are write-only.

### Change

In `base_runner.py:_inject_manifest_and_memory()`, after the learnings recall, add:

```python
if hindsight and query_context:
    # Already doing learnings recall...

    # Add retrospective context (what worked/didn't on similar past issues)
    retro_memories = await recall_safe(hindsight, Bank.RETROSPECTIVES, query_context, limit=3)
    if retro_memories:
        sections.append(f"## Past Retrospectives\n\n{format_memories_as_markdown(retro_memories)}")

    # Add troubleshooting patterns (known fixes for similar failures)
    trouble_memories = await recall_safe(hindsight, Bank.TROUBLESHOOTING, query_context, limit=3)
    if trouble_memories:
        sections.append(f"## Known Troubleshooting Patterns\n\n{format_memories_as_markdown(trouble_memories)}")
```

Cap total injected memory at `config.max_memory_prompt_chars` across all banks. Prioritize learnings > troubleshooting > retrospectives > review insights.

---

## Part 7: HITL Correction Learning

**Bead:** ops-audit-fixes-0n1 (P1)

### Current state

HITL corrections run an agent with human correction text. The correction text is lost after the fix cycle. Only agent-volunteered memory suggestions are captured.

### Change

In `hitl_phase.py`, after a successful HITL correction:

```python
if result.success and correction_text:
    memory_title = f"HITL lesson: {issue.title[:60]}"
    memory_body = (
        f"**Type:** instruction\n"
        f"**Learning:** {correction_text}\n"
        f"**Context:** Human correction applied to issue #{issue.id}. "
        f"Original cause: {cause}. Fix was successful.\n"
    )
    await safe_file_memory_suggestion(
        prs, config, memory_title, memory_body, memory_type="instruction"
    )
```

HITL corrections are filed as `instruction` type (highest trust — human-provided) and go through the normal memory pipeline.

---

## Part 8: Transcript Summary Parsing

**Bead:** ops-audit-fixes-btn (P2)

### Current state

`TranscriptSummarizer` posts structured markdown with sections: Key Decisions, Patterns Discovered, Errors Encountered, Workarounds Applied, Codebase Insights. Posted as issue comments for humans.

### Change

After posting the comment, parse the "Patterns Discovered" and "Codebase Insights" sections. For each non-empty item, file a `[Memory]` issue with type `knowledge`:

```python
patterns = extract_section(summary, "Patterns Discovered")
insights = extract_section(summary, "Codebase Insights")

for item in patterns + insights:
    if len(item.strip()) > 20:  # skip trivial entries
        await safe_file_memory_suggestion(
            prs, config,
            f"Transcript insight: {item[:60]}",
            f"**Type:** knowledge\n**Learning:** {item}\n**Context:** Extracted from agent transcript for issue #{issue_id}.",
            memory_type="knowledge",
        )
```

Rate-limit to max 3 memory items per transcript to avoid flooding.

---

## Part 9: Review Rejection Detail Capture

**Bead:** ops-audit-fixes-du2 (P2)

### Current state

When a PR is rejected, the `ReviewRecord` captures `verdict`, `summary`, and `categories` (keyword labels). The raw reviewer feedback text (specific actionable instructions) is lost after the retry cycle.

### Change

In `review_phase.py:_record_review_insight()`, also store the raw feedback:

```python
record = ReviewRecord(
    verdict=result.verdict,
    summary=result.summary,
    categories=extract_categories(result.summary),
    raw_feedback=result.review_body,  # NEW: preserve the full text
    issue_number=issue.id,
    pr_number=pr.number,
)
```

Add `raw_feedback: str = ""` field to `ReviewRecord`. This data feeds into the Hindsight `Bank.REVIEW_INSIGHTS` store and becomes available for semantic recall.

---

## Part 10: Improvement Proposal Verification

**Bead:** ops-audit-fixes-vo3 (P2)

### Current state

`[Review Insight]` issues are filed and marked in `proposed_categories.json` to prevent re-filing. But there's no follow-up to check if the pattern frequency actually decreased.

### Change

In the review insights analysis cycle, after detecting patterns:

```python
for category, count in pattern_counts.items():
    if category in proposed_categories:
        proposal_date = proposed_categories[category]["date"]
        pre_count = proposed_categories[category].get("pre_count", count)

        if count < pre_count * 0.5:
            logger.info("Review insight %s: pattern reduced by >50%% since proposal", category)
            proposed_categories[category]["verified"] = True
        elif (now - proposal_date).days > 30 and count >= pre_count:
            logger.warning("Review insight %s: pattern unchanged 30 days after proposal", category)
            # Re-file with higher priority
            await prs.create_issue(
                f"[Review Insight - Unresolved] {category}",
                f"Pattern '{category}' was proposed {proposal_date} but frequency has not decreased.",
                labels=list(config.hitl_label),  # escalate to human
            )
```

Store `pre_count` at filing time. Check periodically. Escalate if no improvement after 30 days.

---

## Part 11: Per-Context Scoring (Phase 2)

**Bead:** ops-audit-fixes-f8c (P2)

### Current state (after Parts 1-4)

Items have a single global score.

### Future change

Replace the single score with per-context scores where context is derived from the issue:

```python
def _classify_context(issue: Task) -> str:
    """Classify task into a context bucket for scoring."""
    labels = {t.lower() for t in issue.tags}
    if "bug" in labels or "fix" in labels:
        return "bugfix"
    if "refactor" in labels:
        return "refactor"
    if "docs" in labels or "documentation" in labels:
        return "docs"
    return "feature"  # default
```

Item scores become `dict[str, float]` keyed by context. Digest construction samples per-context. This is deferred because it requires:
1. Reliable task classification
2. Enough per-context data to be meaningful
3. Changes to digest construction (currently static, would need to be dynamic per-task)

---

## Implementation Order

| Phase | Beads | Dependency |
|-------|-------|------------|
| 1 | 0lm (outcome tracking) | None — foundation |
| 2 | 6l1 (item confidence + trail) | Depends on 0lm |
| 3 | 1cz (noise filtering) | Depends on 6l1 |
| 4 | 1sx (informed compaction) | Depends on 6l1 |
| 5 | arn (harness auto-file) | Independent |
| 6 | o06 (Hindsight all banks) | Independent |
| 7 | 0n1 (HITL learning) | Independent |
| 8 | btn (transcript parsing) | Independent |
| 9 | du2 (rejection details) | Independent |
| 10 | vo3 (proposal verification) | Independent |
| 11 | f8c (per-context scoring) | Depends on 6l1, deferred |

Phases 1-4 are sequential (scoring foundation). Phases 5-10 are independent and can be parallelized.

## Testing Strategy

- **Outcome tracking:** Unit test `record_outcome()` writes correct JSONL. Integration test: mock post_merge_handler flow records outcome.
- **Item scoring:** Unit test score updates, decay, trail management, eviction candidates. Property test: score always in [0,1].
- **Noise filtering:** Parametrized test: `(memory_type, failure_category) -> should_score` matrix.
- **Informed compaction:** Test curation prompt is built correctly with trail data. Mock the model call, verify keep/rephrase/evict handling.
- **Harness auto-file:** Test suggestion -> issue creation with dedup guard.
- **Hindsight recall:** Test that all 5 banks produce prompt sections. Test priority ordering and cap.
- **HITL learning:** Test that successful correction files memory issue with correct type.

## Files to Create/Modify

| File | Action |
|------|--------|
| `src/memory_scoring.py` | **Create** — MemoryScorer class, record_outcome, RELEVANCE_MATRIX |
| `src/memory.py` | **Modify** — integrate scoring into _compact_digest, add curation step |
| `src/post_merge_handler.py` | **Modify** — call record_outcome at merge |
| `src/review_phase.py` | **Modify** — call record_outcome at HITL escalation, store raw feedback |
| `src/implement_phase.py` | **Modify** — capture digest_hash, call record_outcome at max attempts |
| `src/base_runner.py` | **Modify** — recall from all Hindsight banks |
| `src/hitl_phase.py` | **Modify** — auto-file memory from correction text |
| `src/harness_insights.py` | **Modify** — auto-file suggestions as issues |
| `src/transcript_summarizer.py` | **Modify** — parse and file patterns/insights |
| `src/models.py` | **Modify** — add raw_feedback to ReviewRecord |
| `src/review_insights.py` | **Modify** — verification tracking |
| `tests/test_memory_scoring.py` | **Create** — full test suite |
| `tests/test_memory_loops.py` | **Create** — integration tests for closed loops |
