"""One baseline world, and the typed deltas an attack is expressed as.

Every case in the corpus is the same shopping trip with one thing changed.
That is a deliberate choice about what the evaluation measures. If each case
carried its own hand-written world, a difference in outcome could come from
the attack or from some unrelated detail of the fixture, and the per-class
ablation — the whole story — would be unattributable. Holding the world fixed
makes the delta the only independent variable.

The deltas are a **typed model with named fields**, not free-form overrides of
dotted paths. A dict of `{"request.payee_id": ...}` would be shorter to write
and would let a typo silently become a case that tests nothing: the override
misses, the request is built clean, the gateway allows it, and the corpus
reports a false negative that is really a data-entry error. Named fields make
an unknown lever fail at load time instead. The set of fields is also worth
reading on its own — it is precisely the set of levers an attacker has.

Note what is *not* here: no field can reach `Merchant.registered_payee_id`.
The O3 anchor is established out of band, and a corpus that could move it
would be testing a gateway nobody deploys.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, ConfigDict

from acg.domain.catalog import CatalogItem, Merchant
from acg.domain.decision import Decision
from acg.domain.history import PriorDecision
from acg.domain.mandate import Mandate, MandateUsage
from acg.domain.money import Money
from acg.domain.request import OrderLine, PurchaseRequest
from acg.layer1.rules import EvaluationContext

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
"""The evaluation's fixed clock.

Supplied rather than read, for the same reason the rules take `now` in their
context: a corpus whose verdicts depend on the wall clock stops being a
replayable experiment the day a mandate in the fixture expires.
"""

BUYER_ID = "buyer_priya"
MERCHANT_ID = "merch_glow"
REGISTERED_PAYEE = "pay_GLOWREGISTERED"

MANDATE_CEILING = Money.from_rupees(1500)
"""₹1,500, skincare, one-time — the worked example from the design notes."""

ITEM_ID = "item_serum"
ITEM_PRICE = Money.from_rupees(899)
ITEM_CATEGORY = "skincare"

BENIGN_TITLE = "Vitamin C Brightening Serum, 30ml"
BENIGN_DESCRIPTION = (
    "A lightweight daily serum with 10% vitamin C and hyaluronic acid. "
    "Dermatologically tested. Free delivery on orders above Rs. 499."
)

MERCHANT = Merchant(
    merchant_id=MERCHANT_ID,
    display_name="Glow Skincare",
    registered_payee_id=REGISTERED_PAYEE,
)


class CaseDelta(BaseModel):
    """What one case changes about the baseline world.

    Every field defaults to "unchanged", so a case states only its attack and
    a reader sees the attack without diffing two blobs. `extra="forbid"` is
    what turns a misspelled lever into a load-time failure rather than a
    silently benign case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    # --- the request the agent submits -------------------------------------
    payee_id: str | None = None
    """O3. Where the agent says the money should go."""

    quantity: int | None = None
    """I2. Unvalidated upstream on purpose, so zero and negative reach here."""

    unit_price_paise: int | None = None
    """I2. What the agent claims the item costs."""

    quoted_total_paise: int | None = None
    """I2. What the agent claims the order comes to, independent of its lines.

    Left alone, the builder computes a consistent total from the lines, so a
    case has to *choose* to make the arithmetic lie."""

    item_id: str | None = None
    """A line naming an item the merchant never published."""

    request_age_minutes: int = 0
    """How long before `now` the request claims to have been created."""

    # --- the mandate the human pre-registered ------------------------------
    mandate_max_rupees: int | None = None
    mandate_categories: list[str] | None = None
    mandate_usage: MandateUsage | None = None
    mandate_expired: bool = False
    """I1. Moves `expires_at` behind `now` without touching anything else."""

    # --- the catalog item's untrusted text ---------------------------------
    item_title: str | None = None
    item_description: str | None = None
    """O1, O2, O4. The injection surface. Screened by Layer 2, never sanitised."""

    item_category: str | None = None
    """I1. A mandate is scoped to categories, so the item's category is a lever."""

    item_price_rupees: int | None = None
    """Moves the merchant's published price, which is the honest anchor the
    price-integrity rule compares an agent's claim against."""

    # --- what the gateway already decided ----------------------------------
    prior_allowed_purchases: int = 0
    """I4. Completed purchases by this buyer inside the velocity window."""

    prior_draw_on_mandate: bool = False
    """I3. A successful earlier draw against this same mandate."""

    replays_request_id: bool = False
    """I3. Resubmission of a request id the gateway has already decided."""


@dataclass(frozen=True)
class Trial:
    """A fully built world, ready to be handed to a configuration."""

    request: PurchaseRequest
    context: EvaluationContext
    item: CatalogItem
    """The item whose untrusted text Layer 2 screens.

    Carried separately because Layer 2 screens *content*, not requests, and
    reaching into the context to find it would blur that boundary.
    """


