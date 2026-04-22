from hydraflow.arch import Allowlist, Fitness, LayerMap, python_ast_extractor

EXTRACTOR = python_ast_extractor

LAYERS = LayerMap(
    {
        # Layer 1 — Domain
        "src/models.py": 1,
        "src/config.py": 1,
        "src/config_io.py": 1,
        # Layer 2 — Application (explicit phase/loop files)
        "src/orchestrator.py": 2,
        "src/plan_phase.py": 2,
        "src/implement_phase.py": 2,
        "src/review_phase.py": 2,
        "src/triage_phase.py": 2,
        "src/hitl_phase.py": 2,
        "src/discover_phase.py": 2,
        "src/shape_phase.py": 2,
        "src/phase_utils.py": 2,
        "src/pr_unsticker.py": 2,
        "src/base_background_loop.py": 2,
        "src/bg_worker_manager.py": 2,
        # Layer 2 — pattern: any *_loop or *_phase under src/
        "src/*_loop.py": 2,
        "src/*_phase.py": 2,
        # Layer 3 — Runners
        "src/base_runner.py": 3,
        "src/agent.py": 3,
        "src/planner.py": 3,
        "src/reviewer.py": 3,
        "src/hitl_runner.py": 3,
        "src/triage_runner.py": 3,
        "src/triage.py": 3,
        "src/runner_utils.py": 3,
        "src/runner_constants.py": 3,
        "src/diagnostic_runner.py": 3,
        "src/discover_runner.py": 3,
        "src/research_runner.py": 3,
        "src/shape_runner.py": 3,
        "src/docker_runner.py": 3,
        "src/*_runner.py": 3,
        # Layer 4 — Infrastructure/Adapters
        "src/pr_manager.py": 4,
        "src/worktree.py": 4,
        "src/workspace.py": 4,
        "src/merge_conflict_resolver.py": 4,
        "src/post_merge_handler.py": 4,
        "src/dashboard.py": 4,
        "src/dashboard_routes/**": 4,
        "src/server.py": 4,
        "src/prep.py": 4,
        "src/ci_scaffold.py": 4,
        "src/lint_scaffold.py": 4,
        "src/test_scaffold.py": 4,
        "src/makefile_scaffold.py": 4,
        "src/polyglot_prep.py": 4,
        "src/prep_hooks.py": 4,
        "src/prep_ignore.py": 4,
        "src/*_scaffold.py": 4,
    }
)

ALLOWLIST = Allowlist(
    {
        # Ported verbatim from FILE_ALLOWLIST in scripts/check_layer_imports.py.
        # Cross-cutting modules and the composition root are exempted implicitly
        # by not appearing in LAYERS.
        "src/implement_phase.py": {"src/agent.py"},
        "src/plan_phase.py": {"src/planner.py", "src/research_runner.py"},
        "src/review_phase.py": {
            "src/reviewer.py",
            "src/merge_conflict_resolver.py",
            "src/post_merge_handler.py",
        },
        "src/hitl_phase.py": {"src/hitl_runner.py"},
        "src/triage_phase.py": {"src/triage.py"},
        "src/discover_phase.py": {"src/discover_runner.py", "src/pr_manager.py"},
        "src/shape_phase.py": {"src/shape_runner.py", "src/pr_manager.py"},
        "src/base_background_loop.py": {"src/runner_utils.py"},
        "src/code_grooming_loop.py": {"src/runner_utils.py"},
        "src/report_issue_loop.py": {"src/runner_utils.py"},
    }
)

FITNESS: list[Fitness] = []
