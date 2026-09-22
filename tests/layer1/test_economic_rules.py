"""I2 — the contracts implemented by the three economic rules.

These fail until the rules are written. They are the specification.

`line_total` is plumbing rather than policy, so it is implemented and its tests
pass now — it is what keeps the rules from disagreeing about the arithmetic.
"""

from dataclasses import replace

import pytest

from acg.domain.catalog import CatalogItem
from acg.domain.decision import Decision
from acg.domain.money import Money
from acg.domain.request import OrderLine
from acg.layer1.economic import (
    ATTACK_CLASS,
    PRICE_RULE_ID,
    QUANTITY_RULE_ID,
    TOTAL_RULE_ID,
    PriceIntegrityRule,
    QuantityRule,
    TotalIntegrityRule,
    line_total,
)
from acg.layer1.engine import evaluate
from acg.layer1.rules import EvaluationContext, Finding


@pytest.fixture
def quantity_rule() -> QuantityRule:
    return QuantityRule()


@pytest.fixture
def price_rule() -> PriceIntegrityRule:
    return PriceIntegrityRule()


@pytest.fixture
def total_rule() -> TotalIntegrityRule:
    return TotalIntegrityRule()


def order(*lines: OrderLine) -> dict[str, object]:
    """Request overrides for these lines and a total that matches them."""
    total = Money.zero()
    for line in lines:
        part = line_total(line)
        if part is not None:
            total = total + part
    return {"lines": lines, "quoted_total": total}


class TestLineTotal:
    """Plumbing, implemented and green — the rules depend on it agreeing."""

    def test_multiplies_price_by_quantity(self) -> None:
        line = OrderLine(item_id="i", quantity=3, unit_price=Money.from_rupees(19))

        assert line_total(line) == Money.from_rupees(57)

    def test_a_single_item_costs_its_price(self) -> None:
        line = OrderLine(item_id="i", quantity=1, unit_price=Money(1_999))

        assert line_total(line) == Money(1_999)

    @pytest.mark.parametrize("quantity", [0, -1, -1000])
    def test_is_none_when_the_quantity_is_unorderable(self, quantity: int) -> None:
        """Rather than raising, so a rule can say "cannot verify" and move on.

        `Money.__mul__` refuses a negative multiplier, so the naive call would
        crash on input the request model deliberately permits.
        """
        line = OrderLine(
            item_id="i", quantity=quantity, unit_price=Money.from_rupees(19)
        )

        assert line_total(line) is None

    def test_does_not_raise_on_a_hostile_quantity(self) -> None:
        line = OrderLine(item_id="i", quantity=-5, unit_price=Money.from_rupees(19))

        line_total(line)  # must not raise


class TestMetadata:
    @pytest.mark.parametrize(
        ("rule", "expected_id"),
        [
            (QuantityRule(), QUANTITY_RULE_ID),
            (PriceIntegrityRule(), PRICE_RULE_ID),
            (TotalIntegrityRule(), TOTAL_RULE_ID),
        ],
    )
    def test_each_rule_declares_its_identity(
        self, rule: object, expected_id: str
    ) -> None:
        assert rule.rule_id == expected_id  # type: ignore[attr-defined]
        assert rule.attack_class == ATTACK_CLASS  # type: ignore[attr-defined]

    def test_the_three_rule_ids_are_distinct(self) -> None:
        assert len({QUANTITY_RULE_ID, PRICE_RULE_ID, TOTAL_RULE_ID}) == 3

    def test_no_id_collides_with_another_class(self) -> None:
        from acg.layer1.mandate import (
            AMOUNT_RULE_ID,
            CATEGORY_RULE_ID,
            WINDOW_RULE_ID,
        )
        from acg.layer1.payee import RULE_ID as PAYEE_RULE_ID

        everything = {
            QUANTITY_RULE_ID,
            PRICE_RULE_ID,
            TOTAL_RULE_ID,
            AMOUNT_RULE_ID,
            CATEGORY_RULE_ID,
            WINDOW_RULE_ID,
            PAYEE_RULE_ID,
        }

        assert len(everything) == 7


