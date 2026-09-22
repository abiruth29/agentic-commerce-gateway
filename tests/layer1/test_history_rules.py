"""I3 and I4 — the two rules that need memory, plus the memory itself."""

from dataclasses import replace
from datetime import timedelta

import pytest

from acg.domain.decision import Decision
from acg.domain.history import PriorDecision, allowed, within_window
from acg.domain.mandate import MandateUsage
from acg.domain.money import Money
from acg.layer1.replay import ATTACK_CLASS as I3_CLASS
from acg.layer1.replay import RULE_ID as REPLAY_RULE_ID
from acg.layer1.replay import MandateReplayRule
from acg.layer1.rules import EvaluationContext, Finding
from acg.layer1.velocity import (
    ATTACK_CLASS as I4_CLASS,
)
from acg.layer1.velocity import (
    MAX_ALLOWED_IN_WINDOW,
    VELOCITY_WINDOW,
    VelocityRule,
)
from acg.layer1.velocity import RULE_ID as VELOCITY_RULE_ID

from .conftest import NOW


def prior(
    *,
    request_id: str = "req_old",
    mandate_id: str = "mnd_1",
    buyer_id: str = "buyer_1",
    minutes_ago: int = 10,
    decision: Decision = Decision.ALLOW,
    amount: Money | None = None,
) -> PriorDecision:
    return PriorDecision(
        request_id=request_id,
        mandate_id=mandate_id,
        buyer_id=buyer_id,
        quoted_total=amount or Money.from_rupees(100),
        decided_at=NOW - timedelta(minutes=minutes_ago),
        decision=decision,
    )


def with_history(
    context: EvaluationContext, *priors: PriorDecision
) -> EvaluationContext:
    return replace(context, history=priors)


class TestPriorDecision:
    def test_is_frozen(self) -> None:
        record = prior()

        with pytest.raises(Exception):  # noqa: B017, PT011
            record.decision = Decision.BLOCK  # type: ignore[misc]

    def test_rejects_a_naive_timestamp(self) -> None:
        from datetime import datetime

        with pytest.raises(ValueError, match="timezone-aware"):
            PriorDecision(
                request_id="r",
                mandate_id="m",
                buyer_id="b",
                quoted_total=Money.zero(),
                decided_at=datetime(2026, 1, 1),  # noqa: DTZ001
                decision=Decision.ALLOW,
            )


class TestWithinWindow:
    def test_keeps_a_record_inside_the_window(self) -> None:
        assert within_window((prior(minutes_ago=10),), NOW, timedelta(hours=1))

    def test_drops_a_record_older_than_the_window(self) -> None:
        assert within_window((prior(minutes_ago=61),), NOW, timedelta(hours=1)) == ()

    def test_the_window_is_half_open_at_its_far_edge(self) -> None:
        # now - window is excluded, matching the mandate validity window.
        exactly_at_edge = prior(minutes_ago=60)

        assert within_window((exactly_at_edge,), NOW, timedelta(hours=1)) == ()

    def test_includes_a_record_dated_exactly_now(self) -> None:
        assert within_window((prior(minutes_ago=0),), NOW, timedelta(hours=1))

    def test_excludes_a_record_from_the_future(self) -> None:
        """A clock problem is not a rule's to discover, but it must not count."""
        ahead = replace(prior(), decided_at=NOW + timedelta(minutes=1))

        assert within_window((ahead,), NOW, timedelta(hours=1)) == ()


class TestAllowed:
    def test_keeps_only_allowed_priors(self) -> None:
        kept = allowed(
            (
                prior(request_id="a", decision=Decision.ALLOW),
                prior(request_id="b", decision=Decision.BLOCK),
                prior(request_id="c", decision=Decision.REVIEW),
            )
        )

        assert [p.request_id for p in kept] == ["a"]


