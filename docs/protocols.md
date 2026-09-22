# Where this sits: AP2 and ACP

Two open standards for agent-initiated payments landed while this was being
built. Anyone evaluating this project will ask how it relates to them, so this
is the answer, written against the specifications rather than against the
launch-day summaries — which turn out to differ.

Everything below was checked against primary sources, cited by file path. Where
this gateway is weaker than a protocol, that is stated here rather than left to
be found.

---

## AP2 — Agent Payments Protocol (Google)

Repository: [`google-agentic-commerce/AP2`](https://github.com/google-agentic-commerce/AP2),
Apache 2.0. The specification in `docs/ap2/specification.md` is titled
*Agentic Payment Protocol (v0.2)*.

### It defines two mandates, not three

The spec defines a **Checkout Mandate** and a **Payment Mandate**. The
*Intent Mandate* / *Cart Mandate* / *Payment Mandate* triple that most
write-ups describe is the September 2025 launch framing; it does not appear
anywhere in v0.2, and `docs/ap2/` contains `checkout_mandate.md` and
`payment_mandate.md` and no file for the other two.

Worth knowing before citing the older names in a conversation with someone who
has read the spec.

### Its threat model states this project's premise

From `docs/ap2/security_and_privacy_considerations.md`:

> AP2 assumes that preventing prompt injection attacks is infeasible.
> Therefore, all LLMs and Agents MUST be considered potential attackers.

That is the protocol-level statement of the position this gateway is built on:
*prompting is not a security control; a type and a lattice are.* The
convergence is the useful part. It means this project is not an alternative to
AP2 — it is an implementation of the enforcement a threat model like AP2's
requires, at the layer where the money actually moves.

The same document names five threats: **Manipulated Checkout**, **Manipulated
Payment**, **Payment Credential Theft**, **Manipulated Discovery**, and
**Double Spend**. Under Manipulated Discovery:

> Prompt injection causes the Shopping Agent to select malicious products or
> make poor purchase decisions.

AP2 names that threat. It does not specify the control that catches it. That
control is what Layer 2 of this gateway is.

### What an AP2 mandate constrains

The Checkout Mandate carries `vct`, `checkout_hash`, `checkout_jwt`,
`constraints`, `cnf` (key binding), `iat` and `exp`. An *open* mandate's
constraints are `checkout.line_items` and `checkout.allowed_merchants`. The
Checkout JWT itself carries `order_id`, `merchant`, `line_items`,
`total_price`, `currency`, `shipping_policy` and `return_policy`.

Note what is **not** there: no spend ceiling across purchases, no category
restriction, and no single-use versus recurring designation.

---

## ACP — Agentic Commerce Protocol (OpenAI and Stripe)

Repository:
[`agentic-commerce-protocol/agentic-commerce-protocol`](https://github.com/agentic-commerce-protocol/agentic-commerce-protocol).

ACP is an interaction model for checkout: sessions, capability negotiation,
payment handlers, discounts. Its security-relevant core is delegated payment.
From `rfcs/rfc.payment_handlers.md`, the allowance bounds are:

> Explicit allowance bounds: `max_amount`, `currency`, `expires_at`,
> `checkout_session_id`

Vault tokens are "bound to specific checkout sessions and merchants". The RFC
is explicit that these are set by the agent at delegation time, per checkout —
not pre-registered by the user. It states no mechanism for a user to register
spending rules before shopping, and it does not address prompt injection or
untrusted merchant content; it is payment infrastructure, not content security.

---

## The gap both leave, and what this fills

**Both protocols constrain the payment instrument. Neither constrains the
purchase decision.**

ACP's allowance is an amount, a currency, an expiry and a session. AP2's open
mandate is a set of line items and a set of permitted merchants. Both are
excellent at making a leaked credential worth very little. Neither carries the
thing a human actually wants to express — *₹1,500, skincare, one-time* — and
neither has the vocabulary to refuse a purchase that is correctly signed,
correctly scoped, within its allowance, and simply not what was authorised.

That is attack class I1, and this gateway's `Mandate` is built for it:

| | AP2 open mandate | ACP allowance | this gateway's `Mandate` |
|---|---|---|---|
| maximum amount | — | `max_amount` | `max_amount` |
| expiry | `exp` | `expires_at` | `expires_at` |
| merchant scope | `allowed_merchants` | session + merchant bound | `Merchant.registered_payee_id` |
| item scope | `line_items` | — | `allowed_categories` |
| spend across purchases | — | — | enforced by I2 / I4 rules |
| one-time vs recurring | — | — | `usage` |
| cryptographic binding | `cnf`, signed VC | PSP-vaulted token | **none — see below** |

### How the eight attack classes map

| class | AP2 | ACP |
|---|---|---|
| O1 / O2 / O4 semantic injection | named as *Manipulated Discovery*; no control specified | not addressed |
| O3 payee substitution | `allowed_merchants` constrains the merchant | token bound to merchant + session |
| I1 mandate violation | partially — line items and merchants, no budget or category | not addressed |
| I2 economic abuse | *Manipulated Checkout* / *Manipulated Payment* | `max_amount` per session |
| I3 mandate replay | named as *Double Spend* | `expires_at` limits the window |
| I4 velocity | — | — |

Two rows are worth dwelling on. **I4 appears in neither**: a protocol scoped to
one transaction has no place to notice that this is the ninth transaction in an
hour. And **the semantic row is where a protocol can name a threat but not
supply a control** — which is exactly the division of labour this project
assumes.

---

## Where this gateway is weaker

Stated here rather than left for a reviewer to find.

**It has no cryptography.** AP2 mandates are signed credentials with key
binding; ACP tokens are vaulted by a payment provider. This gateway's mandate
is a trusted local record, and its integrity depends entirely on the store it
lives in. Against an attacker who can write to that store, every rule that
compares against a mandate is defeated at once. Adopting AP2's signed mandates
would fix this and is the single most valuable thing to take from either
protocol.

**It is single-merchant.** `registered_payee_id` is an out-of-band anchor for
one merchant. AP2's `allowed_merchants` is a set, and a real deployment needs
that shape.

**It speaks neither protocol on the wire.** The domain model is compatible in
substance — a pre-registered authorisation, checked before money moves — but
nothing here emits or verifies an AP2 mandate or an ACP checkout session.
Making `Mandate` deserialise from an AP2 Checkout Mandate is a contained piece
of work, and it is the obvious next one.

---

## Sources

- [`google-agentic-commerce/AP2` — `docs/ap2/specification.md`](https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/specification.md)
- [`google-agentic-commerce/AP2` — `docs/ap2/security_and_privacy_considerations.md`](https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/security_and_privacy_considerations.md)
- [`google-agentic-commerce/AP2` — `docs/ap2/checkout_mandate.md`](https://github.com/google-agentic-commerce/AP2/blob/main/docs/ap2/checkout_mandate.md)
- [`agentic-commerce-protocol` — `rfcs/rfc.payment_handlers.md`](https://github.com/agentic-commerce-protocol/agentic-commerce-protocol/blob/main/rfcs/rfc.payment_handlers.md)
- [Announcing Agent Payments Protocol (AP2), Google Cloud](https://cloud.google.com/blog/products/ai-machine-learning/announcing-agents-to-payments-ap2-protocol)
- [Developing an open standard for agentic commerce, Stripe](https://stripe.com/blog/developing-an-open-standard-for-agentic-commerce)
