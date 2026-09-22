"""O3 — payee substitution.

The headline class. Invoice redirection with the human removed from the loop:
the request keeps the right merchant, the right items, the right total, and
changes only where the money lands. Every budget, quantity and item control
passes it, because none of them look at the destination.

It needs no model. The merchant's payee was registered out of band at
onboarding, before any catalog text existed, so the check is a comparison
against an anchor the attacker cannot reach — not a judgement about intent.
That is the claim the project makes about its partition: the most financially
dangerous class is the one most obviously deterministic.
"""

from acg.domain.request import PurchaseRequest
from acg.layer1.rules import EvaluationContext, Finding

RULE_ID = "O3.payee_substitution"
ATTACK_CLASS = "O3"


class PayeeSubstitutionRule:
    """Refuse a request whose payee is not the merchant's registered payee."""

    rule_id = RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Compare the requested payee against the registered one.

        Written by hand: this is the rule the page leads with, and the one a
        reviewer is most likely to point at.

        The contract the tests hold it to:

        - a request whose `payee_id` equals `context.merchant.registered_payee_id`
          yields ALLOW
        - any other payee yields BLOCK, never REVIEW — there is no benign
          reading of money going somewhere the merchant never registered, so
          routing it to a human queue would only add latency to a certain no
        - the comparison is exact: no normalisation, no prefix or suffix
          matching, no case folding. Every one of those is a way to make two
          different destinations compare equal, and a payee identifier is an
          opaque token rather than text a human typed
        - the returned `reason` must not echo the requested payee verbatim,
          because it is attacker-controlled and is rendered downstream

        Args:
            request: the agent's request, as received.
            context: carries the merchant holding the registered payee.

        Returns:
            A Finding carrying ALLOW or BLOCK, this rule's id and class, and a
            reason naming what was compared.
        """
        raise NotImplementedError(
            "PayeeSubstitutionRule.evaluate is written by hand — "
            "see tests/layer1/test_payee.py"
        )
