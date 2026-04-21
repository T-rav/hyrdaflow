# Prompt Audit — 2026-04-20

## Summary

- Prompts audited: 26
- High: 25
- Medium: 1
- Low: 0
- Unscored: 0
- Most common Fails by criterion: [3, 8, 1]

<!-- docs/_prompt_audit_rubric.md — Section 2 of the generated report -->
## Rubric reference

| # | Criterion | Automated rule |
|---|---|---|
| 1 | Leads with the request | First non-whitespace sentence (pre-tag) contains an imperative from `{produce, return, generate, classify, review, decide, output, propose, write, summarize}`. |
| 2 | Specific | 3/3 of: output-artifact noun; named fields or schema; success criteria phrasing. |
| 3 | XML tags | ≥3 distinct `<content>...</content>` pairs (excluding `<thinking>` / `<scratchpad>`). |
| 4 | Examples where applicable | If structured output cues present, `<example>` or `Example:` required. |
| 5 | Output contract | ≥1 of: `respond with`, `do not`, `no prose`, `return only`, `output format`, `the output must`. |
| 6 | Placement of long context | ≥10K-char prompts: largest tagged block must end before the last imperative. |
| 7 | CoT scaffolded | Decision verbs present → require `<thinking>` / `<scratchpad>` / `think step by step`. |
| 8 | Edge cases named | ≥1 of: `if empty/missing/truncated/unclear/no …`, `when the … is not/cannot/fails`, `otherwise,`, `in case of`, `fallback`, `do not assume`. |

Severity: **High** when 2+ Fails, or any Fail on #1 or #6. **Medium** when 1 Fail or 3+ Partials. **Low** otherwise. **Unscored** for builders that can't render under the audit loader.

## Inventory

| Prompt | Category | File:Line | Severity | Fails | Partials |
|---|---|---|---|---|---|
| `adr_reviewer` | Adjacent | src/adr_reviewer.py:273 | High | 3,7,8 | 2 |
| `arch_compliance` | Adjacent | src/arch_compliance.py:15 | High | 3,8 | 1 |
| `conflict_build` | Adjacent | src/conflict_prompt.py:19 | High | 1,3,8 | 2 |
| `conflict_rebuild` | Adjacent | src/conflict_prompt.py:71 | High | 1,3,8 | 2 |
| `diagnostic_runner` | Adjacent | src/diagnostic_runner.py:32 | High | 1,2,3,4,7,8 | — |
| `expert_council_vote` | Adjacent | src/expert_council.py:278 | High | 1,3,4,5,7,8 | 2 |
| `spec_match_requirements_gap` | Adjacent | src/spec_match.py:108 | High | 1,2,3,8 | — |
| `test_adequacy` | Adjacent | src/test_adequacy.py:13 | High | 2,3,8 | 1 |
| `hitl_build_prompt` | HITL | src/hitl_runner.py:175 | High | 3,8 | 1,2 |
| `agent_build_prompt_first_attempt` | Implement | src/agent.py:572 | High | 1,3,4,8 | — |
| `agent_build_prompt_with_prior_failure` | Implement | src/agent.py:572 | High | 1,3,4,8 | — |
| `agent_build_prompt_with_review_feedback` | Implement | src/agent.py:572 | High | 1,3,4,8 | — |
| `agent_pre_quality_review` | Implement | src/agent.py:903 | High | 3,8 | 2 |
| `agent_pre_quality_run_tool` | Implement | src/agent.py:956 | High | 1,2,3,8 | — |
| `agent_quality_fix` | Implement | src/agent.py:877 | High | 2,3,8 | 1 |
| `plan_reviewer` | Plan | src/plan_reviewer.py:233 | High | 1,3,8 | 2 |
| `planner_build_prompt_first_attempt` | Plan | src/planner.py:297 | High | 1,3 | — |
| `planner_retry` | Plan | src/planner.py:857 | High | 1,3,4 | 2 |
| `pr_unsticker_ci_fix` | Review | src/pr_unsticker.py:498 | High | 1,3,4,8 | — |
| `pr_unsticker_ci_timeout` | Review | src/pr_unsticker.py:846 | High | 1,3,4,8 | — |
| `reviewer_build_review` | Review | src/reviewer.py:676 | High | 1,3,7,8 | — |
| `reviewer_ci_fix` | Review | src/reviewer.py:473 | High | 1,2,3,7,8 | — |
| `reviewer_review_fix` | Review | src/reviewer.py:441 | High | 3,4,7,8 | — |
| `triage_build_prompt` | Triage | src/triage.py:194 | High | 1,3,4,7 | 2 |
| `triage_decomposition` | Triage | src/triage.py:511 | High | 1,3,4,7,8 | 2 |
| `diff_sanity` | Adjacent | src/diff_sanity.py:13 | Medium | 3 | 1,2 |

