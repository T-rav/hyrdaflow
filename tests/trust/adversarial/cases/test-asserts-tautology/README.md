# test-asserts-tautology

A test was added for `Counter.reset()` but it only asserts `c is not None`
— a tautology that never fails. test-adequacy must flag the ineffective
coverage.

Keyword: tautology
