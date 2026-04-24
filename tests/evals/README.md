# HydraFlow eval harness

Opt-in tests that measure **model output quality** on representative
inputs — not covered by the default `pytest` run because they:

- Make real LLM calls (cost + latency).
- Require provider credentials.
- Are useful when deciding *which model tier* to use for a given
  caretaker loop, not on every CI tick.

## Running

```bash
# All evals:
uv run pytest tests/evals/ --run-evals

# Single eval:
uv run pytest tests/evals/test_wiki_generalization_evals.py --run-evals -v

# Environment alternative:
HYDRAFLOW_RUN_EVALS=1 uv run pytest tests/evals/
```

Without `--run-evals`, collection marks everything skipped — safe to
include in broad `pytest tests/` runs.

## Layout

```
tests/evals/
├── conftest.py                  # opt-in gating
├── corpus/
│   └── generalization/
│       ├── same/*.json          # pairs judged as same-principle
│       └── different/*.json     # pairs judged as different
└── test_wiki_generalization_evals.py
```

Each corpus JSON is a single case:

```json
{
  "topic": "testing",
  "entry_a": {
    "title": "Short title",
    "content": "Full body of the entry as the wiki stores it.",
    "source_repo": "owner/repo-a"
  },
  "entry_b": { "...": "..." },
  "expected_same_principle": true,
  "notes": "Human rationale — both entries advise <same rule>."
}
```

## Adding a case

1. Pick a topic that WikiCompiler's generalization pass actually sees
   in practice (testing / architecture / patterns / gotchas).
2. Draft a pair — copy from real wiki entries or synthesize.
3. Decide ground truth (same or different principle) and drop the
   file into the right subdirectory.
4. Include a `notes` field explaining *why* you labeled it — if
   reviewers disagree with the label, the case isn't unambiguous
   enough to be a useful eval.

## Interpreting results

The test output reports per-model:

- **accuracy** — fraction of cases where LLM matches ground truth.
- **same-principle precision / recall** — false-positive and
  false-negative rates. Useful for deciding whether haiku is strict
  enough, or whether sonnet catches nuance haiku misses.
