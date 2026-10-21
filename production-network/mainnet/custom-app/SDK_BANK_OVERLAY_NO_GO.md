# Pinned SDK native PRVI bank overlay — NONLIVE

The source-pinned disposable Cosmos SDK v0.54.3 overlay is NOT part of any
deployed production binary. It restricts raw `MintCoins`, native
`UncheckedSetBalance`, and now repeated raw `InitGenesis` calls. Unmodified
SDK `InitGenesis` directly writes both native account balances and total supply
without calling `MintCoins`.

The one-time marker is stored at key `ff 50 52 56 49 01` in the bank module
store, with the pinned SDK bank collections occupying prefixes 0 through 5.
It is written only after bank genesis succeeds and is checked BEFORE any
repeated call writes new balances or params. Because a full burn removes the
native supply entry, checking only current supply would be insufficient.
An existing upgraded network without this marker MUST NOT assume it is safe
to re-run genesis. Unreviewed migrations and any direct KV mutation remain
separate security blockers.

These checks cannot secure a Cosmos EVM app unless the hardened exact SDK
copy is linked into its executable, independently built and audited. CI
exercises only disposable local replacements, not financial issuance or
production network activation. Mainnet status remains NO-GO.
