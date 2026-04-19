---
id: 0012
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.849563+00:00
status: active
---

# Dynamic Discovery with Convention-Based Naming

Avoid import-time registry population; instead call discovery functions on-demand (e.g., `discover_skills(repo_root)` per call without caching). Discovery must happen at runtime not import-time to stay fresh and avoid blocking startup. Establish reversible naming conventions: hf.diff-sanity command → diff_sanity module with `build_diff_sanity_prompt()` and `parse_diff_sanity_result()` functions. This eliminates need for separate registry mapping files. Lightweight frontmatter parsing (split on `---` delimiters) avoids adding parser dependencies. Catch broad exceptions during module imports (not just ImportError) to handle syntax errors, missing dependencies, and other runtime errors. Dynamic skill definitions in JSONL use generic templated builders (functools.partial) + result markers. Multiple registration mechanisms (bg_loop_registry dict, loop_factories tuple) require unified discovery via set union. See also: Workspace Isolation for command discovery patterns, Background Loops for registration.
