"""S3 — the payment port, the fake, and the Razorpay request shape."""

import pytest

from acg.domain.money import Money
from acg.payments import (
    FakePaymentGateway,
    PaymentError,
    RazorpayGateway,
    build_payment_gateway,
    mock_mode_enabled,
)
from acg.payments.fake import FAKE_ID_PREFIX


class RecordingClient:
    """Stands in for the Razorpay SDK client.

    Injecting one keeps the request shaping testable without a network and
    without real credentials, which is the part of this integration most
    likely to be wrong and least likely to be noticed.
    """

    def __init__(self, response: dict | None = None, raises: Exception | None = None):
        self.response = response
        self.raises = raises
        self.calls: list[dict] = []
        self.order = self

    def create(self, data: dict) -> dict:
        self.calls.append(data)
        if self.raises is not None:
            raise self.raises
        return self.response or {}


def razorpay_with(
    response=None, raises=None
) -> tuple[RazorpayGateway, RecordingClient]:
    client = RecordingClient(response=response, raises=raises)
    return RazorpayGateway("rzp_test_x", "secret", client=client), client


class TestMockMode:
    def test_defaults_to_on_when_unset(self) -> None:
        # A missing value must not arm a path that talks to a real provider.
        assert mock_mode_enabled({}) is True

    @pytest.mark.parametrize("raw", ["false", "FALSE", "0", "no", "off", " Off "])
    def test_explicit_falsey_words_turn_it_off(self, raw: str) -> None:
        assert mock_mode_enabled({"MOCK_MODE": raw}) is False

    @pytest.mark.parametrize("raw", ["true", "1", "yes", "maybe", ""])
    def test_anything_else_leaves_it_on(self, raw: str) -> None:
        assert mock_mode_enabled({"MOCK_MODE": raw}) is True


class TestTheFactory:
    def test_mock_mode_yields_the_fake(self) -> None:
        assert isinstance(
            build_payment_gateway({"MOCK_MODE": "true"}), FakePaymentGateway
        )

    def test_real_mode_without_credentials_fails_at_construction(self) -> None:
        """Not on the first charge — a blank-keyed gateway looks configured."""
        with pytest.raises(ValueError, match="credentials are missing"):
            build_payment_gateway({"MOCK_MODE": "false"})

    def test_real_mode_with_a_blank_secret_also_fails(self) -> None:
        with pytest.raises(ValueError, match="credentials are missing"):
            build_payment_gateway(
                {"MOCK_MODE": "false", "RAZORPAY_KEY_ID": "rzp_test_x"}
            )


class TestTheFake:
    def test_creates_an_order_for_the_amount(self) -> None:
        order = FakePaymentGateway().create_order(Money.from_rupees(1200), "req_1")

        assert order.amount == Money(120_000)
        assert order.receipt == "req_1"

    def test_is_deterministic(self) -> None:
        # A replayed evaluation must produce identical results.
        first = FakePaymentGateway().create_order(Money.from_rupees(1), "req_1")
        second = FakePaymentGateway().create_order(Money.from_rupees(1), "req_1")

        assert first.order_id == second.order_id

    def test_different_receipts_give_different_ids(self) -> None:
        gateway = FakePaymentGateway()

        assert (
            gateway.create_order(Money.from_rupees(1), "a").order_id
            != gateway.create_order(Money.from_rupees(1), "b").order_id
        )

    def test_ids_are_visibly_fake(self) -> None:
        """So a fake id cannot be mistaken for a real one in a screenshot."""
        order = FakePaymentGateway().create_order(Money.from_rupees(1), "req_1")

        assert order.order_id.startswith(FAKE_ID_PREFIX)

    def test_records_what_it_created(self) -> None:
        gateway = FakePaymentGateway()
        gateway.create_order(Money.from_rupees(1), "a")
        gateway.create_order(Money.from_rupees(2), "b")

        assert [o.receipt for o in gateway.created] == ["a", "b"]

    def test_can_be_made_to_fail(self) -> None:
        gateway = FakePaymentGateway()
        gateway.fail_next = True

        with pytest.raises(PaymentError):
            gateway.create_order(Money.from_rupees(1), "a")

    def test_failure_is_not_sticky(self) -> None:
        gateway = FakePaymentGateway()
        gateway.fail_next = True
        with pytest.raises(PaymentError):
            gateway.create_order(Money.from_rupees(1), "a")

        assert gateway.create_order(Money.from_rupees(1), "b")


class TestRazorpayRequestShape:
    def test_sends_the_amount_in_paise_unchanged(self) -> None:
        """The whole reason Money holds paise.

        Razorpay wants the smallest currency unit, which is what Money
        already is — so this boundary has no arithmetic to get wrong.
        """
        amount = Money.from_rupees("1999.99")
        gateway, client = razorpay_with(
            {"id": "order_abc", "amount": amount.paise, "currency": "INR"}
        )

        gateway.create_order(amount, "req_1")

        assert client.calls[0]["amount"] == 199_999

    def test_sends_inr_and_the_receipt(self) -> None:
        gateway, client = razorpay_with(
            {"id": "order_abc", "amount": 100, "currency": "INR"}
        )

        gateway.create_order(Money(100), "req_42")

        assert client.calls[0]["currency"] == "INR"
        assert client.calls[0]["receipt"] == "req_42"

    def test_does_not_auto_capture(self) -> None:
        """Creating an order must not move money on its own."""
        gateway, client = razorpay_with(
            {"id": "order_abc", "amount": 100, "currency": "INR"}
        )

        gateway.create_order(Money(100), "req_1")

        assert client.calls[0]["payment_capture"] == 0

    def test_returns_the_providers_order_id(self) -> None:
        gateway, _ = razorpay_with(
            {"id": "order_RealLooking123", "amount": 100, "currency": "INR"}
        )

        assert gateway.create_order(Money(100), "r").order_id == "order_RealLooking123"


class TestRazorpayFailureHandling:
    def test_a_provider_exception_becomes_a_payment_error(self) -> None:
        gateway, _ = razorpay_with(raises=RuntimeError("connection reset"))

        with pytest.raises(PaymentError):
            gateway.create_order(Money(100), "r")

    def test_the_providers_message_is_not_echoed(self) -> None:
        """It can carry request text, and this error is logged and rendered."""
        injected = "<script>alert(1)</script>"
        gateway, _ = razorpay_with(raises=RuntimeError(injected))

        with pytest.raises(PaymentError) as caught:
            gateway.create_order(Money(100), "r")

        assert injected not in str(caught.value)

    def test_a_missing_order_id_is_an_error(self) -> None:
        gateway, _ = razorpay_with({"amount": 100, "currency": "INR"})

        with pytest.raises(PaymentError, match="no order id"):
            gateway.create_order(Money(100), "r")

    def test_an_amount_mismatch_is_an_error(self) -> None:
        """Neither number can be trusted once they disagree.

        Taking the provider's would let the mismatch become the charge;
        taking ours would misreport what was actually created.
        """
        gateway, _ = razorpay_with(
            {"id": "order_abc", "amount": 999, "currency": "INR"}
        )

        with pytest.raises(PaymentError, match="different amount"):
            gateway.create_order(Money(100), "r")


class TestConstruction:
    @pytest.mark.parametrize(("key_id", "secret"), [("", "s"), ("k", ""), ("", "")])
    def test_blank_credentials_are_refused(self, key_id: str, secret: str) -> None:
        with pytest.raises(ValueError, match="credentials are missing"):
            RazorpayGateway(key_id, secret, client=RecordingClient())
