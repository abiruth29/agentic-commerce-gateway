"""Money as an integer count of paise.

Every amount in this system is an exact integer number of paise. Floats are
refused at every entry point, because binary floating point cannot represent
19.99 and a gateway that quietly rounds is a gateway that loses money.

This type exists to make attack class I2 (economic abuse) structurally harder:
"paise/rupee confusion" is not a bug that happens deep in a calculation, it
happens at the boundary where a bare number becomes an amount. So there is no
bare-number constructor — the caller must say which unit it is holding.
"""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Final

PAISE_PER_RUPEE: Final = 100


def _check_int(value: object, what: str) -> int:
    """Accept only a genuine int.

    bool is excluded deliberately: it is a subclass of int, so True would
    otherwise sail through as 1 and an amount would silently become one paisa.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{what} must be an int, got {type(value).__name__}")
    return value


@dataclass(frozen=True, order=True)
class Money:
    """An exact, non-negative amount of Indian rupees, held as paise.

    Ordering and equality come from the single `paise` field, so comparisons
    are exact integer comparisons with no tolerance and no rounding.
    """

    paise: int

    def __post_init__(self) -> None:
        _check_int(self.paise, "paise")
        if self.paise < 0:
            # A negative amount is never a legitimate value here. Money moving
            # the other way is a refund, which is a direction on a transfer,
            # not a sign on an amount. Refusing it at construction means no
            # downstream rule has to ask whether an amount might be negative.
            raise ValueError(f"amount must not be negative, got {self.paise} paise")

    @classmethod
    def zero(cls) -> "Money":
        return cls(0)

    @classmethod
    def from_paise(cls, paise: int) -> "Money":
        """Build from paise. The explicit twin of `from_rupees`.

        `Money(1500)` and `Money.from_rupees(1500)` differ by a factor of 100,
        which is exactly the confusion I2 exploits. Prefer the named
        constructors at call sites where the unit is not obvious from context.
        """
        return cls(paise)

    @classmethod
    def from_rupees(cls, rupees: int | str | Decimal) -> "Money":
        """Build from rupees, given as an int, a decimal string, or a Decimal.

        float is refused: it cannot represent most two-decimal amounts, so
        accepting it would reintroduce the rounding this type exists to avoid.
        Pass "19.99" or Decimal("19.99") instead of 19.99.
        """
        if isinstance(rupees, float):
            raise TypeError(
                "rupees must not be a float, because float cannot represent "
                "amounts like 19.99 exactly — pass a str or Decimal instead"
            )
        if isinstance(rupees, bool):
            raise TypeError("rupees must not be a bool")

        try:
            amount = Decimal(rupees)
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"not a valid rupee amount: {rupees!r}") from exc

        paise = amount * PAISE_PER_RUPEE
        if paise != paise.to_integral_value():
            # Sub-paise precision is not representable and must not be
            # silently dropped: "1.005" is a request the caller has to resolve.
            raise ValueError(
                f"{rupees!r} is finer than one paisa and cannot be held exactly"
            )
        return cls(int(paise))

    def __add__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        return Money(self.paise + other.paise)

    def __sub__(self, other: "Money") -> "Money":
        if not isinstance(other, Money):
            return NotImplemented
        # Money(...) rejects the negative result, so an underflow raises here
        # rather than travelling on as a nonsensical amount.
        return Money(self.paise - other.paise)

    def __mul__(self, quantity: int) -> "Money":
        """Scale by a whole quantity.

        Rejecting a negative quantity here is the other half of I2's
        "negative qty": a line total cannot be driven below zero to offset
        another line in the same order.
        """
        _check_int(quantity, "quantity")
        if quantity < 0:
            raise ValueError(f"quantity must not be negative, got {quantity}")
        return Money(self.paise * quantity)

    __rmul__ = __mul__

    def as_rupees(self) -> Decimal:
        """Exact rupee value, for display and for serialisation to humans."""
        return Decimal(self.paise) / PAISE_PER_RUPEE

    def __str__(self) -> str:
        return f"₹{self.as_rupees():.2f}"
