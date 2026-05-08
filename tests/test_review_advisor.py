import asyncio
from typing import Any

import pytest
from pydantic import ValidationError

from mockworld.fakes import FakeLLM
from review_advisor import (
    CRITICAL_PATHS,
    SURFACE_ADVISOR_CONFIGS,
    AlwaysTrigger,
    CompositeTrigger,
    DiffStats,
    Disagreement,
    FocusArea,
    PostVerifyAdvisor,
    PostVerifyInput,
    PostVerifyResult,
    PRContext,
    PreFlightInput,
    ReviewPlan,
    build_surface_config,
    is_advisor_enabled,
    resolve_model,
    should_pre_flight,
)


class TestReviewPlanSchema:
    def test_focus_area_requires_description_files_rationale(self):
        fa = FocusArea(description="d", files=["a.py"], rationale="r")
        assert fa.description == "d"
        assert fa.files == ["a.py"]

    def test_review_plan_full_shape(self):
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[FocusArea(description="d", files=["a.py"], rationale="r")],
            rubric=["check 1", "check 2"],
            escalation_signals=["see X"],
        )
        assert plan.rubric == ["check 1", "check 2"]

    def test_review_plan_serializes_to_json_round_trip(self):
        plan = ReviewPlan(
            risk_summary="r", focus_areas=[], rubric=[], escalation_signals=[]
        )
        data = plan.model_dump_json()
        restored = ReviewPlan.model_validate_json(data)
        assert restored == plan


class TestPostVerifyResultSchema:
    def test_verdict_must_be_approve_or_veto(self):
        with pytest.raises(ValidationError):
            PostVerifyResult(verdict="MAYBE", reasoning="r", disagreements=[])

    def test_disagreement_severity_constrained(self):
        with pytest.raises(ValidationError):
            Disagreement(
                executor_claim="c",
                advisor_assessment="a",
                severity="critical",
            )

    def test_post_verify_result_minimal(self):
        r = PostVerifyResult(verdict="APPROVE", reasoning="ok", disagreements=[])
        assert r.suggested_fix_direction is None


class TestInputSchemas:
    def test_pre_flight_input_minimal(self):
        inp = PreFlightInput(surface="pr_review", diff="d")
        assert inp.spec is None
        assert inp.related_paths == []
        assert inp.prior_attempts == 0

    def test_post_verify_input_minimal(self):
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        assert inp.attempt_number == 0
        assert inp.pre_flight_plan is None


class TestModelResolution:
    def test_per_surface_overrides_global(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", "haiku")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", "sonnet")
        assert resolve_model("pr_review", "executor", default="opus") == "haiku"

    def test_global_used_when_per_surface_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.setenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", "sonnet")
        assert resolve_model("pr_review", "executor", default="opus") == "sonnet"

    def test_default_used_when_both_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.delenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", raising=False)
        assert resolve_model("pr_review", "executor", default="sonnet") == "sonnet"


