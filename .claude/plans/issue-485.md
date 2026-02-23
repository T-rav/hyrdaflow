PLAN_START

## Issue Restated

Issue #485 identifies dead code in `review_phase.py`: `_get_judge_result()` always returns `None`, making `_create_verification_issue()` unreachable. Meanwhile, `VerificationJudge.judge()` runs successfully (lines 306-318) but its `JudgeVerdict` return value is discarded. The fix is to wire the judge output through so verification issues are actually created after merge.

**Key complication**: There are two distinct models — `JudgeVerdict` (returned by `VerificationJudge.judge()`) and `JudgeResult` (expected by `_create_verification_issue()` and `verification.py`). The `_get_judge_result()` method must bridge these types.

## Files to Modify

1. **`models.py`** (line 276-285) — Add `verification_instructions: str = ""` field to `JudgeVerdict` so it carries the parsed instructions text through to the conversion step.

2. **`verification_judge.py`** (lines 60, 100-126) — Store the (possibly refined) verification instructions in `verdict.verification_instructions` before returning. Set it initially from `instructions_text` after parsing, then update to the refined version if refinement occurs.

3. **`review_phase.py`** (lines 305-332, 724-733) — Three changes:
   - **Line 308**: Capture return value: `verdict = await self._verification_judge.judge(...)`
   - **Line 321**: Pass verdict: `judge_result = await self._get_judge_result(issue, pr, verdict)`
   - **Lines 724-733**: Rewrite `_get_judge_result()` to accept a `JudgeVerdict | None` parameter and convert it to `JudgeResult | None` by mapping `CriterionResult` → `VerificationCriterion` and passing through `verification_instructions` and `summary`.
   - Add imports: `CriterionVerdict`, `JudgeVerdict`, `VerificationCriterion`

4. **`tests/test_review_phase.py`** — Update existing tests and add new ones for the conversion logic.

5. **`tests/test_verification_judge.py`** — Add test verifying `verdict.verification_instructions` is populated.

## New Files

None

## Implementation Steps

1. **Add `verification_instructions` field to `JudgeVerdict`** (`models.py:285`):
   Add `verification_instructions: str = ""` to the `JudgeVerdict` model. This allows the judge to carry the parsed instructions text through to downstream consumers.

2. **Store instructions in verdict in `VerificationJudge.judge()`** (`verification_judge.py`):
   - After `criteria_list, instructions_text = self._parse_criteria(criteria_text)` (line 60), set `verdict.verification_instructions = instructions_text`.
   - In the refinement block (around line 114), after computing `revalidate_text = refined or instructions_text`, update `verdict.verification_instructions = revalidate_text` so the final (possibly refined) instructions are captured.

3. **Update imports in `review_phase.py`**:
   Add `CriterionVerdict`, `JudgeVerdict`, and `VerificationCriterion` to the existing `from models import (...)` block.

4. **Capture judge return value** (`review_phase.py` lines 305-318):
   Change the judge call block to:
   ```python
   # Run verification judge (non-blocking)
   verdict: JudgeVerdict | None = None
   if self._verification_judge:
       try:
           verdict = await self._verification_judge.judge(
               issue_number=pr.issue_number,
               pr_number=pr.number,
               diff=diff,
           )
       except Exception:  # noqa: BLE001
           logger.warning(
               "Verification judge failed for issue #%d",
               pr.issue_number,
               exc_info=True,
           )
   ```

5. **Pass verdict to `_get_judge_result()`** (`review_phase.py` line 321):
   Change `judge_result = await self._get_judge_result(issue, pr)` to `judge_result = await self._get_judge_result(issue, pr, verdict)`.

6. **Rewrite `_get_judge_result()`** (`review_phase.py` lines 724-733):
   Replace the stub with conversion logic:
   ```python
   async def _get_judge_result(
       self,
       issue: GitHubIssue,
       pr: PRInfo,
       verdict: JudgeVerdict | None,
   ) -> JudgeResult | None:
       """Convert a JudgeVerdict into a JudgeResult for verification issue creation.

       Returns None if no verdict was produced (judge not configured, no criteria
       file, or judge failed).
       """
       if verdict is None:
           return None

       criteria = [
           VerificationCriterion(
               description=cr.criterion,
               passed=cr.verdict == CriterionVerdict.PASS,
               details=cr.reasoning,
           )
           for cr in verdict.criteria_results
       ]

       return JudgeResult(
           issue_number=issue.number,
           pr_number=pr.number,
           criteria=criteria,
           verification_instructions=verdict.verification_instructions,
           summary=verdict.summary,
       )
   ```

7. **Update `TestGetJudgeResult` tests** (`tests/test_review_phase.py`):
   Replace the single "returns None" test with:
   - `test_returns_none_when_verdict_is_none` — pass `verdict=None`, assert returns `None`
   - `test_converts_passing_verdict` — pass a `JudgeVerdict` with PASS criteria, assert correct `JudgeResult` with `passed=True`
   - `test_converts_failing_verdict` — pass a `JudgeVerdict` with FAIL criteria, assert correct `JudgeResult` with `passed=False`
   - `test_passes_through_instructions` — assert `verification_instructions` is carried from verdict to result
   - `test_passes_through_summary` — assert `summary` is carried through
   - `test_empty_criteria_results` — pass verdict with no criteria, assert empty criteria list

