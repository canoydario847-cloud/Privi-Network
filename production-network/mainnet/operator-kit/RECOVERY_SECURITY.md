# Privi validator cold recovery — independent operator review (draft)

**Status: REVIEW-ONLY. No backup or recovery action here authorizes PRVI mainnet start.** Privi's 1-billion-native-PRVI Cosmos EVM network is still design-stage; the Railway TEST prototype is valueless and unrelated. No testnet/CI signing key can ever become a PRVI production key.

## What this prevents

Cosmos/Comet validators can be slashed for double signing at the same height/round/step. A VM disk image or a clone of `priv_validator_key.json` does not safely replace a validator on another machine. If the original signer is still operating and the backup copy is activated, two instances can sign conflicting votes. If the backup's `priv_validator_state.json` is stale, the restored signer may also sign a height/round/step it already signed.

**Never run two copies of one consensus identity.** Never restore an old last-sign file to an active signer. Keep signing keys and last-sign material out of GitHub, issue comments, CI artifacts, Railway, chats, cloud object storage without verified operator-managed encryption, and support tickets.

## Required operator-controlled handoff

1. Declare a maintenance incident; stop the original validator and ALL attached remote/HSM signers. Establish **positive fencing** using infrastructure ownership controls and independent evidence. If the old signer cannot be definitively disabled, do not launch its replacement.
2. Confirm the **independently held approved operator identity and network IDs**, audited binary digest, canonical genesis digest and expected consensus public key from the approved release, not from the untrusted backup.
3. Protect the original `priv_validator_key.json` and `priv_validator_state.json` with operator-controlled offline encryption and access policies. Restore only onto a secured, OFFLINE host in a dedicated permissions-restricted directory. Do **not** clone a validator while the original is alive.
4. Capture a **fresh, operator-signed public recovery assertion** with the original signer and remote signer both declared fenced, matching genesis, the original consensus public key and a **minimum required last-sign checkpoint** known to be at least as recent as the latest vote. A signature proves the operator made the statement; it does **not** independently prove either signer is really disabled.
5. Run `recovery_preflight.py` offline against the **restored but NOT running** validator home, using trusted public keys supplied separately by the independent operator roster. The command reads but never writes private files, starts nodes, copies keys, opens RPC or creates assets.

   ```bash
   python3 operator-kit/recovery_preflight.py \
     --home /secure/offline-restored-validator-home \
     --signed-assertion /secure/public-recovery-attestation.json \
     --trusted-operator-ed25519-hex '<trusted-operator-public-key-hex>' \
     --trusted-consensus-ed25519-hex '<reviewed-consensus-public-key-hex>' \
     --trusted-chain-id '<independently-approved-mainnet-chain-id>'
   ```

6. The output is **OFFLINE_RECOVERY_EVIDENCE_CHECK_PASSED_NOT_AUTHORIZED_TO_START**, not a release ticket. Separately verify original signer destruction/fencing, remote signer disablement, authorization signatures, last-sign high watermark sourced from independent evidence, network liveness and production incident runbook approvals. A **human-led operator launch gate** must remain locked absent these verified facts. The helper cannot infer them from an offline file.
7. Only an audited operator-managed external runbook may schedule the fenced signer replacement; never automate this through ChatGPT or GitHub Actions. After activation, verify only one signer holds the original identity, chain continuity and correct Comet height, and monitor for duplicate vote alerts. If uncertain, stop and perform incident response.

## Signed public assertion schema

The signed JSON has exactly `statement` and `signature_b64`. Signature: Ed25519 over ASCII JSON produced with keys sorted, no whitespace (`json.dumps(statement,sort_keys=True,separators=(',',':'),ensure_ascii=True)`). Statement has these fields and nothing else:

| Field | Constraint |
| --- | --- |
| `schema_version` | `1` |
| `status` | `COLD_RECOVERY_OPERATOR_ATTESTATION_NO_AUTOMATIC_START` |
| `operator_id` | verified operator roster identifier |
| `cosmos_chain_id` | independently approved unique chain ID |
| `genesis_sha256` | exact lowercase SHA-256 of restored `genesis.json` |
| `consensus_pubkey_b64` | approved original 32-byte Ed25519 public key |
| `minimum_sign_state` | object with `height`, `round`, `step` monotonic vote watermark |
| `original_signer_fenced_claim` | `true`, the operator's statement, not verified fact |
| `remote_signer_fenced_claim` | `true`, the operator's statement, not verified fact |
| `created_at`, `expires_at` | UTC `Z` timestamps; validity at most 24 hours |
| `nonce` | freshly generated lowercase hex, 32–64 characters |

Do **not** supply a production attestation or private key in this repository. A signed report must be matched to a trusted **external** operator public key, not a key copied from the same attestation. Replay prevention across different restorations, accurate last-sign watermark and real-world fencing require out-of-band operator coordination. This static tool cannot guarantee any of them.

## CI coverage and limits

`test_operator_recovery_preflight.py` generates temporary synthetic signing identities and tests valid read-only review plus invalid signatures, stale state, changed genesis/pubkey, expired or missing claims, too-broad file permissions, and symlinks. This is strictly an offline negative-test suite: no real backup is produced, no signer key is shipped, no recovery goes live, and external validators are **not** provisioned. It does not test HSM, snapshot encryption, multisig vault custody, network partitions, cryptographic double-sign attempts, slashing or production recovery certification.

**Privi financial mainnet remains OFF** until seven truly independent validator operators, audited genesis and supply controls, verified beneficial owners, legally scoped reviews and signed final launch approval are available.
