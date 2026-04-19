---
id: 0023
topic: architecture
source_issue: unknown
source_phase: synthesis
created_at: 2026-04-10T03:41:18.852310+00:00
status: active
---

# Prompt Deduplication and Memory Context Capping

Multi-bank Hindsight recall causes duplicate or overlapping memories in prompts. Deduplication strategy: (1) Pool items from all banks, track via exact-text matching with character counts; (2) Deduplicate via PromptDeduplicator.dedup_bank_items() which merges duplicate text and tracks which banks contributed; (3) Rebuild per-bank strings avoiding exact-string set-rebuilding (which fails for merged items)—instead return per-bank surviving items directly from dedup; (4) Cap memory injection with multi-tier limits: max_recall_thread_items_per_phase (5), max_inherited_memory_chars (2000), max_memory_prompt_chars (4000). Semantic vs exact matching: dedup removes exact duplicates while preserving content overlap between banks (acceptable). Text-based dedup respects display modifications (e.g., prefixes like **AVOID:**). Antipatterns use 1.15x boost multiplier for recall priority, but must be tuned if antipatterns dominate results. See also: Optional Dependencies for Hindsight service handling, Side Effect Consumption for context threading.
