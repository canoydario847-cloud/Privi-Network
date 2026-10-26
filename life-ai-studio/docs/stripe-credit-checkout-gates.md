# Stripe Checkout for LIFE credits — test-mode integration contract

Status: DESIGN / NOT ACTIVATED. Stripe account connection alone does not enable payment fulfillment.

## Scope
- Sell **non-transferable LIFE AI service credits** (not PRVI, PRIV, USDC, or an investment).
- Start with Stripe **test mode** and one-time hosted Checkout Sessions. Do not put a secret key in frontend code or Git.
- Never enable the existing native PRVI/BNB payment switches as part of Stripe work.
- Set credit pack prices and exact credits per pack only after owner approval.

## Required server flow (not implemented yet)
1. Authenticated user selects an allowlisted pack ID. The server resolves the fixed price ID, currency and credit quantity from trusted configuration; never trust client-supplied amounts or credits.
2. Server creates a Stripe Checkout Session in payment mode, attaching an opaque internal member ID and pack ID as metadata. Use a fixed allowed success/cancel origin and authenticate all credit-account reads.
3. Verify the Stripe webhook signature against the **raw request body** and endpoint signing secret; reject malformed or replayed events. Never fulfill from a browser redirect.
4. For `checkout.session.completed`, independently retrieve and verify the Session's payment status, mode, amount, currency, expected price/line items and metadata before crediting.
5. In one durable DB transaction, insert a unique Stripe session/payment fulfillment record and the matching credit ledger entry. Duplicate webhook deliveries must not double-credit. Record refunds/disputes for review and define a reversal policy before launch.
6. Provide a customer receipt and ledger entry, with restricted admin reconciliation and monitoring for missed webhooks. Do not expose customer email, raw card data or secrets in logs.
7. Test successful, failed, expired, duplicate, reordered, refunded and disputed transactions in Stripe sandbox. Verify backup/restore preserves fulfillment uniqueness and credit balances.
8. Only after independent privacy, authorization, billing, financial safety and disaster-recovery review should live-mode checkout be considered.

## Explicitly excluded
- **Base PRIV purchase or swap:** No token sale, bridge, mint, DEX swap, on-ramp, custody, or payout is authorized by this document. Confirm the exact Base token address, ownership, liquidity, supported jurisdiction and counsel/processor approval before designing a separate crypto flow.
- No production Stripe keys, live payment links, real-money charges or user credits are created by this document.

Official integration references:
- https://docs.stripe.com/checkout/quickstart
- https://docs.stripe.com/webhooks/signature
- https://docs.stripe.com/payments/checkout/fulfill-orders

## Confirmed Stripe sandbox catalog (2026-10-25)
- Connected account: `Privi` (test mode only).
- Product: `prod_VVfuwqhQqW4N2u` — 100 non-transferable LIFE credits; **inactive**.
- One-time price: `price_1UUeYxBQR6zcBQ9LjHniLyKv` — USD 1000 cents ($10.00); **inactive**.
- No checkout links, sessions, webhooks, credit fulfillment or live products were enabled by this catalog setup.
- Activate **test-mode-only** checkout after signed webhook handling, durable idempotent ledger, account authorization and automated sandbox tests pass; do not activate real-money billing without a separate review.
