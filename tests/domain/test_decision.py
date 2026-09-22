"""The lattice guarantee, proved by exhaustion rather than measured.

`Decision` has three members, so `combine` has exactly nine possible input
pairs. Every property below is checked against the complete cross-product,
which makes these proofs of the structural claim and not samples of it — the
distinction the project page draws between what is proved and what is measured.

A sampling strategy (hypothesis and friends) would be the right tool for an
unbounded input space. This one is nine cases wide, so enumerating it is both
stronger and cheaper.
"""

import itertools

import pytest

from acg.domain.decision import Decision, combine

ALL_PAIRS = list(itertools.product(Decision, repeat=2))


class TestLatticeOrdering:
    """The order itself, which holds regardless of how `combine` is written."""

    def test_allow_is_loosest_and_block_is_most_restrictive(self) -> None:
        assert Decision.ALLOW < Decision.REVIEW < Decision.BLOCK

    def test_has_exactly_three_members(self) -> None:
        # If a member is added, every exhaustive proof below silently widens
        # to cover it. This test is what makes that widening deliberate.
        assert len(Decision) == 3

    def test_renders_as_its_name(self) -> None:
        assert str(Decision.BLOCK) == "BLOCK"


class TestCombineIsTotal:
    def test_the_cross_product_is_nine_pairs(self) -> None:
        # Guards the exhaustiveness claim: if this number is not 9, the
        # parametrised proofs below are no longer covering the whole space.
        assert len(ALL_PAIRS) == 9

    @pytest.mark.parametrize(("first", "second"), ALL_PAIRS)
    def test_returns_a_decision_for_every_pair(
        self, first: Decision, second: Decision
    ) -> None:
        assert isinstance(combine(first, second), Decision)


class TestTheGuarantee:
    """`combine(l1, l2) >= l1` — Layer 2 can never loosen Layer 1."""

    @pytest.mark.parametrize(("first", "second"), ALL_PAIRS)
    def test_is_never_looser_than_the_first_input(
        self, first: Decision, second: Decision
    ) -> None:
        assert combine(first, second) >= first

    @pytest.mark.parametrize(("first", "second"), ALL_PAIRS)
    def test_is_never_looser_than_the_second_input(
        self, first: Decision, second: Decision
    ) -> None:
        assert combine(first, second) >= second


class TestAlgebraicProperties:
    @pytest.mark.parametrize(
        ("first", "second", "expected"),
        [
            (Decision.ALLOW, Decision.ALLOW, Decision.ALLOW),
            (Decision.ALLOW, Decision.REVIEW, Decision.REVIEW),
            (Decision.ALLOW, Decision.BLOCK, Decision.BLOCK),
            (Decision.REVIEW, Decision.ALLOW, Decision.REVIEW),
            (Decision.REVIEW, Decision.REVIEW, Decision.REVIEW),
            (Decision.REVIEW, Decision.BLOCK, Decision.BLOCK),
            (Decision.BLOCK, Decision.ALLOW, Decision.BLOCK),
            (Decision.BLOCK, Decision.REVIEW, Decision.BLOCK),
            (Decision.BLOCK, Decision.BLOCK, Decision.BLOCK),
        ],
    )
    def test_the_full_truth_table(
        self, first: Decision, second: Decision, expected: Decision
    ) -> None:
        assert combine(first, second) is expected

    @pytest.mark.parametrize(("first", "second"), ALL_PAIRS)
    def test_is_commutative(self, first: Decision, second: Decision) -> None:
        assert combine(first, second) is combine(second, first)

    @pytest.mark.parametrize("value", list(Decision))
    def test_is_idempotent(self, value: Decision) -> None:
        assert combine(value, value) is value

    @pytest.mark.parametrize("value", list(Decision))
    def test_allow_is_the_identity(self, value: Decision) -> None:
        """This is what makes Layer 2's ABSTAIN path safe.

        A failed or garbage Layer 2 yields ALLOW, and the identity property
        means the combined result is exactly Layer 1's verdict. The fallback
        is not a branch in the caller; it falls out of the algebra.
        """
        assert combine(value, Decision.ALLOW) is value
        assert combine(Decision.ALLOW, value) is value

    @pytest.mark.parametrize("value", list(Decision))
    def test_block_absorbs(self, value: Decision) -> None:
        assert combine(value, Decision.BLOCK) is Decision.BLOCK
        assert combine(Decision.BLOCK, value) is Decision.BLOCK

    @pytest.mark.parametrize(
        ("first", "second", "third"),
        list(itertools.product(Decision, repeat=3)),
    )
    def test_is_associative(
        self, first: Decision, second: Decision, third: Decision
    ) -> None:
        """Associativity is what lets more than two layers be folded later."""
        assert combine(combine(first, second), third) is combine(
            first, combine(second, third)
        )
