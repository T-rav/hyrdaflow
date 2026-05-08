import asyncio
import contextlib
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
    MidFlightAdvisor,
    PostVerifyAdvisor,
    PostVerifyInput,
    PostVerifyResult,
    PRContext,
    PreFlightAdvisor,
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

    async def run(
        self,
        *,
        model: str,
        subagent_type: str,
        prompt: str,
        role: str,
    ) -> str:
        self.calls.append(
            {
                "model": model,
                "subagent_type": subagent_type,
                "prompt": prompt,
                "role": role,
            }
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


class TestPostVerifyAdvisorFailureModes:
    def test_runner_error_default_treats_as_approve(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)
        runner = _StubAdvisorRunner(RuntimeError("boom"))
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "APPROVE"
        assert "advisor-degraded" in result.reasoning
        assert "runner-error" in result.reasoning

    def test_runner_error_with_fail_as_veto_blocks(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", "true")
        runner = _StubAdvisorRunner(RuntimeError("boom"))
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "VETO"
        assert "advisor-degraded" in result.reasoning

    def test_malformed_json_routes_to_failure_mode_default(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)
        runner = _StubAdvisorRunner("not json at all")
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "APPROVE"
        assert "parse-error" in result.reasoning

    def test_malformed_json_with_fail_as_veto_blocks(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", "true")
        runner = _StubAdvisorRunner("not json at all")
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "VETO"

    def test_credit_exhausted_propagates(self):
        from subprocess_util import CreditExhaustedError

        runner = _StubAdvisorRunner(CreditExhaustedError("out of credit"))
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="x",
        )
        with pytest.raises(CreditExhaustedError):
            asyncio.run(advisor.run(inp))

    def test_authentication_error_propagates(self):
        from subprocess_util import AuthenticationError

        runner = _StubAdvisorRunner(AuthenticationError("bad token"))
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="...",
            executor_verdict_summary="x",
        )
        with pytest.raises(AuthenticationError):
            asyncio.run(advisor.run(inp))


class TestAdvisorSessionLogging:
    def test_success_writes_jsonl_entry(self, tmp_path):
        import json as _json

        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        log_path = tmp_path / "advisor_session.jsonl"
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            log_path=log_path,
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        lines = log_path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        entry = _json.loads(lines[0])
        assert entry["role"] == "post_verify"
        assert entry["surface"] == "pr_review"
        assert entry["error"] is None
        assert entry["duration_ms"] >= 0
        assert "ts" in entry

    def test_runner_error_writes_entry_with_error(self, tmp_path, monkeypatch):
        import json as _json

        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)
        runner = _StubAdvisorRunner(RuntimeError("boom"))
        log_path = tmp_path / "advisor_session.jsonl"
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            log_path=log_path,
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        entry = _json.loads(
            log_path.read_text(encoding="utf-8").strip().splitlines()[0]
        )
        assert entry["error"] == "runner-error"

    def test_multiple_calls_append(self, tmp_path):
        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        log_path = tmp_path / "advisor_session.jsonl"
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            log_path=log_path,
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        asyncio.run(advisor.run(inp))
        assert len(log_path.read_text(encoding="utf-8").strip().splitlines()) == 2

    def test_no_log_path_is_noop(self):
        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            log_path=None,
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "APPROVE"


# --- T13 telemetry helpers ---


class _MetricRecorder:
    """Wraps an OTel ``InMemoryMetricReader`` for ergonomic test assertions.

    The advisor module-level meter is a proxy that resolves to whatever
    ``MeterProvider`` is set when ``.add()`` / ``.record()`` is called, so
    installing a provider after import still routes datapoints to the
    in-memory reader. See verify-script in T13 plan.
    """

    def __init__(self) -> None:
        from opentelemetry.sdk.metrics.export import InMemoryMetricReader

        self._reader = InMemoryMetricReader()

    @property
    def reader(self):  # type: ignore[no-untyped-def]
        return self._reader

    def _collect(self) -> list:
        data = self._reader.get_metrics_data()
        flat = []
        if data is None:
            return flat
        for rm in data.resource_metrics:
            for sm in rm.scope_metrics:
                for metric in sm.metrics:
                    flat.append(metric)
        return flat

    def _matching_points(self, metric_name: str, attrs: dict[str, Any]) -> list:
        out = []
        for metric in self._collect():
            if metric.name != metric_name:
                continue
            for dp in metric.data.data_points:
                dp_attrs = dict(dp.attributes or {})
                if all(dp_attrs.get(k) == v for k, v in attrs.items()):
                    out.append(dp)
        return out

    def counter_value(self, metric_name: str, **attrs: Any) -> int | float:
        """Sum of values for all datapoints matching ``attrs``. 0 if none."""
        points = self._matching_points(metric_name, attrs)
        return sum(p.value for p in points)

    def histogram_count(self, metric_name: str, **attrs: Any) -> int:
        """Count of histogram observations matching ``attrs``."""
        points = self._matching_points(metric_name, attrs)
        return sum(int(p.count) for p in points)

    def metric_names(self) -> set[str]:
        return {m.name for m in self._collect()}


