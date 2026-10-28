# Privi Wallet

A website where people sign up with an email, create a PRIVI wallet on Base (or watch a wallet they already own), send and
receive PRIVI, USDC and ETH, and see the live status of the Privi Quantum Ledger.

## What it does

- **Accounts:** email + password (scrypt). Sessions are HttpOnly, SameSite=Strict cookies; every write needs the
  `X-Privi-Wallet: 1` header, so other sites can't post on a user's behalf.
- **Privi-held wallets** (custodial, `WALLET_CUSTODY=1`): a new secp256k1 key per wallet (`eth-account`), encrypted
  with AES-256-GCM under `WALLET_MASTER_KEY` and bound to its account and address. Sending and exporting the key
  both need the account password again.
- **Watch-only wallets:** add any Base address to see its balances. Privi never sees that key.
- **Limits:** per account, per rolling 24 hours (`WALLET_MAX_SEND_*_24H`), plus rate limits on sign-in and sends.
- **Account record:** every action (sign-up, wallet created, send, key export, wrong password) is appended to a
  per-account chain hashed with SHA3-512; `/api/activity` re-checks the whole chain.
- **Quantum Ledger:** `/api/quantum-ledger` shows a summary of `privi-ledger`'s `/quantum-ledger`, linking to Quantum Scan.

## Turning on Privi-held wallets

The service starts with `WALLET_CUSTODY=0`: sign-up and watch-only wallets work, wallet creation is off.

Before setting it to `1`:

1. Set `WALLET_MASTER_KEY` to 32+ random characters (`python3 -c "import secrets;print(secrets.token_urlsafe(48))"`)
   and keep a copy offline. Losing it, or the `/data` disk, loses every Privi-held wallet.
2. Holding customers' crypto can require money-transmitter licenses in many US states (FinCEN MSB registration,
   state licenses). Get a lawyer's view before taking deposits from the public.
3. Add backups of `/data/wallet.db` (Render disk snapshots).

## Run locally

```
pip install -e ".[dev]"
WALLET_SECURE_COOKIES=0 WALLET_CUSTODY=1 WALLET_MASTER_KEY=$(python3 -c "import secrets;print(secrets.token_urlsafe(48))") privi-wallet
pytest -q
```
