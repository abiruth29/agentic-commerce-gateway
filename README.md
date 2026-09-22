# Agentic Commerce Gateway

A trust gateway for agent-initiated payments — it sits between an AI buyer
agent's purchase request and the money, and decides whether that request is
honest.

When software does the buying, the question stops being *is this card stolen*
and becomes *did a human authorise this, and is the money going where they
meant it to*.

## The claim

**Five of the eight attack classes need no language model at all.** They are
decided by arithmetic and comparison against values the request cannot reach.
Three do need one, because they are unbounded natural language. The evaluation
says which is which, and what the defence costs in refused genuine orders.

*Need no model* is a claim about the design, not a claim that all five are
finished. Four are at zero below. The fifth, I2, is short three rules — and
those three are arithmetic too, so the partition holds even where the
implementation does not yet.

Measured over a published corpus of 120 attacks, Layer 1 alone — no model:

| class | | attack success |
|---|---|---|
| O3 | payee substitution | **0.0% (0/15)** |
| I1 | mandate violation | **0.0% (0/15)** |
| I3 | mandate replay | **0.0% (0/15)** |
| I4 | velocity abuse | **0.0% (0/15)** |
| I2 | economic abuse | 26.7% (4/15) — one designed rule unbuilt, predicted in advance |
| O1 / O2 / O4 | semantic injection | 100.0% (15/15) — Layer 1 reads no text; this is why a model is here |

*Prompting is not a security control. A type and a lattice are.*

## Reproduce it

```bash
git clone https://github.com/abiruth29/agentic-commerce-gateway
cd agentic-commerce-gateway
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m acg.eval
```

That runs the whole corpus through all three configurations, prints the
per-class ablation and the false block rate, checks seven predictions that
were committed to git *before* the corpus existed, and writes every case's
decision to `web/results.json`.

`pytest` runs the full suite.

## Where to look

| | |
|---|---|
| the decision lattice | `acg/domain/decision.py` |
| the nine Layer 1 rules | `acg/layer1/` |
| semantic screening, and why it cannot loosen a verdict | `acg/layer2/port.py` |
| what counts as a successful attack, and as a false block | `acg/eval/metrics.py` |
| the predictions, committed before the data | `acg/eval/predictions.py` |
| the published corpus | `corpus/` |
| how this sits against AP2 and ACP | `docs/protocols.md` |

## Run locally

Requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
cp .env.example .env             # Windows: copy .env.example .env
uvicorn acg.main:app --reload
```

Then:

- <http://127.0.0.1:8000/> — console
- <http://127.0.0.1:8000/health> — liveness probe

```bash
curl -s http://127.0.0.1:8000/health
# {"status":"ok","version":"0.1.0"}
```

If you pulled changes that touched `pyproject.toml`, re-run `pip install -e .`
— a dependency added upstream will not appear in an existing environment on
its own, and the failure it produces is an `ImportError` far from the cause.

## Payments

Outbound integrations are selected by `MOCK_MODE`, which **defaults to on**.
A missing configuration value must not silently arm a path that talks to a
real provider, so only an explicit `false`, `0`, `no` or `off` turns it off.

In mock mode the gateway uses a deterministic fake: the same receipt always
yields the same order id, so a replayed evaluation produces identical results.
Its ids are prefixed `order_FAKE` and cannot be mistaken for real ones.

### Verified against Razorpay test mode

Run from the project root, with `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET`
set in `.env`:

```bash
python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, uuid
from acg.domain.money import Money
from acg.payments import build_payment_gateway
g = build_payment_gateway(dict(os.environ, MOCK_MODE='false'))
o = g.create_order(Money.from_rupees('1999.99'), f'acg_s3_{uuid.uuid4().hex[:8]}')
print(type(g).__name__, o.order_id, o.amount.paise, o.currency)
"
```

Pass `.env` to `load_dotenv` explicitly. Called with no argument from a script
fed through **stdin** — `python -`, or a heredoc — it raises an
`AssertionError`: it locates `.env` by walking up from the calling frame, and
a top-level statement in a stdin-fed script has no caller frame to walk from.
`python -c`, script files and imported modules are all unaffected, which is
why `acg.main` can use the bare form. Passing the path explicitly costs
nothing and works in every case.

A real run against test mode:

```
RazorpayGateway order_Tf6v5zKiYwDGMm 199999 INR
```

A genuine `order_…` id from the provider, `199999` paise for ₹1999.99, INR.
The amount crosses the boundary as `Money.paise` with no conversion — Razorpay
takes the smallest currency unit, which is what `Money` already holds, so the
place most integrations acquire an off-by-100 bug has no arithmetic in it.

The order is created with `payment_capture: 0`. Creating an order does not
move money; settlement stays a separate decision.

## The evaluation

```bash
python -m acg.eval
```

One command, no arguments. It runs the published corpus through three
configurations, prints the per-class ablation, and writes every case's decision
to `web/results.json` — the same file the hosted page reads, so the table a
reviewer sees and the file anyone can recompute from are one artifact.

**The corpus is published**, in `corpus/`. 120 attacks — eight classes × 15,
split 60/60 into a seed half and a held-out half — plus 60 benign flows, half
of which are hard negatives. Each case is one typed delta over a single fixed
baseline world, so the delta is the only independent variable and a difference
in outcome is attributable to the attack rather than to a hand-written fixture.
A delta naming a lever that does not exist fails at load, because the failure
that matters here is silent: a case that stops applying still loads, still
runs, still contributes a row, and measures nothing in the direction that
flatters the system.

### The three configurations

| | what it is |
|---|---|
| `C0` | no guardrail; the request is executed as submitted |
| `C1` | Layer 1 only — the deterministic rules, no model |
| `C2` | Layer 1 joined with Layer 2's semantic screening |

### What a run reports

- **Attack success rate per class.** An attack succeeds iff the final decision
  is `ALLOW`. A `REVIEW` is not a success: the money is held and a human sees
  it. An agent that merely echoes injected text has not succeeded either.
- **False block rate** over the 60 benign flows. Any benign flow not `ALLOW`ed
  counts, `REVIEW` included — on a merchant's P&L a genuine order sent to a
  queue is delayed revenue and a refused one is lost revenue, and neither is
  "no harm done". The refused and delayed halves are reported separately too.
- **Latency per path, never summed.** Layer 2's verdict is cached against the
  content hash, so a steady-state purchase makes zero model calls. Adding the
  two paths would describe a transaction nobody makes.

### Predictions, committed before the corpus existed

Seven falsifiable claims live in `acg/eval/predictions.py`, and every run
checks them and reports which held. They were committed in `adb23b6`, before
the corpus landed in `108a080` — the order is checkable in git rather than
asserted in prose. Each one carries what its failure would *mean*, which is
the reason to write predictions down at all: `P1 FAILED` is a number, but "the
payee comparison is not being made, and the first place to look is whether the
rule returns a Finding at all" is a place to start.

### Reproducing the reportable numbers

The committed `web/results.json` was produced by the **fake screener**, which
matches nine marker phrases. Its O1/O2/O4 figures measure the marker list, not
a model, and must not be quoted — the run says so itself, and the flag
`semantic_numbers_are_reportable` travels inside the results file.

For the real figures, with `GEMINI_API_KEY` set in `.env`:

```bash
python -c "
from dotenv import load_dotenv; load_dotenv('.env')
import os, sys
os.environ['MOCK_MODE'] = 'false'
from acg.eval.__main__ import main
sys.exit(main())
"
```

Pass `.env` to `load_dotenv` explicitly, for the reason given under the
Razorpay section above. It overwrites `web/results.json`, so the page then
shows real figures and drops its own disclaimer — commit the result.

Two of the seven predictions — P4 (the model lowers O1/O2/O4) and P5 (the false
block rate rises) — **cannot be tested by a mock run at all**, and the
committed results record both as `FAILED` rather than skipping them. That is
the mechanism working: the run states plainly that it did not test what it set
out to test.

### Known gaps, stated here rather than left to be found

- **Three of the twelve designed Layer 1 rules are not built**, all in I2.
  Split-order structuring is exercised by four corpus cases and walks straight
  through, which is why I2 does not reach 0% under C1 — that was predicted in
  advance as `P2`. Coupon stacking and refund-before-fulfilment **cannot be
  expressed by the corpus at all**: the domain has no coupon concept and no
  order lifecycle, so there is no delta to write. They are absent rather than
  failing, and I2's reported rate understates the real gap.
- **C0's semantic cells are unmeasured, not zero.** Whether an injection moves
  money depends on whether the buyer agent obeys it, which this harness cannot
  determine on the gateway's behalf — the agent is the thing under test, not a
  component of the system. Those cells read `not measured` and are excluded
  from every rate. Reporting 100% across the whole C0 row would flatter the
  before/after and would be indefensible: a model that ignores a clumsy
  injection is not an attack that succeeded.
- **The gateway trusts the merchant's category.** An item mis-categorised at
  source passes the mandate category check, and no corpus case can test that,
  because the corpus has no way to disagree with the catalog.

## The console

The hosted page is the evidence, with the gateway embedded in it rather than
standing in for it. The claim and the ablation are above the fold; the panel
below lets you put any of the 180 published cases — or your own catalog text —
through the real rule engine and see which rule fired and why.

Every verdict on the page comes from `/api/evaluate`, which runs the same
`ALL_RULES` and the same lattice join the evaluation measured. Nothing decides
anything in the browser: a second implementation could disagree with the
measured one, and a demo that disagrees with its own results is worse than no
demo. Sixty tests replay the corpus through the endpoint and compare it
against the engine directly.

### Layer 2 is stubbed in the hosted deployment

With no `GEMINI_API_KEY` set, `build_content_screener` returns the fake, and
the console says so in a banner before it shows any verdict. This matters:
with the stub, an O1 case comes back `ALLOW`, and without the caption that
reads as the gateway missing an obvious injection rather than as the model not
being connected. Layer 1 is unaffected — no model is involved in the five
deterministic classes, which is the point of the partition.

To run the hosted console for real, set `GEMINI_API_KEY` and `MOCK_MODE=false`
in the deployment's environment. The banner disappears on its own, because it
is driven by `/api/rules` rather than written into the page.

### What the page costs to open

The whole app — page, results file and API — is served by one Python function
on Vercel (`[tool.vercel] entrypoint` in `pyproject.toml`), so a cold start
applies to the page and not only to the API. Serving `web/` as static assets
would put the evidence on the CDN and leave only `/api/*` on the function;
that is a deployment change, and it is not made here because it cannot be
verified without deploying.

## The gateway as an agent tool (MCP)

```bash
pip install -e ".[mcp]"
python -m acg.mcp_server
```

An MCP server over stdio, exposing two tools: `evaluate_purchase` and
`describe_rules`. This is the demonstration that the thesis survives contact
with a real agent loop — the buyer agent is the *caller*, and it cannot reach
the money except through a tool that runs the rules first. The agent may be
carrying injected instructions, may be arguing for the purchase, may be
confidently wrong. None of it changes the verdict, because the verdict is a
fold over deterministic rules and a lattice join, not a negotiation.

Two things it deliberately does:

- **It offers no way to set the destination account.** An agent can ask to pay
  a different `payee_id` — that argument exists so the O3 rule can refuse it —
  but nothing in the interface reaches `Merchant.registered_payee_id`. A tool
  that let its caller supply both sides of that comparison would be theatre.
  The signature is the control, and a test asserts it.
- **It returns findings, not just a verdict.** An agent told only "BLOCK" will
  retry, because it has no way to know what was wrong. One told which rule
  fired and why can tell its user. `describe_rules` also reports the three
  rules that are *not* built, because an agent that believes the partition is
  complete will trust an `ALLOW` more than it should.

`fastmcp` is an optional extra, not a runtime dependency: the hosted function
has no use for a stdio server and a serverless bundle should not carry one.
The dev extra installs it, so CI exercises the server rather than letting it
rot unimported.
