---
id: 0009
topic: gotchas
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-18T15:40:17.674522+00:00
status: active
---

# Infrastructure — Events, Dispatch, and Parser Implementation

Alpine's minimal tooling excludes Python and standard utilities. Use portable shell commands like `dd if=/dev/zero bs=1M count=32 of=/dev/null` or `head -c` to consume memory in constrained environments, avoiding allocation failures from missing interpreter tools.

Event dispatch dicts benefit from separating truly silent events from events that produce no display output but set a result value (e.g., agent_end, turn_end set result but print nothing). Use _SILENT_WITH_RESULT frozenset checked before _SILENT_EVENTS to correctly route these cases. Handlers must have uniform signatures (event: dict) -> str to avoid type checker errors. This pattern complements exception-based signaling in background loops where fatal errors propagate via exception and supervisor routes the outcome.

When a general method returns insufficient data for specific use case, create separate specialized method rather than overloading general one. Example: `list_issues_by_label` returns basic issue metadata; `get_issue_updated_at()` handles timestamps separately. This keeps methods focused and avoids coupling unrelated concerns.

Explicitly document top 3-5 failure risks in plan phase before implementation. This identifies potential issues early and guides implementer decisions. Pre-mortems catch mistakes before code review and establish concrete failure modes to guard against during implementation.

Validate parsers against realistic multi-paragraph agent output containing both prose and structured markers—not bare marker strings. Test assertions focus on markers themselves, not prose wording, so transcript updates don't break tests. Maintain explicit assertions on structured markers rather than narrative content. Explicit `## Output Format` sections in markdown skill definitions (with 'do not modify without updating parser' warnings) make the contract visible. Maintain SKILL_MARKERS mapping for consistency and add test cases verifying all 4 backend copies match.

When extracting from Claude CLI transcripts, modified files, or external formats, use best-effort regex with try/except wrapping—never raise on parse failure. Log warnings when extraction finds zero matches on non-empty input to catch format drift early. Fall back to empty lists or default values on JSONDecodeError and other parsing errors. Leverage existing utilities like delta_verifier.parse_file_delta() and task_graph.extract_phases() instead of reimplementing.

CLI command framework passes $ARGUMENTS as everything after command name—verify scope routing with both single-word and multi-word arguments. Markdown splitting on '\n- ' double-prefixes first item ('- - ')—_split_md_items() helper must explicitly fix this edge case.

See also: Code Quality — type-checking applies to parser signatures; Testing — parser assertions validate against realistic multi-paragraph output.
