"""The HTTP surface the console talks to.

Only three endpoints, and two of them are reads. The one that does work,
`/api/evaluate`, exists so a reviewer can put a request through the real rule
engine rather than watch a recording of one — the console's whole value is
that its verdicts come from the same code the evaluation measured, not from a
JavaScript reimplementation that could quietly disagree.

Input hardening lives here rather than in `CaseDelta`. The corpus model's job
is to express attacks, and it is deliberately permissive about things a rule
should refuse — a negative quantity has to survive construction or the I2 rule
can never be shown to catch it. That permissiveness is right for a corpus file
written in the repository and wrong for a JSON body from the open internet, so
the bounds are applied at the boundary the untrusted input actually crosses.
None of them are security controls for the *gateway*; the gateway's controls
are the rules. They are controls for the *service*: they stop a request asking
the process to build a hundred million prior decisions.
"""

from typing import Any, Final

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from acg.eval.corpus import load_all
from acg.eval.pipeline import Config, decide
from acg.eval.scenario import CaseDelta, build
from acg.layer1 import ALL_RULES
from acg.layer2 import build_content_screener
from acg.layer2.port import ScreeningResult

router = APIRouter(prefix="/api", tags=["console"])

MAX_TEXT_CHARS: Final = 2_000
"""Untrusted catalog text is screened, and screening costs a model call."""

MAX_PRIOR_DECISIONS: Final = 200
"""Each prior is an object the builder constructs. A request asking for
millions of them is not a scenario, it is a way to spend the host's memory."""

MAX_PAISE: Final = 10_000_000_00
"""Ten crore rupees. Well above anything a mandate would authorise, and far
below the point where integer arithmetic gets expensive."""

MAX_QUANTITY: Final = 100_000

_SCREENER = build_content_screener()
"""Built once, at import.

Cached, so repeated console calls on the same text cost one model call — the
same property the evaluation measured, rather than a separate code path that
could quietly behave differently.
"""


def _screener_name(screener: object) -> str:
    """The name of the screener that actually answers.

    Unwraps the cache. Reporting `CachingScreener` would be true and useless:
    the question the page needs answered is whether a verdict came from a
    model or from the nine-phrase fake, and the decorator's name hides exactly
    that.
    """
    inner = getattr(screener, "inner", None)
    return type(screener if inner is None else inner).__name__


SCREENER_NAME = _screener_name(_SCREENER)
IS_MOCK_SCREENER = SCREENER_NAME == "FakeContentScreener"


class EvaluateRequest(BaseModel):
    """What the console asks the gateway to judge."""

    model_config = ConfigDict(extra="forbid")

    case_id: str | None = Field(default=None, max_length=64)
    """A published corpus case to load. Takes precedence over `delta`."""

    delta: dict[str, Any] | None = None
    """A scenario delta, validated against `CaseDelta` and then bounded."""

    config: Config = Config.C2


class FindingOut(BaseModel):
    rule_id: str
    attack_class: str
    decision: str
    reason: str


class ScreeningOut(BaseModel):
    outcome: str
    decision: str
    reason: str
    classes: list[str]


class EvaluateResponse(BaseModel):
    """The verdict, and enough of the reasoning to be worth reading."""

    decision: str
    config: str
    stopped_by: str | None
    findings: list[FindingOut]
    screening: ScreeningOut | None
    screener: str
    """Which screener answered, with the cache decorator unwrapped."""

    screener_is_mock: bool
    """Whether that screener is the nine-phrase fake.

    Carried on every response rather than fetched once by the page, so a
    console that renders a verdict cannot render it without the caveat."""

    request: dict[str, Any]
    """What was actually built and judged, so the panel shows the request the
    rules saw rather than the one the form thinks it sent."""


