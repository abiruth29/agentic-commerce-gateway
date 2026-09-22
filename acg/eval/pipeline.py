"""The three configurations the ablation compares, and the join between layers.

This is where the guarantee stops being a property of `combine` and starts
being a property of the gateway: the final decision is the join of Layer 1's
verdict with Layer 2's, so Layer 2 can tighten and cannot loosen. Layer 1's
verdict is carried through unchanged alongside it, which is what lets a result
row say *which layer* stopped a case — the per-class ablation is the story, and
a bare final decision cannot tell it.

On C0 and what it is honest to claim
------------------------------------
C0 is "a buyer agent with no gateway". For the five deterministic classes it
is not measured and does not need to be: the attack is in the request itself,
the request is executed as submitted, and the money moves. C0 is 100% for
O3 and I1-I4 **by construction**, and the code says so rather than running a
model to produce a number that was never in doubt.

O1, O2 and O4 are different. Whether an injected instruction actually moves
money depends on whether the agent obeys it, and that is a real measurement of
a real model — one this gateway cannot make on its own behalf, because the
agent is the thing under test, not a component of the system. Those cells are
reported as not measured, with the naive-agent run that would fill them named
on the page.

The temptation is to report 100% across the whole C0 row because it makes the
before/after look better. It would also be the one number in the table a
reviewer could catch, and it would be indefensible: a model that ignores a
clumsy injection is not an attack that succeeded.
"""

from dataclasses import dataclass
from enum import StrEnum

from acg.domain.decision import Decision, combine
from acg.eval.scenario import Trial
from acg.layer1.engine import Layer1Verdict, evaluate
from acg.layer1.rules import Rule
from acg.layer2.port import ContentScreener, ScreeningResult


class Config(StrEnum):
    """The three columns of the ablation."""

    C0 = "C0"
    """No guardrail. The request is executed as submitted."""

    C1 = "C1"
    """Layer 1 only: the deterministic rules, no model."""

    C2 = "C2"
    """Layer 1 joined with Layer 2's semantic screening."""


@dataclass(frozen=True)
class GatewayVerdict:
    """What the gateway decided, and enough of why to attribute it."""

    decision: Decision
    layer1: Layer1Verdict | None
    screening: ScreeningResult | None

    @property
    def stopped_by(self) -> str | None:
        """Which layer is responsible for a non-ALLOW decision.

        Attribution, not explanation. When both layers would have stopped a
        case, Layer 1 is named: it decided first, deterministically, and would
        have stopped it with the model switched off.
        """
        if self.decision is Decision.ALLOW:
            return None
        if self.layer1 is not None and self.layer1.decision is not Decision.ALLOW:
            return "layer1"
        if self.screening is not None and self.screening.decision is not Decision.ALLOW:
            return "layer2"
        return None


def decide(
    trial: Trial,
    config: Config,
    rules: tuple[Rule, ...],
    screener: ContentScreener | None = None,
) -> GatewayVerdict:
    """Run one trial under one configuration.

    Args:
        trial: the built world.
        config: which columns of the ablation this run is producing.
        rules: the Layer 1 rules to run. Passed in rather than discovered so
            an ablation can run an explicit subset and so no rule can join the
            evaluation by being imported.
        screener: required by C2, unused by C0 and C1.

    Returns:
        The joined decision with both layers' evidence attached.

    Raises:
        ValueError: if C2 is asked for without a screener. Silently degrading
            to C1 would produce a C2 column that is really a second C1 column,
            which is the single most misleading thing this function could do.
    """
    if config is Config.C0:
        # No gateway: nothing is consulted and nothing is refused.
        return GatewayVerdict(decision=Decision.ALLOW, layer1=None, screening=None)

    layer1 = evaluate(trial.request, trial.context, rules)

    if config is Config.C1:
        return GatewayVerdict(decision=layer1.decision, layer1=layer1, screening=None)

    if screener is None:
        raise ValueError("C2 requires a content screener; refusing to run it as C1")

    screening = screener.screen(trial.item)
    return GatewayVerdict(
        decision=combine(layer1.decision, screening.decision),
        layer1=layer1,
        screening=screening,
    )