class TestQuantity:
    def test_allows_an_ordinary_order(
        self, quantity_rule: QuantityRule, request_factory, context: EvaluationContext
    ) -> None:
        assert (
            quantity_rule.evaluate(request_factory(), context).decision
            is Decision.ALLOW
        )

    def test_allows_a_large_but_orderable_quantity(
        self,
        quantity_rule: QuantityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        # Quantity is this rule's axis; whether 50 breaks the budget is I1's.
        request = request_factory(
            **order(OrderLine(item_id=item.item_id, quantity=50, unit_price=item.price))
        )

        assert quantity_rule.evaluate(request, context).decision is Decision.ALLOW

    @pytest.mark.parametrize("quantity", [0, -1, -1000])
    def test_blocks_an_unorderable_quantity(
        self,
        quantity_rule: QuantityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
        quantity: int,
    ) -> None:
        request = request_factory(
            lines=(
                OrderLine(
                    item_id=item.item_id, quantity=quantity, unit_price=item.price
                ),
            )
        )

        assert quantity_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_blocks_when_one_line_of_many_is_bad(
        self,
        quantity_rule: QuantityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=2, unit_price=item.price),
                OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),
            )
        )

        assert quantity_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_never_routes_to_review(
        self,
        quantity_rule: QuantityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            lines=(OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),)
        )

        assert quantity_rule.evaluate(request, context).decision is not Decision.REVIEW

    def test_returns_a_finding_carrying_its_own_identity(
        self, quantity_rule: QuantityRule, request_factory, context: EvaluationContext
    ) -> None:
        finding = quantity_rule.evaluate(request_factory(), context)

        assert isinstance(finding, Finding)
        assert finding.rule_id == QUANTITY_RULE_ID
        assert finding.attack_class == ATTACK_CLASS