class TestKillSwitches:
    def test_master_off_disables_all(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "false")
        assert is_advisor_enabled("pr_review", "post_verify") is False

    def test_role_off_disables_role(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED", "false")
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED", "true")
        assert is_advisor_enabled("pr_review", "pre_flight") is False
        assert is_advisor_enabled("pr_review", "post_verify") is True

    def test_surface_off_disables_surface(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("HYDRAFLOW_VISUAL_GATE_ADVISOR_ENABLED", "false")
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED", "true")
        assert is_advisor_enabled("visual_gate", "post_verify") is False
        assert is_advisor_enabled("pr_review", "post_verify") is True

    def test_all_default_true(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_PREFLIGHT_ENABLED",
            "HYDRAFLOW_REVIEW_POSTVERIFY_ENABLED",
            "HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        assert is_advisor_enabled("pr_review", "post_verify") is True


class TestRoleEnvSegmentConsistency:
    def test_resolve_model_normalizes_role_like_kill_switch(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_MODEL", "opus")
        assert resolve_model("pr_review", "pre_flight", default="x") == "opus"


class TestShouldPreFlight:
    @staticmethod
    def _trivial(paths, lines=5, prior=0):
        return DiffStats(changed_paths=paths, lines_changed=lines), PRContext(
            prior_fix_attempts=prior
        )

    def test_docs_only_returns_false(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["README.md", "docs/wiki/x.md"], lines=200)
        assert should_pre_flight(diff, pr) is False

    def test_test_only_returns_false(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["tests/test_foo.py"], lines=200)
        assert should_pre_flight(diff, pr) is False

    def test_small_src_change_returns_false(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/foo.py"], lines=10)
        assert should_pre_flight(diff, pr) is False

    def test_large_src_change_returns_true(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/foo.py"], lines=50)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_always_true(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/orchestrator.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_glob_persistence(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/persistence/store.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_glob_loop(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/edge_proposer_loop.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_critical_path_glob_state(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["src/state/checkpoint.py"], lines=2)
        assert should_pre_flight(diff, pr) is True

    def test_prior_fix_attempt_always_true(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        diff, pr = self._trivial(["docs/wiki/x.md"], lines=5, prior=1)
        assert should_pre_flight(diff, pr) is True

    def test_force_on_overrides(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", "true")
        diff, pr = self._trivial(["docs/wiki/x.md"], lines=5)
        assert should_pre_flight(diff, pr) is True

    def test_review_phase_self_modification_critical(self):
        assert "src/review_phase.py" in CRITICAL_PATHS
        assert "src/review_advisor.py" in CRITICAL_PATHS

    def test_composite_trigger_delegates_to_should_pre_flight(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_PREFLIGHT_FORCE_ON", raising=False)
        trigger = CompositeTrigger()
        diff, pr = self._trivial(["src/foo.py"], lines=50)
        assert trigger.should_run(diff, pr) is True
        diff, pr = self._trivial(["docs/x.md"], lines=5)
        assert trigger.should_run(diff, pr) is False


class TestSurfaceConfigs:
    def test_all_five_surfaces_present(self):
        expected = {
            "pr_review",
            "pre_merge_spec_check",
            "adr_review",
            "visual_gate",
            "wiki_ingest",
        }
        assert set(SURFACE_ADVISOR_CONFIGS) == expected

    def test_pr_review_full_pattern(self):
        c = SURFACE_ADVISOR_CONFIGS["pr_review"]
        assert c.pre_flight_enabled is True
        assert c.mid_flight_enabled is True
        assert c.post_verify_enabled is True
        assert c.post_verify_authority == "veto"
        assert c.max_veto_retries == 2
        assert isinstance(c.pre_flight_trigger, CompositeTrigger)

    def test_pre_merge_spec_check_no_preflight(self):
        c = SURFACE_ADVISOR_CONFIGS["pre_merge_spec_check"]
        assert c.pre_flight_enabled is False
        assert c.pre_flight_trigger is None
        assert c.mid_flight_enabled is True
        assert c.post_verify_enabled is True
        assert c.post_verify_authority == "veto"

    def test_adr_review_no_midflight_always_preflight(self):
        c = SURFACE_ADVISOR_CONFIGS["adr_review"]
        assert c.pre_flight_enabled is True
        assert isinstance(c.pre_flight_trigger, AlwaysTrigger)
        assert c.mid_flight_enabled is False
        assert c.post_verify_enabled is True
        assert c.post_verify_authority == "veto"

    def test_visual_gate_post_verify_only(self):
        c = SURFACE_ADVISOR_CONFIGS["visual_gate"]
        assert c.pre_flight_enabled is False
        assert c.mid_flight_enabled is False
        assert c.post_verify_enabled is True
        assert c.post_verify_authority == "veto"
        assert c.max_veto_retries == 1

    def test_wiki_ingest_advisory_only(self):
        c = SURFACE_ADVISOR_CONFIGS["wiki_ingest"]
        assert c.pre_flight_enabled is False
        assert c.mid_flight_enabled is False
        assert c.post_verify_enabled is True
        assert c.post_verify_authority == "advisory"
        assert c.max_veto_retries == 0

    def test_build_resolves_models_from_env(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", "haiku")
        c = build_surface_config("pr_review")
        assert c.executor_model == "haiku"

    def test_build_uses_global_when_per_surface_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.setenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", "sonnet-special")
        c = build_surface_config("pr_review")
        assert c.executor_model == "sonnet-special"

    def test_build_uses_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.delenv("HYDRAFLOW_REVIEW_EXECUTOR_MODEL", raising=False)
        monkeypatch.delenv("HYDRAFLOW_PR_REVIEW_ADVISOR_MODEL", raising=False)
        monkeypatch.delenv("HYDRAFLOW_REVIEW_ADVISOR_MODEL", raising=False)
        c = build_surface_config("pr_review")
        assert c.executor_model == "sonnet"
        assert c.advisor_model == "opus"

    def test_build_unknown_surface_raises(self):
        with pytest.raises(KeyError):
            build_surface_config("not_a_surface")


class TestFakeLLMAdvisorExtension:
    def test_script_advisor_separates_from_executor(self):
        llm = FakeLLM()
        llm.script_review(123, ["EXECUTOR_VERDICT"])
        llm.script_advisor(123, "post_verify", ["APPROVE"])
        assert llm.advisor_call_count_for("post_verify") == 0

    def test_advisor_call_count_increments_on_pop(self):
        llm = FakeLLM()
        llm.script_advisor(123, "post_verify", ["APPROVE"])
        result = llm.pop_advisor_result(123, "post_verify")
        assert result == "APPROVE"
        assert llm.advisor_call_count_for("post_verify") == 1

    def test_advisor_call_count_per_role(self):
        llm = FakeLLM()
        llm.script_advisor(123, "pre_flight", ["PLAN"])
        llm.script_advisor(123, "post_verify", ["APPROVE"])
        llm.pop_advisor_result(123, "pre_flight")
        llm.pop_advisor_result(123, "post_verify")
        assert llm.advisor_call_count_for("pre_flight") == 1
        assert llm.advisor_call_count_for("post_verify") == 1

    def test_pop_with_no_script_returns_none(self):
        llm = FakeLLM()
        result = llm.pop_advisor_result(456, "post_verify")
        assert result is None

    def test_advisor_independent_of_executor_calls(self):
        llm = FakeLLM()
        llm.script_review(123, ["v1", "v2"])
        llm.script_advisor(123, "post_verify", ["a1", "a2"])
        # Pop one of each; advisor count tracks only advisor pops
        llm.pop_advisor_result(123, "post_verify")
        # Note: we don't have a public pop for executor at the same level —
        # this test just confirms scripting is independent
        assert llm.advisor_call_count_for("post_verify") == 1
        # Second advisor pop still has a result
        result = llm.pop_advisor_result(123, "post_verify")
        assert result == "a2"
        assert llm.advisor_call_count_for("post_verify") == 2

    def test_script_advisor_replaces_existing_queue(self):
        """script_advisor REPLACES (not appends) — matches _ScriptedRunner semantics."""
        llm = FakeLLM()
        llm.script_advisor(123, "post_verify", ["a1", "a2"])
        llm.script_advisor(123, "post_verify", ["b1"])  # second call wins
        assert llm.pop_advisor_result(123, "post_verify") == "b1"
        assert llm.pop_advisor_result(123, "post_verify") is None


class _StubAdvisorRunner:
    """Minimal stand-in for the subagent runner; returns canned JSON."""

    def __init__(self, payload: str | Exception) -> None:
        self._payload = payload
        self.calls: list[dict[str, Any]] = []

    async def run(self, *, model: str, subagent_type: str, prompt: str) -> str:
        self.calls.append(
            {"model": model, "subagent_type": subagent_type, "prompt": prompt}
        )
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class TestPostVerifyAdvisorHappyPath:
    def test_returns_approve_on_well_formed_json(self):
        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="approved",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "APPROVE"

    def test_returns_veto_on_well_formed_json(self):
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"missed regression",'
            '"disagreements":[],"suggested_fix_direction":"add test"}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="approved",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "VETO"
        assert result.suggested_fix_direction == "add test"

    def test_advisory_authority_downgrades_veto_to_approve(self):
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"x","disagreements":[]}'
        )
        # wiki_ingest is advisory, not veto
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
        )
        inp = PostVerifyInput(
            surface="wiki_ingest",
            diff="...",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        # advisory mode: veto downgraded to APPROVE; reasoning + disagreements preserved
        assert result.verdict == "APPROVE"
        assert result.reasoning == "x"

    def test_runner_called_with_correct_model_and_subagent_type(self):
        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["model"] == "opus"  # default advisor_model
        assert call["subagent_type"] == "hydraflow-review-advisor"
        assert "pr_review" in call["prompt"]
        assert "## Diff" in call["prompt"]

    def test_pre_flight_plan_threaded_into_prompt(self):
        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[FocusArea(description="d", files=["a.py"], rationale="r")],
            rubric=["check 1"],
            escalation_signals=["see X"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
            pre_flight_plan=plan,
        )
        asyncio.run(advisor.run(inp))
        call = runner.calls[0]
        assert "Pre-flight plan" in call["prompt"]
        assert "check 1" in call["prompt"]
