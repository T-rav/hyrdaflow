---
name: hf.adr
description: Create a draft ADR issue for HydraFlow processing
---

# Create ADR Draft Issue

Create an ADR draft issue that HydraFlow queues into the normal pipeline for triage, implementation, and review.

## Usage

```
/hf.adr Adopt queue memory handoff between stages
/hf.adr Standardize visual validation gating policy
```

`$ARGUMENTS` is the ADR title suffix.

## Workflow

### 1) Resolve configuration

- `REPO`: `HYDRAFLOW_GITHUB_REPO` fallback to git origin slug
- `ASSIGNEE`: `HYDRAFLOW_GITHUB_ASSIGNEE` fallback to repo owner
- `LABEL`: `HYDRAFLOW_LABEL_FIND` fallback to `hydraflow-find`

### 2) Build ADR content

Issue title must be `[ADR] <title>`.

Body must include:

- `## Context`
- `## Decision`
- `## Consequences`

Optional:

- `## Alternatives considered`
- `## Related`

Keep the decision concrete and implementation-actionable.

### 3) Create issue

Create the issue directly with `gh issue create` and `--body-file`:

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

Use `hydraflow-find` (or `HYDRAFLOW_LABEL_FIND`) so the ADR is queued into the pipeline.

### 4) Report result

Return:

- issue URL
- resolved repo/label
- short summary of the decision captured
- confirmation that it is queued for pipeline processing
