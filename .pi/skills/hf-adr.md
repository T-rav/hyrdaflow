# HF ADR Workflow

Create a draft ADR issue and queue it into HydraFlow's normal pipeline.

## Inputs

- ADR title suffix
- Context
- Decision
- Consequences

## Steps

1. Resolve repo/assignee/label defaults:
   - repo: `HYDRAFLOW_GITHUB_REPO` or git origin slug
   - assignee: `HYDRAFLOW_GITHUB_ASSIGNEE` or repo owner
   - label: `HYDRAFLOW_LABEL_FIND` or `hydraflow-find`
2. Create issue with title format: `[ADR] <title>`.
3. Ensure body includes:
   - `## Context`
   - `## Decision`
   - `## Consequences`
4. Create with `gh issue create --body-file` and include the resolved label.
5. Confirm the issue is queued for pipeline processing (triage -> implement/review).
6. Return issue URL and summary.

## Notes

- ADR shape is validated in HydraFlow triage/review phases.
- Use `hydraflow-find` to queue ADR work into the pipeline.
- Keep decisions explicit, bounded, and actionable.