## Triage

### triage_build_prompt
src/triage.py:194 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 Fail · #8 Pass

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #7 failed

Excerpt (first 500 chars):

```
You are a triage agent evaluating a GitHub issue and enriching it if needed so a planning agent can succeed.

## Issue #42

**Title:** Retry transient S3 upload failures

**Body:**
Intermittent 503s from S3 during upload cause job failures. Expected: retry up to 3 times with exponential backoff. Observed: first failure kills the job. Affected: src/upload.py.

## Evaluation Criteria

Evaluate the issue against these four criteria:

1. **Clarity**: Is the issue clearly written? Can an engineer und…
```

Full rendered: [`tests/fixtures/prompts/rendered/triage_build_prompt.txt`](../tests/fixtures/prompts/rendered/triage_build_prompt.txt)

### triage_decomposition
src/triage.py:511 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 Fail · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
You are a decomposition agent. This issue has been identified as too complex for a single implementation pass.

## Issue #99

**Title:** Replatform billing to Stripe

**Body:**
Migrate from Paddle to Stripe. Includes subscription, invoicing, tax, webhooks, dashboard updates, docs.

## Instructions

Determine whether this issue should be broken into smaller, independently implementable child issues.

If YES, provide:
1. An epic title (concise summary)
2. An epic body with a checkbox list of child…
```

Full rendered: [`tests/fixtures/prompts/rendered/triage_decomposition.txt`](../tests/fixtures/prompts/rendered/triage_decomposition.txt)

## Plan

### planner_build_prompt_first_attempt
src/planner.py:297 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Pass · #5 Pass · #6 N/A · #7 N/A · #8 Pass

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed

Excerpt (first 500 chars):

```
You are a planning agent for GitHub issue #42.

## Issue: Retry transient S3 upload failures

Intermittent 503s from S3 during upload cause job failures. Expected: retry up to 3 times with exponential backoff. Observed: first failure kills the job. Affected: src/upload.py.

## Instructions

**Plan mode: FULL** — This issue requires a comprehensive plan with all sections.

