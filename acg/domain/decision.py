"""The decision lattice: ALLOW < REVIEW < BLOCK.

Both screening layers emit a value from this lattice, and `combine` joins them.
The guarantee the design rests on is:

    combine(l1, l2) >= l1

Layer 2 can tighten Layer 1's verdict and can never loosen it. That is a
property of a type and a join, not of a prompt — which is the point. Gemini's
output is parsed into this enum and then passed through `combine`, so a model
that is confused, truncated, or actively manipulated still cannot widen what
Layer 1 already decided. Prompting is not a security control; a lattice is.

Ordering is carried by IntEnum so the guarantee can be stated with `>=` and
checked directly, rather than through a comparison helper that could itself be
wrong.
"""

from enum import IntEnum


class Decision(IntEnum):
    """What the gateway does with a request, ordered by restrictiveness.

    The integer values exist only to order the members. Nothing should persist
    or transmit them as integers — the names are the contract, and renumbering
    must stay a local change.
    """

    ALLOW = 0
    REVIEW = 1
    BLOCK = 2

    def __str__(self) -> str:
        return self.name


def combine(first: Decision, second: Decision) -> Decision:
    """Join two lattice values, returning the more restrictive of the two.

    This is the enforcement guarantee of the whole gateway, so it is written by
    hand rather than generated. The contract the tests hold it to:

    - result is never looser than either input: `result >= first` and
      `result >= second`
    - commutative: order of arguments cannot change the outcome
    - idempotent: combining a value with itself returns that value
    - ALLOW is the identity: `combine(x, ALLOW) == x`

    That last property is what makes Layer 2's ABSTAIN path safe. When Gemini
    times out, rate-limits, or returns garbage, Layer 2 yields ALLOW, and the
    identity property means the result is exactly Layer 1's verdict — the
    fallback is not a special case in the caller, it falls out of the algebra.
    An attacker who takes Gemini down gains detection evasion, never
    enforcement bypass.

    Args:
        first: one layer's verdict.
        second: the other layer's verdict.

    Returns:
        The more restrictive of `first` and `second`.
    """
    return first if first >= second else second