class TestPriceIntegrity:
    def test_allows_the_published_price(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        assert (
            price_rule.evaluate(request_factory(), context).decision is Decision.ALLOW
        )

    def test_blocks_a_price_above_the_published_one(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        inflated = Money(item.price.paise + 1)
        request = request_factory(
            **order(OrderLine(item_id=item.item_id, quantity=1, unit_price=inflated))
        )

        assert price_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_blocks_a_price_below_the_published_one(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        """Underpaying is still not the agreement.

        A gateway that tolerates deviation downward has no principled reason
        to refuse it upward.
        """
        discounted = Money(item.price.paise - 1)
        request = request_factory(
            **order(OrderLine(item_id=item.item_id, quantity=1, unit_price=discounted))
        )

        assert price_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_blocks_an_item_the_merchant_never_published(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        # A price that cannot be checked is not a price that passes.
        request = request_factory(
            **order(
                OrderLine(
                    item_id="itm_nope", quantity=1, unit_price=Money.from_rupees(10)
                )
            )
        )

        assert price_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_blocks_when_one_line_of_many_is_mispriced(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            **order(
                OrderLine(item_id=item.item_id, quantity=1, unit_price=item.price),
                OrderLine(item_id=item.item_id, quantity=1, unit_price=Money(1)),
            )
        )

        assert price_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_catches_a_stale_price_after_the_merchant_reprices(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        """As far as stale-quote replay goes without quote issuance times.

        The agent quotes yesterday's price; the catalog has today's.
        """
        repriced = item.model_copy(update={"price": Money.from_rupees(1500)})
        ctx = replace(context, items={repriced.item_id: repriced})
        request = request_factory(
            **order(OrderLine(item_id=item.item_id, quantity=1, unit_price=item.price))
        )

        assert price_rule.evaluate(request, ctx).decision is Decision.BLOCK


class TestTotalIntegrity:
    def test_allows_a_total_that_matches_its_lines(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        assert (
            total_rule.evaluate(request_factory(), context).decision is Decision.ALLOW
        )

    def test_allows_a_multi_line_total(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            **order(
                OrderLine(item_id=item.item_id, quantity=2, unit_price=item.price),
                OrderLine(item_id=item.item_id, quantity=3, unit_price=item.price),
            )
        )

        assert total_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_blocks_a_total_above_the_line_sum(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(quoted_total=Money(item.price.paise + 1))

        assert total_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_blocks_a_total_below_the_line_sum(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(quoted_total=Money(item.price.paise - 1))

        assert total_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_catches_paise_rupee_confusion(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        """A total computed in the wrong unit is off by exactly 100x.

        Exact equality catches it without looking for the factor.
        """
        wrong_unit = Money(item.price.paise * 100)
        request = request_factory(quoted_total=wrong_unit)

        assert total_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_catches_the_other_direction_of_unit_confusion(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        wrong_unit = Money(item.price.paise // 100)
        request = request_factory(quoted_total=wrong_unit)

        assert total_rule.evaluate(request, context).decision is Decision.BLOCK

    def test_allows_when_the_sum_cannot_be_computed(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        """Not failing open — deferring to the rule whose axis actually failed.

        A negative quantity makes the sum meaningless. The quantity rule
        blocks it; this rule staying quiet keeps the finding attributable.
        `test_the_engine_still_blocks_an_uncomputable_order` pins that the
        request is refused regardless.
        """
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),
            ),
            quoted_total=Money.from_rupees(1),
        )

        assert total_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_does_not_raise_on_a_hostile_quantity(
        self,
        total_rule: TotalIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            lines=(OrderLine(item_id=item.item_id, quantity=-3, unit_price=item.price),)
        )

        total_rule.evaluate(request, context)  # must not raise


class TestTheRulesAreIndependent:
    """One dishonest order must not light up the whole class."""

    def test_a_mispriced_line_does_not_trip_the_quantity_rule(
        self,
        quantity_rule: QuantityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            **order(OrderLine(item_id=item.item_id, quantity=1, unit_price=Money(1)))
        )

        assert quantity_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_a_bad_total_does_not_trip_the_price_rule(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        request = request_factory(quoted_total=Money.from_rupees(99_999))

        assert price_rule.evaluate(request, context).decision is Decision.ALLOW

    def test_a_bad_quantity_does_not_trip_the_price_rule(
        self,
        price_rule: PriceIntegrityRule,
        request_factory,
        context: EvaluationContext,
        item: CatalogItem,
    ) -> None:
        request = request_factory(
            lines=(OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),)
        )

        assert price_rule.evaluate(request, context).decision is Decision.ALLOW


class TestComposition:
    """The engine over the real I2 rules, not stubs."""

    @pytest.fixture
    def rules(self) -> tuple[object, ...]:
        return (QuantityRule(), PriceIntegrityRule(), TotalIntegrityRule())

    def test_a_benign_order_passes_every_rule(
        self, rules, request_factory, context: EvaluationContext
    ) -> None:
        verdict = evaluate(request_factory(), context, rules)  # type: ignore[arg-type]

        assert verdict.decision is Decision.ALLOW
        assert len(verdict.findings) == 3

    def test_the_engine_still_blocks_an_uncomputable_order(
        self, rules, request_factory, context: EvaluationContext, item: CatalogItem
    ) -> None:
        """The total rule allows it; the join blocks it anyway.

        This is what makes the total rule's quiet ALLOW safe rather than a
        hole, and it is the claim that would be challenged in review.
        """
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),
            ),
            quoted_total=Money.from_rupees(1),
        )

        verdict = evaluate(request, context, rules)  # type: ignore[arg-type]

        assert verdict.decision is Decision.BLOCK

    def test_the_blocking_finding_names_the_quantity_rule(
        self, rules, request_factory, context: EvaluationContext, item: CatalogItem
    ) -> None:
        """Attribution is the point of keeping the other rules quiet."""
        request = request_factory(
            lines=(
                OrderLine(item_id=item.item_id, quantity=-1, unit_price=item.price),
            ),
            quoted_total=Money.from_rupees(1),
        )

        verdict = evaluate(request, context, rules)  # type: ignore[arg-type]

        assert [f.rule_id for f in verdict.blocking] == [QUANTITY_RULE_ID]


def test_the_baseline_is_genuinely_benign(
    context: EvaluationContext, request_factory
) -> None:
    """Otherwise every ALLOW case above proves nothing."""
    request = request_factory()
    item = context.items[request.lines[0].item_id]
    computed = Money.zero()
    for line in request.lines:
        part = line_total(line)
        assert part is not None
        computed = computed + part

    assert all(line.quantity >= 1 for line in request.lines)
    assert all(line.unit_price == item.price for line in request.lines)
    assert request.quoted_total == computed
