"""I4 — velocity abuse: too much, too fast, from one buyer.

This is the class where REVIEW finally earns its place in the lattice, and the
only one so far where it should be reached for.

Every other Layer 1 rule answers a question with a definite answer. Money went
somewhere the merchant never registered; the total does not follow from its
own lines; a one-time mandate was spent twice. There is no benign reading of
any of those, so a human queue would only add latency to a certain no.

Velocity is different in kind. Six purchases in an hour is what a compromised
agent looks like and also what a person doing their weekly shop looks like.
The rule cannot tell them apart, and that is exactly the situation a
three-value lattice exists for: too suspicious to wave through, not certain
enough to refuse. A lattice whose middle value nothing ever returns is a
lattice with a dead value, and a reviewer would be right to ask why it is
there.
"""

from datetime import timedelta

from acg.domain.decision import Decision
from acg.domain.history import allowed, within_window
from acg.domain.request import PurchaseRequest
from acg.layer1.rules import EvaluationContext, Finding

RULE_ID = "I4.velocity"
ATTACK_CLASS = "I4"

VELOCITY_WINDOW = timedelta(hours=1)
"""How far back the rule counts.

A policy number rather than a derived one. It is short enough that a burst
stands out and long enough that ordinary shopping does not straddle it.
"""

MAX_ALLOWED_IN_WINDOW = 5
"""How many completed purchases in that window are unremarkable.

Also policy. Two consequences worth stating rather than discovering:

- the evaluation's benign flows must stay under it, or the False Block Rate
  counts REVIEWs this rule was designed to produce and the number stops
  measuring what it claims to
- it is a count, not an amount. A buyer making one enormous purchase is the
  amount ceiling's problem, not this rule's
"""


class VelocityRule:
    """Flag a buyer completing purchases faster than a person plausibly would."""

    rule_id = RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Count this buyer's completed purchases in the recent window.

        Counts *allowed* priors rather than all attempts. A burst of blocked
        attempts is a probe and arguably its own signal, but counting it here
        would let one refused attack push a buyer's next legitimate purchase
        into review — inflating the False Block Rate on the strength of an
        attack the gateway already stopped. Attempt-velocity would be a second
        rule with its own threshold, deliberately not built.

        Scoped to this buyer. History may carry other buyers' activity, and
        one busy buyer must not put another into review.

        Returns REVIEW rather than BLOCK when over the limit, for the reason
        in the module docstring: the rule cannot distinguish a compromised
        agent from a busy person, and refusing outright would turn every busy
        afternoon into lost GMV.
        """
        recent = within_window(allowed(context.history), context.now, VELOCITY_WINDOW)
        by_this_buyer = [
            prior for prior in recent if prior.buyer_id == request.buyer_id
        ]
        over_limit = len(by_this_buyer) >= MAX_ALLOWED_IN_WINDOW

        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.REVIEW if over_limit else Decision.ALLOW,
            reason=(
                "this buyer has completed an unusual number of purchases "
                "in the recent window"
                if over_limit
                else "this buyer's recent purchase rate is unremarkable"
            ),
        )
