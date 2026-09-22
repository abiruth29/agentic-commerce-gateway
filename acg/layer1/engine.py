"""Running the Layer 1 rules and folding their findings into one verdict.

The fold is the whole engine:

    reduce(combine, (f.decision for f in findings), Decision.ALLOW)

Starting from ALLOW is not a convenience default. ALLOW is the lattice
identity, so an empty rule set yields ALLOW and each finding can only tighten
the result. The same property makes the fold order-independent — `combine` is
commutative and associative — so no rule can be made to win by being
registered first, and the verdict does not depend on registration order.

Every rule runs. Short-circuiting on the first BLOCK would be faster and would
throw away the per-class breakdown the evaluation depends on: the story is
which classes each configuration stops, and that needs every rule's finding on
every request, not just the first one that fired.
"""

from dataclasses import dataclass
from functools import reduce

from acg.domain.decision import Decision, combine
from acg.domain.request import PurchaseRequest
from acg.layer1.rules import EvaluationContext, Finding, Rule


@dataclass(frozen=True)
class Layer1Verdict:
    """The folded decision, and every finding that produced it."""

    decision: Decision
    findings: tuple[Finding, ...]

    @property
    def blocking(self) -> tuple[Finding, ...]:
        """Findings at least as restrictive as the overall verdict.

        These are the ones that actually decided the outcome and the ones worth
        showing first; a rule that returned ALLOW inside a BLOCKed request is
        true but not the reason.
        """
        return tuple(f for f in self.findings if f.decision >= self.decision)


def evaluate(
    request: PurchaseRequest,
    context: EvaluationContext,
    rules: tuple[Rule, ...],
) -> Layer1Verdict:
    """Run every rule and join the results.

    Args:
        request: the agent's request, as received.
        context: the facts the rules are allowed to consult.
        rules: the rules to run. Passed in rather than discovered, so a test or
            an ablation configuration can run an explicit subset.

    Returns:
        The joined decision and the full set of findings, in rule order.
    """
    findings = tuple(rule.evaluate(request, context) for rule in rules)
    decision = reduce(
        combine, (finding.decision for finding in findings), Decision.ALLOW
    )
    return Layer1Verdict(decision=decision, findings=findings)