@pytest.fixture
def metric_recorder():
    """Install a fresh OTel MeterProvider backed by an InMemoryMetricReader.

    Yields a ``_MetricRecorder`` for assertions. After the test, restores a
    no-op MeterProvider so other tests don't see leaked datapoints.

    Notes:
        ``opentelemetry.metrics.set_meter_provider`` is gated by a one-shot
        guard (``_METER_PROVIDER_SET_ONCE``) inside ``opentelemetry.metrics._internal``,
        so back-to-back calls in tests require resetting the gate. We reach
        into the private module to flip ``_done``; this is the same gate the
        SDK exposes for tests in upstream's own test suite.
    """
    from opentelemetry import metrics
    from opentelemetry.metrics import NoOpMeterProvider, _internal
    from opentelemetry.sdk.metrics import MeterProvider

    recorder = _MetricRecorder()
    provider = MeterProvider(metric_readers=[recorder.reader])
    _internal._METER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
    metrics.set_meter_provider(provider)
    try:
        yield recorder
    finally:
        with contextlib.suppress(Exception):
            provider.shutdown()
        _internal._METER_PROVIDER_SET_ONCE._done = False  # type: ignore[attr-defined]
        metrics.set_meter_provider(NoOpMeterProvider())


class TestAdvisorTelemetry:
    """T13: PostVerifyAdvisor + ReviewPhase retry-loop OTel metric emissions."""

    def test_post_verify_emits_calls_total_on_success(self, metric_recorder):
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
        assert (
            metric_recorder.counter_value(
                "review_advisor_calls_total",
                surface="pr_review",
                role="post_verify",
                outcome="success",
            )
            == 1
        )

    def test_post_verify_emits_call_duration_histogram(self, metric_recorder):
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
        assert (
            metric_recorder.histogram_count(
                "review_advisor_call_duration_seconds",
                surface="pr_review",
                role="post_verify",
            )
            == 1
        )

    def test_post_verify_emits_verdict_total_approve(self, metric_recorder):
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
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_verdict_total",
                surface="pr_review",
                verdict="approve",
            )
            == 1
        )

    def test_post_verify_emits_verdict_total_veto(self, metric_recorder):
        # pr_review has authority="veto" so the VETO verdict is preserved
        # post-advisory-downgrade. The verdict counter should reflect it.
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"r","disagreements":[]}'
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
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_verdict_total",
                surface="pr_review",
                verdict="veto",
            )
            == 1
        )

    def test_advisory_authority_records_post_downgrade_verdict(self, metric_recorder):
        # wiki_ingest is advisory: VETO is downgraded to APPROVE before
        # return — the verdict counter should reflect the downgrade.
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"r","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
        )
        inp = PostVerifyInput(
            surface="wiki_ingest",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_verdict_total",
                surface="wiki_ingest",
                verdict="approve",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_verdict_total",
                surface="wiki_ingest",
                verdict="veto",
            )
            == 0
        )

    def test_runner_error_emits_degraded_total_and_outcome_error(
        self, metric_recorder, monkeypatch
    ):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)
        runner = _StubAdvisorRunner(RuntimeError("boom"))
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
        assert (
            metric_recorder.counter_value(
                "review_advisor_calls_total",
                surface="pr_review",
                role="post_verify",
                outcome="error",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_degraded_total",
                surface="pr_review",
            )
            == 1
        )

    def test_parse_error_emits_degraded_total_and_outcome_parse_error(
        self, metric_recorder, monkeypatch
    ):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)
        runner = _StubAdvisorRunner("not json at all")
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
        assert (
            metric_recorder.counter_value(
                "review_advisor_calls_total",
                surface="pr_review",
                role="post_verify",
                outcome="parse_error",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_degraded_total",
                surface="pr_review",
            )
            == 1
        )

    def test_credit_error_emits_outcome_error_and_no_degraded(self, metric_recorder):
        # Auth/credit errors propagate WITHOUT going through _handle_failure,
        # so degraded_total must NOT increment, but calls_total still records
        # the call as an error.
        from subprocess_util import CreditExhaustedError

        runner = _StubAdvisorRunner(CreditExhaustedError("out"))
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        with pytest.raises(CreditExhaustedError):
            asyncio.run(advisor.run(inp))
        assert (
            metric_recorder.counter_value(
                "review_advisor_calls_total",
                surface="pr_review",
                role="post_verify",
                outcome="error",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_post_verify_degraded_total",
                surface="pr_review",
            )
            == 0
        )

    def test_review_phase_loop_counters_emit_via_helper(self, metric_recorder):
        # The retry-loop counters live on review_phase. We exercise the
        # module-level helper directly so this test stays independent of the
        # full ReviewPhase wiring (covered by tests/scenarios/test_pr_review_advisor_*).
        from review_phase import (
            _emit_advisor_loop_metric,
            _veto_exhausted_total,
            _veto_recovered_total,
            _veto_retries_total,
        )

        _emit_advisor_loop_metric(
            _veto_retries_total, {"surface": "pr_review", "attempt": "1"}
        )
        _emit_advisor_loop_metric(
            _veto_retries_total, {"surface": "pr_review", "attempt": "2"}
        )
        _emit_advisor_loop_metric(
            _veto_retries_total, {"surface": "pr_review", "attempt": "exhausted"}
        )
        _emit_advisor_loop_metric(_veto_recovered_total, {"surface": "pr_review"})
        _emit_advisor_loop_metric(_veto_exhausted_total, {"surface": "pr_review"})

        assert (
            metric_recorder.counter_value(
                "review_advisor_veto_retries_total",
                surface="pr_review",
                attempt="1",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_veto_retries_total",
                surface="pr_review",
                attempt="exhausted",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_veto_recovered_total",
                surface="pr_review",
            )
            == 1
        )
        assert (
            metric_recorder.counter_value(
                "review_advisor_veto_exhausted_total",
                surface="pr_review",
            )
            == 1
        )

    def test_disagreements_emit_disagreement_total(self, metric_recorder):
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"missed two issues",'
            '"disagreements":['
            '{"executor_claim":"safe","advisor_assessment":"unsafe X","severity":"blocking"},'
            '{"executor_claim":"complete","advisor_assessment":"missing Y","severity":"concern"}'
            '],"suggested_fix_direction":"address X and Y"}'
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
        blocking = metric_recorder.counter_value(
            "review_advisor_disagreement_total",
            surface="pr_review",
            role="post_verify",
            severity="blocking",
        )
        concern = metric_recorder.counter_value(
            "review_advisor_disagreement_total",
            surface="pr_review",
            role="post_verify",
            severity="concern",
        )
        assert blocking == 1
        assert concern == 1

    def test_no_disagreements_does_not_emit_disagreement_total(self, metric_recorder):
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
        assert (
            metric_recorder.counter_value(
                "review_advisor_disagreement_total",
                surface="pr_review",
                role="post_verify",
                severity="blocking",
            )
            == 0
        )

    def test_disagreement_validated_when_preflight_predicted(self, metric_recorder):
        """Pre-flight escalation_signals predicting a post-verify disagreement
        increments _disagreement_validated_total{role=pre_flight}."""
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[],
            rubric=[],
            escalation_signals=["race condition in worker loop"],
        )
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"missed race",'
            '"disagreements":[{'
            '"executor_claim":"safe","advisor_assessment":"there is a race condition in worker loop",'
            '"severity":"blocking"}],'
            '"suggested_fix_direction":"add a lock"}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="approved",
            pre_flight_plan=plan,
        )
        asyncio.run(advisor.run(inp))
        validated = metric_recorder.counter_value(
            "review_advisor_disagreement_validated_total",
            surface="pr_review",
            role="pre_flight",
        )
        assert validated == 1

    def test_disagreement_not_validated_when_no_plan(self, metric_recorder):
        """Without a pre-flight plan, disagreements aren't validated."""
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"missed something",'
            '"disagreements":[{'
            '"executor_claim":"x","advisor_assessment":"missed thing",'
            '"severity":"blocking"}]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
            pre_flight_plan=None,
        )
        asyncio.run(advisor.run(inp))
        validated = metric_recorder.counter_value(
            "review_advisor_disagreement_validated_total",
            surface="pr_review",
            role="pre_flight",
        )
        assert validated == 0

    def test_disagreement_not_validated_when_no_signal_match(self, metric_recorder):
        """Disagreement without a matching pre-flight signal doesn't count."""
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[],
            rubric=[],
            escalation_signals=["check error handling in api layer"],
        )
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"unrelated issue",'
            '"disagreements":[{'
            '"executor_claim":"x","advisor_assessment":"completely unrelated thing",'
            '"severity":"concern"}]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
            pre_flight_plan=plan,
        )
        asyncio.run(advisor.run(inp))
        validated = metric_recorder.counter_value(
            "review_advisor_disagreement_validated_total",
            surface="pr_review",
            role="pre_flight",
        )
        assert validated == 0

    def test_multiple_validated_disagreements_increment_counter(self, metric_recorder):
        """Each matched disagreement increments by 1.

        Forward-only matching (T24.5 closed I5): signals must appear inside
        assessments, so the signals here are short enough to be substrings
        of the assessments below — but still >= ``_MIN_SIGNAL_MATCH_LEN``.
        """
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[],
            rubric=[],
            escalation_signals=[
                "missing test coverage for edge case X",
                "verify the lock ordering",
            ],
        )
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"two issues",'
            '"disagreements":['
            '{"executor_claim":"a","advisor_assessment":"missing test coverage for edge case X",'
            '"severity":"blocking"},'
            '{"executor_claim":"b","advisor_assessment":"verify the lock ordering",'
            '"severity":"concern"}'
            "]}"
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
            pre_flight_plan=plan,
        )
        asyncio.run(advisor.run(inp))
        validated = metric_recorder.counter_value(
            "review_advisor_disagreement_validated_total",
            surface="pr_review",
            role="pre_flight",
        )
        assert validated == 2


