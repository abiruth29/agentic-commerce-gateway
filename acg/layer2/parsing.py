"""Turning model output into a lattice value, or refusing to.

This is the narrowest and most security-relevant code in Layer 2, because it
is where attacker-controlled text and the gateway's decision come closest
together.

The model is asked to judge text that an attacker wrote. Models echo. So a
parser that searched the response for a word — `"BLOCK" in response` — would
be steerable by the text under judgement: a description containing the word
ALLOW could flip a verdict about itself. The parse is therefore exact. The
whole response must be one JSON object with a known shape and a verdict that
is exactly one of three tokens. Anything else is not interpreted generously,
it is refused, and the caller abstains.

Refusing is safe precisely because abstention means "fall back to Layer 1"
rather than "allow". There is no pressure to salvage a doubtful answer.
"""

import json
from typing import Final

from acg.domain.decision import Decision
from acg.layer2.port import SEMANTIC_CLASSES

VERDICTS: Final[dict[str, Decision]] = {
    "allow": Decision.ALLOW,
    "review": Decision.REVIEW,
    "block": Decision.BLOCK,
}

MAX_RESPONSE_CHARS: Final = 4_000
"""Anything longer is not a verdict.

A model that has started reproducing the item's description has stopped
answering the question, and parsing further into it only widens the surface.
"""


def parse_verdict(raw: str | None) -> tuple[Decision, tuple[str, ...]] | None:
    """Parse a screening response.

    Args:
        raw: the model's response text, or None if it returned nothing.

    Returns:
        The decision and the attack classes cited, or **None** when the
        response cannot be trusted to mean anything. None is not an error
        condition to recover from — it is the answer, and the caller abstains.
    """
    if not raw:
        return None
    if len(raw) > MAX_RESPONSE_CHARS:
        return None

    text = raw.strip()
    # Models commonly wrap JSON in a fenced block even when asked not to.
    # Stripping a fence is not generous interpretation: the content inside
    # still has to parse exactly.
    if text.startswith("```"):
        text = _strip_fence(text)

    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(payload, dict):
        return None

    verdict = payload.get("verdict")
    if not isinstance(verdict, str):
        return None

    decision = VERDICTS.get(verdict.strip().lower())
    if decision is None:
        # An unrecognised verdict is not nudged toward the nearest match.
        return None

    classes = payload.get("classes", [])
    if not isinstance(classes, list):
        return None
    if not all(isinstance(c, str) for c in classes):
        return None

    named = tuple(sorted({c.strip().upper() for c in classes}))
    if set(named) - SEMANTIC_CLASSES:
        # A verdict citing a class this layer cannot judge is not a verdict
        # this layer made. Refusing beats believing half of it.
        return None

    if decision is not Decision.ALLOW and not named:
        # A non-ALLOW verdict that names nothing is unattributable, and the
        # per-class breakdown is the point of the evaluation.
        return None

    return decision, named


def _strip_fence(text: str) -> str:
    """Remove one surrounding ``` fence, if the whole response is fenced."""
    lines = text.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return text
    return "\n".join(lines[1:-1])
