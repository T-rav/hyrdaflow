# renamed-symbol-callsite

The function `compute_total` was renamed to `compute_sum`, but the call
site in `run()` still references the old name. This leaves a NameError
at call time that static review should flag.

Keyword: compute_total
