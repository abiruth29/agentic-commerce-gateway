"""Loading the published corpus, and refusing to run a corpus that has drifted.

The corpus lives as JSON in `corpus/` rather than as Python fixtures, because
it is meant to be read by someone who does not want to read the harness. It is
the answer to "who wrote the attacks?", and an answer that requires running the
code is not much of one.

Everything here is a guard. A corpus is the one part of an evaluation that
degrades silently: a case whose delta stops applying still loads, still runs,
and still contributes a row — it just measures nothing, and it measures
nothing in the direction that flatters the system. So loading validates the
discipline the design committed to (fifteen per class, an even split), and the
deltas are parsed through the same `extra="forbid"` model the harness builds
worlds from, so an unknown lever fails here rather than becoming a case the
gateway trivially allows.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

from acg.eval.metrics import BENIGN
from acg.eval.scenario import CaseDelta

CORPUS_DIR: Final = Path(__file__).resolve().parent.parent.parent / "corpus"

ATTACK_CLASSES: Final = ("O1", "O2", "O3", "O4", "I1", "I2", "I3", "I4")
CASES_PER_CLASS: Final = 15
SPLITS: Final = ("seed", "held_out")


@dataclass(frozen=True)
class Case:
    """One corpus entry: an identifier, a claim, and the delta that makes it."""

    id: str
    attack_class: str
    split: str
    summary: str
    delta: CaseDelta
    hard_negative: bool = False
    """Benign only: a flow written to look like an attack.

    These are what make the false block rate worth reporting. A benign set of
    unambiguous product copy would score a perfect zero and would have tested
    nothing.
    """

    @property
    def is_attack(self) -> bool:
        return self.attack_class != BENIGN


def _load_file(path: Path) -> list[Case]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError(f"{path.name}: unsupported corpus version")

    cases = []
    for raw in payload["cases"]:
        cases.append(
            Case(
                id=raw["id"],
                attack_class=raw["attack_class"],
                split=raw["split"],
                summary=raw["summary"],
                # Parsed through the same model the harness builds from, so a
                # lever that no longer exists fails at load rather than
                # producing a case that quietly tests nothing.
                delta=CaseDelta.model_validate(raw["delta"]),
                hard_negative=raw.get("hard_negative", False),
            )
        )
    return cases


@lru_cache(maxsize=1)
def load_attacks() -> tuple[Case, ...]:
    return tuple(_load_file(CORPUS_DIR / "attacks.json"))


@lru_cache(maxsize=1)
def load_benign() -> tuple[Case, ...]:
    return tuple(_load_file(CORPUS_DIR / "benign.json"))


def load_all() -> tuple[Case, ...]:
    """The whole corpus: attacks first, then benign flows."""
    return load_attacks() + load_benign()
