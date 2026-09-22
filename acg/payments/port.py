"""What the gateway needs from a payment provider, and nothing more.

The interface is one method. That is deliberate: the narrower the port, the
less of the provider's surface can leak into the rule engine, and the more
honestly the fake can stand in for the real thing in the evaluation harness.

Ordering matters more than the interface does. An order is created **after**
Layer 1 returns a verdict, never before and never alongside. The gateway's
claim is that it decides whether a request is honest before money is asked to
move, and a provider call that happened while the rules were still running
would quietly make that false.
"""

from dataclasses import dataclass
from typing import Protocol

from acg.domain.money import Money


class PaymentError(RuntimeError):
    """The provider could not create the order.

    A distinct type so a caller can tell "the provider refused or was
    unreachable" from a bug in the gateway. It never carries the provider's
    raw response, which can echo attacker-supplied text back into a log.
    """


@dataclass(frozen=True)
class Order:
    """A created order, as the gateway cares about it."""

    order_id: str
    """The provider's identifier. Real in test mode — this is the artefact
    that shows the integration is genuine rather than mocked for the demo."""

    amount: Money
    currency: str
    receipt: str
    """The gateway's own reference for this order, carried through so a
    provider record can be traced back to the request that caused it."""


class PaymentGateway(Protocol):
    """Creates orders. Deliberately cannot do anything else."""

    def create_order(self, amount: Money, receipt: str) -> Order:
        """Create an order for this amount.

        Args:
            amount: what to charge. Passed as `Money`, so no caller has to
                decide what unit the provider wants — that translation happens
                once, at the edge.
            receipt: the gateway's reference, used to tie the provider's
                record back to the request.

        Returns:
            The created order.

        Raises:
            PaymentError: if the provider refused or could not be reached.
        """
        ...
