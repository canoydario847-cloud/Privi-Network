# PRVI coin portal — pre-launch website

A static, accessible, responsive PRVI coin-portal website.

## Current status

**Not a token sale. No payment, swap, custody, fundraising or exchange connection exists.**

- Proposed PRVI native financial mainnet is **not live**.
- Proposed supply cap **1,000,000,000 PRVI**, not minted or independently audited.
- Disposable developer tests have passed; these are **not public validators**.
- The four independent validator requirement is deferred by the owner, **not waived**.
- The BNB PRIV asset is separate, and valueless TEST / atest cannot be sold as PRVI.
- Purchase button is intentionally disabled (HTML disabled attribute).
- "Check wallet (read only)" only calls EIP-1193 \`eth_requestAccounts\` and
  \`eth_chainId\`, and does not send coins, request signatures or authorizations.
- Website does not collect wallet addresses, emails, telemetry or private keys.
- No addresses, price, payment methods, presale dates, exchange listings or
  fake discounts are fabricated.

## Preview

Open \`index.html\` locally or deploy the three static files in this folder
as a Vercel static project. No build pipeline or paid API key required.

## Future purchase activation — separate project / mandatory go-no-go

Do not simply remove the disabled button to enable coin sales. Before a
genuine purchase path can accept value:
1. Verify product and token issuance permissions and legal compliance for
   intended jurisdictions, including applicable securities, AML/KYC,
   consumer protection and payments requirements.
2. Activate independently audited and approved real PRVI mainnet and
   **enforced** 1B lifetime cap, or independently verify a distinct deployed
   token and its specific contract/chain with clear consumer disclosures.
3. Publish immutable signed chain identifiers, source/contract addresses,
   liquidity market route, contract audit and relevant operational ownership.
4. Implement a separate audited DEX or purchase integration with onchain
   network/contract/recipient/amount/gas preflight and anti-phishing UX.
5. Do not custody passwords, seed phrases or private keys. Allow transaction
   simulation and proper slippage/fee disclosure; do not promise returns.
6. Obtain operator acceptance and formal legal/security GO authorization.

**Launch cannot be certified by test scripts alone.** Reference readiness
work in [GitHub PR #13](https://github.com/canoydario847-cloud/Privi-Network/pull/13).

## Local QA
- Use Node 20+ to run \`node --check app.js\`
- Check mobile and desktop rendering; test browser console.
- Verify no \`eth_sendTransaction\`, \`eth_sendRawTransaction\`,
  \`personal_sign\` or spending approvals are used.
- Check that purchase CTA is disabled in production HTML.
- Keep noindex until launch-facing factual claims are reviewed.
