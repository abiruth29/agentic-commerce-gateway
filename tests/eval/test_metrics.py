"""Tests for the metric definitions.

Arithmetic this simple does not usually earn a test file this size. It earns
one here because these are the numbers that go on the page, and every one of
them has a failure mode that makes the system look *better* than it is: an
unmeasured cell counted as a defence, a REVIEW quietly excluded from the false
block rate, a percentile taken over a list that included the cases nobody ran.
Each of those is tested for directly.
"""

import pytest

from acg.domain.decision import Decision
from acg.eval.metrics import (
    BENIGN,
    Outcome,
    Rate,
    attack_success_rate,
    false_block_rate,
    filter_split,
    latency_profile,
    percentile,
    rate_of_decision,
    summarise,
)
from acg.eval.pipeline import Config


def outcome(
    decision: Decision,
    attack_class: str = "O3",
    *,
    config: Config = Config.C1,
    split: str = "seed",
    measured: bool = True,
    payment_ms: float = 1.0,
    content_ms: float | None = None,
    case_id: str = "c",
) -> Outcome:
    return Outcome(
        case_id=case_id,
        attack_class=attack_class,
        split=split,
        config=config,
        decision=decision,
        stopped_by=None if decision is Decision.ALLOW else "layer1",
        payment_path_ms=payment_ms,
        content_path_ms=content_ms,
        measured=measured,
    )


class TestWhatCountsAsASuccessfulAttack:
    def test_an_allowed_attack_succeeded(self) -> None:
        assert outcome(Decision.ALLOW).succeeded

    def test_a_blocked_attack_did_not(self) -> None:
        assert not outcome(Decision.BLOCK).succeeded

    def test_a_reviewed_attack_did_not(self) -> None:
        # The money is held and a human sees it. Counting REVIEW as a success
        # would make the middle lattice value worthless by definition.
        assert not outcome(Decision.REVIEW).succeeded

    def test_the_rate_is_allowed_over_measured(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW),
            outcome(Decision.BLOCK),
            outcome(Decision.BLOCK),
            outcome(Decision.REVIEW),
        ]
        assert attack_success_rate(outcomes) == Rate(1, 4)

    def test_benign_flows_never_enter_an_attack_denominator(self) -> None:
        outcomes = [outcome(Decision.ALLOW), outcome(Decision.ALLOW, BENIGN)]
        assert attack_success_rate(outcomes) == Rate(1, 1)


class TestUnmeasuredCellsAreNotCredited:
    def test_an_unmeasured_outcome_leaves_the_denominator(self) -> None:
        outcomes = [outcome(Decision.ALLOW, measured=False)]
        assert attack_success_rate(outcomes) == Rate(0, 0)

    def test_an_all_unmeasured_class_reads_as_not_measured(self) -> None:
        # The failure this prevents: C0's semantic cells reading 0%, which
        # would claim a defence that was never tested.
        rate = attack_success_rate([outcome(Decision.ALLOW, measured=False)])
        assert rate.value is None
        assert str(rate) == "not measured"

    def test_a_mixed_class_counts_only_the_measured_half(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW),
            outcome(Decision.ALLOW, measured=False),
            outcome(Decision.BLOCK),
        ]
        assert attack_success_rate(outcomes) == Rate(1, 2)


class TestWhatCountsAsAFalseBlock:
    def test_an_allowed_benign_flow_is_not_a_false_block(self) -> None:
        assert not outcome(Decision.ALLOW, BENIGN).falsely_stopped

    def test_a_blocked_benign_flow_is(self) -> None:
        assert outcome(Decision.BLOCK, BENIGN).falsely_stopped

    def test_a_reviewed_benign_flow_is_too(self) -> None:
        # Delayed revenue is not "no harm done". This is the unflattering
        # choice and the one the metric is defined on.
        assert outcome(Decision.REVIEW, BENIGN).falsely_stopped

    def test_the_rate_counts_review_and_block_together(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW, BENIGN),
            outcome(Decision.ALLOW, BENIGN),
            outcome(Decision.REVIEW, BENIGN),
            outcome(Decision.BLOCK, BENIGN),
        ]
        assert false_block_rate(outcomes) == Rate(2, 4)

    def test_attacks_never_enter_the_benign_denominator(self) -> None:
        outcomes = [outcome(Decision.BLOCK), outcome(Decision.ALLOW, BENIGN)]
        assert false_block_rate(outcomes) == Rate(0, 1)

    def test_the_halves_are_reported_separately(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW, BENIGN),
            outcome(Decision.REVIEW, BENIGN),
            outcome(Decision.BLOCK, BENIGN),
        ]
        assert rate_of_decision(outcomes, Decision.BLOCK) == Rate(1, 3)
        assert rate_of_decision(outcomes, Decision.REVIEW) == Rate(1, 3)

    def test_the_halves_sum_to_the_whole(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW, BENIGN),
            outcome(Decision.REVIEW, BENIGN),
            outcome(Decision.BLOCK, BENIGN),
            outcome(Decision.BLOCK, BENIGN),
        ]
        blocked = rate_of_decision(outcomes, Decision.BLOCK).numerator
        reviewed = rate_of_decision(outcomes, Decision.REVIEW).numerator
        assert blocked + reviewed == false_block_rate(outcomes).numerator


