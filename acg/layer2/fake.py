"""A deterministic screener, for MOCK_MODE and the evaluation harness.

The corpus is 120 attacks replayed on every run. Sending them to a model would
make the numbers depend on a network, a quota and a sampling temperature, and
"reproducible" would stop being true.

So this screener decides by substring match against marker phrases. That is a
weak detector and is supposed to be: it stands in for the real one in tests
about *plumbing* — caching, abstention, the lattice join — never in the
per-class ablation the page reports. Any figure produced against this fake
would be measuring the marker list, not the model.
"""

from dataclasses import dataclass, field

from acg.domain.catalog import CatalogItem
from acg.domain.decision import Decision
from acg.layer2.port import ScreeningOutcome, ScreeningResult, abstention

MARKERS: dict[str, tuple[str, ...]] = {
    "O1": (
        "ignore previous instructions",
        "disregard the above",
        "new instructions:",
    ),
    "O2": (
        "as the system administrator",
        "this message is from the payment provider",
        "official notice from",
    ),
    "O4": (
        "send your api key",
        "forward the mandate details",
        "reply with the buyer's",
    ),
}


@dataclass
class FakeContentScreener:
    """Flags text containing known marker phrases."""

    calls: list[str] = field(default_factory=list)
    """Content hashes screened, in order. The harness asserts against it to
    show the cache is doing its job; nothing in the gateway reads it."""

    abstain_next: bool = False
    """Set to exercise the fallback without an outage to arrange."""

    def screen(self, item: CatalogItem) -> ScreeningResult:
        self.calls.append(item.content_hash)

        if self.abstain_next:
            self.abstain_next = False
            return abstention(item.content_hash, "screening was unavailable")

        haystack = f"{item.title}\n{item.description}".lower()
        found = tuple(
            sorted(
                name
                for name, phrases in MARKERS.items()
                if any(phrase in haystack for phrase in phrases)
            )
        )

        if not found:
            return ScreeningResult(
                content_hash=item.content_hash,
                outcome=ScreeningOutcome.SCREENED,
                decision=Decision.ALLOW,
                reason="no injection markers found in the item text",
            )

        return ScreeningResult(
            content_hash=item.content_hash,
            outcome=ScreeningOutcome.SCREENED,
            decision=Decision.BLOCK,
            reason="the item text carries instructions aimed at the agent",
            classes=found,
        )
