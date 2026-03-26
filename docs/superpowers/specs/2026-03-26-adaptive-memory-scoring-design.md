# Adaptive Memory Scoring Design — Dark Factory Learning System

**Date:** 2026-03-26
**Status:** Draft
**Beads:** ops-audit-fixes-0lm, 6l1, 1cz, 1sx, arn, o06, 0n1, btn, du2, vo3, f8c, wnm, cbz, he7, pad, jyr, az7, ins, t9o, 0kc, g2u, dqh, 96i, d9m

## Problem

HydraFlow's memory system captures learnings but never evaluates whether they help. Memories accumulate without scoring, demotion, or eviction based on outcomes. Seven of eight observation channels are open loops. The system doesn't monitor its own performance trajectory, can't self-correct between runs, and has no mechanism for cross-project knowledge sharing. For a dark factory — fully autonomous, lights-out software production — this means every project learns from scratch and the factory can't improve as a whole.

## Goal

Build a three-tier learning system that replicates how a self-improving human team operates:

1. **Tier 1 (Reactive):** Score memories by outcomes, decay stale knowledge, evict what doesn't help. The immune system.
2. **Tier 2 (Active):** Self-monitor performance trends, auto-adjust safe parameters, escalate unsafe changes as HITL issues, track all decisions with audit trails, and verify that adjustments actually worked. The nervous system.
3. **Tier 3 (Organizational):** Share knowledge across projects. Promote learnings that work everywhere, allow local overrides where global knowledge doesn't apply. The organizational brain.

## Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                  TIER 3: CROSS-PROJECT               │
│                                                      │
│   Global Memory Store ◄──── Promotion (3+ projects)  │
│         │                                            │
│         ▼                                            │
│   ┌─────────┐  ┌─────────┐  ┌─────────┐             │
│   │Project A│  │Project B│  │Project C│  ...         │
│   │ Local   │  │ Local   │  │ Local   │              │
│   │ Memory  │  │ Memory  │  │ Memory  │              │
│   │ + Override│ │ + Override│ │ + Override│            │
│   └────┬────┘  └────┬────┘  └────┬────┘             │
│        │            │            │                    │
└────────┼────────────┼────────────┼───────────────────┘
         │            │            │
┌────────┼────────────┼────────────┼───────────────────┐
│        ▼            ▼            ▼   TIER 2: ACTIVE   │
│                                                       │
│   Health Monitor Loop (every 2 hours)                 │
│     ├── Trend analysis (outcomes, scores, harness)    │
│     ├── Safe auto-adjust (within bounds)              │
│     ├── HITL issue for unsafe changes                 │
│     ├── Decision audit trail                          │
│     ├── Outcome verification (did adjustment help?)   │
│     ├── Knowledge gap detection                       │
│     └── Sentry metrics emission                       │
│                                                       │
└───────────────────────┬───────────────────────────────┘
                        │
