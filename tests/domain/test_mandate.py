from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from acg.domain.mandate import Mandate, MandateUsage
from acg.domain.money import Money

CREATED = datetime(2026, 1, 1, tzinfo=UTC)
EXPIRES = CREATED + timedelta(days=30)


def build(**overrides: object) -> Mandate:
    fields: dict[str, object] = {
        "mandate_id": "mnd_1",
        "buyer_id": "buyer_1",
        "max_amount": Money.from_rupees(1500),
        "allowed_categories": ["skincare"],
        "usage": MandateUsage.ONE_TIME,
        "created_at": CREATED,
        "expires_at": EXPIRES,
    }
    return Mandate(**(fields | overrides))  # type: ignore[arg-type]


class TestDeclaration:
    def test_holds_what_the_human_authorised(self) -> None:
        mandate = build()

        assert mandate.max_amount == Money(150_000)
        assert mandate.allowed_categories == frozenset({"skincare"})
        assert mandate.usage is MandateUsage.ONE_TIME

    def test_is_frozen(self) -> None:
        # The record the gateway compares against must not be movable.
        with pytest.raises(ValidationError):
            build().max_amount = Money.from_rupees(999_999)  # type: ignore[misc]

    def test_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            build(payee_id="attacker")

    def test_is_hashable(self) -> None:
        assert build() == build()


class TestCategories:
    def test_normalises_case_and_whitespace(self) -> None:
        mandate = build(allowed_categories=["  SkinCare  ", "Wellness"])

        assert mandate.allowed_categories == frozenset({"skincare", "wellness"})

    def test_collapses_duplicates_that_differ_only_in_case(self) -> None:
        mandate = build(allowed_categories=["skincare", "SKINCARE"])

        assert mandate.allowed_categories == frozenset({"skincare"})

    def test_rejects_an_empty_set(self) -> None:
        # Authorising nothing must not quietly mean authorising everything.
        with pytest.raises(ValidationError):
            build(allowed_categories=[])

    def test_rejects_a_bare_string(self) -> None:
        # "skincare" would otherwise iterate into single characters.
        with pytest.raises(ValidationError):
            build(allowed_categories="skincare")

    def test_rejects_a_blank_category(self) -> None:
        with pytest.raises(ValidationError):
            build(allowed_categories=["   "])


class TestTimestamps:
    def test_rejects_a_naive_created_at(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            build(created_at=datetime(2026, 1, 1))  # noqa: DTZ001

    def test_rejects_a_naive_expires_at(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            build(expires_at=datetime(2026, 2, 1))  # noqa: DTZ001

    def test_rejects_expiry_before_creation(self) -> None:
        with pytest.raises(ValidationError, match="after created_at"):
            build(expires_at=CREATED - timedelta(seconds=1))

    def test_rejects_expiry_equal_to_creation(self) -> None:
        # A zero-length window is a mandate that can never be used.
        with pytest.raises(ValidationError, match="after created_at"):
            build(expires_at=CREATED)


class TestAmount:
    def test_rejects_a_negative_ceiling(self) -> None:
        # Money refuses this at construction, so the mandate never sees it.
        # The ceiling cannot be negative because the type cannot be.
        with pytest.raises(ValueError, match="must not be negative"):
            build(max_amount=Money(-1))

    def test_accepts_the_paise_ceiling_exactly(self) -> None:
        assert build(max_amount=Money(150_000)).max_amount.paise == 150_000