8. **Update `TestVerificationIssuePostMerge` tests** (`tests/test_review_phase.py`):
   These tests mock `_get_judge_result` directly, so the signature change means updating the mock. Since these tests use `phase._get_judge_result = AsyncMock(return_value=...)`, the mock automatically accepts any arguments — **no changes needed** to these tests. The mocks will continue to work because `AsyncMock` accepts any call signature.

9. **Add test for `verification_instructions` in `VerificationJudge`** (`tests/test_verification_judge.py`):
   Add a test that verifies when `judge()` returns a `JudgeVerdict`, the `verification_instructions` field contains the parsed instructions from the criteria file.

10. **Run `make quality`** to verify all tests pass, linting is clean, and types check.

## Testing Strategy

### Files to modify:
- **`tests/test_review_phase.py`**: Replace `TestGetJudgeResult.test_returns_none` with 5-6 tests covering the conversion logic (None passthrough, PASS/FAIL criterion mapping, instructions passthrough, summary passthrough, empty criteria). The `TestVerificationIssuePostMerge` tests should continue to pass without changes since they mock `_get_judge_result` with `AsyncMock`.
- **`tests/test_verification_judge.py`**: Add a test that when `judge()` runs with a valid criteria file, the returned `JudgeVerdict.verification_instructions` is populated with the instructions text from the file.

### What to verify:
1. `_get_judge_result(issue, pr, None)` returns `None`
2. `_get_judge_result(issue, pr, verdict)` correctly converts `CriterionResult` → `VerificationCriterion`:
   - `criterion` → `description`
   - `CriterionVerdict.PASS` → `passed=True`
   - `CriterionVerdict.FAIL` → `passed=False`
   - `reasoning` → `details`
3. `verification_instructions` and `summary` are passed through from verdict to result
4. `issue_number` and `pr_number` come from the `issue`/`pr` args (not the verdict)
5. The end-to-end flow: `judge()` runs → return value captured → `_get_judge_result()` converts → `_create_verification_issue()` receives a real `JudgeResult`
6. All existing tests in `TestCreateVerificationIssue` and `TestVerificationIssuePostMerge` still pass

## Acceptance Criteria

1. `VerificationJudge.judge()` return value is captured and used (not discarded)
2. `_get_judge_result()` no longer always returns `None` — it converts `JudgeVerdict` → `JudgeResult`
3. `_create_verification_issue()` is reachable when the judge produces a verdict
4. The `JudgeVerdict` → `JudgeResult` conversion correctly maps all fields
5. Verification instructions are carried through from the criteria file to the verification issue
6. When no verdict is produced (no criteria file, judge not configured, or judge fails), `_get_judge_result()` still returns `None` (graceful degradation)
7. All existing tests pass, new tests cover the conversion logic
8. `make quality` passes clean

## Key Considerations

### Type mapping between models
The two model hierarchies are intentionally different:
- `CriterionResult` (judge-internal) has `criterion: str`, `verdict: CriterionVerdict`, `reasoning: str`
- `VerificationCriterion` (issue-facing) has `description: str`, `passed: bool`, `details: str`

The mapping is: `criterion→description`, `verdict==PASS→passed`, `reasoning→details`. This is straightforward but must be tested.

### Instructions may be refined during judge execution
`VerificationJudge.judge()` can refine instructions (write updated text back to the criteria file). The `verification_instructions` on `JudgeVerdict` must reflect the final (possibly refined) version. The implementation stores the initial text and overwrites it if refinement occurs.

### Backward compatibility
- `JudgeVerdict` gains a new optional field with a default — no breaking changes for existing code/tests
- `_get_judge_result()` signature changes from `(issue, pr)` to `(issue, pr, verdict)` — this is a private method only called in one place, but existing tests that mock it (`TestVerificationIssuePostMerge`) use `AsyncMock` which accepts any arguments, so they continue to work

### Pre-mortem — top 3 risks for failure:
1. **Test mocks for `_get_judge_result` break** — The `TestVerificationIssuePostMerge` tests assign `AsyncMock` to `_get_judge_result`. Since `AsyncMock` accepts any call signature, the additional `verdict` parameter should be transparent. However, if any test uses `assert_awaited_once_with(issue, pr)` (checking exact args), it would fail. Need to verify no such assertions exist. *Mitigation: checked — these tests don't assert on `_get_judge_result` call args, only on `_create_verification_issue`.*

2. **Refined instructions not captured correctly** — If the refinement codepath in `judge()` sets `verdict.verification_instructions` too early or too late, the wrong version of instructions could propagate. *Mitigation: set initial value after parsing, then overwrite in refinement block.*

3. **`pr_number` not on `JudgeVerdict`** — `JudgeResult` requires `pr_number` but `JudgeVerdict` only has `issue_number`. The `_get_judge_result` method gets `pr_number` from the `PRInfo` argument, not from the verdict. This is correct but could be confusing. *Mitigation: clear docstring and tests.*

PLAN_END

SUMMARY: Wire VerificationJudge.judge() return value through _get_judge_result() to enable verification issue creation, converting JudgeVerdict → JudgeResult.