class TestMandateReplay:
    @pytest.fixture
    def rule(self) -> MandateReplayRule:
        return MandateReplayRule()

    def test_allows_a_first_draw(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        assert rule.evaluate(request_factory(), context).decision is Decision.ALLOW

    def test_declares_its_identity(self, rule: MandateReplayRule) -> None:
        assert rule.rule_id == REPLAY_RULE_ID
        assert rule.attack_class == I3_CLASS

    def test_blocks_a_second_draw_on_a_one_time_mandate(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        spent = with_history(context, prior(mandate_id="mnd_1"))

        assert rule.evaluate(request_factory(), spent).decision is Decision.BLOCK

    def test_allows_a_second_draw_on_a_recurring_mandate(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        recurring = replace(
            context,
            mandate=context.mandate.model_copy(
                update={"usage": MandateUsage.RECURRING}
            ),
        )
        used = with_history(recurring, prior(mandate_id="mnd_1"))

        assert rule.evaluate(request_factory(), used).decision is Decision.ALLOW

    def test_a_blocked_prior_does_not_spend_the_mandate(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        """Otherwise one refused attack locks out a mandate the human holds."""
        attempted = with_history(
            context, prior(mandate_id="mnd_1", decision=Decision.BLOCK)
        )

        assert rule.evaluate(request_factory(), attempted).decision is Decision.ALLOW

    def test_another_mandate_being_spent_is_irrelevant(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        other = with_history(context, prior(mandate_id="mnd_other"))

        assert rule.evaluate(request_factory(), other).decision is Decision.ALLOW

    def test_blocks_a_repeated_request_id(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        seen = with_history(context, prior(request_id="req_1", mandate_id="mnd_x"))

        assert rule.evaluate(request_factory(), seen).decision is Decision.BLOCK

    def test_blocks_a_repeated_request_id_even_if_it_was_refused(
        self,
        rule: MandateReplayRule,
        request_factory,
        context: EvaluationContext,
    ) -> None:
        """Re-deciding a replayed request is the bug, whatever was decided."""
        seen = with_history(
            context,
            prior(request_id="req_1", mandate_id="mnd_x", decision=Decision.BLOCK),
        )

        assert rule.evaluate(request_factory(), seen).decision is Decision.BLOCK

    def test_never_routes_replay_to_review(
        self, rule: MandateReplayRule, request_factory, context: EvaluationContext
    ) -> None:
        spent = with_history(context, prior(mandate_id="mnd_1"))

        assert rule.evaluate(request_factory(), spent).decision is not Decision.REVIEW


class TestVelocity:
    @pytest.fixture
    def rule(self) -> VelocityRule:
        return VelocityRule()

    def test_allows_an_ordinary_rate(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        assert rule.evaluate(request_factory(), context).decision is Decision.ALLOW

    def test_declares_its_identity(self, rule: VelocityRule) -> None:
        assert rule.rule_id == VELOCITY_RULE_ID
        assert rule.attack_class == I4_CLASS

    def test_allows_right_up_to_the_limit(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        busy = with_history(
            context,
            *(
                prior(request_id=f"req_{i}", minutes_ago=i + 1)
                for i in range(MAX_ALLOWED_IN_WINDOW - 1)
            ),
        )

        assert rule.evaluate(request_factory(), busy).decision is Decision.ALLOW

    def test_reviews_at_the_limit(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        """REVIEW, not BLOCK — this is the class the middle value exists for."""
        busy = with_history(
            context,
            *(
                prior(request_id=f"req_{i}", minutes_ago=i + 1)
                for i in range(MAX_ALLOWED_IN_WINDOW)
            ),
        )

        assert rule.evaluate(request_factory(), busy).decision is Decision.REVIEW

    def test_does_not_block(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        # A busy afternoon must not become lost GMV.
        very_busy = with_history(
            context,
            *(
                prior(request_id=f"req_{i}", minutes_ago=i + 1)
                for i in range(MAX_ALLOWED_IN_WINDOW * 4)
            ),
        )

        assert (
            rule.evaluate(request_factory(), very_busy).decision is not Decision.BLOCK
        )

    def test_ignores_activity_outside_the_window(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        old_minutes = int(VELOCITY_WINDOW.total_seconds() // 60) + 5
        historic = with_history(
            context,
            *(
                prior(request_id=f"req_{i}", minutes_ago=old_minutes + i)
                for i in range(MAX_ALLOWED_IN_WINDOW * 2)
            ),
        )

        assert rule.evaluate(request_factory(), historic).decision is Decision.ALLOW

    def test_ignores_another_buyers_activity(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        """One busy buyer must not put a different one into review."""
        someone_else = with_history(
            context,
            *(
                prior(request_id=f"req_{i}", buyer_id="buyer_other", minutes_ago=i + 1)
                for i in range(MAX_ALLOWED_IN_WINDOW * 2)
            ),
        )

        assert rule.evaluate(request_factory(), someone_else).decision is Decision.ALLOW

    def test_ignores_blocked_attempts(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        """Counting them would inflate FBR on the strength of stopped attacks."""
        probed = with_history(
            context,
            *(
                prior(
                    request_id=f"req_{i}",
                    minutes_ago=i + 1,
                    decision=Decision.BLOCK,
                )
                for i in range(MAX_ALLOWED_IN_WINDOW * 2)
            ),
        )

        assert rule.evaluate(request_factory(), probed).decision is Decision.ALLOW

    def test_returns_a_finding_carrying_its_own_identity(
        self, rule: VelocityRule, request_factory, context: EvaluationContext
    ) -> None:
        finding = rule.evaluate(request_factory(), context)

        assert isinstance(finding, Finding)
        assert finding.rule_id == VELOCITY_RULE_ID


class TestTheLatticeNowUsesItsMiddleValue:
    def test_velocity_is_the_only_rule_that_returns_review(
        self, request_factory, context: EvaluationContext
    ) -> None:
        """Documents the partition rather than enforcing it.

        If another rule later needs REVIEW this test should change — but it
        should change deliberately, because "which decisions are uncertain" is
        a claim the page makes.
        """
        busy = with_history(
            context,
            *(
                prior(request_id=f"req_{i}", minutes_ago=i + 1)
                for i in range(MAX_ALLOWED_IN_WINDOW)
            ),
        )

        assert VelocityRule().evaluate(request_factory(), busy).decision is (
            Decision.REVIEW
        )


class TestAllTwelveIdsAreDistinct:
    def test_no_rule_id_collides(self) -> None:
        from acg.layer1.economic import (
            PRICE_RULE_ID,
            QUANTITY_RULE_ID,
            TOTAL_RULE_ID,
        )
        from acg.layer1.mandate import (
            AMOUNT_RULE_ID,
            CATEGORY_RULE_ID,
            WINDOW_RULE_ID,
        )
        from acg.layer1.payee import RULE_ID as PAYEE_RULE_ID

        ids = {
            PAYEE_RULE_ID,
            AMOUNT_RULE_ID,
            CATEGORY_RULE_ID,
            WINDOW_RULE_ID,
            QUANTITY_RULE_ID,
            PRICE_RULE_ID,
            TOTAL_RULE_ID,
            REPLAY_RULE_ID,
            VELOCITY_RULE_ID,
        }

        assert len(ids) == 9
