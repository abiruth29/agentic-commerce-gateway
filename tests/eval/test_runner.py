"""Tests for the runner and the command that publishes its results.

The runner is where an honest harness can quietly become a dishonest one: by
counting an unmeasured cell, by screening on the payment path and reporting
the number anyway, or by emitting a table with no record of what produced it.
Each of those is tested here.
"""

import json

from acg.domain.catalog import CatalogItem
from acg.domain.decision import Decision
from acg.eval import __main__ as cli
from acg.eval.corpus import load_all
from acg.eval.metrics import BENIGN
from acg.eval.pipeline import Config
from acg.eval.runner import counts_by_decision, run, to_dict
from acg.eval.scenario import build
from acg.layer2 import FakeContentScreener
from acg.layer2.port import ScreeningOutcome, ScreeningResult

CORPUS = load_all()


class StubScreener:
    """A screener with a name that is not the fake's, for reportability."""

    def __init__(self) -> None:
        self.calls = 0

    def screen(self, item: CatalogItem) -> ScreeningResult:
        self.calls += 1
        return ScreeningResult(
            content_hash=item.content_hash,
            outcome=ScreeningOutcome.SCREENED,
            decision=Decision.ALLOW,
            reason="stub",
        )


RESULT = run(FakeContentScreener())


class TestEveryCaseIsRun:
    def test_each_case_appears_once_per_config(self) -> None:
        assert len(RESULT.outcomes) == len(CORPUS) * 3

    def test_every_config_covers_the_whole_corpus(self) -> None:
        for config in (Config.C0, Config.C1, Config.C2):
            ids = {o.case_id for o in RESULT.outcomes if o.config is config}
            assert ids == {case.id for case in CORPUS}

    def test_splits_are_carried_through_from_the_corpus(self) -> None:
        by_id = {case.id: case.split for case in CORPUS}
        assert all(o.split == by_id[o.case_id] for o in RESULT.outcomes)


class TestUnmeasuredCellsStayUnmeasured:
    def test_c0_semantic_classes_are_not_measured(self) -> None:
        semantic = [
            o
            for o in RESULT.outcomes
            if o.config is Config.C0 and o.attack_class in {"O1", "O2", "O4"}
        ]
        assert semantic
        assert not any(o.measured for o in semantic)

    def test_c0_deterministic_classes_are_measured(self) -> None:
        deterministic = [
            o
            for o in RESULT.outcomes
            if o.config is Config.C0
            and o.attack_class in {"O3", "I1", "I2", "I3", "I4"}
        ]
        assert deterministic
        assert all(o.measured for o in deterministic)

    def test_the_unmeasured_cells_report_as_such(self) -> None:
        report = RESULT.reports[Config.C0]
        for name in ("O1", "O2", "O4"):
            assert report.asr_by_class[name].value is None

    def test_c0_is_total_on_the_classes_it_does_measure(self) -> None:
        # No guardrail means nothing is refused; this is the baseline the
        # ablation is measured against.
        assert RESULT.reports[Config.C0].asr_overall.value == 1.0

    def test_every_config_after_c0_measures_everything(self) -> None:
        later = [o for o in RESULT.outcomes if o.config is not Config.C0]
        assert all(o.measured for o in later)


class TestTheCacheKeepsScreeningOffThePaymentPath:
    def test_misses_equal_the_number_of_distinct_texts(self) -> None:
        # The corpus has one baseline text plus one per semantic case and per
        # hard negative. A miss count above that would mean the cache key is
        # not the content hash.
        distinct = {build(case.id, case.delta).item.content_hash for case in CORPUS}
        assert RESULT.cache_misses == len(distinct)

    def test_most_screening_calls_are_served_from_cache(self) -> None:
        assert RESULT.cache_hits > RESULT.cache_misses

    def test_a_repeated_text_is_screened_once(self) -> None:
        screener = StubScreener()
        result = run(screener, cases=tuple(c for c in CORPUS if c.id.startswith("O3")))

        # Every O3 case changes only the payee, so all fifteen share one text.
        assert result.cache_misses == 1
        assert screener.calls == 1


class TestTheResultKnowsWhatProducedIt:
    def test_a_fake_run_is_not_reportable(self) -> None:
        assert RESULT.screener == "FakeContentScreener"
        assert RESULT.semantic_numbers_are_reportable is False

    def test_a_real_screener_is_reportable(self) -> None:
        assert run(StubScreener(), cases=CORPUS[:5]).semantic_numbers_are_reportable

    def test_the_flag_reaches_the_published_file(self) -> None:
        payload = to_dict(RESULT)
        assert payload["screener"] == "FakeContentScreener"
        assert payload["semantic_numbers_are_reportable"] is False


