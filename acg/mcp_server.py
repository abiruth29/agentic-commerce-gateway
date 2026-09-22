"""The gateway as a tool an agent can call, over MCP.

This is the demonstration that the thesis survives contact with a real agent
loop: the buyer agent is the *caller* here, and it cannot reach the money
except through a tool that runs the rules first. The agent may be carrying
injected instructions, may be arguing for the purchase, may be confidently
wrong — and none of that changes what `evaluate_purchase` returns, because the
verdict is a fold over deterministic rules and a lattice join, not a
negotiation.

Two design points are worth stating, because both are places this could have
been built to look good and be useless.

**The tool does not offer a way to set the destination account.** An agent can
ask to pay a different `payee_id` — that argument exists precisely so the O3
rule can refuse it — but nothing in this interface reaches
`Merchant.registered_payee_id`. A tool that let its caller supply both sides
of that comparison would be theatre.

**The tool returns findings, not just a verdict.** An agent that is told
"BLOCK" and nothing else will retry, because it has no way to know what was
wrong. One that is told which rule fired and why can tell its user. That is
the difference between a guardrail and a wall.

Runs over stdio, which is how MCP servers are normally hosted:

    python -m acg.mcp_server

It is an optional extra (`pip install -e ".[mcp]"`) and is deliberately not a
runtime dependency of the deployed application — the hosted function has no
use for it, and a serverless bundle should not carry a stdio server.
"""

from typing import Any

from acg.eval.pipeline import Config, decide
from acg.eval.scenario import CaseDelta, build
from acg.layer1 import ALL_RULES
from acg.layer2 import build_content_screener

_SCREENER = build_content_screener()


def evaluate_purchase(
    quantity: int = 1,
    unit_price_rupees: int | None = None,
    payee_id: str | None = None,
    item_description: str | None = None,
    prior_purchases_this_hour: int = 0,
) -> dict[str, Any]:
    """Ask the gateway whether a purchase may proceed.

    Args:
        quantity: units requested. Not validated here on purpose — a zero or
            negative quantity is a coherent thing for a compromised agent to
            ask for, and the I2 rule's job is to refuse it.
        unit_price_rupees: the price the agent believes applies. Compared
            against the merchant's published price rather than trusted.
        payee_id: where the agent says the money should go. Compared against
            the merchant's out-of-band registered payee. This argument exists
            to be refused.
        item_description: the merchant's catalog text, which is untrusted and
            is the injection surface Layer 2 screens.
        prior_purchases_this_hour: completed purchases by this buyer, for the
            velocity rule.

    Returns:
        The decision, which layer is responsible, and every rule's finding.
    """
    delta = CaseDelta(
        quantity=quantity,
        item_price_rupees=unit_price_rupees,
        payee_id=payee_id,
        item_description=item_description,
        prior_allowed_purchases=prior_purchases_this_hour,
    )
    trial = build("mcp", delta)
    verdict = decide(trial, Config.C2, ALL_RULES, _SCREENER)

    return {
        "decision": verdict.decision.name,
        "may_proceed": verdict.decision.name == "ALLOW",
        "stopped_by": verdict.stopped_by,
        "findings": [
            {
                "rule": finding.rule_id,
                "attack_class": finding.attack_class,
                "decision": finding.decision.name,
                "reason": finding.reason,
            }
            for finding in (verdict.layer1.findings if verdict.layer1 else ())
            if finding.decision.name != "ALLOW"
        ],
        "mandate": {
            "ceiling_rupees": trial.context.mandate.max_amount.paise // 100,
            "allowed_categories": sorted(trial.context.mandate.allowed_categories),
            "usage": trial.context.mandate.usage.value,
        },
    }


def describe_rules() -> dict[str, Any]:
    """What the gateway enforces, and what it does not.

    The second half matters: an agent that believes the partition is complete
    will trust an ALLOW more than it should.
    """
    return {
        "enforced": [
            {"rule": rule.rule_id, "attack_class": rule.attack_class}
            for rule in ALL_RULES
        ],
        "not_built": [
            "I2.split_order_structuring",
            "I2.coupon_stacking",
            "I2.refund_before_fulfilment",
        ],
        "note": (
            "Layer 1 is deterministic and decides O3, I1, I2, I3, I4. Layer 2 "
            "screens untrusted catalog text for O1, O2, O4 and can only "
            "tighten Layer 1's verdict, never loosen it."
        ),
    }


def build_server() -> Any:  # noqa: ANN401 - FastMCP is an optional import
    """Build the MCP server.

    The import is deferred so that importing this module — which the tests do
    — does not require the optional dependency to be installed.
    """
    from fastmcp import FastMCP

    server = FastMCP("agentic-commerce-gateway")
    server.tool()(evaluate_purchase)
    server.tool()(describe_rules)
    return server


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
