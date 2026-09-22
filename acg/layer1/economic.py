"""I2 — economic abuse: the arithmetic of the order is dishonest.

Nothing here is about *what* is being bought or *who* is being paid. Those are
I1 and O3. This class is about the sum itself: quantities that cannot be
ordered, prices that are not the merchant's, and a total that does not follow
from its own lines.

Three of the class's named sub-cases fit inside a single request and are
implemented here. The other three — coupon stacking, refund before
fulfilment, and split-order structuring — cannot be expressed yet: there is no
coupon, no fulfilment state, and no memory of earlier requests. They are not
stubbed, because a stub whose inputs do not exist is a promise rather than a
plan.

As in I1, each rule owns one axis and stays quiet on the others. That matters
more here than anywhere else, because these three failures cascade: a negative
quantity also makes the total unverifiable, and a tampered price also makes the
total wrong. If every rule reported every consequence, one attack would light
up the whole class and the per-class breakdown would say nothing. The engine's
join is what turns three quiet ALLOWs and one loud BLOCK into a blocked
request, and `blocking` is what names the rule that decided it.
"""

from acg.domain.decision import Decision
from acg.domain.money import Money
from acg.domain.request import OrderLine, PurchaseRequest
from acg.layer1.rules import EvaluationContext, Finding

ATTACK_CLASS = "I2"

QUANTITY_RULE_ID = "I2.quantity"
PRICE_RULE_ID = "I2.price_integrity"
TOTAL_RULE_ID = "I2.total_integrity"


def line_total(line: OrderLine) -> Money | None:
    """The cost of one line, or None when the quantity makes it meaningless.

    Shared by the rules below so they agree on the arithmetic, and separate
    from them because it is plumbing rather than policy.

    `Money.__mul__` refuses a negative multiplier, so calling it on a hostile
    quantity raises. Returning None instead lets a rule say "I cannot verify
    this" without crashing and without having to re-implement the check that
    the quantity rule already owns.
    """
    if line.quantity < 1:
        return None
    return line.unit_price * line.quantity


class QuantityRule:
    """Refuse a line that orders a number of items nobody can order."""

    rule_id = QUANTITY_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check every line's quantity.

        The contract the tests hold it to:

        - every quantity must be at least 1; ALLOW only when all of them are
        - zero blocks as well as negative. A zero-quantity line is not a
          rounding artefact, it is a line that contributes nothing to the total
          while still appearing in the order, which is a way to make an order
          read as larger than it is
        - a negative quantity blocks. This is the half of I2 that the `Money`
          type cannot prevent on its own: `Money` refuses to *multiply* by a
          negative, but the request model deliberately carries one so this rule
          can see it and reject it
        - one bad line among many is still a violation
        - BLOCK, never REVIEW — there is no benign reading of an order for
          minus one item
        - the reason must not echo the item id

        Args:
            request: the agent's request, as received.
            context: unused; quantities are judged on their own.

        Returns:
            A Finding carrying ALLOW or BLOCK.
        """
        orderable = all(line.quantity >= 1 for line in request.lines)
        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.ALLOW if orderable else Decision.BLOCK,
            reason=(
                "every line orders at least one item"
                if orderable
                else "a line orders fewer than one item"
            ),
        )


class PriceIntegrityRule:
    """Refuse a line priced at anything but the merchant's published price."""

    rule_id = PRICE_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Compare each line's claimed unit price against the catalog.

        The contract the tests hold it to:

        - ALLOW only when every line's `unit_price` equals the `price` of the
          matching item in `context.items`, exactly
        - a line naming an item absent from the catalog blocks, for the same
          reason it does in I1: a price that cannot be checked is not a price
          that passes
        - a price *below* the published one blocks too. The instinct is that
          underpaying harms only the attacker, but the merchant's published
          price is the agreement, and a gateway that tolerates deviation in one
          direction has no principled reason to refuse the other
        - the comparison is exact `Money` equality, which is exact integer
          paise — no tolerance, no nearest-rupee
        - BLOCK, never REVIEW
        - the reason must not echo the item id or either amount

        This is also as far as stale-quote replay can be taken today. A stale
        quote is a price that *was* the merchant's, so comparing against the
        current catalog catches it — but only because there is no quote
        issuance to consult. Distinguishing a replayed old quote from a
        tampered price needs quotes to carry an issued-at, which they do not.

        Args:
            request: the agent's request, as received.
            context: carries the merchant's published catalog.

        Returns:
            A Finding carrying ALLOW or BLOCK.
        """

        def published(line: OrderLine) -> bool:
            item = context.items.get(line.item_id)
            # An unknown item fails closed: a price that cannot be checked is
            # not a price that passes.
            return item is not None and line.unit_price == item.price

        honest = all(published(line) for line in request.lines)
        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.ALLOW if honest else Decision.BLOCK,
            reason=(
                "every line is priced at the merchant's published price"
                if honest
                else "a line is not priced at the merchant's published price"
            ),
        )


class TotalIntegrityRule:
    """Refuse a quoted total that does not follow from its own lines."""

    rule_id = TOTAL_RULE_ID
    attack_class = ATTACK_CLASS

    def evaluate(self, request: PurchaseRequest, context: EvaluationContext) -> Finding:
        """Check the quoted total against the sum of the lines.

        This is the rule I1's amount ceiling deliberately does not do. The
        ceiling asks whether the human authorised this charge; this asks
        whether the charge is what the order actually comes to. Keeping them
        apart is what lets the breakdown say which of the two went wrong.

        It is also where paise/rupee confusion surfaces. A total computed in
        the wrong unit is off by exactly a factor of 100, and an exact equality
        check catches that without needing to look for the factor.

        The contract the tests hold it to:

        - ALLOW when `request.quoted_total` equals the sum of
          `unit_price * quantity` across every line, exactly
        - BLOCK when it does not, in either direction. A total *below* the line
          sum is as wrong as one above: it means the request is not internally
          consistent, and a gateway that accepts one under-total has no
          principled place to stop
        - **ALLOW when the sum cannot be computed** — that is, when any line's
          quantity is below 1 and `line_total` returns None. That is not this
          rule failing open. The quantity rule blocks such a request, and the
          engine's join makes the verdict BLOCK regardless; returning ALLOW
          here keeps the finding attributable to the rule whose axis actually
          failed. A test at the engine level pins that the request is still
          blocked
        - BLOCK, never REVIEW
        - the reason must not echo either amount

        Args:
            request: the agent's request, as received.
            context: unused; the total is checked against the request's own
                lines, not against the catalog. Whether those line prices are
                the merchant's is the price rule's question.

        Returns:
            A Finding carrying ALLOW or BLOCK.
        """
        summed = Money.zero()
        for line in request.lines:
            part = line_total(line)
            if part is None:
                # The sum is meaningless, which is the quantity rule's axis
                # rather than this one's. Staying quiet keeps the finding
                # attributable; the join still blocks the request.
                return Finding(
                    rule_id=self.rule_id,
                    attack_class=self.attack_class,
                    decision=Decision.ALLOW,
                    reason="total not checked: a line quantity is unorderable",
                )
            summed = summed + part

        consistent = request.quoted_total == summed
        return Finding(
            rule_id=self.rule_id,
            attack_class=self.attack_class,
            decision=Decision.ALLOW if consistent else Decision.BLOCK,
            reason=(
                "quoted total matches the sum of the lines"
                if consistent
                else "quoted total does not match the sum of the lines"
            ),
        )
