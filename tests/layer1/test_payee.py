"""O3 — payee substitution: the contract implemented by `PayeeSubstitutionRule`.

These fail until the rule is written. They are the specification.
"""

import pytest

from acg.domain.decision import Decision
from acg.layer1.payee import ATTACK_CLASS, RULE_ID, PayeeSubstitutionRule
from acg.layer1.rules import EvaluationContext, Finding

from .conftest import ATTACKER_PAYEE, REGISTERED_PAYEE


@pytest.fixture
def rule() -> PayeeSubstitutionRule:
    return PayeeSubstitutionRule()


class TestMetadata:
    def test_declares_its_identity(self, rule: PayeeSubstitutionRule) -> None:
        assert rule.rule_id == RULE_ID
        assert rule.attack_class == ATTACK_CLASS


class TestTheBenignCase:
    def test_allows_the_registered_payee(
        self, rule: PayeeSubstitutionRule, request_factory, context: EvaluationContext
    ) -> None:
        finding = rule.evaluate(request_factory(), context)

        assert finding.decision is Decision.ALLOW

    def test_returns_a_finding_carrying_its_own_identity(
        self, rule: PayeeSubstitutionRule, request_factory, context: EvaluationContext
    ) -> None:
        finding = rule.evaluate(request_factory(), context)

        assert isinstance(finding, Finding)
        assert finding.rule_id == RULE_ID
        assert finding.attack_class == ATTACK_CLASS


class TestTheAttack:
    def test_blocks_a_substituted_payee(
        self, rule: PayeeSubstitutionRule, request_factory, context: EvaluationContext
    ) -> None:
        finding = rule.evaluate(request_factory(payee_id=ATTACKER_PAYEE), context)

        assert finding.decision is Decision.BLOCK

    def test_never_routes_a_substitution_to_review(
        self, rule: PayeeSubstitutionRule, request_factory, context: EvaluationContext
    ) -> None:
        # There is no benign reading of money going somewhere the merchant
        # never registered, so a human queue would only add latency to a
        # certain no.
        finding = rule.evaluate(request_factory(payee_id=ATTACKER_PAYEE), context)

        assert finding.decision is not Decision.REVIEW

    @pytest.mark.parametrize(
        "payee",
        [
            pytest.param(REGISTERED_PAYEE.upper(), id="case-changed"),
            pytest.param(f" {REGISTERED_PAYEE} ", id="whitespace-padded"),
            pytest.param(f"{REGISTERED_PAYEE}_evil", id="suffixed"),
            pytest.param(f"evil_{REGISTERED_PAYEE}", id="prefixed"),
            pytest.param(REGISTERED_PAYEE[:-1], id="truncated"),
            pytest.param(f"{REGISTERED_PAYEE}​", id="zero-width-suffixed"),
        ],
    )
    def test_the_comparison_is_exact(
        self,
        rule: PayeeSubstitutionRule,
        request_factory,
        context: EvaluationContext,
        payee: str,
    ) -> None:
        """Every near-miss is a different destination.

        Normalisation, case folding, prefix or suffix matching are each a way
        to make two different payees compare equal. A payee id is an opaque
        token, not text a human typed, so nothing is forgiven.
        """
        finding = rule.evaluate(request_factory(payee_id=payee), context)

        assert finding.decision is Decision.BLOCK


class TestTheReason:
    def test_explains_itself(
        self, rule: PayeeSubstitutionRule, request_factory, context: EvaluationContext
    ) -> None:
        finding = rule.evaluate(request_factory(payee_id=ATTACKER_PAYEE), context)

        assert finding.reason

    def test_does_not_echo_the_requested_payee(
        self, rule: PayeeSubstitutionRule, request_factory, context: EvaluationContext
    ) -> None:
        """The requested payee is attacker-controlled and is rendered downstream.

        A reason that quotes it verbatim carries the attacker's text into the
        console and the audit log.
        """
        injected = "payee_x</script><script>alert(1)</script>"

        finding = rule.evaluate(request_factory(payee_id=injected), context)

        assert injected not in finding.reason
