# HF Issue Workflow

Create a well-structured GitHub issue and queue it into HydraFlow's normal pipeline.

## Inputs

- Rough issue description from user (`$ARGUMENTS`)

## Steps

1. Resolve repo/assignee/label defaults:
   - repo: `HYDRAFLOW_GITHUB_REPO` or git origin slug
   - assignee: `HYDRAFLOW_GITHUB_ASSIGNEE` or repo owner
   - label: `hydraflow-find`
2. Parse user input to identify area, problem/feature, and relevant services.
3. Research codebase (Grep/Glob/Read) for concrete context: file paths, functions, patterns.
4. Check for duplicates: `gh issue list --label hydraflow-find --state open --search "<terms>"`.
5. Create issue with `gh issue create --body-file`:
   - Title: concise summary (under 70 chars)
   - Body: Problem, Current State, Proposed Solution, Scope, Acceptance Criteria (min 200 chars)
   - Label: resolved `$LABEL` (default `hydraflow-find`)
6. Return issue URL and summary.

## Epic Detection

If user mentions "epic" or multi-component work:
- Prefix title with `[Epic]`
- Use `hydraflow-epic` label for parent (NOT `hydraflow-find`)
- Create sub-issues separately, each WITH `hydraflow-find` label
- Link sub-issues in epic body with checkboxes: `- [ ] #123 — title`

## Notes

- Issues enter the triage pipeline via `hydraflow-find` label.
- Body must be at least 200 chars — never create empty/one-line issues.
- All user input goes into the body, not the title.
