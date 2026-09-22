"""What a Layer 1 rule is, and what it is allowed to say.

Every rule is deterministic. No rule calls a model, reaches the network, or
reads a clock of its own — the evaluation time arrives in the context so that a
replay of the same inputs produces the same verdict, which is what makes the
evaluation harness reproducible and the per-class ablation meaningful.

A rule returns a `Finding` rather than a bare `Decision` because the decision
alone is not defensible. "BLOCK" is an outcome; "BLOCK, rule O3.payee
_substitution, requested payee is not the merchant's registered payee" is an
audit trail, and it is what the console has to render to be worth looking at.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from acg.domain.catalog import CatalogItem, Merchant
from acg.domain.decision import Decision
from acg.domain.history import PriorDecision
from acg.domain.mandate import Mandate
from acg.domain.request import PurchaseRequest


@dataclass(frozen=True)
class EvaluationContext:
    """Everything a rule may look at besides the request itself.

    Assembled once by the caller and passed to every rule unchanged. Rules do
    not fetch: if a rule needs a fact, that fact is a field here, which keeps
    the set of inputs to a verdict finite and inspectable.
    """

    mandate: Mandate
    merchant: Merchant
    items: dict[str, CatalogItem]
    """The merchant's published catalog, keyed by item id.

    This is the authority a request's claims are checked against. A line naming
    an item that is not here is not a lookup miss to be tolerated — it is a
    claim about a product the merchant never published.
    """

    now: datetime
    """Evaluation time, supplied rather than read.

    Expiry and velocity windows both depend on it, so a rule that called
    datetime.now() itself would be untestable and would make two rules in the
    same evaluation disagree about when "now" is.
    """

    history: tuple[PriorDecision, ...] = ()
    """What the gateway already decided, oldest first.

    Assembled by the caller like everything else here, so a rule that needs
    memory stays a pure function of its inputs and a replay of the same
    evaluation reproduces the same verdict.

    Defaults to empty because most rules do not need it: a rule that judges a
    request on its own terms should not have to be handed history to ignore.
    The obligation that cannot be checked from inside a rule is the caller's —
    the history must reach back at least as far as the widest window any rule
    applies, or that rule under-counts without failing.
    """


@dataclass(frozen=True)
class Finding:
    """One rule's verdict, with the reason attached."""

    rule_id: str
    attack_class: str
    decision: Decision
    reason: str
    """Human-readable, specific, and safe to show.

    Written for the console and the audit log, so it should name what was
    compared and what did not match. It must never quote untrusted catalog or
    request text back verbatim, since the reason is rendered downstream and
    would carry the injection with it.
    """


@runtime_checkable
class Rule(Protocol):
    """A single deterministic check against one attack class."""

    rule_id: str
    attack_class: str

    def evaluate(
        self, request: PurchaseRequest, context: EvaluationContext
    ) -> Finding: ...