class TestRateCarriesItsCounts:
    def test_a_rate_reports_its_denominator(self) -> None:
        # "6.7%" with no denominator hides that it is one case out of fifteen.
        assert str(Rate(1, 15)) == "6.7% (1/15)"

    def test_an_empty_rate_is_none_not_zero(self) -> None:
        assert Rate(0, 0).value is None
        assert Rate(0, 0).percent is None

    def test_a_zero_rate_is_zero_not_none(self) -> None:
        assert Rate(0, 15).value == 0.0
        assert Rate(0, 15).percent == 0.0


class TestPercentiles:
    def test_the_median_of_an_odd_sample(self) -> None:
        assert percentile([3.0, 1.0, 2.0], 0.5) == 2.0

    def test_every_reported_value_was_observed(self) -> None:
        sample = [1.0, 2.0, 3.0, 4.0]
        assert percentile(sample, 0.5) in sample
        assert percentile(sample, 0.95) in sample

    def test_p95_of_twenty_is_the_nineteenth(self) -> None:
        assert percentile([float(n) for n in range(1, 21)], 0.95) == 19.0

    def test_p100_is_the_maximum(self) -> None:
        assert percentile([5.0, 1.0, 9.0], 1.0) == 9.0

    def test_an_empty_sample_has_no_percentile(self) -> None:
        assert percentile([], 0.5) is None

    @pytest.mark.parametrize("fraction", [0.0, -0.1, 1.5])
    def test_a_nonsense_fraction_is_refused(self, fraction: float) -> None:
        with pytest.raises(ValueError, match="fraction must be in"):
            percentile([1.0], fraction)

    def test_the_sample_is_not_assumed_sorted(self) -> None:
        assert percentile([9.0, 1.0, 5.0], 0.5) == 5.0


class TestLatencyProfiles:
    def test_an_empty_path_has_no_percentiles(self) -> None:
        profile = latency_profile([])
        assert profile.samples == 0
        assert profile.p50 is None

    def test_the_sample_count_is_carried(self) -> None:
        assert latency_profile([1.0, 2.0, 3.0]).samples == 3


class TestSummarise:
    def test_only_the_requested_config_is_counted(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW, config=Config.C0),
            outcome(Decision.BLOCK, config=Config.C1),
        ]
        report = summarise(outcomes, Config.C1)
        assert report.asr_overall == Rate(0, 1)

    def test_classes_are_reported_separately(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW, "O1"),
            outcome(Decision.BLOCK, "O3"),
        ]
        report = summarise(outcomes, Config.C1)

        assert report.asr_by_class["O1"] == Rate(1, 1)
        assert report.asr_by_class["O3"] == Rate(0, 1)

    def test_benign_flows_do_not_become_a_class(self) -> None:
        outcomes = [outcome(Decision.ALLOW, BENIGN), outcome(Decision.BLOCK, "O3")]
        report = summarise(outcomes, Config.C1)
        assert BENIGN not in report.asr_by_class

    def test_the_paths_are_profiled_separately(self) -> None:
        # Summing them would describe a transaction nobody makes: in steady
        # state a purchase makes zero model calls.
        outcomes = [
            outcome(Decision.ALLOW, payment_ms=2.0, content_ms=500.0),
            outcome(Decision.ALLOW, payment_ms=4.0, content_ms=700.0),
        ]
        report = summarise(outcomes, Config.C1)

        assert report.payment_path.p50 == 2.0
        assert report.content_path.p50 == 500.0

    def test_a_config_that_screened_nothing_has_an_empty_content_path(self) -> None:
        outcomes = [outcome(Decision.ALLOW, payment_ms=2.0, content_ms=None)]
        assert summarise(outcomes, Config.C1).content_path.samples == 0

    def test_an_empty_config_summarises_without_raising(self) -> None:
        report = summarise([], Config.C2)
        assert report.asr_overall.value is None
        assert report.false_block_rate.value is None


class TestSplits:
    def test_the_halves_are_separable(self) -> None:
        outcomes = [
            outcome(Decision.ALLOW, split="seed"),
            outcome(Decision.BLOCK, split="held_out"),
        ]
        assert len(filter_split(outcomes, "seed")) == 1
        assert len(filter_split(outcomes, "held_out")) == 1

    def test_a_split_can_be_summarised_on_its_own(self) -> None:
        # "Who wrote the attacks?" is answered by reporting the halves
        # separately, so this has to be possible without re-running anything.
        outcomes = [
            outcome(Decision.ALLOW, split="seed"),
            outcome(Decision.BLOCK, split="held_out"),
        ]
        held_out = summarise(filter_split(outcomes, "held_out"), Config.C1)
        assert held_out.asr_overall == Rate(0, 1)
