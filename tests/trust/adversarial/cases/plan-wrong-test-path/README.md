# plan-wrong-test-path

Plan says tests go at `tests/test_calc.py`. Diff puts them in
`src/tests_calc_scratch.py` — wrong location, and the planned file was
never created. Plan-compliance must flag the path divergence.

Keyword: plan
