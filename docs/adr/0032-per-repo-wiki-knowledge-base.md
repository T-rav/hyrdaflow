# ADR-0032: Per-Repo Wiki Knowledge Base (Karpathy Pattern)

**Status:** Accepted
**Enforced by:** tests/test_repo_wiki.py, tests/test_repo_wiki_store_git.py, tests/test_repo_wiki_ingest.py, tests/test_wiki_drift_detector.py, tests/test_wiki_drift_symbols.py, tests/test_wiki_semantic_drift.py, tests/test_repo_wiki_temporal.py, tests/test_wiki_corroboration.py
**Date:** 2026-04-05

## Context

HydraFlow's agents repeatedly work on the same target repositories across many issue cycles. Each cycle discovers architecture patterns, gotchas, test conventions, and dependency quirks — but this knowledge was either lost after the session or stored in Hindsight vector banks where retrieval added noise and lacked transparency.

Andrej Karpathy's "LLM Knowledge Base" pattern proposes an alternative: instead of vector-search RAG, maintain a structured markdown wiki that the LLM reads directly via an index. At moderate scale (~100s of entries), index-first navigation beats embedding search — every claim is traceable to a specific `.md` file a human can read, edit, or delete.

### Related

- `src/repo_wiki.py:RepoWikiStore` — core store (ingest, query, active_lint, dedup)
- `src/wiki_compiler.py:WikiCompiler` — LLM synthesis (compile_topic, synthesize_ingest)
- `src/repo_wiki_loop.py:RepoWikiLoop` — background maintenance loop
- `src/base_runner.py:_inject_repo_wiki` — prompt injection into all runners
- `src/hindsight.py` — existing vector-search memory (complementary, not replaced)

## Decision

Adopt a file-based, per-repo wiki system with three layers:

1. **Raw sources** (immutable) — plan outputs, review transcripts, implementation logs. The LLM reads but never modifies these.

2. **Wiki layer** (LLM-maintained) — structured markdown topic pages (architecture, patterns, gotchas, testing, dependencies) with a JSON index and append-only operation log. The LLM compiles, synthesizes, and cross-references entries via `WikiCompiler`.

3. **Schema layer** (config-driven) — `HydraFlowConfig` fields control intervals, model selection, prompt budgets, and thresholds.

### Key design choices

- **Markdown over vectors**: At wiki scale, structured markdown with index-first retrieval is more transparent and auditable than embedding search. Hindsight remains for cross-repo general memory; the wiki is per-repo compiled knowledge.

- **LLM as librarian**: `WikiCompiler` uses Claude (via `build_lightweight_command`) to synthesize redundant entries, add cross-references between topics, resolve contradictions, and extract durable knowledge from raw phase output. This is the core Karpathy insight — the LLM maintains the wiki, not just reads it.

- **Active self-healing lint**: The background loop marks entries stale when their source issues close (via `StateTracker` outcomes), prunes entries older than 90 days, and rebuilds the index. The wiki degrades gracefully without manual curation.

- **Drift detection (two layers)**: A deterministic pass (`wiki_drift_detector.detect_drift`) flags entries whose `src/path.py:Symbol` citations point at files or symbols that no longer exist — cheap, side-effect-free, and auto-marks stale. An optional LLM layer (`scan_semantic_drift`, gated by `semantic_drift_enabled`) asks the compilation model whether an entry's CLAIM still matches the current source for entries older than `semantic_drift_min_age_days`, capped at `semantic_drift_max_entries_per_tick` per loop tick. Semantic findings are logged for human review; only the deterministic layer auto-stales.

- **Depth signals (corroborations + temporal tags)**: every active entry carries a `corroborations` counter in its frontmatter (default 1). `WikiCompiler.dedup_or_corroborate` uses `generalize_pair` to decide whether a newly-ingested entry is a re-discovery of an existing active entry and returns a `CorroborationDecision` carrying the canonical's file path; callers then use `increment_corroboration(path)` to atomically bump the counter instead of writing a sibling duplicate. On the read path, `RepoWikiStore.query_with_tags` returns a `{title: temporal_tag}` map alongside the markdown, and `BaseRunner._inject_repo_wiki` weaves the tags inline as italic lines under each entry — so the planner/reviewer sees `### Always use factories\n*(stable for 6 months (+4))*`. Tag vocabulary: `recently added` (<30d), `stable for N months`, `stable for N year(s)`, `age unknown`; `(+N)` suffix when corroborations > 1. Addresses two depth gaps vs. agentic-memory systems: evidence-weighting and temporal reasoning about when claims settled.

- **Dedup tracking**: `DedupStore`-backed per-repo tracking prevents re-ingesting the same (issue, source_type) pair. Failed ingests are not marked, so retries work.

- **Transcript over summary**: When `WikiCompiler` is available, review ingestion passes the full agent transcript (truncated to 40k chars) for richer multi-insight extraction. Mechanical fallback uses the structured summary.

## Consequences

### Positive

- Agents get smarter about each specific repo over time without RAG infrastructure
- Every piece of knowledge is a readable markdown file — fully auditable
- Cross-references between topics (e.g., "See also: gotchas — circular imports") connect related insights
- Self-healing lint prevents unbounded growth of stale entries
- Complements Hindsight rather than replacing it — wiki is per-repo compiled knowledge, Hindsight is cross-repo general memory

### Negative

- Additional LLM calls for compilation (mitigated: haiku model, 5-entry threshold, configurable interval)
- Wiki content quality depends on WikiCompiler prompt engineering
- File I/O on every ingest (mitigated: only runs once per issue per phase via dedup)

### Risks

- Wiki could accumulate contradictory entries if compilation prompts are poorly tuned — mitigated by periodic lint passes and the compilation dedup threshold
- Large repos with many issues could produce large wiki directories — mitigated by stale pruning and the 90-day eviction window
