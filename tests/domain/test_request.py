from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from acg.domain.money import Money
from acg.domain.request import OrderLine, PurchaseRequest

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)


def build(**overrides: object) -> PurchaseRequest:
    fields: dict[str, object] = {
        "request_id": "req_1",
        "mandate_id": "mnd_1",
        "buyer_id": "buyer_1",
        "merchant_id": "mer_1",
        "payee_id": "payee_glow_labs",
        "lines": (
            OrderLine(item_id="itm_1", quantity=1, unit_price=Money.from_rupees(1200)),
        ),
        "quoted_total": Money.from_rupees(1200),
        "created_at": NOW,
    }
    return PurchaseRequest(**(fields | overrides))  # type: ignore[arg-type]


class TestWellFormedness:
    def test_holds_what_the_agent_asked_for(self) -> None:
        assert build().payee_id == "payee_glow_labs"

    def test_is_frozen(self) -> None:
        # What the rules judged must be provably what arrived.
        with pytest.raises(ValidationError):
            build().payee_id = "payee_attacker_99"  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            build(override_decision="ALLOW")

    def test_rejects_an_empty_order(self) -> None:
        with pytest.raises(ValidationError):
            build(lines=())

    def test_rejects_a_blank_payee(self) -> None:
        with pytest.raises(ValidationError):
            build(payee_id="")

    def test_rejects_a_naive_timestamp(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            build(created_at=datetime(2026, 2, 1, 12, 0))  # noqa: DTZ001


class TestTheDeliberateAsymmetry:
    """Attacks must survive parsing to reach the rule that rejects them."""

    @pytest.mark.parametrize("quantity", [0, -1, -1000])
    def test_a_hostile_quantity_is_representable(self, quantity: int) -> None:
        # Refusing this at construction would mean the I2 rule never sees the
        # attack, and a rule that never sees an attack cannot be shown to
        # catch it.
        line = OrderLine(
            item_id="itm_1", quantity=quantity, unit_price=Money.from_rupees(1200)
        )

        assert line.quantity == quantity

    def test_a_negative_quoted_total_is_not_representable(self) -> None:
        # A negative total is not a quote at all, so Money refuses it and the
        # request fails at the boundary — a rejection, not a rule decision.
        with pytest.raises(ValueError, match="must not be negative"):
            build(quoted_total=Money(-1))

    def test_a_price_the_agent_invented_is_representable(self) -> None:
        # The gap between the claimed price and the published one is exactly
        # what a later rule compares; the model must not close it.
        line = OrderLine(item_id="itm_1", quantity=1, unit_price=Money.from_rupees(1))

        assert line.unit_price == Money.from_rupees(1)

    def test_a_total_that_contradicts_the_lines_is_representable(self) -> None:
        assert build(quoted_total=Money.from_rupees(1)).quoted_total == (
            Money.from_rupees(1)
        )
