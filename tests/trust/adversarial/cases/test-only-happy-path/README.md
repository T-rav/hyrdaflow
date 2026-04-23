# test-only-happy-path

`parse()` grew two new raising branches (empty input, non-numeric input).
The only test still only covers the happy path. test-adequacy must flag
the missing edge-case coverage.

Keyword: edge case