You are in READ-ONLY mode for the repository. Do NOT modify any repository files.
Do NOT run any commands that change state (…
```

Full rendered: [`tests/fixtures/prompts/rendered/planner_build_prompt_first_attempt.txt`](../tests/fixtures/prompts/rendered/planner_build_prompt_first_attempt.txt)

### planner_retry
src/planner.py:857 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 N/A · #8 Pass

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed

Excerpt (first 500 chars):

```
You previously generated a plan for GitHub issue #42 but it failed validation.

## Issue: Retry transient S3 upload failures

Intermittent 503s from S3 during upload cause job failures. Expected: retry up to 3 times with exponential backoff. Observed: first failure kills the job. Affected: src/upload.py.

## Previous Plan (FAILED VALIDATION)

## Summary

Add retry logic to the upload function.

## Task Graph

### P1 — Retry wrapper
**Files:** src/upload.py (modify)
**Tests:**
- Upload with 503 r…
```

Full rendered: [`tests/fixtures/prompts/rendered/planner_retry.txt`](../tests/fixtures/prompts/rendered/planner_retry.txt)

### plan_reviewer
src/plan_reviewer.py:233 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are an adversarial plan reviewer for HydraFlow issue #42. Critique the implementation plan below across the dimensions listed. Be skeptical — your job is to find problems, not to validate work.

## Issue

**Title:** Retry transient S3 upload failures

**Body:**
Intermittent 503s from S3 during upload cause job failures. Expected: retry up to 3 times with exponential backoff. Observed: first failure kills the job. Affected: src/upload.py.

## Plan to review

## Summary

Add exponential-backof…
```

Full rendered: [`tests/fixtures/prompts/rendered/plan_reviewer.txt`](../tests/fixtures/prompts/rendered/plan_reviewer.txt)

## Implement

### agent_build_prompt_first_attempt
src/agent.py:572 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #8 failed

Excerpt (first 500 chars):

```
You are implementing GitHub issue #42.

## Issue: Retry transient S3 upload failures

Intermittent 503s on large file uploads. Expected: retry 3x with exponential backoff. Affected: src/upload.py.## Implementation Plan

Follow this plan closely. It was created by a planner agent that already analyzed the codebase.

1. Wrap upload in retry loop.
2. Use exponential backoff (1s, 2s, 4s).
3. Add test for retry behavior.

## Instructions — Test-Driven Development

Follow TDD discipline: **tests first…
```

Full rendered: [`tests/fixtures/prompts/rendered/agent_build_prompt_first_attempt.txt`](../tests/fixtures/prompts/rendered/agent_build_prompt_first_attempt.txt)

### agent_build_prompt_with_review_feedback
src/agent.py:572 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #8 failed

Excerpt (first 500 chars):

```
You are implementing GitHub issue #42.

## Issue: Retry transient S3 upload failures

Intermittent 503s on large file uploads. Expected: retry 3x with exponential backoff. Affected: src/upload.py.## Implementation Plan

Follow this plan closely. It was created by a planner agent that already analyzed the codebase.

1. Wrap upload in retry loop.
2. Use exponential backoff (1s, 2s, 4s).
3. Add test for retry behavior.## Review Feedback

A reviewer rejected the previous implementation. Address all…
```

Full rendered: [`tests/fixtures/prompts/rendered/agent_build_prompt_with_review_feedback.txt`](../tests/fixtures/prompts/rendered/agent_build_prompt_with_review_feedback.txt)

### agent_build_prompt_with_prior_failure
src/agent.py:572 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #8 failed

Excerpt (first 500 chars):

```
You are implementing GitHub issue #42.

## Issue: Retry transient S3 upload failures

Intermittent 503s on large file uploads. Expected: retry 3x with exponential backoff. Affected: src/upload.py.## Implementation Plan

Follow this plan closely. It was created by a planner agent that already analyzed the codebase.

1. Wrap upload in retry loop.
2. Use exponential backoff (1s, 2s, 4s).
3. Add test for retry behavior.## Prior Attempt Failure

Your previous implementation attempt failed with the fo…
```

Full rendered: [`tests/fixtures/prompts/rendered/agent_build_prompt_with_prior_failure.txt`](../tests/fixtures/prompts/rendered/agent_build_prompt_with_prior_failure.txt)

### agent_quality_fix
src/agent.py:877 · Severity: **High**

Scores: #1 Partial · #2 Fail · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #2 failed
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are fixing quality gate failures for issue #42: Retry transient S3 upload failures

## Quality Gate Failure Output

```
FAILED tests/test_upload.py::test_retries - AssertionError: expected 3 retries, got 1
mypy: src/upload.py:42: error: Argument 1 to 'upload' has incompatible type 'int'; expected 'str'
```

## Fix Attempt 1

1. Read the failing output above carefully.
2. Fix ALL lint, type-check, security, and test issues.
3. Do NOT skip or disable tests, type checks, or lint rules.
4. Run `…
```

Full rendered: [`tests/fixtures/prompts/rendered/agent_quality_fix.txt`](../tests/fixtures/prompts/rendered/agent_quality_fix.txt)

### agent_pre_quality_review
src/agent.py:903 · Severity: **High**

Scores: #1 Pass · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are running the Pre-Quality Review Skill for issue #42: Retry transient S3 upload failures.

Attempt: 1

Review the current branch changes thoroughly for bugs, gaps, and test coverage.

Bug check:
- look for logic errors, off-by-one mistakes, wrong comparisons, swapped arguments
- check None/null handling: are optional values dereferenced without guards?
- verify error paths: do exceptions propagate correctly? are resources cleaned up?
- check concurrency issues: race conditions, missing awa…
```

Full rendered: [`tests/fixtures/prompts/rendered/agent_pre_quality_review.txt`](../tests/fixtures/prompts/rendered/agent_pre_quality_review.txt)

### agent_pre_quality_run_tool
src/agent.py:956 · Severity: **High**

Scores: #1 Fail · #2 Fail · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #2 failed
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are running the Run-Tool Skill for issue #42: Retry transient S3 upload failures.

Attempt: 2

Run these commands in order and fix failures:
1. `make lint`
2. `make test`
3. `make quality-lite`

Rules:
- If a command fails, fix root causes and rerun from command 1
- Do not skip tests or reduce quality gates
- Keep changes scoped to this issue

Required output:
RUN_TOOL_RESULT: OK
or
RUN_TOOL_RESULT: RETRY
SUMMARY: <one-line summary>
```

Full rendered: [`tests/fixtures/prompts/rendered/agent_pre_quality_run_tool.txt`](../tests/fixtures/prompts/rendered/agent_pre_quality_run_tool.txt)

## Review

### reviewer_build_review
src/reviewer.py:676 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Pass · #5 Pass · #6 N/A · #7 Fail · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
You are reviewing PR #77 which implements issue #42.

## Issue: Retry transient S3 upload failures

Issue body summarized for token efficiency:
- Intermittent 503s on large file uploads. Expected: retry 3x with exponential backoff. Affected: src/upload.py.

[Body summarized for prompt efficiency]

## Precheck Context

No low-tier precheck context provided.

## PR Diff

### Diff Summary
- Files changed (detected): 1
- Added lines (detected): 15
- Removed lines (detected): 1
- Top changed files:
-…
```

Full rendered: [`tests/fixtures/prompts/rendered/reviewer_build_review.txt`](../tests/fixtures/prompts/rendered/reviewer_build_review.txt)

### reviewer_ci_fix
src/reviewer.py:473 · Severity: **High**

Scores: #1 Fail · #2 Fail · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 Fail · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #2 failed
- #3 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
You are fixing CI failures on PR #77 (issue #42: Retry transient S3 upload failures).

## CI Failure Summary

pytest tests/test_upload.py::test_upload_retry FAILED
AssertionError: Expected 3 upload attempts, got 1.

mypy src/upload.py:18: error: Name 'TransientError' is not defined

## Full CI Failure Logs

```
=== short test summary info ===
FAILED tests/test_upload.py::test_upload_retry - AssertionError: Expected 3 upload attempts, got 1.
```

## Fix Attempt 1

1. Read the failing CI output ab…
```

Full rendered: [`tests/fixtures/prompts/rendered/reviewer_ci_fix.txt`](../tests/fixtures/prompts/rendered/reviewer_ci_fix.txt)

### reviewer_review_fix
src/reviewer.py:441 · Severity: **High**

Scores: #1 Pass · #2 Pass · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 Fail · #8 Fail

Findings:
- #3 failed
- #4 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
You are fixing review findings on PR #77 (issue #42: Retry transient S3 upload failures).

## Review Feedback

1. Missing test for the backoff timing logic.
2. Logger call uses wrong level — should be `warning` not `info` per project standards.
3. `TransientError` is not imported; code will raise NameError at runtime.

## Instructions

1. Read the review feedback above carefully.
2. Fix every issue identified by the reviewer.
3. Run `make lint` and `make test` to verify your fixes pass.
4. Commi…
```

Full rendered: [`tests/fixtures/prompts/rendered/reviewer_review_fix.txt`](../tests/fixtures/prompts/rendered/reviewer_review_fix.txt)

### pr_unsticker_ci_fix
src/pr_unsticker.py:498 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #8 failed

Excerpt (first 500 chars):

```
You are fixing CI/quality failures for a pull request.

## Issue: Retry transient S3 upload failures
Issue URL: https://github.com/owner/repo/issues/42
PR URL: https://github.com/owner/repo/pull/77

## Escalation Reason

make quality FAILED: mypy error in src/upload.py:18 — Name 'TransientError' is not defined. Also pytest reports 2 failures in tests/test_upload.py.

## Instructions

Plan before fixing. Run `make quality` to see failures, then read the
failing code and its context to understand…
```

Full rendered: [`tests/fixtures/prompts/rendered/pr_unsticker_ci_fix.txt`](../tests/fixtures/prompts/rendered/pr_unsticker_ci_fix.txt)

### pr_unsticker_ci_timeout
src/pr_unsticker.py:846 · Severity: **High**

Scores: #1 Fail · #2 Pass · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #8 failed

Excerpt (first 500 chars):

```
You are fixing a CI timeout caused by hanging tests in a pull request.

## Issue: Retry transient S3 upload failures
Issue URL: https://github.com/owner/repo/issues/42
PR URL: https://github.com/owner/repo/pull/77

## Escalation Reason

CI timed out after 10 minutes. The test suite hung waiting for an async event that was never set.

## Test Isolation Output

tests/test_upload.py::test_upload_retry_backoff STARTED
... (no output for 8 minutes)
process killed after timeout

## Common Causes of Ha…
```

Full rendered: [`tests/fixtures/prompts/rendered/pr_unsticker_ci_timeout.txt`](../tests/fixtures/prompts/rendered/pr_unsticker_ci_timeout.txt)

## HITL

### hitl_build_prompt
src/hitl_runner.py:175 · Severity: **High**

Scores: #1 Partial · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are applying a human-in-the-loop correction for GitHub issue #42.

## Issue: Retry transient S3 upload failures

Planner could not generate a plan after 3 retries. Escalated to HITL.

The upload handler does not retry on transient 503 errors from S3. Each failure kills the job immediately instead of retrying with exponential backoff.

## Escalation Reason

CI test failures on upload_handler tests after merge.

## Human Guidance

Please implement retry logic with exponential backoff (max 3 at…
```

Full rendered: [`tests/fixtures/prompts/rendered/hitl_build_prompt.txt`](../tests/fixtures/prompts/rendered/hitl_build_prompt.txt)

## Adjacent

### arch_compliance
src/arch_compliance.py:15 · Severity: **High**

Scores: #1 Partial · #2 Pass · #3 Fail · #4 Pass · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are running the Architecture Compliance Check skill for issue #42: Add S3 upload retry logic.

Review the git diff below and check for architectural violations against the HydraFlow layer model.

## HydraFlow Layer Model

The codebase has four layers. Dependencies MUST flow inward only (higher layers depend on lower layers, never the reverse):

```
Layer 4 — Infrastructure/Adapters (I/O, external systems)
  pr_manager.py, worktree.py, merge_conflict_resolver.py,
  post_merge_handler.py, dash…
```

Full rendered: [`tests/fixtures/prompts/rendered/arch_compliance.txt`](../tests/fixtures/prompts/rendered/arch_compliance.txt)

### diff_sanity
src/diff_sanity.py:13 · Severity: **Medium**

Scores: #1 Partial · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Pass

Findings:
- #3 failed

Excerpt (first 500 chars):

```
You are running the Diff Sanity Check skill for issue #42: Add S3 upload retry logic.

Review the git diff below and check for the following problems:

1. **Accidental deletions** — unrelated code removed that should not have been
2. **Leftover debug code** — print(), console.log(), debugger, breakpoint(), commented-out code
3. **Missing imports** — new symbols referenced but not imported; removed code with stale imports
4. **Scope creep** — files changed that are unrelated to the issue
5. **Har…
```

Full rendered: [`tests/fixtures/prompts/rendered/diff_sanity.txt`](../tests/fixtures/prompts/rendered/diff_sanity.txt)

### test_adequacy
src/test_adequacy.py:13 · Severity: **High**

Scores: #1 Partial · #2 Fail · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #2 failed
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
You are running the Test Adequacy skill for issue #42: Add S3 upload retry logic.

Review the git diff below and assess whether the changed production code has adequate test coverage.

## Diff

```diff
diff --git a/src/upload.py b/src/upload.py
index abc1234..def5678 100644
--- a/src/upload.py
+++ b/src/upload.py
@@ -1,8 +1,20 @@
 import boto3
+import time
 
 def upload_file(bucket, key, data):
-    client = boto3.client('s3')
-    client.put_object(Bucket=bucket, Key=key, Body=data)
+    client…
```

Full rendered: [`tests/fixtures/prompts/rendered/test_adequacy.txt`](../tests/fixtures/prompts/rendered/test_adequacy.txt)

### spec_match_requirements_gap
src/spec_match.py:108 · Severity: **High**

Scores: #1 Fail · #2 Fail · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #2 failed
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```

## Requirements Gap Detection

As you implement, you may discover that the specification is incomplete —
a needed API isn't mentioned, a dependency wasn't considered, or a user
flow wasn't specified. When this happens:

1. STILL implement what you can with reasonable assumptions
2. Flag the gap using these markers:

REQUIREMENTS_GAP_START
- gap: <what's missing from the spec>
  impact: <how this affects the implementation>
  assumption: <what you assumed to proceed>
REQUIREMENTS_GAP_END

Only f…
```

Full rendered: [`tests/fixtures/prompts/rendered/spec_match_requirements_gap.txt`](../tests/fixtures/prompts/rendered/spec_match_requirements_gap.txt)

### conflict_build
src/conflict_prompt.py:19 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
Merge conflicts exist on this branch. Resolve them so `make quality` passes.

- Issue: https://github.com/owner/repo/issues/42
- PR: https://github.com/owner/repo/pull/99

Commit when done. Do not push.

## Optional: Tribal-Knowledge Suggestion

This conflict resolution may have surfaced tribal knowledge — the kind of durable,
hard-won fact a senior engineer would write on a whiteboard for a new hire
on day one. If — and ONLY if — what you learned meets ALL of these criteria:

  1. Durable: stil…
```

Full rendered: [`tests/fixtures/prompts/rendered/conflict_build.txt`](../tests/fixtures/prompts/rendered/conflict_build.txt)

### conflict_rebuild
src/conflict_prompt.py:71 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 N/A · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #8 failed

Excerpt (first 500 chars):

```
Re-apply this PR's changes onto a clean branch from main. The original branch had unresolvable merge conflicts.

- Issue: https://github.com/owner/repo/issues/42
- PR: https://github.com/owner/repo/pull/99

## Original PR Diff

Adapt these changes to the current codebase — main may have evolved.

```diff
diff --git a/src/upload.py b/src/upload.py
index abc1234..def5678 100644
--- a/src/upload.py
+++ b/src/upload.py
@@ -1,8 +1,20 @@
 import boto3
+import time
 
 def upload_file(bucket, key, data)…
```

Full rendered: [`tests/fixtures/prompts/rendered/conflict_rebuild.txt`](../tests/fixtures/prompts/rendered/conflict_rebuild.txt)

### expert_council_vote
src/expert_council.py:278 · Severity: **High**

Scores: #1 Fail · #2 Partial · #3 Fail · #4 Fail · #5 Fail · #6 N/A · #7 Fail · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #3 failed
- #4 failed
- #5 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
You are the Architect on a product council voting on the best direction for a product initiative.

## Your Perspective

You focus on long-term maintainability, clean abstractions, and consistency with existing patterns.

## Issue #42: Add S3 upload retry logic

The upload handler should retry transient S3 failures up to 3 times with exponential backoff.

## Proposed Directions

A: Use boto3 built-in retry config
B: Implement manual retry loop in application code
C: Use a third-party retry librar…
```

Full rendered: [`tests/fixtures/prompts/rendered/expert_council_vote.txt`](../tests/fixtures/prompts/rendered/expert_council_vote.txt)

### diagnostic_runner
src/diagnostic_runner.py:32 · Severity: **High**

Scores: #1 Fail · #2 Fail · #3 Fail · #4 Fail · #5 Pass · #6 N/A · #7 Fail · #8 Fail

Findings:
- #1 failed — request buried — model may misidentify task intent
- #2 failed
- #3 failed
- #4 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
# Diagnostic Analysis — Issue #42

**Title:** Retry transient S3 upload failures

**Body:**
The upload handler does not retry on transient S3 503 errors. Each failure kills the job immediately instead of retrying with exponential backoff.

**Escalation cause:** CI test failures: upload_handler tests failed after 3 implementation attempts

**Origin phase:** implement

**CI Logs:**
```
FAILED tests/test_upload.py::test_upload_retries_on_503
AssertionError: expected 3 retry attempts, got 0
```

**R…
```

Full rendered: [`tests/fixtures/prompts/rendered/diagnostic_runner.txt`](../tests/fixtures/prompts/rendered/diagnostic_runner.txt)

### adr_reviewer
src/adr_reviewer.py:273 · Severity: **High**

Scores: #1 Pass · #2 Partial · #3 Fail · #4 N/A · #5 Pass · #6 N/A · #7 Fail · #8 Fail

Findings:
- #3 failed
- #7 failed
- #8 failed

Excerpt (first 500 chars):

```
You are chairing an ADR Review Council meeting with up to 3 rounds of voting.
Your job: spawn judge agents, check for consensus, run deliberation if needed,
and output a structured final result.

## ADR Under Review
# ADR-0099: Use boto3 built-in retry config for S3 uploads

## Status
Proposed

## Context
Transient S3 503 errors cause upload jobs to fail immediately. We need retry logic.

## Decision
Use boto3's built-in retry configuration (`retries={'max_attempts': 3, 'mode': 'exponential'}`)…
```

Full rendered: [`tests/fixtures/prompts/rendered/adr_reviewer.txt`](../tests/fixtures/prompts/rendered/adr_reviewer.txt)

## Prioritized fix list

### High

- `triage_build_prompt` (Triage) — request buried — model may misidentify task intent
- `triage_decomposition` (Triage) — request buried — model may misidentify task intent
- `plan_reviewer` (Plan) — request buried — model may misidentify task intent
- `planner_build_prompt_first_attempt` (Plan) — request buried — model may misidentify task intent
- `planner_retry` (Plan) — request buried — model may misidentify task intent
- `agent_build_prompt_first_attempt` (Implement) — request buried — model may misidentify task intent
- `agent_build_prompt_with_prior_failure` (Implement) — request buried — model may misidentify task intent
- `agent_build_prompt_with_review_feedback` (Implement) — request buried — model may misidentify task intent
- `agent_pre_quality_review` (Implement)
- `agent_pre_quality_run_tool` (Implement) — request buried — model may misidentify task intent
- `agent_quality_fix` (Implement)
- `pr_unsticker_ci_fix` (Review) — request buried — model may misidentify task intent
- `pr_unsticker_ci_timeout` (Review) — request buried — model may misidentify task intent
- `reviewer_build_review` (Review) — request buried — model may misidentify task intent
- `reviewer_ci_fix` (Review) — request buried — model may misidentify task intent
- `reviewer_review_fix` (Review)
- `hitl_build_prompt` (HITL)
- `adr_reviewer` (Adjacent)
- `arch_compliance` (Adjacent)
- `conflict_build` (Adjacent) — request buried — model may misidentify task intent
- `conflict_rebuild` (Adjacent) — request buried — model may misidentify task intent
- `diagnostic_runner` (Adjacent) — request buried — model may misidentify task intent
- `expert_council_vote` (Adjacent) — request buried — model may misidentify task intent
- `spec_match_requirements_gap` (Adjacent) — request buried — model may misidentify task intent
- `test_adequacy` (Adjacent)

### Medium

- `diff_sanity` (Adjacent)

<!-- docs/_prompt_audit_handoff.md — Section 6 of the generated report -->
## Handoff to sub-projects 2–4

- **Sub-project 2 (eval gate):** inherits `tests/fixtures/prompts/*.json` + `rendered/*.txt` as the gate's input corpus + baseline.
- **Sub-project 3 (shared template):** codifies the recurring tag vocabulary `<issue>`, `<plan>`, `<diff>`, `<history>`, `<constraints>`, `<manifest>`, `<prior_review>`, `<output_format>`, `<example>`, `<thinking>`.
- **Sub-project 4 (normalization PRs):** one PR per loop (Triage / Plan / Implement / Review / HITL) + one for Adjacent. Each PR must pass the sub-project 2 gate.
