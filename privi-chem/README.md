# Privi Chem — chemistry evidence, project receipts and token-linked hashes

Privi Chem stores **simulation predictions** and **real laboratory observations** as **different evidence types** inside a chemistry project. Every entry includes a customer-supplied SHA-256 source digest and optional code digest, a canonical JSON payload hash, an append-only per-project hash link, and a unique **Privi Data Token (PDT) receipt ID**.

**Important:** A PDT is presently a non-transferable off-chain **data receipt**, not minted cryptocurrency, an ERC-721, or existing Privi mainnet coin. The report exports digests for future independently verifiable anchoring, but never claims an on-chain transaction was performed. Do not confuse a database token ID with a liquid token or asset. Existing PRIV/PRVI tokens are untouched.

No hazardous synthesis, chemical reaction procedure, instrument control or experiment execution is performed. Formula is descriptive metadata. Measurements must be supplied by a trusted laboratory, not inferred as experimentally confirmed from a simulation.

## Project workflow

1. Create project: `POST /v1/projects` with `{"title":"Water properties study","formula":"H2O"}`.
2. Record simulation: `POST /v1/projects/{id}/entries` with type `simulation`, method, numeric data with units, source SHA-256 and optional code SHA-256.
3. Record real observations separately using type `measurement`. Add a real signed lab report's file hash; the API does **not** independently validate lab credentials.
4. Get a project report: `GET /v1/projects/{id}/report`. It includes both evidence types, payload hashes, the hash chain, the report SHA-256 and explicit `blockchain_anchor_status: not_submitted`.
5. Look up a Privi data receipt: `GET /v1/tokens/{token_id}`; contains formula and code/source commitment hashes, but not a financial token or actual token mint.

All project and token endpoints require `Authorization: Bearer <private-key>`, where the key is configured using `PRIVI_CHEM_API_KEYS`. Keys are per-tenant and should be strong and distinct. The API stores only their SHA-256 digest as the tenant identifier, not their plaintext value. Never publish access keys. No public project discovery or sharing.

Example:

```bash
curl -X POST https://YOUR-CHEM-SERVICE/v1/projects \
  -H 'Authorization: Bearer YOUR_PRIVATE_KEY' \
  -H 'Content-Type: application/json' \
  --data '{"title":"Water properties study","formula":"H2O"}'
```

Then submit an entry, replacing the example source hash with your actual file digest:

```json
{
  "source_type": "simulation",
  "method": "recorded numerical model version 1",
  "data": { "temperature": {"value": 298.15, "unit": "K"} },
  "source_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "code_sha256": null,
  "notes": "Predicted result, NOT a laboratory measurement"
}
```

## Reliability and security

The service uses a **single-instance SQLite database**. Deploy it only with a durable disk mounted at `/data` and `PRIVI_CHEM_DB_PATH=/data/privi-chem.sqlite3`. A free instance without a persistent disk must not be used to hold actual research records. Production requires authentication, TLS termination, backup/recovery, quotas, privacy review and external verification. A recorded file hash does not prove that the input is truthful, and a local hash chain is not independently immutable.

The current proof of concept **does not anchor on the blockchain**. An external Privi Anchor transaction and independently checked chain receipt must be added before representing any report as on-chain. Actual token issuance would require a reviewed NFT/data-rights contract, authorization, chain/network, metadata pointer and transaction receipt; this service deliberately does not mint financial or transferable tokens.

## Local tests

```bash
cd privi-chem
python -m unittest discover -s tests -v
```

Copyright (c) 2026 Privi World Corp.