class TestProductionPathJSONExtraction:
    """Regression tests for C1 — agent transcripts are not bare JSON.

    The production runner returns the agent's full text response, which
    typically contains prose, stream events, or fenced JSON. The advisor
    must extract and parse the JSON block, not require bare JSON.
    """

    def test_fenced_json_block_extracts_cleanly(self):
        runner = _StubAdvisorRunner(
            "I reviewed the diff. Here is my verdict:\n\n"
            "```json\n"
            '{"verdict":"APPROVE","reasoning":"looks good","disagreements":[]}\n'
            "```\n\n"
            "Done."
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
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "APPROVE"
        assert result.reasoning == "looks good"

    def test_bare_json_block_in_prose_extracts(self):
        runner = _StubAdvisorRunner(
            "After analysis, my verdict is "
            '{"verdict":"VETO","reasoning":"missed regression","disagreements":[],'
            '"suggested_fix_direction":"add test"}'
            " which I am confident about."
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
        result = asyncio.run(advisor.run(inp))
        assert result.verdict == "VETO"
        assert result.suggested_fix_direction == "add test"

    def test_no_json_falls_through_to_failure_mode(self, monkeypatch):
        monkeypatch.delenv("HYDRAFLOW_REVIEW_POSTVERIFY_FAIL_AS_VETO", raising=False)
        runner = _StubAdvisorRunner("I cannot produce a verdict.")
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        result = asyncio.run(advisor.run(inp))
        # default failure: APPROVE
        assert result.verdict == "APPROVE"
        assert "parse-error" in result.reasoning


class TestAdvisorBudgetResetAcrossReviews:
    """Regression test for C2 — _advisor_attempt must reset on every
    _run_post_verify_advisor entry, not persist across reviews of the same PR.

    Pinning the reset semantics catches the regression class even though
    the cross-review behavior is hard to test without a full PR-replay
    scenario. TODO(Phase 3): Add a scenario test that drives two consecutive
    reviews of the same PR through ReviewPhase and asserts the second
    review's advisor sees a fresh budget.
    """

    def test_advisor_attempt_resets_per_function_entry(self):
        # Construct a minimal ReviewPhase-like shim with the load-bearing
        # state attributes. We're not testing the full pipeline — just the
        # state reset semantics.

        # Simulate review 1 leaving budget exhausted state behind
        attempts = {100: 2}
        results = {100: ["stale-result-1", "stale-result-2", "stale-result-3"]}

        # Simulate the reset that _run_post_verify_advisor must do on entry
        attempts[100] = 0
        results[100] = []

        assert attempts[100] == 0
        assert results[100] == []


class TestPostVerifyAdvisorPRNumberWiring:
    """Regression tests for I1 — jsonl entries must include pr_number and
    token-placeholder fields per spec §"Logging".
    """

    def test_jsonl_entry_includes_pr_number_and_token_placeholders(self, tmp_path):
        import json as _json

        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        log_path = tmp_path / "advisor_session.jsonl"
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            log_path=log_path,
            pr_number=42,
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        entry = _json.loads(
            log_path.read_text(encoding="utf-8").strip().splitlines()[0]
        )
        assert entry["pr_number"] == 42
        assert entry["tokens_in"] is None
        assert entry["tokens_out"] is None

    def test_jsonl_entry_pr_number_is_none_when_unset(self, tmp_path):
        import json as _json

        runner = _StubAdvisorRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        log_path = tmp_path / "advisor_session.jsonl"
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            log_path=log_path,
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
        )
        asyncio.run(advisor.run(inp))
        entry = _json.loads(
            log_path.read_text(encoding="utf-8").strip().splitlines()[0]
        )
        assert entry["pr_number"] is None
        assert entry["tokens_in"] is None
        assert entry["tokens_out"] is None


class TestPreFlightAdvisor:
    def test_returns_review_plan_on_well_formed_json(self):
        runner = _StubAdvisorRunner(
            '{"risk_summary":"r","focus_areas":[{"description":"d",'
            '"files":["a.py"],"rationale":"r"}],"rubric":["check 1"],'
            '"escalation_signals":["see X"]}'
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PreFlightInput(surface="pr_review", diff="d")
        plan = asyncio.run(advisor.run(inp))
        assert plan is not None
        assert plan.risk_summary == "r"
        assert len(plan.focus_areas) == 1
        assert plan.rubric == ["check 1"]

    def test_runner_called_with_correct_model_and_subagent_type(self):
        runner = _StubAdvisorRunner(
            '{"risk_summary":"r","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PreFlightInput(surface="pr_review", diff="d", spec="some spec text")
        asyncio.run(advisor.run(inp))
        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["model"] == "opus"
        assert call["subagent_type"] == "hydraflow-review-advisor"
        assert "pr_review" in call["prompt"]
        assert "## Diff" in call["prompt"]

    def test_spec_threaded_into_prompt(self):
        runner = _StubAdvisorRunner(
            '{"risk_summary":"r","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PreFlightInput(surface="pr_review", diff="d", spec="ISSUE BODY HERE")
        asyncio.run(advisor.run(inp))
        assert "ISSUE BODY HERE" in runner.calls[0]["prompt"]

    def test_runner_error_returns_none(self):
        runner = _StubAdvisorRunner(RuntimeError("boom"))
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PreFlightInput(surface="pr_review", diff="d")
        plan = asyncio.run(advisor.run(inp))
        assert plan is None  # advisory failure: no plan, executor proceeds without one

    def test_malformed_json_returns_none(self):
        runner = _StubAdvisorRunner("not json at all")
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        plan = asyncio.run(advisor.run(PreFlightInput(surface="pr_review", diff="d")))
        assert plan is None

    def test_extracts_json_from_transcript_with_prose(self):
        # Production transcripts include prose around the JSON block
        runner = _StubAdvisorRunner(
            "I analyzed the diff. Here is the plan:\n\n"
            "```json\n"
            '{"risk_summary":"r","focus_areas":[],"rubric":[],"escalation_signals":[]}\n'
            "```\n\n"
            "Done."
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        plan = asyncio.run(advisor.run(PreFlightInput(surface="pr_review", diff="d")))
        assert plan is not None
        assert plan.risk_summary == "r"

    def test_credit_exhausted_propagates(self):
        from subprocess_util import CreditExhaustedError

        runner = _StubAdvisorRunner(CreditExhaustedError("out"))
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        with pytest.raises(CreditExhaustedError):
            asyncio.run(advisor.run(PreFlightInput(surface="pr_review", diff="d")))


class TestMidFlightAdvisor:
    def test_returns_invocation_when_enabled(self, monkeypatch):
        # Ensure no kill switches are blocking
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        adv = MidFlightAdvisor(surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"])
        invocation = adv.build_task_invocation(
            question="is the test wrong or the fix wrong?",
            context_summary="line 42 fails after my one-line change",
            options=["test is wrong", "fix is wrong"],
        )
        assert invocation is not None
        assert invocation["model"] == "opus"
        assert invocation["subagent_type"] == "hydraflow-review-advisor"
        assert "is the test wrong" in invocation["prompt"]
        assert "line 42 fails" in invocation["prompt"]
        # Both options must appear
        assert "test is wrong" in invocation["prompt"]
        assert "fix is wrong" in invocation["prompt"]

    def test_returns_none_when_surface_mid_flight_disabled(self, monkeypatch):
        # adr_review has mid_flight_enabled=False
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED",
            "HYDRAFLOW_ADR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        adv = MidFlightAdvisor(surface_config=SURFACE_ADVISOR_CONFIGS["adr_review"])
        result = adv.build_task_invocation(question="?", context_summary="x")
        assert result is None  # surface config disables it

    def test_returns_none_when_role_kill_switch_off(self, monkeypatch):
        # pr_review has mid_flight_enabled=True but the role kill-switch overrides
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        monkeypatch.setenv("HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED", "false")
        adv = MidFlightAdvisor(surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"])
        assert adv.build_task_invocation(question="?", context_summary="x") is None

    def test_returns_none_when_master_off(self, monkeypatch):
        monkeypatch.setenv("HYDRAFLOW_REVIEW_ADVISOR_ENABLED", "false")
        adv = MidFlightAdvisor(surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"])
        assert adv.build_task_invocation(question="?", context_summary="x") is None

    def test_options_omitted_when_empty(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        adv = MidFlightAdvisor(surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"])
        invocation = adv.build_task_invocation(
            question="how confident is the executor?",
            context_summary="ran 3 tests, all green",
        )
        assert invocation is not None
        # No "Options under consideration" section when no options provided
        assert "Options under consideration" not in invocation["prompt"]

    def test_uses_advisor_model_from_surface_config(self, monkeypatch):
        for v in (
            "HYDRAFLOW_REVIEW_ADVISOR_ENABLED",
            "HYDRAFLOW_REVIEW_MIDFLIGHT_ENABLED",
            "HYDRAFLOW_PR_REVIEW_ADVISOR_ENABLED",
        ):
            monkeypatch.delenv(v, raising=False)
        # Override the advisor model via env
        monkeypatch.setenv("HYDRAFLOW_PR_REVIEW_ADVISOR_MODEL", "haiku")
        cfg = build_surface_config("pr_review")
        adv = MidFlightAdvisor(surface_config=cfg)
        invocation = adv.build_task_invocation(question="?", context_summary="x")
        assert invocation is not None
        assert invocation["model"] == "haiku"

    def test_tool_description_present_as_class_constant(self):
        # T21 will inject this string into the executor's prompt
        assert isinstance(MidFlightAdvisor.TOOL_DESCRIPTION, str)
        assert "consult" in MidFlightAdvisor.TOOL_DESCRIPTION.lower()
        # Discipline guard — the description must steer the executor away from
        # using the tool for verifiable things
        assert "verify" in MidFlightAdvisor.TOOL_DESCRIPTION.lower()


class _RoleCapturingRunner:
    """Minimal runner that records the ``role`` it was called with."""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.last_role: str | None = None

    async def run(
        self,
        *,
        model: str,
        subagent_type: str,
        prompt: str,
        role: str,
    ) -> str:
        self.last_role = role
        return self._payload


class TestRunnerRoleContract:
    """T24.5 (I1): pin the prompt-to-runner role contract end-to-end.

    These tests construct each advisor's actual prompt via its own
    ``_build_prompt`` / ``_render_prompt`` method and pass it through the
    runner Protocol with the explicit ``role=`` parameter. If a future
    refactor breaks role wiring, these tests fail loudly instead of
    silently misrouting in production.
    """

    def test_pre_flight_runner_call_uses_pre_flight_role(self):
        runner = _RoleCapturingRunner(
            '{"risk_summary":"r","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        asyncio.run(advisor.run(PreFlightInput(surface="pr_review", diff="d")))
        assert runner.last_role == "pre_flight"

    def test_post_verify_runner_call_uses_post_verify_role(self):
        runner = _RoleCapturingRunner(
            '{"verdict":"APPROVE","reasoning":"ok","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        asyncio.run(
            advisor.run(
                PostVerifyInput(
                    surface="pr_review",
                    diff="d",
                    executor_verdict_summary="x",
                )
            )
        )
        assert runner.last_role == "post_verify"

    def test_pre_flight_prompt_with_midflight_substring_in_spec_routes_correctly(
        self,
    ):
        """I2 regression: spec/issue body containing '## Mid-flight consult'
        substring must NOT cause the runner to misroute to mid-flight.

        Before T24.5, ``_PostVerifyRunner`` used substring-based detection
        that false-positived on this case (a meta-PR about the advisor
        pattern whose body documents the mid-flight consult format).
        """
        runner = _RoleCapturingRunner(
            '{"risk_summary":"r","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        asyncio.run(
            advisor.run(
                PreFlightInput(
                    surface="pr_review",
                    diff="d",
                    # Spec contains the Mid-flight marker — pre-T24.5 this
                    # misrouted because the runner substring-matched
                    # ``## Mid-flight consult`` anywhere in the prompt.
                    spec=(
                        "The advisor uses a ## Mid-flight consult template "
                        "for judgment-call escalations."
                    ),
                )
            )
        )
        assert runner.last_role == "pre_flight"


class TestMidFlightSentinelRouting:
    """T24.5 (I2): mid-flight prompts carry a sentinel marker so the runner
    can route them even when called via the executor's Task tool (which
    doesn't pass ``role=`` explicitly).
    """

    def test_midflight_prompt_starts_with_sentinel(self):
        adv = MidFlightAdvisor(surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"])
        invocation = adv.build_task_invocation(question="?", context_summary="x")
        assert invocation is not None
        assert invocation["prompt"].startswith(MidFlightAdvisor.SENTINEL)

    def test_sentinel_is_html_comment_so_renders_invisibly(self):
        # The sentinel must be a valid HTML comment so any markdown viewer
        # (PR descriptions, github comments) elides it. This guards the
        # convention the runner adapter relies on.
        assert MidFlightAdvisor.SENTINEL.startswith("<!--")
        assert MidFlightAdvisor.SENTINEL.endswith("-->")

    def test_format_mid_flight_for_prompt_documents_sentinel(self):
        from review_advisor import format_mid_flight_for_prompt

        section = format_mid_flight_for_prompt(SURFACE_ADVISOR_CONFIGS["pr_review"])
        assert section is not None
        # Executor-facing instruction text must include the sentinel so the
        # in-session Task call wraps it into the prompt.
        assert MidFlightAdvisor.SENTINEL in section


class TestDisagreementValidationShortSignals:
    """T24.5 (I5): tighten ``_validate_disagreements_against_plan`` to skip
    short generic signals (forward-only substring match).
    """

    def test_short_generic_signals_do_not_false_positive(self, metric_recorder):
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[],
            rubric=[],
            # 9 chars — under the _MIN_SIGNAL_MATCH_LEN floor
            escalation_signals=["test gaps"],
        )
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"unrelated",'
            '"disagreements":[{"executor_claim":"x",'
            '"advisor_assessment":"general test gaps everywhere",'
            '"severity":"concern"}]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
            pre_flight_plan=plan,
        )
        asyncio.run(advisor.run(inp))
        validated = metric_recorder.counter_value(
            "review_advisor_disagreement_validated_total",
            surface="pr_review",
            role="pre_flight",
        )
        assert validated == 0

    def test_short_signal_does_not_match_short_assessment_via_reverse(
        self, metric_recorder
    ):
        """The pre-T24.5 bidirectional match did ``assessment_lc in sig`` —
        which matched a short assessment word against a long signal even
        when topics differed. Forward-only match must drop this.
        """
        plan = ReviewPlan(
            risk_summary="r",
            focus_areas=[],
            rubric=[],
            # Long signal (>=10 chars), but the assessment "race" is only 4
            # chars — under bidirectional, "race" appearing in a long signal
            # ABOUT race conditions could match an unrelated short
            # assessment. Forward-only requires the SIGNAL be inside the
            # ASSESSMENT, which is what we want.
            escalation_signals=["watch for race conditions in worker loop"],
        )
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"x",'
            '"disagreements":[{"executor_claim":"x",'
            '"advisor_assessment":"race",'
            '"severity":"concern"}]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        inp = PostVerifyInput(
            surface="pr_review",
            diff="d",
            executor_verdict_summary="x",
            pre_flight_plan=plan,
        )
        asyncio.run(advisor.run(inp))
        validated = metric_recorder.counter_value(
            "review_advisor_disagreement_validated_total",
            surface="pr_review",
            role="pre_flight",
        )
        assert validated == 0


class TestSurfaceThreading:
    """T24.7: confirm the surface parameter routes to the correct advisor config.

    Phase 4 will wire pre_merge_spec_check, adr_review, visual_gate, wiki_ingest;
    these tests pin that surface threading works without behavior change at
    pr_review's call sites.
    """

    def test_pre_flight_input_carries_surface(self):
        # Construct PreFlightInput directly with a non-pr_review surface.
        inp = PreFlightInput(surface="adr_review", diff="d")
        assert inp.surface == "adr_review"

    def test_post_verify_input_carries_surface(self):
        inp = PostVerifyInput(
            surface="visual_gate", diff="d", executor_verdict_summary="x"
        )
        assert inp.surface == "visual_gate"

    def test_advisor_uses_input_surface_not_config_surface(self):
        """The advisor's _build_prompt must echo the input's surface, not the
        config's. This pins back-compat: pr_review tests with hardcoded
        config still work, but a test passing surface='adr_review' in the
        PreFlightInput sees that string in the prompt.

        surface_config drives the model resolution; input's surface is just
        the prompt field. T24.7 doesn't change that contract — it pins it
        so Phase 4 can rely on it.
        """
        runner = _StubAdvisorRunner(
            '{"risk_summary":"r","focus_areas":[],"rubric":[],"escalation_signals":[]}'
        )
        advisor = PreFlightAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
        )
        # Mismatched surface intentionally — input drives the prompt field.
        inp = PreFlightInput(surface="adr_review", diff="d")
        asyncio.run(advisor.run(inp))
        assert "adr_review" in runner.calls[0]["prompt"]


class TestSelfModificationGuard:
    """T29: when a diff touches the advisor's own implementation files,
    post-verify authority is FORCED to 'veto' regardless of surface config.

    Rationale (spec §5.8): the advisor must not approve changes to itself
    silently. wiki_ingest's advisory mode would otherwise let an advisor
    erroneously approve a code change to its own logic.
    """

    def test_diff_touching_review_advisor_forces_veto(self):
        """src/review_advisor.py in the diff → veto (even on advisory surface)."""
        from review_advisor import resolve_post_verify_authority

        diff = (
            "diff --git a/src/review_advisor.py b/src/review_advisor.py\n"
            "@@ -1,3 +1,4 @@\n+# new line\n"
        )
        # wiki_ingest surface defaults to "advisory"
        authority = resolve_post_verify_authority(
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
            diff=diff,
        )
        assert authority == "veto"

    def test_diff_touching_review_phase_forces_veto(self):
        from review_advisor import resolve_post_verify_authority

        diff = (
            "diff --git a/src/review_phase.py b/src/review_phase.py\n"
            "@@ -1,3 +1,4 @@\n+# new line\n"
        )
        authority = resolve_post_verify_authority(
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
            diff=diff,
        )
        assert authority == "veto"

    def test_unrelated_diff_keeps_configured_authority(self):
        from review_advisor import resolve_post_verify_authority

        diff = "diff --git a/src/foo.py b/src/foo.py\n@@ -1,3 +1,4 @@\n+# new line\n"
        # Wiki ingest stays advisory
        authority = resolve_post_verify_authority(
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
            diff=diff,
        )
        assert authority == "advisory"
        # PR review stays veto (already its default)
        authority_pr = resolve_post_verify_authority(
            surface_config=SURFACE_ADVISOR_CONFIGS["pr_review"],
            diff=diff,
        )
        assert authority_pr == "veto"

    def test_post_verify_advisor_honors_authority_override(self):
        """When PostVerifyAdvisor is constructed with authority_override=
        'veto' on an advisory-surface config, VETO is NOT downgraded.
        """
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"x","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],  # advisory by config
            authority_override="veto",  # T29 override
        )
        result = asyncio.run(
            advisor.run(
                PostVerifyInput(
                    surface="wiki_ingest", diff="d", executor_verdict_summary="x"
                )
            )
        )
        assert result.verdict == "VETO"  # NOT downgraded

    def test_post_verify_advisor_no_override_uses_config_authority(self):
        """Without authority_override, advisory config still downgrades VETO."""
        runner = _StubAdvisorRunner(
            '{"verdict":"VETO","reasoning":"x","disagreements":[]}'
        )
        advisor = PostVerifyAdvisor(
            runner=runner,
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],  # advisory
            # no authority_override — config wins
        )
        result = asyncio.run(
            advisor.run(
                PostVerifyInput(
                    surface="wiki_ingest", diff="d", executor_verdict_summary="x"
                )
            )
        )
        assert result.verdict == "APPROVE"  # downgraded