def _bounded(delta: CaseDelta) -> CaseDelta:
    """Refuse a delta that would cost the service more than it is worth.

    Raises:
        HTTPException: 422, naming the field, so the console can say which
            input it refused rather than failing opaquely.
    """
    limits: list[tuple[str, int | None, int, int]] = [
        ("quantity", delta.quantity, -MAX_QUANTITY, MAX_QUANTITY),
        ("unit_price_paise", delta.unit_price_paise, 0, MAX_PAISE),
        ("quoted_total_paise", delta.quoted_total_paise, 0, MAX_PAISE),
        ("mandate_max_rupees", delta.mandate_max_rupees, 0, MAX_PAISE // 100),
        ("item_price_rupees", delta.item_price_rupees, 0, MAX_PAISE // 100),
        (
            "prior_allowed_purchases",
            delta.prior_allowed_purchases,
            0,
            MAX_PRIOR_DECISIONS,
        ),
        ("request_age_minutes", delta.request_age_minutes, 0, 60 * 24 * 365),
    ]

    for name, value, low, high in limits:
        if value is not None and not low <= value <= high:
            raise HTTPException(422, f"{name} must be between {low} and {high}")

    for name in ("item_title", "item_description"):
        text = getattr(delta, name)
        if text is not None and len(text) > MAX_TEXT_CHARS:
            raise HTTPException(422, f"{name} must be at most {MAX_TEXT_CHARS} chars")

    return delta


def _resolve(payload: EvaluateRequest) -> tuple[str, CaseDelta]:
    """Work out which scenario to build, from a case id or a raw delta."""
    if payload.case_id is not None:
        for case in load_all():
            if case.id == payload.case_id:
                return case.id, case.delta
        raise HTTPException(404, f"no corpus case with id {payload.case_id!r}")

    try:
        delta = CaseDelta.model_validate(payload.delta or {})
    except ValidationError as error:
        # extra="forbid" means an unknown lever lands here rather than being
        # silently dropped into a scenario that tests nothing.
        # `from None`: the pydantic error quotes the submitted value back,
        # and the submitted value is attacker-written text.
        raise HTTPException(
            422, f"invalid delta: {error.error_count()} problem(s)"
        ) from None

    return "console", _bounded(delta)


def _screening_out(screening: ScreeningResult | None) -> ScreeningOut | None:
    if screening is None:
        return None
    return ScreeningOut(
        outcome=screening.outcome.value,
        decision=screening.decision.name,
        reason=screening.reason,
        classes=list(screening.classes),
    )


@router.post("/evaluate", response_model=EvaluateResponse)
def evaluate(payload: EvaluateRequest) -> EvaluateResponse:
    """Judge one request with the real rule engine.

    The console calls this rather than reimplementing the lattice in the
    browser. A second implementation could disagree with the measured one, and
    a demo that disagrees with its own evaluation is worse than no demo.
    """
    case_id, delta = _resolve(payload)
    trial = build(case_id, delta)
    verdict = decide(trial, payload.config, ALL_RULES, _SCREENER)

    findings = [] if verdict.layer1 is None else verdict.layer1.findings

    return EvaluateResponse(
        decision=verdict.decision.name,
        config=payload.config.value,
        stopped_by=verdict.stopped_by,
        findings=[
            FindingOut(
                rule_id=f.rule_id,
                attack_class=f.attack_class,
                decision=f.decision.name,
                reason=f.reason,
            )
            for f in findings
        ],
        screening=_screening_out(verdict.screening),
        screener=SCREENER_NAME,
        screener_is_mock=IS_MOCK_SCREENER,
        request={
            "payee_id": trial.request.payee_id,
            "registered_payee_id": trial.context.merchant.registered_payee_id,
            "quoted_total_paise": trial.request.quoted_total.paise,
            "mandate_ceiling_paise": trial.context.mandate.max_amount.paise,
            "mandate_categories": sorted(trial.context.mandate.allowed_categories),
            "item_category": trial.item.category,
            "item_price_paise": trial.item.price.paise,
            "lines": [
                {
                    "item_id": line.item_id,
                    "quantity": line.quantity,
                    "unit_price_paise": line.unit_price.paise,
                }
                for line in trial.request.lines
            ],
            "prior_decisions": len(trial.context.history),
            # Truncated because the console renders it, and the whole point of
            # this field is that it is attacker-written.
            "item_title": trial.item.title[:200],
            "item_description": trial.item.description[:400],
        },
    )


@router.get("/corpus")
def corpus() -> dict[str, Any]:
    """The published corpus, for the console's case picker.

    Served from the same file the evaluation reads, so the console cannot
    offer a case the measured run did not include.
    """
    return {
        "cases": [
            {
                "id": case.id,
                "attack_class": case.attack_class,
                "split": case.split,
                "summary": case.summary,
                "hard_negative": case.hard_negative,
            }
            for case in load_all()
        ]
    }


@router.get("/rules")
def rules() -> dict[str, Any]:
    """What this deployment is actually running.

    Two halves, and the second is the point. A console that listed only the
    rules that exist would let a reader infer the partition is complete, and a
    console that did not say which screener is loaded would let a stubbed
    Layer 2 be mistaken for a model declining to fire.
    """
    return {
        "screener": {
            "name": SCREENER_NAME,
            "is_mock": IS_MOCK_SCREENER,
            "note": (
                "Layer 2 is stubbed in this deployment. The fake screener "
                "matches nine marker phrases, so most real injections walk "
                "past it and C2 returns C1's verdict unchanged. Set "
                "GEMINI_API_KEY, GEMINI_MODEL and MOCK_MODE=false to run it "
                "for real."
                if IS_MOCK_SCREENER
                else "Layer 2 is screening with a live model."
            ),
        },
        "enforced": [
            {"rule_id": rule.rule_id, "attack_class": rule.attack_class}
            for rule in ALL_RULES
        ],
        "not_built": [
            {
                "rule_id": "I2.split_order_structuring",
                "attack_class": "I2",
                "status": "designed, unbuilt, exercised by four corpus cases",
            },
            {
                "rule_id": "I2.coupon_stacking",
                "attack_class": "I2",
                "status": "designed, unbuilt, cannot be expressed: no coupon concept",
            },
            {
                "rule_id": "I2.refund_before_fulfilment",
                "attack_class": "I2",
                "status": "designed, unbuilt, cannot be expressed: no order lifecycle",
            },
        ],
    }
