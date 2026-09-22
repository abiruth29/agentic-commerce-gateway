"""Screening once per version of the text, not once per transaction.

This is what makes "Layer 2 is off the payment path" true rather than
aspirational. A verdict is computed when content is served and keyed by
`CatalogItem.content_hash`, so in steady state a purchase costs zero model
calls and zero added milliseconds. The claim is then a property of the
architecture, not a hope about latency.

Caching is a decorator rather than something each screener implements. Both
the fake and the Gemini screener get identical caching behaviour, and neither
can quietly differ from the other in the evaluation.
"""

from dataclasses import dataclass, field

from acg.domain.catalog import CatalogItem
from acg.layer2.port import ContentScreener, ScreeningOutcome, ScreeningResult


@dataclass
class CachingScreener:
    """Wraps a screener, remembering a verdict per version of the text."""

    inner: ContentScreener
    entries: dict[str, ScreeningResult] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0

    def screen(self, item: CatalogItem) -> ScreeningResult:
        cached = self.entries.get(item.content_hash)
        if cached is not None:
            self.hits += 1
            return cached

        self.misses += 1
        result = self.inner.screen(item)

        # Abstentions are not cached. An abstention records that the model
        # was unreachable, not that the text is fine, and caching it would
        # turn a momentary outage into a lasting hole: every later request
        # for this content would skip screening on the strength of one
        # timeout.
        if result.outcome is not ScreeningOutcome.ABSTAINED:
            self.entries[item.content_hash] = result

        return result