┌───────────────────────┼───────────────────────────────┐
│                       ▼          TIER 1: REACTIVE      │
│                                                        │
│   Outcome Tracking ──► Item Scoring ──► Compaction     │
│     (terminal states)   (batting avg)    (keep/rephrase│
│                         (decay)           /evict)      │
│                         (noise filter)                 │
│                         (surprise flag)                │
│                         (score trail)                  │
│                                                        │
│   Closed Loops:                                        │
│     Harness insights ──► auto-file issues              │
│     Hindsight 5 banks ──► prompt injection             │
│     HITL corrections ──► memory items                  │
│     Transcript summaries ──► memory items              │
│     Review rejections ──► stored with detail           │
│     Improvement proposals ──► verified                 │
│                                                        │
└────────────────────────────────────────────────────────┘
```

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

---

## Part 12: Health Monitor Background Loop

**Bead:** ops-audit-fixes-wnm (P0)

### New file: `src/health_monitor_loop.py`

A background loop (extends `BaseBackgroundLoop`) running on `config.health_monitor_interval` (default: 7200s / 2 hours).

### `_do_work()` method

Each cycle:

1. **Load recent data** — last N outcomes from `outcomes.jsonl`, current `item_scores.json`, recent `harness_failures.jsonl`
2. **Compute trend metrics:**
   - `first_pass_rate` = successes / total outcomes (last 50 issues)
   - `avg_memory_score` = mean of all item scores
   - `surprise_rate` = surprising trail entries / total trail entries (last 50)
   - `eviction_rate` = items evicted in last compaction cycle
   - `hitl_escalation_rate` = HITL outcomes / total outcomes (last 50)
   - `stale_item_count` = items with score < 0.3 and appearances >= 5
3. **Compare against thresholds** — each metric has a "healthy" range
4. **Act** — auto-adjust safe knobs or file HITL recommendations

### Trend thresholds

```python
HEALTH_THRESHOLDS = {
    "first_pass_rate": {"healthy": (0.3, 0.8), "warn_low": 0.2, "warn_high": 0.9},
    "avg_memory_score": {"healthy": (0.4, 0.7), "warn_low": 0.3},
    "surprise_rate": {"healthy": (0.0, 0.15), "warn_high": 0.2},
    "hitl_escalation_rate": {"healthy": (0.0, 0.15), "warn_high": 0.2},
}
```

---

## Part 13: Safe Auto-Adjustment

**Bead:** ops-audit-fixes-cbz (P1)

### Tunable parameters with bounds

```python
TUNABLE_BOUNDS: dict[str, tuple[int | float, int | float]] = {
    "max_quality_fix_attempts": (1, 5),
    "agent_timeout": (120, 900),
    "memory_compaction_threshold": (0.15, 0.45),
    "memory_sync_interval": (1800, 7200),
    "compaction_decay_factor": (0.90, 0.99),
}
```

### Adjustment rules

| Condition | Parameter | Direction | Step |
|-----------|-----------|-----------|------|
| first_pass_rate < 0.2 | max_quality_fix_attempts | +1 | int |
| first_pass_rate > 0.9 | max_quality_fix_attempts | -1 | int |
| surprise_rate > 0.2 | compaction_decay_factor | +0.02 (slower decay) | float |
| avg_memory_score < 0.3 | memory_compaction_threshold | -0.05 (evict more) | float |
| stale_item_count > 20 | trigger compaction cycle | immediate | action |
| agent timeout rate > 10% | agent_timeout | +60s | int |

### Application

Auto-adjustments are applied via `object.__setattr__` on the live config (same pattern used by env var overrides). The config is NOT persisted to disk — adjustments are session-scoped and re-derived each restart from the data. This prevents config drift.

---

## Part 14: HITL Recommendations for Unsafe Changes

**Bead:** ops-audit-fixes-he7 (P1)

### What's "unsafe"

Any adjustment that changes agent behavior significantly:
- Modifying prompt templates or agent instructions
- Changing quality gate strictness beyond the tunable bounds
- Disabling a phase or loop
- Changing the model used for any agent
- Any adjustment that would affect ALL projects in the factory

### Issue format

```markdown
## [Health Monitor] {metric} at {value} — recommendation

### Observation
Over the last {window} issues, {metric} measured {value}.
This is {above/below} the healthy range of {range}.

### Current Config
{relevant config values}

### Recommendation
{specific actionable recommendation}

### Evidence
{last 10 relevant outcome/failure summaries}

### Decision Required
- [ ] Approve recommendation
- [ ] Reject with reason
- [ ] Modify and apply

---
Filed by HydraFlow Health Monitor. Decision ID: {decision_id}
```

Labels: `hydraflow-hitl` (requires human review). The HITL phase processes it like any other correction.

---

## Part 15: Decision Audit Trail

**Bead:** ops-audit-fixes-pad (P1)

### Storage: `.hydraflow/memory/decisions.jsonl`

```json
{
  "decision_id": "adj-0042",
  "timestamp": "2026-03-26T10:00:00Z",
  "type": "auto_adjust",
  "project": "8thlight/keystone",
  "parameter": "max_quality_fix_attempts",
  "before": 2,
  "after": 3,
  "reason": "first_pass_rate 0.18 below threshold 0.2 over last 50 issues",
  "evidence_summary": "26 of 50 issues needed retry; top failure: quality_gate (15), review_rejection (8)",
  "evidence_ids": ["outcome-101", "outcome-115"],
  "outcome_verified": null,
  "outcome_verification_date": null,
  "reverted": false,
  "revert_reason": null
}
```

For HITL recommendations:
```json
{
  "decision_id": "rec-0015",
  "type": "hitl_recommendation",
  "issue_number": 5742,
  "status": "pending",
  "human_action": null,
  "human_action_date": null
}
```

### Memory integration

Decision records are also filed as `[Memory]` items with type `instruction` after verification:
- Auto-adjustment that improved metrics → "Increasing quality fix attempts to 3 improved first-pass rate from 18% to 35%"
- Auto-adjustment that was reverted → "Increasing quality fix attempts to 3 did not improve outcomes — reverted"

This ensures the knowledge from self-adjustment feeds back into the memory system itself.

---

## Part 16: Decision Outcome Verification

**Bead:** ops-audit-fixes-jyr (P1)

### Verification cycle

After each auto-adjustment, the health monitor tracks:
- `verification_window`: next 20 issues after adjustment
- `baseline_metric`: the metric value that triggered the adjustment
- `target_metric`: the expected improved value

After the window completes:

```python
if improved >= 0.1 * abs(baseline - target):
    # Adjustment helped — mark verified, file positive memory
    decision["outcome_verified"] = "improved"
    file_memory(f"Adjustment {param} {before}→{after} improved {metric} by {delta}")
