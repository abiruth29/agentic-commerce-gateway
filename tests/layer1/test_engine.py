"""The fold, tested against stub rules rather than real ones.

The engine's job is to run rules and join their findings. Testing it with
fake rules whose verdicts are fixed keeps those two concerns apart: an engine
test that depended on a real rule would fail for two unrelated reasons.
"""

from dataclasses import dataclass

import pytest

from acg.domain.decision import Decision
from acg.domain.request import PurchaseRequest
from acg.layer1.engine import evaluate
from acg.layer1.rules import EvaluationContext, Finding


@dataclass
class StubRule:
    """A rule that always returns the verdict it was built with."""

    rule_id: str
    attack_class: str
    verdict: Decision
    calls: int = 0

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        self.calls += 1
        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=self.verdict,
            reason=f"stub {self.rule_id}",
        )


def stub(verdict: Decision, name: str = "stub") -> StubRule:
    return StubRule(rule_id=name, attack_class="TEST", verdict=verdict)


class TestTheFold:
    def test_no_rules_yields_allow(
        self, request_factory, context: EvaluationContext
    ) -> None:
        # ALLOW is the lattice identity, so an empty rule set is a clean pass
        # rather than a special case.
        verdict = evaluate(request_factory(), context, ())

        assert verdict.decision is Decision.ALLOW
        assert verdict.findings == ()

    @pytest.mark.parametrize(
        ("verdicts", "expected"),
        [
            ([Decision.ALLOW], Decision.ALLOW),
            ([Decision.REVIEW], Decision.REVIEW),
            ([Decision.BLOCK], Decision.BLOCK),
            ([Decision.ALLOW, Decision.ALLOW], Decision.ALLOW),
            ([Decision.ALLOW, Decision.REVIEW], Decision.REVIEW),
            ([Decision.ALLOW, Decision.BLOCK], Decision.BLOCK),
            ([Decision.REVIEW, Decision.BLOCK], Decision.BLOCK),
            ([Decision.BLOCK, Decision.REVIEW, Decision.ALLOW], Decision.BLOCK),
        ],
    )
    def test_takes_the_most_restrictive_finding(
        self,
        request_factory,
        context: EvaluationContext,
        verdicts: list[Decision],
        expected: Decision,
    ) -> None:
        rules = tuple(stub(v, f"stub_{i}") for i, v in enumerate(verdicts))

        assert evaluate(request_factory(), context, rules).decision is expected

    def test_does_not_depend_on_rule_order(
        self, request_factory, context: EvaluationContext
    ) -> None:
        # combine is commutative and associative, so no rule can win by being
        # registered first.
        forwards = (stub(Decision.BLOCK, "a"), stub(Decision.ALLOW, "b"))
        backwards = (stub(Decision.ALLOW, "b"), stub(Decision.BLOCK, "a"))

        assert (
            evaluate(request_factory(), context, forwards).decision
            is evaluate(request_factory(), context, backwards).decision
        )


class TestEveryRuleRuns:
    def test_does_not_short_circuit_after_a_block(
        self, request_factory, context: EvaluationContext
    ) -> None:
        """The per-class breakdown needs every rule's finding on every request.

        Stopping at the first BLOCK would be faster and would destroy the
        ablation the evaluation is built on.
        """
        blocker = stub(Decision.BLOCK, "blocker")
        follower = stub(Decision.ALLOW, "follower")

        evaluate(request_factory(), context, (blocker, follower))

        assert follower.calls == 1

    def test_keeps_every_finding_in_rule_order(
        self, request_factory, context: EvaluationContext
    ) -> None:
        rules = (
            stub(Decision.ALLOW, "first"),
            stub(Decision.BLOCK, "second"),
            stub(Decision.REVIEW, "third"),
        )

        verdict = evaluate(request_factory(), context, rules)

        assert [f.rule_id for f in verdict.findings] == ["first", "second", "third"]


class TestBlockingFindings:
    def test_surfaces_only_the_findings_that_decided_it(
        self, request_factory, context: EvaluationContext
    ) -> None:
        rules = (
            stub(Decision.ALLOW, "quiet"),
            stub(Decision.BLOCK, "loud"),
            stub(Decision.REVIEW, "middling"),
        )

        verdict = evaluate(request_factory(), context, rules)

        assert [f.rule_id for f in verdict.blocking] == ["loud"]

    def test_an_all_allow_verdict_reports_every_finding_as_blocking(
        self, request_factory, context: EvaluationContext
    ) -> None:
        # At ALLOW every finding is >= the verdict, which is correct rather
        # than surprising: nothing was withheld, so nothing is singled out.
        rules = (stub(Decision.ALLOW, "a"), stub(Decision.ALLOW, "b"))

        verdict = evaluate(request_factory(), context, rules)

        assert len(verdict.blocking) == 2
