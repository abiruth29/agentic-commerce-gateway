"""Tests that the published corpus is the corpus the design committed to.

A corpus degrades silently. A case whose delta stops applying still loads,
still runs and still contributes a row — it simply measures nothing, and it
does so in the direction that makes the system look good. Almost every test
here is aimed at that: that the counts are what was promised, that the splits
are even, and above all that every attack case actually attacks something.

That last one is the important test in this file.
`TestEveryAttackActuallyAttacks` builds each case and asserts the world it
produces differs from the benign baseline, so a case that has quietly become
a no-op cannot sit in the corpus inflating a detection rate.
"""

from collections import Counter

import pytest

from acg.domain.decision import Decision
from acg.eval.corpus import (
    ATTACK_CLASSES,
    CASES_PER_CLASS,
    SPLITS,
    Case,
    load_all,
    load_attacks,
    load_benign,
)
from acg.eval.metrics import BENIGN
from acg.eval.pipeline import Config, decide
from acg.eval.scenario import CaseDelta, build
from acg.layer1 import ALL_RULES

ATTACKS = load_attacks()
BENIGN_CASES = load_benign()


class TestCorpusDiscipline:
    def test_there_are_one_hundred_and_twenty_attacks(self) -> None:
        assert len(ATTACKS) == len(ATTACK_CLASSES) * CASES_PER_CLASS == 120

    def test_every_class_has_fifteen(self) -> None:
        counts = Counter(case.attack_class for case in ATTACKS)
        assert counts == {name: CASES_PER_CLASS for name in ATTACK_CLASSES}

    def test_the_attack_split_is_even(self) -> None:
        # The held-out half is the answer to "who wrote the attacks?". An
        # uneven split would make the two halves not comparable.
        counts = Counter(case.split for case in ATTACKS)
        assert counts["seed"] == counts["held_out"] == 60

    def test_there_are_sixty_benign_flows(self) -> None:
        assert len(BENIGN_CASES) == 60

    def test_the_benign_split_is_even(self) -> None:
        counts = Counter(case.split for case in BENIGN_CASES)
        assert counts["seed"] == counts["held_out"] == 30

    def test_half_the_benign_flows_are_hard_negatives(self) -> None:
        assert sum(1 for case in BENIGN_CASES if case.hard_negative) == 30

    def test_hard_negatives_are_spread_across_both_splits(self) -> None:
        # All the hard ones in one half would make the halves measure
        # different things and the split comparison meaningless.
        counts = Counter(c.split for c in BENIGN_CASES if c.hard_negative)
        assert counts["seed"] == counts["held_out"] == 15

    @pytest.mark.parametrize("case", load_all(), ids=lambda c: c.id)
    def test_every_case_declares_a_known_split(self, case: Case) -> None:
        assert case.split in SPLITS

    def test_every_id_is_unique(self) -> None:
        ids = [case.id for case in load_all()]
        assert len(ids) == len(set(ids))

    @pytest.mark.parametrize("case", load_all(), ids=lambda c: c.id)
    def test_every_case_explains_itself(self, case: Case) -> None:
        # The corpus is published to be read. A case with no summary is a
        # delta a reviewer has to reverse-engineer.
        assert len(case.summary) > 15

    def test_benign_flows_are_not_an_attack_class(self) -> None:
        assert all(case.attack_class == BENIGN for case in BENIGN_CASES)
        assert all(not case.is_attack for case in BENIGN_CASES)


class TestEveryAttackActuallyAttacks:
    """The test this file exists for.

    A delta that no longer applies produces a case the gateway allows for the
    wrong reason. Run with no guardrail, every attack must differ from the
    benign baseline in the built world.
    """

    @pytest.mark.parametrize("case", ATTACKS, ids=lambda c: c.id)
    def test_the_case_changes_the_world(self, case: Case) -> None:
        baseline = build("baseline", CaseDelta())
        trial = build(case.id, case.delta)

        differs = (
            trial.request.payee_id != baseline.request.payee_id
            or trial.request.lines != baseline.request.lines
            or trial.request.quoted_total != baseline.request.quoted_total
            or trial.request.created_at != baseline.request.created_at
            or trial.item != baseline.item
            or trial.context.mandate != baseline.context.mandate
            or trial.context.history != baseline.context.history
        )
        assert differs, f"{case.id} builds the baseline world and tests nothing"

    @pytest.mark.parametrize("case", ATTACKS, ids=lambda c: c.id)
    def test_the_delta_is_not_empty(self, case: Case) -> None:
        assert case.delta.model_dump(exclude_defaults=True)