elif improved < 0:
    # Adjustment made things worse — revert
    revert_adjustment(decision)
    decision["outcome_verified"] = "reverted"
    decision["revert_reason"] = f"{metric} worsened from {baseline} to {current}"
    file_memory(f"Adjustment {param} {before}→{after} worsened {metric} — reverted")
else:
    # No significant change — keep but note
    decision["outcome_verified"] = "neutral"
```

---

## Part 17: Knowledge Gap Detection

**Bead:** ops-audit-fixes-az7 (P2)

### Active learning: identify what's NOT in memory

During each health monitor cycle, analyze failures that don't match ANY existing memory item:

```python
for failure in recent_failures:
    # Check if any memory item's content is semantically related
    related = [item for item in memory_items if overlap(failure.details, item.content) > 0.3]
    if not related:
        knowledge_gaps.append({
            "failure_category": failure.category,
            "details": failure.details,
            "frequency": count_similar(failure, recent_failures),
        })

# For gaps appearing 3+ times: file a [Memory] issue proposing new knowledge
for gap in knowledge_gaps:
    if gap["frequency"] >= 3:
        await file_memory_suggestion(
            f"Knowledge gap: {gap['failure_category']} failures unaddressed",
            f"**Type:** instruction\n**Learning:** {synthesize_learning(gap)}\n"
            f"**Context:** {gap['frequency']} recent failures with no matching memory item.",
        )
```

This is the "active learning" component — the system doesn't just score existing knowledge, it identifies where knowledge is MISSING.

---

## Part 18: Global Memory Store

**Bead:** ops-audit-fixes-ins (P1)

### Architecture

The factory operates across multiple repos. Each repo has its own `.hydraflow/memory/` directory (project-local). A new global store lives at `~/.hydraflow/global_memory/`:

```
~/.hydraflow/global_memory/
  ├── digest.md              # global knowledge digest
  ├── items/                 # global memory items
  ├── item_scores.json       # global item scores
  ├── outcomes.jsonl          # aggregated outcomes across projects
  └── decisions.jsonl         # factory-wide decision audit trail
```

### Prompt injection

In `base_runner.py:_inject_manifest_and_memory()`, inject BOTH digests:

```python
# Project-local memory (existing)
local_digest = load_memory_digest(config.memory_dir)

# Global factory memory (new)
global_dir = Path(config.data_root) / "global_memory"
global_digest = load_memory_digest(global_dir)

# Combine: global first (baseline), then local (overrides)
combined = f"## Factory-Wide Knowledge\n\n{global_digest}\n\n## Project-Specific Knowledge\n\n{local_digest}"
```

Cap combined at `config.max_memory_prompt_chars`. Prioritize local over global when truncating (project-specific knowledge is more relevant).

---

## Part 19: Project-Local Overrides

**Bead:** ops-audit-fixes-t9o (P1)

### Override mechanism

A project can override a global memory item by creating a local item with a `overrides_global: <item_id>` field:

```json
{
  "id": "local-42",
  "content": "This repo uses Prisma, NOT raw SQL (overrides global SQL guidance)",
  "overrides_global": "global-15",
  "memory_type": "instruction"
}
```

During digest construction, when a local item overrides a global item, the global item is excluded from the combined digest for this project.

### Auto-detection

When the scoring system detects a global item consistently scoring poorly on ONE project but well on others:

```python
for item_id, project_scores in cross_project_scores.items():
    global_avg = mean(all_scores)
    for project, project_score in project_scores.items():
        if global_avg > 0.6 and project_score < 0.3 and appearances >= 5:
            # Global item works everywhere except this project
            file_override_suggestion(project, item_id, project_score, global_avg)
