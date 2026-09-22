"""Payment provider integration.

One port, two implementations, and a factory that picks between them from
configuration. Nothing above this package knows which one it is holding.
"""

import os

from acg.payments.fake import FakePaymentGateway
from acg.payments.port import Order, PaymentError, PaymentGateway
from acg.payments.razorpay_gateway import RazorpayGateway

__all__ = [
    "FakePaymentGateway",
    "Order",
    "PaymentError",
    "PaymentGateway",
    "RazorpayGateway",
    "build_payment_gateway",
    "mock_mode_enabled",
]


def mock_mode_enabled(environ: dict[str, str] | None = None) -> bool:
    """Whether outbound integrations should use deterministic fakes.

    Defaults to **true** when unset. A missing configuration value should not
    silently arm a path that talks to a real provider; the deployment that
    wants real calls says so explicitly.

    Only an explicit falsey word turns it off, so `MOCK_MODE=maybe` leaves the
    fakes on rather than being read as truthy.
    """
    env = os.environ if environ is None else environ
    raw = env.get("MOCK_MODE")
    if raw is None:
        return True
    return raw.strip().lower() not in {"false", "0", "no", "off"}


def build_payment_gateway(
    environ: dict[str, str] | None = None,
) -> PaymentGateway:
    """The gateway this deployment should use.

    Raises:
        ValueError: when real mode is selected without credentials. Failing at
            construction rather than on the first charge means a
            misconfiguration surfaces at startup, not on the money path.
    """
    env = os.environ if environ is None else environ
    if mock_mode_enabled(env):
        return FakePaymentGateway()
    return RazorpayGateway(
        key_id=env.get("RAZORPAY_KEY_ID", ""),
        key_secret=env.get("RAZORPAY_KEY_SECRET", ""),
    )
