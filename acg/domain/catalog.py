"""The merchant catalog: the untrusted surface, and the payee anchor.

Two things live here and they pull in opposite directions.

`CatalogItem.title` and `CatalogItem.description` are **attacker-controlled**.
A merchant is usually an unwitting host rather than the attacker, but the text
a buyer agent reads is the injection surface for the whole outbound family
(O1, O2, O4). Nothing in this module sanitises that text, because sanitising
it would imply it had been made safe. It is carried as data, marked as
untrusted, and screened by Layer 2.

`Merchant.registered_payee_id` is the opposite: it is the one field the
attacker must not be able to move. O3, payee substitution, is invoice
redirection with the human taken out of the loop — it changes only where money
lands, so it slips past every budget, quantity and item control. The defence is
not detection but comparison: money may only go to the payee registered against
the merchant, out of band, before any of this text existed. That check is a
Layer 1 rule; this module's job is to hold the anchor it compares against.
"""

import hashlib

from pydantic import BaseModel, ConfigDict, Field, field_validator

from acg.domain.category import normalise_category
from acg.domain.money import Money

_HASH_DOMAIN = b"acg.catalog.content.v1"


class Merchant(BaseModel):
    """A merchant, and the only destination its money may go to."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    merchant_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)

    registered_payee_id: str = Field(min_length=1)
    """Where money for this merchant is allowed to land.

    Established out of band at onboarding, never read from catalog text or from
    a purchase request. This is the value an O3 attack exists to replace, so
    anything that could let request-time input reach it is the vulnerability
    rather than a feature.
    """


class CatalogItem(BaseModel):
    """One purchasable item. Its text is untrusted input, not description.

    Frozen, so a screened item cannot be mutated afterwards: a Layer 2 verdict
    is cached against `content_hash`, and text that could change under a cached
    verdict would make the cache a bypass.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    item_id: str = Field(min_length=1)
    merchant_id: str = Field(min_length=1)

    title: str = Field(min_length=1)
    """UNTRUSTED. Rendered to a buyer agent; screened, never sanitised."""

    description: str = Field(min_length=1)
    """UNTRUSTED. The primary injection surface for O1, O2 and O4."""

    price: Money
    category: str

    @field_validator("category", mode="before")
    @classmethod
    def _normalise_category(cls, value: object) -> str:
        return normalise_category(value)

    @property
    def content_hash(self) -> str:
        """Stable digest of the untrusted text, identifying a content version.

        This is the cache key that keeps Layer 2 off the payment path: a
        verdict is computed once per version of the text on the content-serving
        path, so in steady state Gemini costs zero milliseconds per
        transaction.

        Only the untrusted fields are hashed. Price and category are checked
        deterministically by Layer 1, so including them would evict a perfectly
        valid semantic verdict every time a merchant ran a discount.

        Each field is length-prefixed before hashing so that concatenation is
        unambiguous: without it, ("ab", "c") and ("a", "bc") would produce the
        same digest, and an attacker could shift bytes across the boundary to
        reuse another item's verdict.

        sha256 of the text itself, not Python's hash(), which is randomised per
        process and would silently miss the cache on every restart.
        """
        digest = hashlib.sha256(_HASH_DOMAIN)
        for field in (self.title, self.description):
            encoded = field.encode("utf-8")
            digest.update(len(encoded).to_bytes(8, "big"))
            digest.update(encoded)
        return digest.hexdigest()
