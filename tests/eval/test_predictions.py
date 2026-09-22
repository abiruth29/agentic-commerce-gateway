"""Tests for the predictions themselves.

A prediction that cannot fail is not a prediction. Every case below feeds the
checker numbers that should make a prediction fail and asserts that it does —
otherwise the "held" column on the results page is decoration with extra
steps.
"""

import pytest

from acg.eval.metrics import ConfigReport, LatencyProfile, Rate
from acg.eval.pipeline import Config
from acg.eval.predictions import (
    ALL_PREDICTIONS,
    I2_HAS_A_KNOWN_GAP,
    LAYER_1_CANNOT_SEE_THE_SEMANTIC_CLASSES,
    LAYER_1_ZEROES_THE_DETERMINISTIC_CLASSES,
    LAYER_2_COSTS_SOMETHING,
    LAYER_2_IS_WHAT_MOVES_THE_SEMANTIC_CLASSES,
    LAYER_2_NEVER_LOOSENS_LAYER_1,
    PAYMENT_PATH_IS_UNCHANGED_BY_LAYER_2,
    Prediction,
    check_all,
)


def report(
    config: Config,
    asr: dict[str, float],
    fbr: float = 0.0,
    payment_p95: float = 1.0,
) -> ConfigReport:
    """A report with the given per-class rates, as fifteenths."""
    return ConfigReport(
        config=config,
        asr_by_class={name: Rate(round(value * 15), 15) for name, value in asr.items()},
        asr_overall=Rate(
            sum(round(value * 15) for value in asr.values()), 15 * len(asr)
        ),
        false_block_rate=Rate(round(fbr * 60), 60),
        payment_path=LatencyProfile(15, payment_p95 / 2, payment_p95),
        content_path=LatencyProfile(0, None, None),
    )


PERFECT_L1 = {"O3": 0.0, "I1": 0.0, "I3": 0.0, "I4": 0.0, "I2": 0.2}
BLIND_L1 = {"O1": 1.0, "O2": 1.0, "O4": 1.0}
SCREENED_L2 = {"O1": 0.2, "O2": 0.2, "O4": 0.2}


def expected_reports() -> dict[Config, ConfigReport]:
    """The shape the design predicts, used as the baseline to perturb."""
    return {
        Config.C1: report(Config.C1, PERFECT_L1 | BLIND_L1, fbr=0.02, payment_p95=1.0),
        Config.C2: report(
            Config.C2, PERFECT_L1 | SCREENED_L2, fbr=0.05, payment_p95=1.5
        ),
    }


class TestThePredictionsHoldOnTheExpectedShape:
    @pytest.mark.parametrize("prediction", ALL_PREDICTIONS, ids=lambda p: p.id)
    def test_each_prediction_holds(self, prediction: Prediction) -> None:
        assert prediction.predicate(expected_reports()) is True

    def test_check_all_reports_every_prediction(self) -> None:
        outcomes = check_all(expected_reports())
        assert len(outcomes) == len(ALL_PREDICTIONS)
        assert all(o.held is True for o in outcomes)
        assert all(o.label == "held" for o in outcomes)


class TestEachPredictionCanActuallyFail:
    def test_p1_fails_when_the_payee_check_lets_one_through(self) -> None:
        reports = expected_reports()
        reports[Config.C1] = report(Config.C1, PERFECT_L1 | BLIND_L1 | {"O3": 1 / 15})
        assert LAYER_1_ZEROES_THE_DETERMINISTIC_CLASSES.predicate(reports) is False

    def test_p2_fails_when_i2_reads_zero(self) -> None:
        # Not a success: it would mean the corpus stopped exercising the
        # three unbuilt rules.
        reports = expected_reports()
        reports[Config.C1] = report(Config.C1, PERFECT_L1 | BLIND_L1 | {"I2": 0.0})
        assert I2_HAS_A_KNOWN_GAP.predicate(reports) is False

    def test_p3_fails_when_layer_1_appears_to_stop_injections(self) -> None:
        reports = expected_reports()
        reports[Config.C1] = report(
            Config.C1, PERFECT_L1 | {"O1": 0.0, "O2": 0.0, "O4": 0.0}
        )
        assert LAYER_1_CANNOT_SEE_THE_SEMANTIC_CLASSES.predicate(reports) is False

    def test_p4_fails_when_the_model_changes_nothing(self) -> None:
        reports = expected_reports()
        reports[Config.C2] = report(Config.C2, PERFECT_L1 | BLIND_L1, fbr=0.05)
        assert LAYER_2_IS_WHAT_MOVES_THE_SEMANTIC_CLASSES.predicate(reports) is False

    def test_p5_fails_when_the_benign_set_has_no_hard_negatives(self) -> None:
        reports = expected_reports()
        reports[Config.C2] = report(Config.C2, PERFECT_L1 | SCREENED_L2, fbr=0.02)
        assert LAYER_2_COSTS_SOMETHING.predicate(reports) is False

    def test_p6_fails_when_c2_is_more_permissive_on_any_class(self) -> None:
        reports = expected_reports()
        reports[Config.C2] = report(
            Config.C2, PERFECT_L1 | SCREENED_L2 | {"O3": 1 / 15}
        )
        assert LAYER_2_NEVER_LOOSENS_LAYER_1.predicate(reports) is False

    def test_p7_fails_when_screening_lands_on_the_payment_path(self) -> None:
        reports = expected_reports()
        reports[Config.C2] = report(
            Config.C2, PERFECT_L1 | SCREENED_L2, fbr=0.05, payment_p95=900.0
        )
        assert PAYMENT_PATH_IS_UNCHANGED_BY_LAYER_2.predicate(reports) is False


class TestAnUnevaluatedPredictionIsNotAPass:
    @pytest.mark.parametrize("prediction", ALL_PREDICTIONS, ids=lambda p: p.id)
    def test_a_missing_config_yields_none_not_true(
        self, prediction: Prediction
    ) -> None:
        assert prediction.predicate({}) is not True

    def test_an_unevaluated_outcome_is_labelled_as_such(self) -> None:
        outcomes = check_all({})
        assert all(o.held is not True for o in outcomes)
        assert all(o.label == "not evaluated" for o in outcomes)

    def test_a_class_with_no_measurement_does_not_count_as_zero(self) -> None:
        # An unmeasured cell must not be read as a perfect defence.
        reports = expected_reports()
        reports[Config.C1] = report(Config.C1, {"O3": 0.0})
        assert LAYER_1_ZEROES_THE_DETERMINISTIC_CLASSES.predicate(reports) is None


class TestPredictionsAreWellFormed:
    def test_ids_are_unique(self) -> None:
        ids = [p.id for p in ALL_PREDICTIONS]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("prediction", ALL_PREDICTIONS, ids=lambda p: p.id)
    def test_each_carries_a_diagnosis_not_just_a_claim(
        self, prediction: Prediction
    ) -> None:
        # The on_failure text is the reason to write predictions down at all:
        # it turns a failed number into a place to look.
        assert len(prediction.on_failure) > 80
        assert prediction.statement
