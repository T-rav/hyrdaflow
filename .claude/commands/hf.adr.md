# Create ADR Draft Issue

Capture an architectural decision as a draft ADR issue routed into HydraFlow.

## Usage

```text
/hf.adr Adopt a single source of truth for pipeline queue counts
/hf.adr Move visual validation into merge worker gate
```

`$ARGUMENTS` should be the ADR title suffix. If empty, ask for one.

## Instructions

### Phase 0: Resolve Configuration

Before creating anything, resolve:

1. `REPO`: `echo "$HYDRAFLOW_GITHUB_REPO"`; if empty, use `git remote get-url origin` and parse `owner/repo`.
2. `ASSIGNEE`: `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"`; if empty, use repo owner.
3. `LABEL`: `echo "$HYDRAFLOW_LABEL_FIND"`; if empty, use `hydraflow-find`.

Never pass empty values to `gh issue create`.

### Phase 1: Build ADR Issue

Create title: `[ADR] <title from $ARGUMENTS>`.

Create body with required sections:

```markdown
## Context

<what problem/constraints drove this decision>

## Decision

<the concrete architectural decision>

## Consequences

<tradeoffs, follow-up work, operational impact>
```

Optional sections when relevant:
- `## Alternatives considered`
- `## Related`

### Phase 2: Create Issue with gh

Use `--body-file` to avoid escaping issues:

```bash
BODY_FILE=$(mktemp)
cat > "$BODY_FILE" <<'ADR_EOF'
## Context
...

## Decision
...

## Consequences
...
ADR_EOF

gh issue create --repo "$REPO" \
  --assignee "$ASSIGNEE" \
  --label "$LABEL" \
  --title "[ADR] <title>" \
  --body-file "$BODY_FILE"

rm -f "$BODY_FILE"
```

### Phase 3: Report Back

Return:
- created issue URL
- resolved repo/assignee/label
- one-line ADR summary
- confirmation it is queued for pipeline processing (triage -> plan/implement -> review)

## Notes

- ADR formatting is validated by HydraFlow ADR routing logic.
- Use `hydraflow-find` (or `HYDRAFLOW_LABEL_FIND`) so the issue is queued into the pipeline.
- Keep decision text concrete and implementation-actionable.
