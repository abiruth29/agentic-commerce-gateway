"""The mandate: what the human authorised, declared before the agent shops.

Attack class I1 is uncheckable without this. "₹1,500, skincare, one-time" has
to reach the gateway *before* the agent goes shopping, or there is nothing to
compare a purchase request against and the gateway is reduced to guessing
intent from the request itself — which is precisely what the attacker controls.
Pre-registration is the forced architectural consequence of taking I1
seriously.

A Mandate is an immutable declaration and nothing more. It carries no policy
predicates: whether a given request is inside its bounds, whether it has
expired, and whether it has already been spent are questions the Layer 1 rules
answer, and they live with the rules rather than being scattered across the
data model.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from acg.domain.category import normalise_category
from acg.domain.money import Money


class MandateUsage(StrEnum):
    """How many times a mandate may be drawn against.

    ONE_TIME is what makes I3 (mandate replay) a detectable event: a second
    draw against a one-time mandate is a replay by definition, without needing
    to reason about what the second request contained.
    """

    ONE_TIME = "one_time"
    RECURRING = "recurring"


def _require_utc(value: datetime, what: str) -> datetime:
    """Reject a naive datetime.

    A naive timestamp silently adopts whatever the host's clock means, which
    puts expiry and velocity windows at the mercy of deployment configuration.
    Both are enforcement inputs, so the ambiguity is refused at the boundary.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware")
    return value


class Mandate(BaseModel):
    """A human's pre-registered authorisation for an agent to spend.

    Frozen: a mandate that could be edited after registration would defeat its
    own purpose, since the record the gateway compares against is exactly the
    thing an attacker would want to move.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    mandate_id: str = Field(min_length=1)
    buyer_id: str = Field(min_length=1)

    max_amount: Money
    """The ceiling the human authorised. Compared against an order total by the
    Layer 1 amount rule, not here."""

    allowed_categories: frozenset[str] = Field(min_length=1)
    """Categories the human authorised, normalised at construction.

    A mandate is useless if it authorises nothing, so an empty set is refused
    rather than being treated as "allow everything" — a default that fails open
    is the wrong default in a gateway.
    """

    usage: MandateUsage
    created_at: datetime
    expires_at: datetime

    @field_validator("created_at", "expires_at")
    @classmethod
    def _timestamps_are_aware(cls, value: datetime, info) -> datetime:  # noqa: ANN001
        return _require_utc(value, info.field_name)

    @field_validator("allowed_categories", mode="before")
    @classmethod
    def _normalise_categories(cls, value: object) -> object:
        """Normalise category names at the boundary.

        Done once here rather than inside each rule that compares a category,
        and through the shared normaliser rather than a local copy, so that
        "Skincare" in a mandate and "skincare" on an item cannot become either
        a false block or a bypass depending on which side ran.
        """
        if isinstance(value, str):
            # A bare string would otherwise iterate into single characters,
            # turning "skincare" into eight one-letter categories.
            raise ValueError(
                "allowed_categories must be a collection of category names, "
                "not a single string"
            )
        if not isinstance(value, (list, tuple, set, frozenset)):
            return value

        return frozenset(normalise_category(category) for category in value)

    @model_validator(mode="after")
    def _expiry_follows_creation(self) -> "Mandate":
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self
