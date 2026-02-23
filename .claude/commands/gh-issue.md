# Create a GitHub Issue

Take a rough description from the user, research the relevant codebase, and create a well-structured GitHub issue with full context, file references, and acceptance criteria.

## Usage

```
/gh-issue add a Stop hook that checks for Langfuse tracing in new LLM code
/gh-issue the tasks service Google Drive auth flow doesn't handle token refresh
```

`$ARGUMENTS` contains the rough issue description from the user.

If `$ARGUMENTS` is empty, ask the user to describe the issue.

## Instructions

### Phase 0: Resolve Configuration

Before doing anything else, resolve these three values. Use the EXACT fallback logic below — do NOT pass empty strings to `gh issue create`:

1. **REPO**: Run `echo "$HYDRAFLOW_GITHUB_REPO"`. If the output is empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
2. **ASSIGNEE**: Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"`. If the output is empty, extract the owner from the repo slug (the part before `/`).
3. **LABEL**: Run `echo "$HYDRAFLOW_LABEL_PLAN"`. If the output is empty, **hardcode `hydraflow-plan`**. NEVER pass an empty `--label` flag.

### Phase 1: Understand the Request

Parse `$ARGUMENTS` to understand what the user wants filed as an issue. Identify:
- What area of the codebase is involved
- What the problem or feature request is
- Any specific services, files, or patterns mentioned

**Epic detection:** If the user mentions "epic", "break into sub-issues", "multiple parts", or describes a large multi-component feature, treat this as an EPIC:
- Prefix the title with `[Epic]`
- Use the `hydraflow-epic` label (NOT `hydraflow-plan` — the parent epic is a tracking issue, not implementable)
- Create sub-issues separately, each WITH the `hydraflow-plan` label
- Link sub-issues in the epic body with checkboxes: `- [ ] #123 — title`

### Phase 2: Research the Codebase

Before writing the issue, explore the codebase to gather concrete context:
- Use Grep/Glob/Read to find the relevant files, services, and patterns
- Understand the current state of the code related to the issue
- Identify specific file paths, function names, and line numbers
- Check for existing related patterns or prior art in the codebase
- Look at how similar things are already done elsewhere
- **If the issue involves UI changes:**
  - Explore `ui/src/components/` for existing component patterns that overlap or could be reused
  - Check `ui/src/constants.js` for shared constants (e.g., `PIPELINE_STAGES`, `ACTIVE_STATUSES`)
  - Check `ui/src/types.js` for shared type definitions
  - Check `ui/src/theme.js` for the design system's color tokens and spacing values
  - Note the styling approach used in similar components (inline styles, CSS modules, etc.)

This research makes the issue actionable rather than vague.

### Phase 3: Check for Duplicates

Before creating, search for existing issues:
```bash
gh issue list --repo $REPO --label hydraflow-plan --state open --search "<key terms>"
```

If a matching open issue already exists, tell the user and show the link instead of creating a duplicate.

### Phase 4: Create the Issue

**CRITICAL RULES:**
- The issue body MUST be detailed (at least 200 characters). NEVER create an issue with an empty or one-line body.
- ALL of the user's input from `$ARGUMENTS` goes into the BODY, not the title. The title is a short summary YOU write.
- The `--label` flag MUST have a non-empty value. Use `hydraflow-plan` as default.
- Use `--body-file` with a temp file for long bodies to avoid shell escaping issues.

Create the issue using `gh issue create` with:
- **Label**: `$LABEL` (MUST be non-empty — default `hydraflow-plan`)
- **Assignee**: `$ASSIGNEE`
- **Title**: Concise, descriptive (under 70 chars) — this is a SHORT summary, NOT the user's full input
- **Body**: Well-structured with the sections below. MUST be at least 200 characters.

#### Issue Body Structure

```markdown
## Problem

Clear description of what's missing, broken, or needed. Include WHY this matters.

## Current State

What exists today — reference specific files, services, and patterns found during research.
Use full file paths so the implementer can navigate directly.

## Proposed Solution

Concrete description of what should be built or changed.
Reference existing patterns in the codebase that should be followed.

## Scope

### Files/Services involved:
- List specific files and directories

### Key integration points:
- List functions, classes, or patterns to hook into

## UI/UX Considerations (if applicable)

_Include this section only when the issue involves frontend/UI changes. Skip entirely for backend-only issues._

### Existing components to reuse or extend:
- List any components in `ui/src/components/` that overlap with the proposed change

### Responsive requirements:
- Min-width constraints needed
- Viewport or container-size considerations

### Shared code:
- Constants, types, or styles to import from centralized modules (`constants.js`, `types.js`, `theme.js`)

## Acceptance Criteria

- [ ] Checklist of concrete, verifiable outcomes
- [ ] Each item should be testable
- [ ] Include test requirements
```

#### gh issue create command

For long bodies, use a temp file to avoid shell escaping issues:

```bash
BODY_FILE=$(mktemp)
cat > "$BODY_FILE" <<'ISSUE_EOF'
<body content here>
ISSUE_EOF

gh issue create --repo $REPO \
  --assignee $ASSIGNEE \
  --label $LABEL \
  --title "<title>" \
  --body-file "$BODY_FILE"

rm -f "$BODY_FILE"
```

For shorter bodies, the HEREDOC approach also works:

```bash
gh issue create --repo $REPO \
  --assignee $ASSIGNEE \
  --label $LABEL \
  --title "<title>" \
  --body "$(cat <<'EOF'
<body content>
EOF
)"
```

### Phase 5: Report Back

Show the user:
- The issue URL
- A brief summary of what was filed
