from decimal import Decimal

import pytest

from acg.domain.money import PAISE_PER_RUPEE, Money


class TestConstruction:
    def test_holds_paise_exactly(self) -> None:
        assert Money(150_000).paise == 150_000

    def test_zero_is_valid(self) -> None:
        assert Money.zero() == Money(0)

    def test_rejects_a_negative_amount(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            Money(-1)

    def test_rejects_a_float(self) -> None:
        with pytest.raises(TypeError, match="must be an int"):
            Money(1500.0)  # type: ignore[arg-type]

    def test_rejects_a_bool(self) -> None:
        # bool subclasses int, so True would otherwise become one paisa.
        with pytest.raises(TypeError, match="must be an int"):
            Money(True)  # type: ignore[arg-type]


class TestRupeeConversion:
    def test_from_rupees_scales_by_a_hundred(self) -> None:
        assert Money.from_rupees(1500) == Money(150_000)

    def test_from_rupees_accepts_a_decimal_string(self) -> None:
        assert Money.from_rupees("19.99") == Money(1_999)

    def test_from_rupees_accepts_a_decimal(self) -> None:
        assert Money.from_rupees(Decimal("19.99")) == Money(1_999)

    def test_from_rupees_rejects_a_float(self) -> None:
        # The whole point of the type: 19.99 is not representable in binary.
        with pytest.raises(TypeError, match="must not be a float"):
            Money.from_rupees(19.99)  # type: ignore[arg-type]

    def test_from_rupees_rejects_sub_paisa_precision(self) -> None:
        with pytest.raises(ValueError, match="finer than one paisa"):
            Money.from_rupees("1.005")

    def test_from_rupees_rejects_nonsense(self) -> None:
        with pytest.raises(ValueError, match="not a valid rupee amount"):
            Money.from_rupees("not-an-amount")

    def test_paise_and_rupee_constructors_differ_by_a_hundred(self) -> None:
        # This is attack class I2's "paise/rupee confusion" written as a test:
        # the two constructors must never be interchangeable.
        assert Money.from_rupees(1500).paise == Money.from_paise(1500).paise * (
            PAISE_PER_RUPEE
        )

    def test_as_rupees_round_trips(self) -> None:
        assert Money(1_999).as_rupees() == Decimal("19.99")

    def test_str_is_human_readable(self) -> None:
        assert str(Money(150_000)) == "₹1500.00"


class TestArithmetic:
    def test_addition(self) -> None:
        assert Money(1_000) + Money(500) == Money(1_500)

    def test_subtraction(self) -> None:
        assert Money(1_000) - Money(400) == Money(600)

    def test_subtraction_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="must not be negative"):
            Money(100) - Money(101)

    def test_multiplication_by_quantity(self) -> None:
        assert Money(1_999) * 3 == Money(5_997)

    def test_multiplication_is_commutative(self) -> None:
        assert 3 * Money(1_999) == Money(1_999) * 3

    def test_rejects_a_negative_quantity(self) -> None:
        # I2's "negative qty": a line total must not be driveable below zero.
        with pytest.raises(ValueError, match="quantity must not be negative"):
            Money(1_999) * -1

    def test_rejects_a_float_quantity(self) -> None:
        with pytest.raises(TypeError, match="quantity must be an int"):
            Money(1_999) * 1.5  # type: ignore[operator]


class TestComparison:
    def test_orders_by_amount(self) -> None:
        assert Money(100) < Money(200)
        assert Money(200) >= Money(200)

    def test_equality_is_exact(self) -> None:
        assert Money(1_999) == Money(1_999)
        assert Money(1_999) != Money(2_000)

    def test_is_hashable(self) -> None:
        # Frozen, so it can key a cache or sit in a set.
        assert len({Money(100), Money(100), Money(200)}) == 2
