"""Trust-fleet anomaly detectors + watched-worker registry (spec §12.1).

Task 4 lands only the ``TRUST_LOOP_WORKERS`` registry — the five
detector functions arrive in Task 5. Splitting the constant out now
keeps ``TrustFleetSanityLoop._collect_window_metrics`` unblocked while
the detectors remain out-of-scope for this commit.
"""

from __future__ import annotations

# Spec §12.2 — exactly the nine trust loops watched by the sanity loop.
# A new trust-loop's introduction PR appends its worker name here in
# its five-checkpoint-wiring task (spec §12.1 "Watched workers set").
TRUST_LOOP_WORKERS: tuple[str, ...] = (
    "corpus_learning",
    "contract_refresh",
    "staging_bisect",
    "principles_audit",
    "flake_tracker",
    "skill_prompt_eval",
    "fake_coverage_auditor",
    "rc_budget",
    "wiki_rot_detector",
)
