"""What Layer 2 is allowed to say, and the one thing it can never do.

Layer 2 is the semantic half of the partition: O1 (direct instruction
injection), O2 (authority spoofing) and O4 (exfiltration lure). Those three are
unbounded natural language, which is why they justify a model at all. The other
five classes are arithmetic and comparisons, and a model would only make them
less certain.

The guarantee is structural, not behavioural. A screening result carries a
lattice value, the engine joins it with Layer 1's via `combine`, and
`combine(l1, l2) >= l1` holds by construction. A Layer 2 that is confused,
truncated, rate-limited or actively manipulated still cannot widen what Layer 1
decided. That is the difference between a prompt and a control.

ABSTAINED is how a failure is expressed. It is deliberately *not* a fourth
lattice value — a fourth value would break the total order the guarantee is
stated in. Instead an abstention carries ALLOW, the lattice identity, so
`combine(l1, ALLOW) == l1` and the verdict is exactly Layer 1's. The fallback
is not a branch a caller might forget; it falls out of the algebra.
"""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from acg.domain.catalog import CatalogItem
from acg.domain.decision import Decision

SEMANTIC_CLASSES = frozenset({"O1", "O2", "O4"})
"""The only classes Layer 2 is competent to name.

A verdict citing anything else is not a finding this layer can make, and is
treated as unparseable rather than believed.
"""


class ScreeningOutcome(StrEnum):
    """Whether the screener actually reached a judgement."""

    SCREENED = "screened"
    ABSTAINED = "abstained"
    """No usable answer: a timeout, a rate limit, an error, or output that did
    not parse. An attacker who takes the model down gains detection evasion,
    never enforcement bypass."""


@dataclass(frozen=True)
class ScreeningResult:
    """One screening verdict about one version of some untrusted text."""

    content_hash: str
    outcome: ScreeningOutcome
    decision: Decision
    reason: str
    classes: tuple[str, ...] = ()
    """Which of O1, O2, O4 the screener says it saw. Reporting only — the
    decision is what the lattice acts on."""

    def __post_init__(self) -> None:
        if self.outcome is ScreeningOutcome.ABSTAINED:
            # The invariant the whole fallback rests on. An abstention that
            # carried REVIEW or BLOCK would let a model outage tighten
            # verdicts, and one that carried anything but the identity would
            # make "fall back to Layer 1" false.
            if self.decision is not Decision.ALLOW:
                raise ValueError(
                    "an abstention must carry ALLOW, the lattice identity, "
                    "so that combining it leaves Layer 1's verdict unchanged"
                )
            if self.classes:
                raise ValueError("an abstention cannot name attack classes")

        unknown = set(self.classes) - SEMANTIC_CLASSES
        if unknown:
            raise ValueError(f"Layer 2 cannot judge these classes: {sorted(unknown)}")

    @property
    def abstained(self) -> bool:
        return self.outcome is ScreeningOutcome.ABSTAINED


def abstention(content_hash: str, reason: str) -> ScreeningResult:
    """The result to return whenever the model could not be believed."""
    return ScreeningResult(
        content_hash=content_hash,
        outcome=ScreeningOutcome.ABSTAINED,
        decision=Decision.ALLOW,
        reason=reason,
    )


class ContentScreener(Protocol):
    """Screens one item's untrusted text.

    Takes a `CatalogItem` rather than raw strings so the implementation cannot
    be handed text from somewhere the content hash does not cover, which would
    make the cache key describe something other than what was screened.
    """

    def screen(self, item: CatalogItem) -> ScreeningResult: ...
