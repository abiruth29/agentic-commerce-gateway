"""I1 — the contracts implemented by the three mandate rules.

These fail until the rules are written. They are the specification.

The baseline fixtures describe a benign order: a ₹1,200 skincare item against a
₹1,500 skincare one-time mandate valid from yesterday to +29 days. Every case
below moves exactly one thing.
"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from acg.domain.catalog import CatalogItem
from acg.domain.decision import Decision
from acg.domain.mandate import Mandate, MandateUsage
from acg.domain.money import Money
from acg.domain.request import OrderLine
from acg.layer1.mandate import (
    AMOUNT_RULE_ID,
    ATTACK_CLASS,
    CATEGORY_RULE_ID,
    WINDOW_RULE_ID,
    MandateAmountRule,
    MandateCategoryRule,
    MandateWindowRule,
)
from acg.layer1.rules import EvaluationContext, Finding

from .conftest import NOW


@pytest.fixture
def amount_rule() -> MandateAmountRule:
    return MandateAmountRule()


@pytest.fixture
def category_rule() -> MandateCategoryRule:
    return MandateCategoryRule()


@pytest.fixture
def window_rule() -> MandateWindowRule:
    return MandateWindowRule()


def with_mandate(context: EvaluationContext, **overrides: object) -> EvaluationContext:
    """A context whose mandate differs in one field."""
    return replace(context, mandate=context.mandate.model_copy(update=overrides))


def with_now(context: EvaluationContext, now: datetime) -> EvaluationContext:
    """A context evaluated at a different moment."""
    return replace(context, now=now)


def with_items(context: EvaluationContext, *items: CatalogItem) -> EvaluationContext:
    """A context whose catalog is exactly these items."""
    return replace(context, items={item.item_id: item for item in items})


class TestMetadata:
    @pytest.mark.parametrize(
        ("rule", "expected_id"),
        [
            (MandateAmountRule(), AMOUNT_RULE_ID),
            (MandateCategoryRule(), CATEGORY_RULE_ID),
            (MandateWindowRule(), WINDOW_RULE_ID),
        ],
    )
    def test_each_rule_declares_its_identity(
        self, rule: object, expected_id: str
    ) -> None:
        assert rule.rule_id == expected_id  # type: ignore[attr-defined]
        assert rule.attack_class == ATTACK_CLASS  # type: ignore[attr-defined]

    def test_the_three_rule_ids_are_distinct(self) -> None:
        # Findings are attributed by rule id; a collision would misreport which
        # bound was crossed in the per-class breakdown.
        assert len({AMOUNT_RULE_ID, CATEGORY_RULE_ID, WINDOW_RULE_ID}) == 3


class TestAmountCeiling:
    def test_allows_a_total_under_the_ceiling(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        finding = amount_rule.evaluate(request_factory(), context)

        assert finding.decision is Decision.ALLOW

    def test_allows_a_total_exactly_at_the_ceiling(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        # "up to ₹1,500" authorises ₹1,500. The ceiling is inclusive.
        request = request_factory(quoted_total=context.mandate.max_amount)

        assert amount_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_blocks_a_total_one_paisa_over(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        over = Money(context.mandate.max_amount.paise + 1)

        finding = amount_rule.evaluate(request_factory(quoted_total=over), context)

        assert finding.decision is Decision.BLOCK

    def test_never_routes_an_over_budget_total_to_review(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        # The human named a number. Over is over.
        over = Money.from_rupees(100_000)

        finding = amount_rule.evaluate(request_factory(quoted_total=over), context)

        assert finding.decision is not Decision.REVIEW

    def test_returns_a_finding_carrying_its_own_identity(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        finding = amount_rule.evaluate(request_factory(), context)

        assert isinstance(finding, Finding)
        assert finding.rule_id == AMOUNT_RULE_ID
        assert finding.attack_class == ATTACK_CLASS

    def test_judges_the_quoted_total_not_a_recomputed_one(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        """Whether the total matches its lines is I2's question, not this one.

        Here the lines would sum to far more than the ceiling while the quoted
        total sits under it. This rule allows, because the charge is the quoted
        total; the mismatch is a separate attack and a separate finding.
        """
        item = next(iter(context.items.values()))
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=50, unit_price=item.price),
            ),
            quoted_total=Money.from_rupees(1000),
        )

        assert amount_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_survives_a_hostile_quantity(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        """A negative quantity must not make this rule raise.

        `Money.__mul__` refuses a negative multiplier, so a rule that computed
        a line total here would explode on input the request model
        deliberately allows. The I2 rule is what rejects the quantity.
        """
        item = next(iter(context.items.values()))
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),
            ),
        )

        assert amount_rule.evaluate(request, context).decision is Decision.ALLOW


class TestCategory:
    def test_allows_an_authorised_category(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        finding = category_rule.evaluate(request_factory(), context)

        assert finding.decision is Decision.ALLOW

    def test_blocks_a_category_the_mandate_does_not_cover(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        narrowed = with_mandate(context, allowed_categories=frozenset({"groceries"}))

        finding = category_rule.evaluate(request_factory(), narrowed)

        assert finding.decision is Decision.BLOCK

    def test_blocks_when_one_line_of_many_is_disallowed(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        """Otherwise the ninth legitimate line is cover for the tenth."""
        contraband = CatalogItem(
            item_id="itm_2",
            merchant_id=item.merchant_id,
            title="Cordless Drill",
            description="18V cordless drill.",
            price=Money.from_rupees(100),
            category="tools",
        )
        widened = with_items(context, item, contraband)
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=1, unit_price=item.price),
                OrderLine(
                    item_id=contraband.item_id,
                    quantity=1,
                    unit_price=contraband.price,
                ),
            ),
        )

        assert category_rule.evaluate(request, widened).decision is Decision.BLOCK

    def test_blocks_an_item_the_merchant_never_published(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        """Fail closed: a category that cannot be determined is not a pass."""
        request = request_factory(
            lines=(
                OrderLine(
                    item_id="itm_does_not_exist",
                    quantity=1,
                    unit_price=Money.from_rupees(10),
                ),
            ),
        )

        assert category_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_reads_the_category_from_the_catalog_not_the_request(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        """The published category is authority; the request has no say.

        The item here is published as `tools` while the mandate allows only
        `skincare`. There is no field on the request that could rescue it —
        and that is the point of the request not carrying a category at all.
        """
        relabelled = item.model_copy(update={"category": "tools"})
        ctx = with_items(context, relabelled)

        assert category_rule.evaluate(request_factory(), ctx).decision is Decision.BLOCK

    def test_allows_any_of_several_authorised_categories(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        widened = with_mandate(
            context, allowed_categories=frozenset({"skincare", "wellness"})
        )

        assert (
            category_rule.evaluate(request_factory(), widened).decision
            is Decision.ALLOW
        )


class TestValidityWindow:
    def test_allows_inside_the_window(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        finding = window_rule.evaluate(request_factory(), context)

        assert finding.decision is Decision.ALLOW

    def test_allows_exactly_at_the_start(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        at_start = with_now(context, context.mandate.created_at)

        assert (
            window_rule.evaluate(request_factory(), at_start).decision is Decision.ALLOW
        )

    def test_blocks_exactly_at_the_expiry(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        # Half-open: an expiry is the instant authorisation stops.
        at_expiry = with_now(context, context.mandate.expires_at)

        assert (
            window_rule.evaluate(request_factory(), at_expiry).decision
            is Decision.BLOCK
        )

    def test_blocks_after_the_expiry(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        expired = with_now(context, context.mandate.expires_at + timedelta(seconds=1))

        assert (
            window_rule.evaluate(request_factory(), expired).decision is Decision.BLOCK
        )

    def test_blocks_before_the_mandate_is_in_force(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        # Not yet in force has authorised nothing.
        early = with_now(context, context.mandate.created_at - timedelta(seconds=1))

        assert window_rule.evaluate(request_factory(), early).decision is Decision.BLOCK

    def test_ignores_the_requests_own_timestamp(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        """An attacker must not revive an expired mandate by lying about time.

        `context.now` is past the expiry; the request claims it was made well
        inside the window. The rule follows the context.
        """
        expired = with_now(context, context.mandate.expires_at + timedelta(days=1))
        request = request_factory(created_at=NOW)

        assert window_rule.evaluate(request, expired).decision is Decision.BLOCK


class TestTheRulesAreIndependent:
    def test_an_over_budget_order_does_not_trip_the_category_rule(
        self,
        category_rule: MandateCategoryRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        """Each rule checks one axis and stays silent on the others.

        Otherwise one violation produces three findings and the per-class
        breakdown stops meaning anything.
        """
        request = request_factory(quoted_total=Money.from_rupees(100_000))

        assert category_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_an_expired_mandate_does_not_trip_the_amount_rule(
        self,
        amount_rule: MandateAmountRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        expired = with_now(context, context.mandate.expires_at + timedelta(days=1))

        assert (
            amount_rule.evaluate(request_factory(), expired).decision is Decision.ALLOW
        )

    def test_a_disallowed_category_does_not_trip_the_window_rule(
        self,
        window_rule: MandateWindowRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        narrowed = with_mandate(context, allowed_categories=frozenset({"groceries"}))

        assert (
            window_rule.evaluate(request_factory(), narrowed).decision is Decision.ALLOW
        )


class TestReasons:
    @pytest.mark.parametrize(
        ("rule", "build_context"),
        [
            pytest.param(
                MandateAmountRule(),
                lambda ctx: ctx,
                id="amount",
            ),
            pytest.param(
                MandateCategoryRule(),
                lambda ctx: with_mandate(
                    ctx, allowed_categories=frozenset({"groceries"})
                ),
                id="category",
            ),
            pytest.param(
                MandateWindowRule(),
                lambda ctx: with_now(ctx, ctx.mandate.expires_at + timedelta(days=1)),
                id="window",
            ),
        ],
    )
    def test_every_rule_explains_itself(
        self, rule: object, build_context, request_factory, context: EvaluationContext
    ) -> None:
        finding = rule.evaluate(  # type: ignore[attr-defined]
            request_factory(quoted_total=Money.from_rupees(100_000)),
            build_context(context),
        )

        assert finding.reason


class TestTheHelpersThemselves:
    """The helpers above are only exercised by tests that currently fail.

    That makes a broken helper invisible until the rules are implemented, at
    which point it surfaces as a confusing failure that looks like the
    implementer's bug rather than the fixture's. These run now.
    """

    def test_with_mandate_changes_only_what_it_is_given(
        self, context: EvaluationContext
    ) -> None:
        changed = with_mandate(context, max_amount=Money.from_rupees(99_999))

        assert changed.mandate.max_amount == Money.from_rupees(99_999)
        assert changed.mandate.allowed_categories == context.mandate.allowed_categories
        assert changed.now == context.now

    def test_with_mandate_does_not_mutate_the_original(
        self, context: EvaluationContext
    ) -> None:
        original = context.mandate.max_amount

        with_mandate(context, max_amount=Money.from_rupees(99_999))

        assert context.mandate.max_amount == original

    def test_with_now_moves_the_clock_and_nothing_else(
        self, context: EvaluationContext
    ) -> None:
        moved = with_now(context, context.mandate.expires_at + timedelta(days=1))

        assert moved.now == context.mandate.expires_at + timedelta(days=1)
        assert moved.now != context.now
        assert moved.mandate == context.mandate
        assert moved.items == context.items

    def test_with_items_replaces_the_catalog(
        self, context: EvaluationContext, item: CatalogItem
    ) -> None:
        other = item.model_copy(update={"item_id": "itm_other"})

        replaced = with_items(context, other)

        assert set(replaced.items) == {"itm_other"}
        assert replaced.mandate == context.mandate

    def test_with_items_keeps_every_item_it_is_given(
        self, context: EvaluationContext, item: CatalogItem
    ) -> None:
        other = item.model_copy(update={"item_id": "itm_other"})

        replaced = with_items(context, item, other)

        assert set(replaced.items) == {item.item_id, "itm_other"}


def test_the_baseline_is_genuinely_benign(
    context: EvaluationContext, request_factory
) -> None:
    """If the baseline already violated a bound, every ALLOW case above would
    be testing nothing. Pin it against the mandate directly."""
    request = request_factory()
    item = context.items[request.lines[0].item_id]

    assert request.quoted_total <= context.mandate.max_amount
    assert item.category in context.mandate.allowed_categories
    assert context.mandate.created_at <= context.now < context.mandate.expires_at
    assert isinstance(Mandate.model_validate(context.mandate.model_dump()), Mandate)
    assert context.mandate.usage is MandateUsage.ONE_TIME