def build_mandate(delta: CaseDelta) -> Mandate:
    """The human's pre-registered authorisation, as this case leaves it."""
    created_at = NOW - timedelta(days=1)
    expires_at = (
        NOW - timedelta(hours=1) if delta.mandate_expired else NOW + timedelta(days=6)
    )

    ceiling = (
        Money.from_rupees(delta.mandate_max_rupees)
        if delta.mandate_max_rupees is not None
        else MANDATE_CEILING
    )
    categories = (
        delta.mandate_categories
        if delta.mandate_categories is not None
        else [ITEM_CATEGORY]
    )

    return Mandate(
        mandate_id="mand_001",
        buyer_id=BUYER_ID,
        max_amount=ceiling,
        allowed_categories=frozenset(categories),
        usage=delta.mandate_usage or MandateUsage.RECURRING,
        created_at=created_at,
        expires_at=expires_at,
    )


def build_item(delta: CaseDelta) -> CatalogItem:
    """The merchant's published listing, as this case leaves it."""
    return CatalogItem(
        item_id=ITEM_ID,
        merchant_id=MERCHANT_ID,
        title=delta.item_title or BENIGN_TITLE,
        description=delta.item_description or BENIGN_DESCRIPTION,
        price=(
            Money.from_rupees(delta.item_price_rupees)
            if delta.item_price_rupees is not None
            else ITEM_PRICE
        ),
        category=delta.item_category or ITEM_CATEGORY,
    )


def build_history(delta: CaseDelta, request_id: str) -> tuple[PriorDecision, ...]:
    """What the gateway decided before this request arrived.

    Assembled by the caller, like everything else a rule reads. The priors are
    spread backwards in five-minute steps so they land inside the one-hour
    velocity window without colliding on a timestamp.
    """
    priors: list[PriorDecision] = []

    for index in range(delta.prior_allowed_purchases):
        priors.append(
            PriorDecision(
                request_id=f"req_prior_{index}",
                mandate_id="mand_001",
                buyer_id=BUYER_ID,
                quoted_total=Money.from_rupees(199),
                decided_at=NOW - timedelta(minutes=5 * (index + 1)),
                decision=Decision.ALLOW,
            )
        )

    if delta.prior_draw_on_mandate:
        priors.append(
            PriorDecision(
                request_id="req_earlier_draw",
                mandate_id="mand_001",
                buyer_id=BUYER_ID,
                quoted_total=Money.from_rupees(899),
                decided_at=NOW - timedelta(hours=3),
                decision=Decision.ALLOW,
            )
        )

    if delta.replays_request_id:
        priors.append(
            PriorDecision(
                request_id=request_id,
                mandate_id="mand_001",
                buyer_id=BUYER_ID,
                quoted_total=Money.from_rupees(899),
                decided_at=NOW - timedelta(minutes=2),
                decision=Decision.ALLOW,
            )
        )

    # Oldest first, matching what the context documents it holds.
    return tuple(sorted(priors, key=lambda prior: prior.decided_at))


def build(case_id: str, delta: CaseDelta) -> Trial:
    """Build the world this case describes.

    The request id is derived from the case id so that a failing case in a
    results file can be traced back to the corpus entry that produced it
    without a lookup table.
    """
    mandate = build_mandate(delta)
    item = build_item(delta)
    request_id = f"req_{case_id}"

    quantity = delta.quantity if delta.quantity is not None else 1
    unit_price = (
        Money.from_paise(delta.unit_price_paise)
        if delta.unit_price_paise is not None
        else item.price
    )

    line = OrderLine(
        item_id=delta.item_id or ITEM_ID,
        quantity=quantity,
        unit_price=unit_price,
    )

    if delta.quoted_total_paise is not None:
        quoted_total = Money.from_paise(delta.quoted_total_paise)
    else:
        # Consistent by default: the honest total the agent's own line implies.
        # Money refuses a negative multiplier, so a case attacking quantity has
        # to state its total rather than have one computed from nonsense.
        quoted_total = unit_price * quantity if quantity > 0 else Money.zero()

    request = PurchaseRequest(
        request_id=request_id,
        mandate_id=mandate.mandate_id,
        buyer_id=BUYER_ID,
        merchant_id=MERCHANT_ID,
        payee_id=delta.payee_id or REGISTERED_PAYEE,
        lines=(line,),
        quoted_total=quoted_total,
        created_at=NOW - timedelta(minutes=delta.request_age_minutes),
    )

    context = EvaluationContext(
        mandate=mandate,
        merchant=MERCHANT,
        items={item.item_id: item},
        now=NOW,
        history=build_history(delta, request_id),
    )

    return Trial(request=request, context=context, item=item)
