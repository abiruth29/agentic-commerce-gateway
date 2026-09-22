"""What the buyer agent asks the gateway to do.

This is the untrusted side of the wire. Everything here arrives from an agent
that may already be carrying injected instructions, so the model's job is to
make the request *representable*, not to make it acceptable.

That distinction drives a deliberate asymmetry with the rest of the domain.
Elsewhere — Money, Mandate, Catalog — invalid states are refused at
construction. Here they are not, because a request that cannot be parsed is
never seen by a rule, and a rule that never sees an attack cannot be shown to
catch it. `quantity` is therefore a plain int and may be zero or negative: the
negative-quantity half of I2 has to survive parsing to reach the rule that
rejects it.

The line is drawn at what is *meaningful* rather than what is *allowed*. A
quantity of -1 is a coherent thing for an attacker to ask for and a rule's job
to refuse. A negative quoted total is not a quote at all, so `Money` still
refuses it and the request fails at the boundary — a rejection, but not a rule
decision, and the evaluation harness counts those separately.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from acg.domain.money import Money


class OrderLine(BaseModel):
    """One line of a requested order."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)

    quantity: int
    """Deliberately unvalidated.

    Zero and negative values are representable so that the I2 rule can reject
    them. Note that `Money.__mul__` refuses a negative multiplier, so a rule
    must check the quantity *before* computing a line total rather than relying
    on the arithmetic to raise.
    """

    unit_price: Money
    """The price the agent believes applies.

    Held separately from the catalog's price on purpose: the gap between what
    the agent claims and what the merchant published is exactly what the
    stale-quote and price-tampering checks compare.
    """


class PurchaseRequest(BaseModel):
    """An agent's request to move money, as received.

    Frozen, so that what the rules judged is provably what arrived — a request
    mutated between two rules would make the verdict unattributable.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    request_id: str = Field(min_length=1)
    mandate_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)

    payee_id: str = Field(min_length=1)
    """Where the agent says the money should go.

    This is the O3 attack surface and the single most dangerous field in the
    request. It is never trusted and never used as a destination; it exists to
    be compared against the merchant's out-of-band registered payee.
    """

    lines: tuple[OrderLine, ...] = Field(min_length=1)
    quoted_total: Money
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def _created_at_is_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value
