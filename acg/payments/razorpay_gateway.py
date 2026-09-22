"""The real provider, in test mode.

Razorpay takes an amount as an integer in the smallest currency unit — paise
for INR. `Money` is already an exact integer count of paise, so the
translation at this boundary is `amount.paise` and nothing else: no scaling,
no rounding, no float. That was the point of the type. The place most
integrations acquire an off-by-100 bug is the place this one has no arithmetic
at all.

The SDK is imported lazily, inside the constructor. Importing it at module
scope would make `acg.payments` — and so the whole app — fail to start when
the dependency is absent, which is exactly the situation MOCK_MODE exists to
support.
"""

from typing import Any

from acg.domain.money import Money
from acg.payments.port import Order, PaymentError

CURRENCY = "INR"


class RazorpayGateway:
    """Creates real orders against Razorpay's test-mode API."""

    def __init__(
        self,
        key_id: str,
        key_secret: str,
        client: Any | None = None,  # noqa: ANN401
    ) -> None:
        """Build a gateway.

        Args:
            key_id: Razorpay key id. Test-mode keys start with `rzp_test_`.
            key_secret: the matching secret.
            client: an already-built SDK client, for tests. Supplying one
                keeps the request-shaping testable without a network and
                without the secrets a real client would need.

        Raises:
            ValueError: if credentials are missing. Failing here is
                deliberate: a gateway built with blank keys would look
                configured and fail later, on the money path.
        """
        if not key_id or not key_secret:
            raise ValueError(
                "Razorpay credentials are missing; set RAZORPAY_KEY_ID and "
                "RAZORPAY_KEY_SECRET, or run with MOCK_MODE=true"
            )

        if client is None:
            import razorpay  # imported here so the app starts without it

            client = razorpay.Client(auth=(key_id, key_secret))

        self._client = client

    def create_order(self, amount: Money, receipt: str) -> Order:
        """Create an order for this amount.

        `amount.paise` goes across unchanged, because paise is already the
        unit Razorpay wants.
        """
        payload = {
            "amount": amount.paise,
            "currency": CURRENCY,
            "receipt": receipt,
            # The gateway settles nothing automatically. Capture is a separate
            # decision, and defaulting it on here would move money on the
            # strength of an order being created.
            "payment_capture": 0,
        }

        try:
            created = self._client.order.create(data=payload)
        except Exception as exc:  # noqa: BLE001 - the SDK raises several types
            # Deliberately not chaining the provider's message into the
            # raised error: it can contain echoed request text, and this
            # exception is rendered and logged downstream.
            raise PaymentError(
                "the payment provider could not create the order"
            ) from exc

        order_id = created.get("id")
        if not order_id:
            raise PaymentError("the payment provider returned no order id")

        returned = created.get("amount")
        if returned != amount.paise:
            # The provider disagreeing about the amount is not something to
            # carry on from. Trusting its number would let a mismatch become
            # the charge; trusting ours would misreport what was created.
            raise PaymentError(
                "the payment provider created an order for a different amount"
            )

        return Order(
            order_id=str(order_id),
            amount=amount,
            currency=str(created.get("currency", CURRENCY)),
            receipt=receipt,
        )
