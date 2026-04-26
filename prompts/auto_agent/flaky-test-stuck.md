# Auto-Agent — flaky-test-stuck Playbook

{{> _envelope.md}}

## Sub-label: flaky-test-stuck

Read the test, the recent flake history, the git blame on the test file. Most
flakes are timing or order-dependent — fix the test, not the production code.
If you can't reproduce, mark `@pytest.mark.flaky(reruns=3)` with a clear comment
and open a follow-up issue.

## Specific guidance

The flake-tracker loop has been retrying this test repair for several attempts;
its prior diagnoses are visible in the escalation context (if any) and in the
prior attempts block.

Order of operations:

1. Read the test file. Look for: time.sleep(), wall-clock comparisons, ordering
   assumptions in async tests, shared-state across tests in the same module.
2. Run the test in isolation 5 times (`pytest path::test_name -v --count=5`).
   If it passes 5/5, it's an order/state issue — find the leak.
3. If it still flakes in isolation, the test logic itself is wrong. Fix it.
4. If you cannot identify the cause within a reasonable budget, mark
   `@pytest.mark.flaky(reruns=3, reruns_delay=2)` with a comment linking back
   to the original issue, open a follow-up `tech-debt` issue, and return
   `resolved`. The flaky decorator is a stop-gap, not a permanent fix.

Do NOT mark a test flaky if a one-line fix is obvious. Do NOT change production
code unless the test was correct and caught a real race.
