"""Shared fixtures for Layer 1.

One benign merchant, catalog and mandate, and a request that satisfies all of
them. Every test builds its case by overriding exactly one field of that
baseline, so a failure names the thing that changed.
"""

from datetime import UTC, datetime, timedelta

import pytest

from acg.domain.catalog import CatalogItem, Merchant
from acg.domain.mandate import Mandate, MandateUsage
from acg.domain.money import Money
from acg.domain.request import OrderLine, PurchaseRequest
from acg.layer1.rules import EvaluationContext

NOW = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
REGISTERED_PAYEE = "payee_glow_labs"
ATTACKER_PAYEE = "payee_attacker_99"


@pytest.fixture
def merchant() -> Merchant:
    return Merchant(
        merchant_id="mer_1",
        display_name="Glow Labs",
        registered_payee_id=REGISTERED_PAYEE,
    )


@pytest.fixture
def item() -> CatalogItem:
    return CatalogItem(
        item_id="itm_1",
        merchant_id="mer_1",
        title="Vitamin C Serum",
        description="A 15% vitamin C serum for daily use.",
        price=Money.from_rupees(1200),
        category="skincare",
    )


@pytest.fixture
def mandate() -> Mandate:
    return Mandate(
        mandate_id="mnd_1",
        buyer_id="buyer_1",
        max_amount=Money.from_rupees(1500),
        allowed_categories=["skincare"],
        usage=MandateUsage.ONE_TIME,
        created_at=NOW - timedelta(days=1),
        expires_at=NOW + timedelta(days=29),
    )


@pytest.fixture
def context(
    mandate: Mandate, merchant: Merchant, item: CatalogItem
) -> EvaluationContext:
    return EvaluationContext(
        mandate=mandate,
        merchant=merchant,
        items={item.item_id: item},
        now=NOW,
    )


@pytest.fixture
def request_factory(item: CatalogItem):  # noqa: ANN201
    """Build a benign request, with any field overridden."""

    def build(**overrides: object) -> PurchaseRequest:
        fields: dict[str, object] = {
            "request_id": "req_1",
            "mandate_id": "mnd_1",
            "buyer_id": "buyer_1",
            "merchant_id": "mer_1",
            "payee_id": REGISTERED_PAYEE,
            "lines": (
                OrderLine(item_id=item.item_id, quantity=1, unit_price=item.price),
            ),
            "quoted_total": item.price,
            "created_at": NOW,
        }
        return PurchaseRequest(**(fields | overrides))  # type: ignore[arg-type]

    return build
