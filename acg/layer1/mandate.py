"""I1 — mandate violation: the request exceeds what the human authorised.

Three rules, each comparing one axis of the request against the mandate that
was registered before the agent went shopping: how much, what kind, and when.
None of them needs a model. "₹1,500, skincare, one-time" is a set of bounds,
and a bound is arithmetic.

This class is the reason pre-registration is not optional. Without a mandate on
file there is nothing to compare against, and the gateway would be left
inferring the human's intent from the request — which is the one thing the
attacker fully controls.

Each rule checks exactly one axis and ignores the others. An over-budget order
in an allowed category fires the amount rule alone; the category rule returns
ALLOW and is right to. The engine joins them, so a request that violates two
axes produces two findings and one verdict, and the per-class breakdown can
still say which bound was crossed.
"""

from acg.domain.request import PurchaseRequest
from acg.layer1.rules import EvaluationContext, Finding

ATTACK_CLASS = "I1"

AMOUNT_RULE_ID = "I1.amount_ceiling"
CATEGORY_RULE_ID = "I1.category"
WINDOW_RULE_ID = "I1.validity_window"


class MandateAmountRule:
    """Refuse a request that charges more than the human authorised."""

    rule_id = AMOUNT_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Compare the quoted total against the mandate's ceiling.

        The contract the tests hold it to:

        - a total at or below `context.mandate.max_amount` yields ALLOW; the
          ceiling is inclusive, since "up to ₹1,500" authorises ₹1,500
        - a total above it yields BLOCK, never REVIEW — the human named a
          number, and a request above it is outside what they authorised
          whether it is over by a rupee or by a lakh
        - the comparison is against `request.quoted_total`, not against a total
          recomputed from the lines. Whether the quoted total honestly reflects
          its own lines is a different attack and belongs to I2; keeping that
          out of here also keeps this rule away from `Money.__mul__`, which
          raises on the negative quantities a request is allowed to carry
        - the reason may name the ceiling, which the human set, but must not
          echo any attacker-supplied text

        Args:
            request: the agent's request, as received.
            context: carries the mandate holding the ceiling.

        Returns:
            A Finding carrying ALLOW or BLOCK.
        """
        raise NotImplementedError(
            "MandateAmountRule.evaluate is written by hand — "
            "see tests/layer1/test_mandate_rules.py"
        )


class MandateCategoryRule:
    """Refuse a request for goods outside the authorised categories."""

    rule_id = CATEGORY_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check every line's published category against the mandate.

        The contract the tests hold it to:

        - ALLOW only when *every* line's category is in
          `context.mandate.allowed_categories`; one disallowed line in an
          otherwise permitted order is still a violation, or an attacker
          smuggles it in behind nine legitimate ones
        - the category comes from the catalog item in `context.items`, never
          from the request. The request does not carry a category, and it must
          not: a category the agent asserts is a category the attacker chooses
        - a line naming an item absent from `context.items` yields BLOCK. That
          is not a lookup miss to tolerate — it is a claim about a product the
          merchant never published, and a rule that cannot determine the
          category must fail closed rather than pass by default
        - comparison relies on both sides already being normalised by
          `acg.domain.category.normalise_category`, which the Mandate and the
          CatalogItem each apply at construction. This rule must not normalise
          again; a second normalisation is a second chance to diverge
        - the reason must not echo the item id or any catalog text

        Args:
            request: the agent's request, as received.
            context: carries the mandate and the merchant's published catalog.

        Returns:
            A Finding carrying ALLOW or BLOCK.
        """
        raise NotImplementedError(
            "MandateCategoryRule.evaluate is written by hand — "
            "see tests/layer1/test_mandate_rules.py"
        )


class MandateWindowRule:
    """Refuse a request outside the mandate's validity window."""

    rule_id = WINDOW_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check the evaluation time against the mandate's window.

        The contract the tests hold it to:

        - the window is half-open: valid when
          `created_at <= now < expires_at`. An expiry is the instant
          authorisation stops, so a request landing exactly on it is out
        - before `created_at` yields BLOCK too. A mandate that is not yet in
          force has not authorised anything, and a request predating it is
          either a clock problem or a forgery
        - time comes from `context.now`, never from `datetime.now()` and never
          from `request.created_at`. The request's own timestamp is
          attacker-supplied, so a rule that trusted it would let an attacker
          revive an expired mandate by lying about when they asked
        - the reason may name the expiry, which the human set

        Args:
            request: the agent's request, as received.
            context: carries the mandate and the evaluation time.

        Returns:
            A Finding carrying ALLOW or BLOCK.
        """
        raise NotImplementedError(
            "MandateWindowRule.evaluate is written by hand — "
            "see tests/layer1/test_mandate_rules.py"
        )