class TestTheShapeTheDesignPredicted:
    """The ablation, asserted rather than eyeballed."""

    def test_layer_1_zeroes_the_classes_whose_rules_are_built(self) -> None:
        report = RESULT.reports[Config.C1]
        for name in ("O3", "I1", "I3", "I4"):
            assert report.asr_by_class[name].value == 0.0

    def test_layer_1_does_not_zero_i2(self) -> None:
        # The known gap: the four split-order cases walk through.
        rate = RESULT.reports[Config.C1].asr_by_class["I2"]
        assert rate.numerator == 4
        assert rate.denominator == 15

    def test_layer_1_stops_none_of_the_semantic_classes(self) -> None:
        report = RESULT.reports[Config.C1]
        for name in ("O1", "O2", "O4"):
            assert report.asr_by_class[name].value == 1.0

    def test_c2_is_never_worse_than_c1_on_any_class(self) -> None:
        c1, c2 = RESULT.reports[Config.C1], RESULT.reports[Config.C2]
        for name, rate in c1.asr_by_class.items():
            assert c2.asr_by_class[name].value <= rate.value

    def test_layer_1_falsely_blocks_nothing(self) -> None:
        # Deterministic, so any false block here is a rule bug rather than a
        # judgement call.
        assert RESULT.reports[Config.C1].false_block_rate.value == 0.0

    def test_the_decision_counts_add_up(self) -> None:
        counts = counts_by_decision(RESULT, Config.C1)
        assert sum(counts.values()) == 120
        assert counts["ALLOW"] == 49


class TestThePublishedFile:
    def test_every_outcome_is_written_out(self) -> None:
        # A results file carrying only percentages asks to be believed. This
        # one carries every case so a reader can recompute the headline.
        payload = to_dict(RESULT)
        assert len(payload["outcomes"]) == len(CORPUS) * 3

    def test_rates_carry_their_counts(self) -> None:
        cell = to_dict(RESULT)["configs"]["C1"]["asr_by_class"]["I2"]
        assert cell == {"percent": 26.7, "numerator": 4, "denominator": 15}

    def test_an_unmeasured_cell_serialises_as_null(self) -> None:
        cell = to_dict(RESULT)["configs"]["C0"]["asr_by_class"]["O1"]
        assert cell["percent"] is None
        assert cell["denominator"] == 0

    def test_the_file_is_json_serialisable(self) -> None:
        json.dumps(to_dict(RESULT))


class TestTheCommand:
    def test_it_runs_and_writes_a_file(self, tmp_path, capsys) -> None:  # noqa: ANN001
        out = tmp_path / "results.json"
        assert cli.main(["--out", str(out)]) == 0

        payload = json.loads(out.read_text())
        assert payload["version"] == 1
        assert len(payload["outcomes"]) == len(CORPUS) * 3

    def test_it_prints_the_ablation_table(self, tmp_path, capsys) -> None:  # noqa: ANN001
        cli.main(["--out", str(tmp_path / "r.json")])
        printed = capsys.readouterr().out

        assert "Attack success rate by class" in printed
        assert "False block rate" in printed
        assert "Added latency by path" in printed

    def test_a_mock_run_prints_its_own_disclaimer(self, tmp_path, capsys) -> None:  # noqa: ANN001
        # The disclaimer is emitted by the run rather than remembered by
        # whoever writes the page.
        cli.main(["--out", str(tmp_path / "r.json")])
        printed = capsys.readouterr().out

        assert "NOT reportable" in printed
        assert "marker phrases" in printed

    def test_it_states_the_limitations_without_being_asked(
        self, tmp_path, capsys
    ) -> None:  # noqa: ANN001
        cli.main(["--out", str(tmp_path / "r.json")])
        printed = capsys.readouterr().out

        assert "Limitations" in printed
        assert "coupon_stacking" in printed
        assert "unmeasured, not zero" in printed

    def test_the_predictions_are_reported_with_the_numbers(
        self, tmp_path, capsys
    ) -> None:  # noqa: ANN001
        out = tmp_path / "r.json"
        cli.main(["--out", str(out)])

        payload = json.loads(out.read_text())
        assert len(payload["predictions"]) == 7
        assert {p["id"] for p in payload["predictions"]} == {
            f"P{n}" for n in range(1, 8)
        }

    def test_a_failed_prediction_carries_its_diagnosis(self, tmp_path) -> None:  # noqa: ANN001
        out = tmp_path / "r.json"
        cli.main(["--out", str(out)])

        payload = json.loads(out.read_text())
        failed = [p for p in payload["predictions"] if p["outcome"] == "FAILED"]
        assert failed
        assert all(len(p["on_failure"]) > 80 for p in failed)

    def test_a_single_split_can_be_run_alone(self, tmp_path) -> None:  # noqa: ANN001
        out = tmp_path / "r.json"
        cli.main(["--split", "held_out", "--out", str(out)])

        payload = json.loads(out.read_text())
        assert payload["split"] == "held_out"
        assert all(o["split"] == "held_out" for o in payload["outcomes"])
        assert len(payload["outcomes"]) == 90 * 3

    def test_the_two_splits_partition_the_corpus(self, tmp_path) -> None:  # noqa: ANN001
        seed = tmp_path / "seed.json"
        held = tmp_path / "held.json"
        cli.main(["--split", "seed", "--out", str(seed)])
        cli.main(["--split", "held_out", "--out", str(held)])

        seed_ids = {o["case_id"] for o in json.loads(seed.read_text())["outcomes"]}
        held_ids = {o["case_id"] for o in json.loads(held.read_text())["outcomes"]}

        assert seed_ids.isdisjoint(held_ids)
        assert len(seed_ids) + len(held_ids) == len(CORPUS)