```

This files a `[Memory]` issue in the project repo suggesting a local override.

---

## Part 20: Cross-Project Promotion

**Bead:** ops-audit-fixes-0kc (P2)

### Promotion criteria

A project-local memory item gets promoted to global when:
1. The SAME learning (>70% keyword overlap) exists in 3+ project-local stores
2. Each instance has score >= 0.6 with >= 5 appearances
3. The learning is type `instruction` or `knowledge` (not `config` — config is inherently project-specific)

### Promotion process

```python
# During global memory sync (new loop or extension of existing)
for candidate in find_promotion_candidates(all_project_items):
    if candidate.project_count >= 3 and candidate.min_score >= 0.6:
        # Create global item
        global_item = create_global_item(
            content=candidate.best_version,  # highest-scoring variant
            source_projects=candidate.projects,
            promotion_evidence=candidate.scores,
        )
        # File as [Memory] issue on the factory-level tracker
        await file_global_memory(global_item)
```

### Demotion

Global items that score < 0.3 across ALL projects get evicted from global store. Global items that score < 0.3 on MOST projects but well on 1-2 get demoted back to project-local for those specific projects.

---

## Part 21: Local Override Detection

**Bead:** ops-audit-fixes-g2u (P2)

### Automatic exception detection

The health monitor (Tier 2) compares global item scores across projects:

```python
for global_item in global_store.items():
    project_scores = {}
    for project in factory.projects:
        project_scores[project.slug] = get_item_score(project, global_item.id)

    outliers = [p for p, s in project_scores.items() if s < 0.3]
    healthy = [p for p, s in project_scores.items() if s >= 0.5]

    if len(healthy) >= 2 and len(outliers) >= 1:
        for outlier_project in outliers:
            file_override_recommendation(
                project=outlier_project,
                global_item=global_item,
                project_score=project_scores[outlier_project],
                global_avg=mean(project_scores.values()),
            )
```

Override recommendations are HITL issues — a human must approve creating the exception.

---

## Part 22: Sentry Metrics for Memory Health

**Beads:** ops-audit-fixes-dqh + 96i + d9m (P1)

### Custom measurements emitted per health monitor cycle

```python
try:
    import sentry_sdk
    sentry_sdk.set_measurement("memory.avg_score", avg_score)
    sentry_sdk.set_measurement("memory.first_pass_rate", first_pass_rate)
    sentry_sdk.set_measurement("memory.surprise_rate", surprise_rate)
    sentry_sdk.set_measurement("memory.eviction_count", evicted_count)
    sentry_sdk.set_measurement("memory.stale_items", stale_count)
    sentry_sdk.set_measurement("memory.auto_adjustments", adjustment_count)
    sentry_sdk.set_measurement("memory.knowledge_gaps", gap_count)
    sentry_sdk.set_measurement("memory.global_items", global_item_count)
    sentry_sdk.set_measurement("memory.local_overrides", override_count)
except ImportError:
    pass
