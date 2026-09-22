"""Layer 1: the deterministic half of the partition.

Five of the eight attack classes are decided here with arithmetic and
comparisons, and no model is consulted for any of them. That is the claim the
whole design rests on — naming exactly which problems justify an LLM, and
proving the rest do not.
"""

from acg.layer1.economic import PriceIntegrityRule, QuantityRule, TotalIntegrityRule
from acg.layer1.engine import Layer1Verdict, evaluate
from acg.layer1.mandate import MandateAmountRule, MandateCategoryRule, MandateWindowRule
from acg.layer1.payee import PayeeSubstitutionRule
from acg.layer1.replay import MandateReplayRule
from acg.layer1.rules import EvaluationContext, Finding, Rule
from acg.layer1.velocity import VelocityRule

ALL_RULES: tuple[Rule, ...] = (
    PayeeSubstitutionRule(),
    MandateAmountRule(),
    MandateCategoryRule(),
    MandateWindowRule(),
    QuantityRule(),
    PriceIntegrityRule(),
    TotalIntegrityRule(),
    MandateReplayRule(),
    VelocityRule(),
)
"""Every rule Layer 1 currently enforces, in a fixed order.

Written out rather than discovered by scanning the package. Discovery would
mean a rule could join the enforcement set by being imported, and the set that
decides whether money moves should be something a reviewer can read in one
place and a diff can show changing.

The order is for reporting only. `combine` is commutative and associative and
the engine folds from ALLOW, so no rule can win by being listed first.

Three of the twelve rules in the design are not here yet: split-order
structuring, coupon stacking, and refund-before-fulfilment. The first is
buildable now that history exists; the other two need domain that does not —
a coupon concept and an order lifecycle. The evaluation reports the resulting
gaps rather than omitting the cases.
"""

__all__ = [
    "ALL_RULES",
    "EvaluationContext",
    "Finding",
    "Layer1Verdict",
    "MandateAmountRule",
    "MandateCategoryRule",
    "MandateReplayRule",
    "MandateWindowRule",
    "PayeeSubstitutionRule",
    "PriceIntegrityRule",
    "QuantityRule",
    "Rule",
    "TotalIntegrityRule",
    "VelocityRule",
    "evaluate",
]
