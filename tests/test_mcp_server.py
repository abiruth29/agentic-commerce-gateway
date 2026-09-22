"""Tests for the gateway exposed as an MCP tool.

The point of this surface is that the buyer agent is the *caller*: it cannot
reach the money except through a tool that runs the rules first. So the tests
that matter are the ones that would catch the tool quietly becoming
negotiable — a caller-supplied payee being trusted, a verdict arriving with no
reason attached, or the tool disagreeing with the engine the evaluation
measured.

`build_server` needs the optional `fastmcp` dependency; everything else here
is importable without it, which is why the import is deferred in the module
rather than done at the top.
"""

import pytest

from acg.eval.pipeline import Config, decide
from acg.eval.scenario import REGISTERED_PAYEE, CaseDelta, build
from acg.layer1 import ALL_RULES
from acg.mcp_server import describe_rules, evaluate_purchase


class TestTheToolAgreesWithTheEngine:
    @pytest.mark.parametrize(
        ("kwargs", "delta"),
        [
            ({}, CaseDelta()),
            (
                {"payee_id": "pay_ATTACKER"},
                CaseDelta(payee_id="pay_ATTACKER"),
            ),
            (
                {"prior_purchases_this_hour": 9},
                CaseDelta(prior_allowed_purchases=9),
            ),
            (
                {"unit_price_rupees": 5000},
                CaseDelta(item_price_rupees=5000),
            ),
        ],
    )
    def test_the_verdict_is_the_engines_verdict(
        self, kwargs: dict, delta: CaseDelta
    ) -> None:
        expected = decide(build("mcp", delta), Config.C2, ALL_RULES, _screener())
        assert evaluate_purchase(**kwargs)["decision"] == expected.decision.name


def _screener():  # noqa: ANN202
    from acg.mcp_server import _SCREENER

    return _SCREENER


class TestTheToolRefusesWhatItShould:
    def test_a_substituted_payee_is_blocked(self) -> None:
        result = evaluate_purchase(payee_id="pay_ATTACKER01")

        assert result["decision"] == "BLOCK"
        assert result["may_proceed"] is False
        assert result["stopped_by"] == "layer1"

    def test_a_negative_quantity_reaches_the_rule(self) -> None:
        # Deliberately unvalidated at this boundary: a compromised agent
        # asking for -1 units is exactly what I2 exists to refuse.
        result = evaluate_purchase(quantity=-1)
        assert result["decision"] == "BLOCK"

    def test_a_burst_is_sent_to_review_not_refused(self) -> None:
        result = evaluate_purchase(prior_purchases_this_hour=9)

        assert result["decision"] == "REVIEW"
        assert result["may_proceed"] is False

    def test_an_ordinary_purchase_proceeds(self) -> None:
        result = evaluate_purchase()

        assert result["decision"] == "ALLOW"
        assert result["may_proceed"] is True
        assert result["findings"] == []


class TestTheCallerCannotReachTheAnchor:
    def test_the_tool_offers_no_way_to_set_the_registered_payee(self) -> None:
        # A tool letting its caller supply both sides of the O3 comparison
        # would be theatre. The signature is the control.
        import inspect

        parameters = set(inspect.signature(evaluate_purchase).parameters)
        assert "registered_payee_id" not in parameters
        assert "merchant_id" not in parameters

    def test_a_substituted_payee_does_not_move_the_anchor(self) -> None:
        evaluate_purchase(payee_id="pay_ATTACKER01")
        trial = build("mcp", CaseDelta(payee_id="pay_ATTACKER01"))
        assert trial.context.merchant.registered_payee_id == REGISTERED_PAYEE


class TestTheToolExplainsItself:
    def test_a_refusal_names_the_rule_and_the_reason(self) -> None:
        # An agent told only "BLOCK" will retry, because it has no way to know
        # what was wrong. One told which rule fired can tell its user.
        findings = evaluate_purchase(payee_id="pay_ATTACKER01")["findings"]

        assert findings
        assert findings[0]["rule"] == "O3.payee_substitution"
        assert findings[0]["attack_class"] == "O3"
        assert len(findings[0]["reason"]) > 20

    def test_only_the_rules_that_fired_are_reported(self) -> None:
        findings = evaluate_purchase(payee_id="pay_ATTACKER01")["findings"]
        assert all(f["decision"] != "ALLOW" for f in findings)

    def test_the_mandate_is_returned_so_the_agent_can_stay_inside_it(
        self,
    ) -> None:
        mandate = evaluate_purchase()["mandate"]

        assert mandate["ceiling_rupees"] == 1500
        assert mandate["allowed_categories"] == ["skincare"]
        assert mandate["usage"] == "recurring"


class TestTheToolDoesNotOversellThePartition:
    def test_it_reports_what_is_enforced(self) -> None:
        enforced = describe_rules()["enforced"]
        assert [r["rule"] for r in enforced] == [r.rule_id for r in ALL_RULES]

    def test_it_also_reports_what_is_not_built(self) -> None:
        # An agent that believes the partition is complete will trust an
        # ALLOW more than it should.
        not_built = describe_rules()["not_built"]
        assert len(not_built) == 3
        assert all(rule.startswith("I2.") for rule in not_built)

    def test_the_note_states_the_direction_of_the_join(self) -> None:
        note = describe_rules()["note"]
        assert "tighten" in note
        assert "never loosen" in note


class TestTheServerBuilds:
    def test_the_server_registers_both_tools(self) -> None:
        pytest.importorskip("fastmcp")

        from acg.mcp_server import build_server

        server = build_server()
        assert server is not None

    def test_the_module_imports_without_fastmcp(self) -> None:
        # The optional dependency must not be needed to import the module, or
        # the tests above would silently stop running wherever it is absent.
        import acg.mcp_server as module

        assert callable(module.evaluate_purchase)
