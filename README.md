# Agentic Commerce Gateway

A trust gateway for agent-initiated payments — it sits between an AI buyer agent's purchase request and the money, and decides whether that request is honest.

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