class TestBenignFlowsAreNotCountedAsAttacks:
    def test_no_benign_case_enters_a_class_rate(self) -> None:
        for config in (Config.C0, Config.C1, Config.C2):
            assert BENIGN not in RESULT.reports[config].asr_by_class

    def test_the_attack_denominator_is_the_attack_count(self) -> None:
        assert RESULT.reports[Config.C1].asr_overall.denominator == 120

    def test_the_benign_denominator_is_the_benign_count(self) -> None:
        assert RESULT.reports[Config.C1].false_block_rate.denominator == 60


class DeadScreener:
    """A real-looking screener whose model never answers.

    Named so it is not mistaken for the fake: this is what a run against a
    retired model, a bad key or an exhausted quota looks like from the
    runner's side.
    """

    def screen(self, item: CatalogItem) -> ScreeningResult:
        from acg.layer2.port import abstention

        return abstention(item.content_hash, "screening was unavailable")


class SometimesDeadScreener:
    """Answers every text but one."""

    def __init__(self, dead_hash: str) -> None:
        self.dead_hash = dead_hash

    def screen(self, item: CatalogItem) -> ScreeningResult:
        from acg.layer2.port import abstention

        if item.content_hash == self.dead_hash:
            return abstention(item.content_hash, "screening was unavailable")
        return StubScreener().screen(item)


class TestAnOutageCannotMasqueradeAsAResult:
    """The failure this guards against was real, and would have been silent.

    The default model was retired. Every call failed, every failure
    abstained, every abstention carried ALLOW, C2 became a copy of C1 — and
    because the screener was the real one, the run would have been marked
    reportable and published as the model's measured result.
    """

    def test_a_run_where_the_model_never_answered_is_not_reportable(self) -> None:
        result = run(DeadScreener())

        assert result.screening_abstentions == len(CORPUS)
        assert result.semantic_numbers_are_reportable is False
        assert "did not answer" in result.not_reportable_because

    def test_one_abstention_is_enough_to_withhold_the_figures(self) -> None:
        dead = build(CORPUS[0].id, CORPUS[0].delta).item.content_hash
        result = run(SometimesDeadScreener(dead), cases=CORPUS[:20])

        assert result.screening_abstentions >= 1
        assert result.semantic_numbers_are_reportable is False

    def test_a_clean_real_run_is_reportable(self) -> None:
        result = run(StubScreener(), cases=CORPUS[:20])

        assert result.screening_abstentions == 0
        assert result.not_reportable_because is None
        assert result.semantic_numbers_are_reportable is True

    def test_only_c2_abstentions_are_counted(self) -> None:
        # C0 and C1 never ask Layer 2 anything, so they cannot abstain.
        result = run(DeadScreener(), configs=(Config.C0, Config.C1))
        assert result.screening_abstentions == 0

    def test_the_reason_reaches_the_published_file(self) -> None:
        payload = to_dict(run(DeadScreener(), cases=CORPUS[:5]))

        assert payload["semantic_numbers_are_reportable"] is False
        assert payload["screening_abstentions"] == 5
        assert "did not answer" in payload["not_reportable_because"]

    def test_a_fake_run_still_says_it_was_the_fake(self) -> None:
        assert "fake screener" in RESULT.not_reportable_because

    def test_the_cache_wrapper_does_not_hide_the_screener_name(self) -> None:
        from acg.layer2 import CachingScreener

        result = run(CachingScreener(StubScreener()), cases=CORPUS[:3])
        assert result.screener == "StubScreener"
