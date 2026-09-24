"""Layer 2: semantic screening of untrusted catalog text.

One port, two implementations, a caching decorator, and a factory that reads
configuration. Nothing above this package knows which implementation it holds,
and nothing below it can loosen a Layer 1 verdict.
"""

import os

from acg.layer2.cache import CachingScreener
from acg.layer2.fake import FakeContentScreener
from acg.layer2.gemini import GeminiContentScreener
from acg.layer2.port import (
    SEMANTIC_CLASSES,
    ContentScreener,
    ScreeningOutcome,
    ScreeningResult,
    abstention,
)
from acg.payments import mock_mode_enabled

__all__ = [
    "SEMANTIC_CLASSES",
    "CachingScreener",
    "ContentScreener",
    "FakeContentScreener",
    "GeminiContentScreener",
    "ScreeningOutcome",
    "ScreeningResult",
    "abstention",
    "build_content_screener",
]


def build_content_screener(
    environ: dict[str, str] | None = None,
    *,
    cached: bool = True,
    max_attempts: int = 1,
) -> ContentScreener:
    """The screener this deployment should use.

    Cached by default: screening once per version of the text is what keeps
    Layer 2 off the payment path, so an uncached screener is the exception and
    has to be asked for.

    `max_attempts` applies to the real screener only. The serving path keeps
    the default of one, because a request is waiting on it; the evaluation
    asks for more, because a rate limit there would otherwise become a run of
    abstentions.

    Raises:
        ValueError: when real mode is selected without a key or a model.
    """
    env = os.environ if environ is None else environ
    inner: ContentScreener
    if mock_mode_enabled(env):
        inner = FakeContentScreener()
    else:
        inner = GeminiContentScreener(
            api_key=env.get("GEMINI_API_KEY", ""),
            model=env.get("GEMINI_MODEL"),
            max_attempts=max_attempts,
        )

    return CachingScreener(inner) if cached else inner