```

### Recommended Sentry alerts

| Alert | Condition | Action |
|-------|-----------|--------|
| Score drift | avg_score drops >15% over 24h | Slack |
| Learning stall | no new memory items in 7 days | Slack |
| Factory divergence | one project's first_pass_rate diverges >30% from factory avg | Investigate |
| Adjustment storm | >5 auto-adjustments in 24h | Throttle + HITL review |
| Memory bloat | global digest >10KB | Trigger compaction |

---

## Implementation Order

### Tier 1: Reactive Learning (foundation — sequential)

| Phase | Bead | Description | Dependency |
|-------|------|-------------|------------|
| 1 | 0lm | Outcome tracking | None |
| 2 | 6l1 | Item confidence + score trail | 0lm |
| 3 | 1cz | Noise filtering matrix | 6l1 |
| 4 | 1sx | Informed compaction | 6l1 |

### Tier 1: Close Open Loops (independent — parallelizable)

| Phase | Bead | Description | Dependency |
|-------|------|-------------|------------|
| 5 | arn | Harness insights auto-file | None |
| 6 | o06 | Hindsight recall all 5 banks | None |
| 7 | 0n1 | HITL correction learning | None |
| 8 | btn | Transcript summary parsing | None |
| 9 | du2 | Review rejection detail capture | None |
| 10 | vo3 | Improvement proposal verification | None |

### Tier 2: Active Learning (depends on Tier 1 scoring)

| Phase | Bead | Description | Dependency |
|-------|------|-------------|------------|
| 11 | wnm | Health monitor loop | 0lm, 6l1 |
| 12 | cbz | Safe auto-adjustment | wnm |
| 13 | he7 | HITL recommendations | wnm |
| 14 | pad | Decision audit trail | cbz, he7 |
| 15 | jyr | Decision outcome verification | pad |
| 16 | az7 | Knowledge gap detection | wnm, 6l1 |
| 17 | dqh | Sentry metrics for memory health | wnm |

### Tier 3: Cross-Project Learning (depends on Tier 2)

| Phase | Bead | Description | Dependency |
|-------|------|-------------|------------|
| 18 | ins | Global memory store | 6l1 |
| 19 | t9o | Project-local overrides | ins |
| 20 | 0kc | Cross-project promotion | ins, 6l1 |
| 21 | g2u | Local override detection | ins, wnm |

### Per-context scoring (depends on Tier 1 + data)

| Phase | Bead | Description | Dependency |
|-------|------|-------------|------------|
| 22 | f8c | Per-context scoring | 6l1, data accumulation |

## Testing Strategy

### Tier 1
- **Outcome tracking:** Unit test `record_outcome()` writes correct JSONL. Integration test: mock post_merge_handler flow records outcome.
- **Item scoring:** Unit test score updates, decay, trail management, eviction candidates. Property test: score always in [0,1].
- **Noise filtering:** Parametrized test: `(memory_type, failure_category) -> should_score` matrix.
- **Informed compaction:** Test curation prompt is built correctly with trail data. Mock the model call, verify keep/rephrase/evict handling.
- **Loop closures:** Test each loop independently — suggestion → issue creation with dedup.

### Tier 2
- **Health monitor:** Test trend computation from fixture data. Test threshold crossing → correct action.
- **Auto-adjustment:** Parametrized test: `(metric, value, threshold) -> (parameter, direction, step)`. Test bounds enforcement.
- **Decision audit:** Test JSONL write, outcome verification after window, revert logic.
- **Knowledge gaps:** Test gap detection when failures have no matching memory items.

### Tier 3
- **Global store:** Test digest construction with both global and local. Test local override exclusion.
- **Promotion:** Test candidate detection across mock project stores. Test 3+ project threshold.
- **Override detection:** Test outlier detection with fixture cross-project scores.

## Files to Create/Modify

| File | Action | Tier |
|------|--------|------|
| `src/memory_scoring.py` | **Create** — MemoryScorer, record_outcome, RELEVANCE_MATRIX | 1 |
| `src/health_monitor_loop.py` | **Create** — HealthMonitorLoop, trend analysis, auto-adjust | 2 |
| `src/global_memory.py` | **Create** — GlobalMemoryStore, promotion, override detection | 3 |
| `src/memory.py` | **Modify** — integrate scoring into _compact_digest, curation step | 1 |
| `src/post_merge_handler.py` | **Modify** — call record_outcome at merge | 1 |
| `src/review_phase.py` | **Modify** — call record_outcome at HITL escalation, raw feedback | 1 |
| `src/implement_phase.py` | **Modify** — capture digest_hash, record_outcome at max attempts | 1 |
| `src/base_runner.py` | **Modify** — recall all Hindsight banks, inject global+local digest | 1,3 |
| `src/hitl_phase.py` | **Modify** — auto-file memory from correction text | 1 |
| `src/harness_insights.py` | **Modify** — auto-file suggestions as issues | 1 |
| `src/transcript_summarizer.py` | **Modify** — parse and file patterns/insights | 1 |
| `src/models.py` | **Modify** — add raw_feedback to ReviewRecord | 1 |
| `src/review_insights.py` | **Modify** — verification tracking | 1 |
| `src/config.py` | **Modify** — add health_monitor_interval, tunable bounds | 2 |
| `src/orchestrator.py` | **Modify** — register health_monitor_loop | 2 |
| `tests/test_memory_scoring.py` | **Create** — Tier 1 test suite | 1 |
| `tests/test_health_monitor.py` | **Create** — Tier 2 test suite | 2 |
| `tests/test_global_memory.py` | **Create** — Tier 3 test suite | 3 |
| `tests/test_memory_loops.py` | **Create** — integration tests for closed loops | 1 |
