# Privi Mainnet Launch Portal

Public prelaunch website. Features: animated responsive landing page, EVM wallet connection using injected provider (no seed phrases, no transactions), staking informational preview (disabled), signed-up-by-email early access request (mailto: opens user's mail app), and configurable launch countdown.

- Mainnet is **not** represented as live.
- PRVI staking, wallet deposits, token minting, APY estimates, airdrops, or token presales are **not** enabled.
- `PRIVI_LAUNCH_AT`: optional publicly announced ISO 8601 launch target; no countdown is shown before one is set. Countdown reaching zero does not automatically enable services.
- Signup is **email-request-only**: do not claim email is collected or registered unless the visitor actually sends the email and it is handled. No backend or database is attached.
- Existing EVM wallet connection is not a newly created Privi-native wallet. Users must not be prompted to enter private keys.
- Free Render: build `cd mainnet-portal && npm test`; start `node mainnet-portal/server.mjs`.

Before a real mainnet launch: publish verified chain ID, RPC, explorer, native wallet flow, audited staking contracts, independent validators, launch criteria, secure persistent signup database, consent records, and privacy policy.
