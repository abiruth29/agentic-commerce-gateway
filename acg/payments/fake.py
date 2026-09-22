"""A deterministic stand-in for the provider.

This is what `MOCK_MODE=true` selects, and what the evaluation harness runs
against. It exists so the 120-attack corpus can be replayed without creating
120 real orders, and so the numbers it produces do not depend on a network.

Determinism is the point. The same receipt always produces the same order id,
so a replay of the same evaluation yields byte-identical results — the same
property the rules preserve by taking history as an argument rather than
fetching it.

Its order ids are visibly fake. `order_FAKE...` cannot be mistaken for a
Razorpay id in a log or a screenshot, which matters when the whole claim of
S3 is that the real integration produces a *real* order id.
"""

import hashlib
from dataclasses import dataclass, field

from acg.domain.money import Money
from acg.payments.port import Order, PaymentError

FAKE_ID_PREFIX = "order_FAKE"


@dataclass
class FakePaymentGateway:
    """Creates orders without leaving the process."""

    currency: str = "INR"
    created: list[Order] = field(default_factory=list)
    """Every order this instance made, in order. The harness asserts against
    it; nothing in the gateway reads it."""

    fail_next: bool = False
    """Set to make the next call raise, so the caller's failure path can be
    exercised without a network that refuses on demand."""

    def create_order(self, amount: Money, receipt: str) -> Order:
        if self.fail_next:
            self.fail_next = False
            raise PaymentError("the payment provider could not create the order")

        digest = hashlib.sha256(receipt.encode("utf-8")).hexdigest()[:14]
        order = Order(
            order_id=f"{FAKE_ID_PREFIX}{digest}",
            amount=amount,
            currency=self.currency,
            receipt=receipt,
        )
        self.created.append(order)
        return order
