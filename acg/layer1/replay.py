"""I3 — mandate replay: an authorisation spent twice.

A one-time mandate is a single permission. Once it has been drawn against, a
second draw is not a borderline case to weigh — the human authorised one
purchase and this is the second, whatever it contains. That is what makes I3
detectable without reasoning about the request at all: the check is whether
this mandate has already been used, not whether this order looks reasonable.

The same applies to a request id arriving twice. A gateway that decided
`req_1` and then sees `req_1` again is being replayed, and re-deciding it
would let an attacker resubmit an approval until it lands.

Both need memory, which arrives in `context.history`.
"""

from acg.domain.decision import Decision
from acg.domain.history import allowed
from acg.domain.mandate import MandateUsage
from acg.domain.request import PurchaseRequest
from acg.layer1.rules import EvaluationContext, Finding

RULE_ID = "I3.mandate_replay"
ATTACK_CLASS = "I3"


class MandateReplayRule:
    """Refuse a request that reuses a spent authorisation."""

    rule_id = RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check this request against what the gateway already let through.

        Two things count as replay:

        - the same `request_id` was decided before, in either direction. A
          replayed request is a replay whether or not the original was
          allowed, and re-deciding it is the bug
        - the mandate is ONE_TIME and has already been drawn against
          successfully

        Only *allowed* priors count as a draw against the mandate. A blocked
        attempt moved no money, so it did not spend the authorisation, and
        counting it would turn one refused attack into a permanent lockout of
        a mandate the human still holds.

        BLOCK, never REVIEW: a spent authorisation is spent, and sending it to
        a human queue only delays the same answer.
        """
        seen_before = any(
            prior.request_id == request.request_id for prior in context.history
        )
        if seen_before:
            return Finding(
                rule_id=self.rule_id,
                attack_class=self.attack_class,
                decision=Decision.BLOCK,
                reason="this request has already been decided",
            )

        one_time = context.mandate.usage is MandateUsage.ONE_TIME
        already_drawn = any(
            prior.mandate_id == request.mandate_id for prior in allowed(context.history)
        )
        spent = one_time and already_drawn

        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.BLOCK if spent else Decision.ALLOW,
            reason=(
                "a one-time mandate has already been drawn against"
                if spent
                else "the mandate has not been spent"
            ),
        )
