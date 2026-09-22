"""I1 — mandate violation: the request exceeds what the human authorised.

Three rules, each comparing one axis of the request against the mandate that
was registered before the agent went shopping: how much, what kind, and when.
None of them needs a model. "₹1,500, skincare, one-time" is a set of bounds,
and a bound is arithmetic.
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
        """Compare the quoted total against the mandate's inclusive ceiling."""
        decision = (
            context.mandate.max_amount >= request.quoted_total
            and __import__("acg.domain.decision", fromlist=["Decision"]).Decision.ALLOW
            or __import__("acg.domain.decision", fromlist=["Decision"]).Decision.BLOCK
        )
        reason = (
            "quoted total is within the mandate amount ceiling"
            if decision.name == "ALLOW"
            else "quoted total exceeds the mandate amount ceiling"
        )
        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=decision,
            reason=reason,
        )


class MandateCategoryRule:
    """Refuse a request for goods outside the authorised categories."""

    rule_id = CATEGORY_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check every line's published category against the mandate."""
        allowed = True
        for line in request.lines:
            item = context.items.get(line.item_id)
            if item is None or item.category not in context.mandate.allowed_categories:
                allowed = False
                break

        from acg.domain.decision import Decision

        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.ALLOW if allowed else Decision.BLOCK,
            reason=(
                "all requested items are in the mandate's allowed categories"
                if allowed
                else "a requested item is not in the mandate's allowed categories"
            ),
        )


class MandateWindowRule:
    """Refuse a request outside the mandate's validity window."""

    rule_id = WINDOW_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check the evaluation time against the mandate's half-open window."""
        from acg.domain.decision import Decision

        mandate = context.mandate
        valid = mandate.created_at <= context.now < mandate.expires_at
        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.ALLOW if valid else Decision.BLOCK,
            reason=(
                "evaluation time is within the mandate validity window"
                if valid
                else "evaluation time is outside the mandate validity window"
            ),
        )
