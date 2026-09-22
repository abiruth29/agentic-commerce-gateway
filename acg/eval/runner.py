"""Running the corpus through each configuration and writing the results down.

Two things here are worth explaining rather than reading off the code.

**Which screener produced the numbers is recorded, and it matters.** The fake
screener is a substring matcher over nine marker phrases. It exists so the
plumbing tests and MOCK_MODE are deterministic, and it is emphatically not fit
to produce a semantic detection rate: any O1/O2/O4 figure measured against it
is measuring the marker list. The corpus was deliberately written in ordinary
attack language rather than in the fake's marker phrases, so a fake run
produces a *poor* semantic number rather than a flattering one — but poor or
not, it is not the figure to report. Results carry `screener` so a table can
never be quoted without it.

**C0's semantic cells are recorded as unmeasured.** Whether an injected
instruction actually moves money depends on whether the buyer agent obeys it,
and the harness cannot determine that on the gateway's behalf. Those cells
carry `measured=False`, which keeps them out of every rate rather than
counting them as defended.

Latency is measured per path with `perf_counter`. The payment path is the
Layer 1 fold plus the join against an already-cached screening verdict — what
a purchase costs in steady state. The content path is the screening call
itself, which happens once per version of the text. They are never summed.
"""

import time
from dataclasses import dataclass, field
from typing import Final

from acg.domain.decision import Decision
from acg.eval.corpus import Case, load_all
from acg.eval.metrics import BENIGN, ConfigReport, Outcome, summarise
from acg.eval.pipeline import Config, decide
from acg.eval.scenario import build
from acg.layer1 import ALL_RULES
from acg.layer1.rules import Rule
from acg.layer2 import CachingScreener
from acg.layer2.port import ContentScreener

SEMANTIC_CLASSES: Final = frozenset({"O1", "O2", "O4"})


@dataclass(frozen=True)
class RunResult:
    """Everything one full run produced."""

    outcomes: list[Outcome]
    reports: dict[Config, ConfigReport]
    screener: str
    """What produced the Layer 2 verdicts. See the module docstring."""

    cache_hits: int = 0
    cache_misses: int = 0

    @property
    def semantic_numbers_are_reportable(self) -> bool:
        """Whether this run's O1/O2/O4 figures may be quoted.

        False for a fake-screener run. The check is a property of the result
        rather than a note in a README, so a table generated from a fake run
        carries its own disclaimer instead of relying on whoever writes the
        page to remember.
        """
        return self.screener not in {"FakeContentScreener"}


@dataclass
class _Timer:
    """Elapsed milliseconds, measured with a monotonic clock."""

    started: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started) * 1000.0


def _is_unmeasured(config: Config, case: Case) -> bool:
    """Whether this cell is reported rather than measured.

    Only C0 on the semantic classes: the answer depends on a buyer agent's
    behaviour, not on anything this gateway does.
    """
    return config is Config.C0 and case.attack_class in SEMANTIC_CLASSES


def run_case(
    case: Case,
    config: Config,
    rules: tuple[Rule, ...],
    screener: ContentScreener | None,
) -> Outcome:
    """Run one corpus case under one configuration, timing both paths."""
    trial = build(case.id, case.delta)

    content_ms: float | None = None
    if config is Config.C2 and screener is not None:
        # Warm the content path first and time it on its own. This is the cost
        # paid once per version of the text, when content is served.
        content_timer = _Timer()
        screener.screen(trial.item)
        content_ms = content_timer.elapsed_ms()

    # The payment path: Layer 1 plus a join against a verdict that is now
    # cached. This is what a purchase costs in steady state.
    payment_timer = _Timer()
    verdict = decide(trial, config, rules, screener)
    payment_ms = payment_timer.elapsed_ms()

    return Outcome(
        case_id=case.id,
        attack_class=case.attack_class,
        split=case.split,
        config=config,
        decision=verdict.decision,
        stopped_by=verdict.stopped_by,
        payment_path_ms=payment_ms,
        content_path_ms=content_ms,
        measured=not _is_unmeasured(config, case),
    )


def run(
    screener: ContentScreener,
    cases: tuple[Case, ...] | None = None,
    rules: tuple[Rule, ...] = ALL_RULES,
    configs: tuple[Config, ...] = (Config.C0, Config.C1, Config.C2),
) -> RunResult:
    """Run the whole corpus through every configuration.

    Args:
        screener: the Layer 2 screener. Wrapped in a cache here rather than
            by the caller, because the cache is the mechanism that keeps
            screening off the payment path and a run that skipped it would
            measure a system nobody deploys.
        cases: the corpus. Defaults to the published one.
        rules: the Layer 1 rules to enforce.
        configs: which columns to produce.

    Returns:
        Every outcome, the per-configuration reports, and what produced the
        semantic verdicts.
    """
    corpus = load_all() if cases is None else cases
    cached = CachingScreener(screener)

    outcomes = [
        run_case(case, config, rules, cached) for config in configs for case in corpus
    ]

    return RunResult(
        outcomes=outcomes,
        reports={config: summarise(outcomes, config) for config in configs},
        screener=type(screener).__name__,
        cache_hits=cached.hits,
        cache_misses=cached.misses,
    )


def to_dict(result: RunResult) -> dict:
    """The results file, as published.

    Written out whole — every case's decision, not only the aggregates — so
    that a reader who distrusts a headline number can recompute it. A results
    file that only carries percentages asks to be believed.
    """
    return {
        "version": 1,
        "screener": result.screener,
        "semantic_numbers_are_reportable": result.semantic_numbers_are_reportable,
        "cache": {"hits": result.cache_hits, "misses": result.cache_misses},
        "configs": {
            config.value: _report_to_dict(report)
            for config, report in result.reports.items()
        },
        "outcomes": [
            {
                "case_id": o.case_id,
                "attack_class": o.attack_class,
                "split": o.split,
                "config": o.config.value,
                "decision": o.decision.name,
                "stopped_by": o.stopped_by,
                "measured": o.measured,
            }
            for o in result.outcomes
        ],
    }


def _report_to_dict(report: ConfigReport) -> dict:
    return {
        "asr_by_class": {
            name: {
                "percent": rate.percent,
                "numerator": rate.numerator,
                "denominator": rate.denominator,
            }
            for name, rate in report.asr_by_class.items()
        },
        "asr_overall": {
            "percent": report.asr_overall.percent,
            "numerator": report.asr_overall.numerator,
            "denominator": report.asr_overall.denominator,
        },
        "false_block_rate": {
            "percent": report.false_block_rate.percent,
            "numerator": report.false_block_rate.numerator,
            "denominator": report.false_block_rate.denominator,
        },
        "falsely_blocked": {
            "percent": report.falsely_blocked.percent,
            "numerator": report.falsely_blocked.numerator,
        },
        "falsely_reviewed": {
            "percent": report.falsely_reviewed.percent,
            "numerator": report.falsely_reviewed.numerator,
        },
        "payment_path_ms": {
            "samples": report.payment_path.samples,
            "p50": _round(report.payment_path.p50),
            "p95": _round(report.payment_path.p95),
        },
        "content_path_ms": {
            "samples": report.content_path.samples,
            "p50": _round(report.content_path.p50),
            "p95": _round(report.content_path.p95),
        },
    }


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def counts_by_decision(result: RunResult, config: Config) -> dict[str, int]:
    """How many cases drew each decision. Useful for a sanity read."""
    counts = {decision.name: 0 for decision in Decision}
    for outcome in result.outcomes:
        if outcome.config is config and outcome.attack_class != BENIGN:
            counts[outcome.decision.name] += 1
    return counts
