"""ScenarioBuilder — compose builders, run pipeline, accumulate expectations.

Intentionally thin over the existing MockWorld.run_pipeline() API. The only
new concept is the .expect_*().run() fluent chain.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from tests.scenarios.builders.repo import RepoStateBuilder
from tests.scenarios.builders.trace import AgentTraceBuilder

if TYPE_CHECKING:
    from tests.scenarios.fakes.mock_world import MockWorld

Expectation = Callable[["MockWorld"], None]


@dataclass(frozen=True)
class _IssueExpectationGroup:
    number: int
    parent: ScenarioBuilder

    def merged(self) -> ScenarioBuilder:
        def _check(world: MockWorld) -> None:
            pr = world.github.pr_for_issue(self.number)
            assert pr is not None, f"issue {self.number}: no PR created"
            assert pr.merged, f"issue {self.number}: PR not merged"

        return self.parent._with_expectation(_check)

    def labels_contain(self, label: str) -> ScenarioBuilder:
        def _check(world: MockWorld) -> None:
            labels = world.github.issue(self.number).labels
            assert label in labels, (
                f"issue {self.number}: label {label!r} missing, got {labels!r}"
            )

        return self.parent._with_expectation(_check)


@dataclass(frozen=True)
class ScenarioBuilder:
    name: str = ""
    _given: RepoStateBuilder | None = None
    _agents: tuple[AgentTraceBuilder, ...] = field(default_factory=tuple)
    _expectations: tuple[Expectation, ...] = field(default_factory=tuple)
    _pipeline_invoked: bool = False

    def given(self, repo: RepoStateBuilder) -> ScenarioBuilder:
        return replace(self, _given=repo)

    def and_agent(self, trace: AgentTraceBuilder) -> ScenarioBuilder:
        return replace(self, _agents=(*self._agents, trace))

    def when_pipeline_runs(self) -> ScenarioBuilder:
        return replace(self, _pipeline_invoked=True)

    def expect_issue(self, number: int) -> _IssueExpectationGroup:
        return _IssueExpectationGroup(number=number, parent=self)

    def _with_expectation(self, exp: Expectation) -> ScenarioBuilder:
        return replace(self, _expectations=(*self._expectations, exp))

    async def run(self, world: MockWorld) -> None:
        if self._given is not None:
            for issue_builder in self._given._issues:
                # Call issue_builder.at to seed world.github, then mirror into
                # world._issues so run_pipeline() sees the issue in its seed dict.
                fake_issue = issue_builder.at(world)
                world._issues[fake_issue.number] = {
                    "number": fake_issue.number,
                    "title": fake_issue.title,
                    "body": fake_issue.body,
                    "labels": list(fake_issue.labels),
                }
            for pr_builder in self._given._prs:
                await pr_builder.at(world)
        for agent in self._agents:
            agent.at(world)
        if self._pipeline_invoked:
            await world.run_pipeline()
        for exp in self._expectations:
            exp(world)
