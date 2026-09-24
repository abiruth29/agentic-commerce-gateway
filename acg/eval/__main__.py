"""`python -m acg.eval` — run the corpus and write the results down.

One command, no arguments needed, so "reproduce this" is a line someone can
paste rather than a procedure they have to follow.

Which screener it uses follows the same MOCK_MODE switch the rest of the
system uses, so there is one answer to "is this talking to a real model?"
across the whole project. A mock run prints its own disclaimer over the
semantic rows rather than relying on the reader to know.
"""

import argparse
import json
import sys
from pathlib import Path

from acg.eval.metrics import ConfigReport
from acg.eval.pipeline import Config
from acg.eval.predictions import UNREPRESENTABLE_RULES, check_all
from acg.eval.runner import RunResult, run, to_dict
from acg.layer2 import build_content_screener

WEB_DIR = Path(__file__).resolve().parent.parent.parent / "web"
"""The results file is written where the page serves it from.

One artifact rather than a canonical copy and a published copy that can
drift apart. It also means the table the page shows is a static file on a
CDN: a reviewer sees the numbers before any Python process wakes up.
"""

CLASS_ORDER = ("O1", "O2", "O3", "O4", "I1", "I2", "I3", "I4")
SEMANTIC = {"O1", "O2", "O4"}


def format_table(result: RunResult) -> str:
    """The ablation table, per class, across the three configurations."""
    lines = [
        "",
        "Attack success rate by class (lower is better)",
        "",
        f"  {'class':<8}{'C0':>16}{'C1':>16}{'C2':>16}",
        f"  {'-' * 54}",
    ]

    for name in CLASS_ORDER:
        cells = []
        for config in (Config.C0, Config.C1, Config.C2):
            rate = result.reports[config].asr_by_class.get(name)
            cells.append("n/a" if rate is None else str(rate))
        marker = (
            " *"
            if name in SEMANTIC and not result.semantic_numbers_are_reportable
            else ""
        )
        lines.append(f"  {name:<8}{cells[0]:>16}{cells[1]:>16}{cells[2]:>16}{marker}")

    lines.append(f"  {'-' * 54}")
    overall = [
        str(result.reports[c].asr_overall) for c in (Config.C0, Config.C1, Config.C2)
    ]
    lines.append(f"  {'all':<8}{overall[0]:>16}{overall[1]:>16}{overall[2]:>16}")
    return "\n".join(lines)


def format_false_blocks(result: RunResult) -> str:
    lines = ["", "False block rate on 60 benign flows (30 of them hard negatives)", ""]
    for config in (Config.C0, Config.C1, Config.C2):
        report = result.reports[config]
        lines.append(
            f"  {config.value}: {report.false_block_rate}"
            f"   [blocked {report.falsely_blocked.numerator}, "
            f"reviewed {report.falsely_reviewed.numerator}]"
        )
    return "\n".join(lines)


def format_latency(result: RunResult) -> str:
    lines = ["", "Added latency by path, milliseconds (never summed)", ""]
    for config in (Config.C1, Config.C2):
        report: ConfigReport = result.reports[config]
        lines.append(
            f"  {config.value} payment path   p50 {_ms(report.payment_path.p50)}"
            f"   p95 {_ms(report.payment_path.p95)}   n={report.payment_path.samples}"
        )
        if report.content_path.samples:
            content = report.content_path
            lines.append(
                f"  {config.value} content path   p50 {_ms(content.p50)}"
                f"   p95 {_ms(content.p95)}   n={content.samples}"
            )
    lines.append("")
    lines.append(
        f"  screening cache: {result.cache_hits} hits, {result.cache_misses} misses "
        "— a purchase costs zero model calls once the text has been seen"
    )
    return "\n".join(lines)


def format_predictions(result: RunResult) -> str:
    lines = ["", "Predictions, committed before the corpus existed", ""]
    for outcome in check_all(result.reports):
        prediction = outcome.prediction
        lines.append(f"  {prediction.id} {outcome.label:<14} {prediction.statement}")
        if outcome.held is False:
            lines.append(f"     -> {outcome.prediction.on_failure}")
    return "\n".join(lines)


def format_limitations(result: RunResult) -> str:
    lines = ["", "Limitations, stated here rather than left to be found", ""]

    if not result.semantic_numbers_are_reportable:
        lines.append(
            "  * The O1/O2/O4 rows above are NOT reportable: "
            f"{result.not_reportable_because}."
        )
    lines.append(
        "  * C0's semantic cells are unmeasured, not zero. Whether an injection "
        "moves\n    money depends on whether the buyer agent obeys it, which "
        "this harness cannot\n    determine on the gateway's behalf."
    )
    lines.append(
        "  * I2 is short three designed rules. Split-order structuring is "
        "unbuilt and the\n    corpus exercises it, which is why I2 does not "
        f"zero. {UNREPRESENTABLE_RULES[0]} and\n    {UNREPRESENTABLE_RULES[1]} "
        "cannot be expressed at all — the domain has no coupon\n    and no "
        "order lifecycle — so they are absent rather than failing, and I2's\n"
        "    number understates the real gap."
    )
    return "\n".join(lines)


def _ms(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m acg.eval",
        description="Run the attack corpus through C0, C1 and C2.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=WEB_DIR / "results.json",
        help="where to write the results file",
    )
    parser.add_argument(
        "--split",
        choices=("seed", "held_out", "all"),
        default="all",
        help="which half of the corpus to run",
    )
    args = parser.parse_args(argv)

    from acg.eval.corpus import load_all

    cases = load_all()
    if args.split != "all":
        cases = tuple(case for case in cases if case.split == args.split)

    # Five attempts with backoff, so a free-tier rate limit is waited out
    # rather than turned into abstentions. Irrelevant to the fake.
    result = run(build_content_screener(cached=False, max_attempts=5), cases=cases)

    print(f"Corpus: {len(cases)} cases ({args.split})")
    print(f"Screener: {result.screener}")
    if result.screening_abstentions:
        print(
            f"\n  !! Layer 2 did not answer for {result.screening_abstentions} "
            "case(s). Those were decided by\n  !! Layer 1 alone, so the "
            "semantic rows below are NOT a model result.\n  !! Check "
            "GEMINI_API_KEY and GEMINI_MODEL, then re-run."
        )
    print(format_table(result))
    print(format_false_blocks(result))
    print(format_latency(result))
    print(format_predictions(result))
    print(format_limitations(result))

    payload = to_dict(result)
    payload["split"] = args.split
    payload["predictions"] = [
        {
            "id": o.prediction.id,
            "statement": o.prediction.statement,
            "outcome": o.label,
            "on_failure": o.prediction.on_failure,
        }
        for o in check_all(result.reports)
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {args.out}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
