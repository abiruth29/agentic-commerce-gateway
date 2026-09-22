"""The README's headline numbers must be the numbers the evaluation produced.

The README quotes the C1 ablation in its first screen, which is where most
readers stop. A figure copied by hand once and never checked again is the most
likely thing in this repository to become quietly false — the eval is meant to
be re-run, and re-running it is exactly what would make a pasted number stale.

Every rate in that table is parsed back out and compared against
`web/results.json`, so re-running the evaluation either keeps the README true
or fails the suite.
"""

import json
import re
from pathlib import Path

import pytest

from acg.main import WEB_DIR

ROOT = Path(WEB_DIR).parent
README = (ROOT / "README.md").read_text(encoding="utf-8")
RESULTS = json.loads((ROOT / "web" / "results.json").read_text(encoding="utf-8"))
C1 = RESULTS["configs"]["C1"]["asr_by_class"]

# "**0.0% (0/15)**" or "26.7% (4/15) — ..." in a table row that opens with the
# class name.
ROW = re.compile(
    r"^\|\s*(O[1-4]|I[1-4])(?:\s*/\s*[OI][1-4])*\s*\|[^|]*\|\s*\**"
    r"(\d+\.\d+)%\s*\((\d+)/(\d+)\)",
    re.M,
)


def quoted_rows() -> list[tuple[str, float, int, int]]:
    return [
        (name, float(percent), int(num), int(den))
        for name, percent, num, den in ROW.findall(README)
    ]


class TestTheHeadlineTableIsTheMeasuredTable:
    def test_the_scan_finds_the_table(self) -> None:
        # Guards the guard: a regex that matched nothing would make every
        # case below vanish and the file pass vacuously.
        assert len(quoted_rows()) >= 5

    @pytest.mark.parametrize("row", quoted_rows(), ids=lambda r: r[0])
    def test_each_quoted_rate_matches_the_results_file(
        self, row: tuple[str, float, int, int]
    ) -> None:
        name, percent, numerator, denominator = row
        measured = C1[name]

        assert measured["percent"] == percent, f"{name} percent is stale"
        assert measured["numerator"] == numerator, f"{name} numerator is stale"
        assert measured["denominator"] == denominator, f"{name} denominator is stale"

    def test_every_deterministic_class_is_quoted(self) -> None:
        quoted = {row[0] for row in quoted_rows()}
        assert {"O3", "I1", "I3", "I4", "I2"} <= quoted

    def test_the_quoted_column_is_the_one_with_no_model_in_it(self) -> None:
        # The table shows C1 only. That matters: C1 consults no screener, so
        # even its semantic row is a fact about Layer 1 rather than a figure
        # from the stubbed model, and it stays quotable in a mock deployment.
        assert "Layer 1 alone — no model" in README


class TestTheReproductionCommandIsReal:
    def test_the_command_the_readme_gives_is_the_one_that_exists(self) -> None:
        assert "python -m acg.eval" in README
        assert (ROOT / "acg" / "eval" / "__main__.py").exists()

    def test_the_paths_the_readme_points_at_exist(self) -> None:
        pointed = re.findall(r"^\|[^|]*\|\s*`([^`]+/[^`]*)`\s*\|", README, re.M)
        assert pointed, "no paths found in the where-to-look table"

        for path in pointed:
            assert (ROOT / path).exists(), f"README points at missing {path}"
