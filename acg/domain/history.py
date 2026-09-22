"""What the gateway already decided, as a rule is allowed to see it.

Three rules need memory: I3 asks whether a one-time mandate has already been
drawn against, I4 asks how fast a buyer is moving, and I2's split-order
structuring asks whether several small orders add up to one large one. None of
them can be answered from a single request.

Memory is the first thing that threatens the property the rest of Layer 1
rests on: every rule is a pure function of `(request, context)`, which is what
makes a verdict reproducible and the per-class ablation meaningful. So history
arrives *in* the context, assembled by the caller before evaluation, and no
rule ever queries for it. A rule that could fetch could see different history
on a replay of the same inputs, and the evaluation harness would stop being an
experiment.

The record deliberately carries the decision rather than only the allowed
requests. What counts as prior activity differs by rule: a blocked attempt is
not a draw against a mandate, but a burst of blocked attempts is exactly the
kind of thing a velocity rule should notice. Filtering is each rule's business.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from acg.domain.decision import Decision
from acg.domain.money import Money


@dataclass(frozen=True)
class PriorDecision:
    """One earlier request, and what the gateway decided about it.

    Frozen, like everything else a rule reads: history that could change
    between two rules in the same evaluation would make the verdict
    unattributable.
    """

    request_id: str
    mandate_id: str
    buyer_id: str
    quoted_total: Money
    decided_at: datetime
    decision: Decision

    def __post_init__(self) -> None:
        if self.decided_at.tzinfo is None or self.decided_at.utcoffset() is None:
            # Same rule as the rest of the domain: a naive timestamp would let
            # a velocity window inherit meaning from the host's clock.
            raise ValueError("decided_at must be timezone-aware")


def within_window(
    history: tuple[PriorDecision, ...],
    now: datetime,
    window: timedelta,
) -> tuple[PriorDecision, ...]:
    """The prior decisions falling inside `window` counted back from `now`.

    Half-open, `now - window < decided_at <= now`, matching the mandate
    validity window's convention so that one reading of "inside a window"
    holds across the whole system.

    A record dated after `now` is excluded. It should not exist, but a rule is
    not the place to discover a clock problem, and counting the future toward
    a velocity limit would be worse than ignoring it.

    Rules filter the history they are given rather than asking for a slice.
    That leaves the caller one obligation, which no rule can check for itself:
    the history passed in must reach back at least as far as the widest window
    any rule uses, or that rule silently under-counts.
    """
    earliest = now - window
    return tuple(prior for prior in history if earliest < prior.decided_at <= now)


def allowed(history: tuple[PriorDecision, ...]) -> tuple[PriorDecision, ...]:
    """Only the prior requests that were let through.

    A blocked attempt did not move money, so it is not a draw against a
    mandate and not a completed order. Rules that count *attempts* rather than
    *outcomes* should use the unfiltered history instead.
    """
    return tuple(prior for prior in history if prior.decision is Decision.ALLOW)