class TestTheSemanticCasesAreSemantic:
    """O1, O2 and O4 must be caught by reading text, or they are mislabelled.

    A semantic case that also trips a deterministic rule would be credited to
    Layer 2 in the write-up while actually being stopped by Layer 1, which
    would overstate the model's contribution — the exact number this project
    is trying to establish honestly.
    """

    @pytest.mark.parametrize(
        "case",
        [c for c in ATTACKS if c.attack_class in {"O1", "O2", "O4"}],
        ids=lambda c: c.id,
    )
    def test_layer_1_alone_does_not_stop_it(self, case: Case) -> None:
        verdict = decide(build(case.id, case.delta), Config.C1, ALL_RULES)
        assert verdict.decision is Decision.ALLOW

    @pytest.mark.parametrize(
        "case",
        [c for c in ATTACKS if c.attack_class in {"O1", "O2", "O4"}],
        ids=lambda c: c.id,
    )
    def test_it_changes_only_the_untrusted_text(self, case: Case) -> None:
        touched = set(case.delta.model_dump(exclude_defaults=True))
        assert touched <= {"item_title", "item_description"}


class TestTheDeterministicCasesAreDeterministic:
    """O3, I1, I3 and I4 must be stopped by Layer 1 alone.

    I2 is excluded: its split-order cases are the known gap, and they are
    expected to walk straight through.
    """

    @pytest.mark.parametrize(
        "case",
        [c for c in ATTACKS if c.attack_class in {"O3", "I1", "I3", "I4"}],
        ids=lambda c: c.id,
    )
    def test_layer_1_stops_it_without_a_model(self, case: Case) -> None:
        verdict = decide(build(case.id, case.delta), Config.C1, ALL_RULES)
        assert verdict.decision is not Decision.ALLOW
        assert verdict.stopped_by == "layer1"

    @pytest.mark.parametrize(
        "case",
        [c for c in ATTACKS if c.attack_class in {"O3", "I1", "I3", "I4"}],
        ids=lambda c: c.id,
    )
    def test_the_right_class_of_rule_fires(self, case: Case) -> None:
        # A case blocked by the correct verdict for the wrong reason would
        # credit the wrong rule in the per-class breakdown.
        verdict = decide(build(case.id, case.delta), Config.C1, ALL_RULES)
        assert verdict.layer1 is not None
        firing = {f.attack_class for f in verdict.layer1.blocking}
        assert case.attack_class in firing


class TestTheKnownGap:
    """I2's split-order cases are expected to get through, and must.

    If these ever start being blocked the gap has been closed, which is good
    news that this test should be updated to record — but silently passing a
    corpus that no longer exercises the gap would hide it instead.
    """

    def test_the_structuring_cases_walk_through_layer_1(self) -> None:
        structuring = [
            c for c in ATTACKS if c.attack_class == "I2" and "Split order" in c.summary
        ]
        assert len(structuring) == 4

        for case in structuring:
            verdict = decide(build(case.id, case.delta), Config.C1, ALL_RULES)
            assert verdict.decision is Decision.ALLOW, (
                f"{case.id} is now blocked; the structuring gap may have been "
                "closed, and this test should record that rather than fail"
            )

    def test_the_structuring_cases_do_not_trip_velocity(self) -> None:
        # Four priors, not five. If they tripped velocity they would look
        # caught, I2 would read 0%, and the gap would become invisible.
        structuring = [
            c for c in ATTACKS if c.attack_class == "I2" and "Split order" in c.summary
        ]
        for case in structuring:
            assert case.delta.prior_allowed_purchases < 5


class TestTheBenignFlowsAreBenign:
    @pytest.mark.parametrize("case", BENIGN_CASES, ids=lambda c: c.id)
    def test_layer_1_allows_every_benign_flow(self, case: Case) -> None:
        # Layer 1 is deterministic, so any false block here is a rule bug
        # rather than a judgement call, and should never reach the page as a
        # measured false-positive rate.
        verdict = decide(build(case.id, case.delta), Config.C1, ALL_RULES)
        assert verdict.decision is Decision.ALLOW, case.summary

    @pytest.mark.parametrize(
        "case", [c for c in BENIGN_CASES if c.hard_negative], ids=lambda c: c.id
    )
    def test_every_hard_negative_carries_real_copy(self, case: Case) -> None:
        touched = case.delta.model_dump(exclude_defaults=True)
        assert "item_description" in touched
        assert len(touched["item_description"]) > 40


class TestTheLoaderRefusesDrift:
    def test_an_unknown_lever_fails_at_load(self, tmp_path) -> None:  # noqa: ANN001
        # The failure mode this prevents: a renamed field turns every case
        # using it into a no-op that the corpus still counts.
        import json

        from acg.eval.corpus import _load_file

        path = tmp_path / "attacks.json"
        path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "cases": [
                        {
                            "id": "X-01",
                            "attack_class": "O3",
                            "split": "seed",
                            "summary": "a lever that no longer exists",
                            "delta": {"payee": "pay_ATTACKER"},
                        }
                    ],
                }
            )
        )
        with pytest.raises(Exception, match="payee"):
            _load_file(path)

    def test_an_unsupported_version_is_refused(self, tmp_path) -> None:  # noqa: ANN001
        import json

        from acg.eval.corpus import _load_file

        path = tmp_path / "attacks.json"
        path.write_text(json.dumps({"version": 99, "cases": []}))
        with pytest.raises(ValueError, match="unsupported corpus version"):
            _load_file(path)
