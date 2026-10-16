# Legacy Privi Network — persistent storage safety

**Current live Railway service Privi-Network: NO volume attached. Do not attach /data blindly.** Its Node.js process uses RAILWAY_VOLUME_MOUNT_PATH when a volume is attached. An empty volume can cause a fresh genesis and a newly generated validator identity.

## Read-only backup of public block history

```bash
python3 production-network/ops/legacy_snapshot.py --out privi-public-records.json
```

This verifies SHA-256 block links and copies public blocks via the explorer API. It is NOT a restorable validator backup. The original `validator.pem` is private, and must be preserved securely before any volume migration.

## Safely preserve ledger and validator private key

An authorized operator must locate the original container's `chain.json`, `validator.pem`, and optional `user-wallet.pem` before changing the active service. Never paste these keys into chat or GitHub. Schedule a write pause, stop the old process, take and verify an encrypted private backup, and only with the **source files still accessible** copy them to an attached volume.

```bash
node production-network/ops/legacy_state_copy.js /path/to/old/privi-data /data/privi-data
```

The copy tool refuses overwrite, validates block hashes and validator signatures, and copies files mode 0600. The target must not already exist. An old ephemeral container's files cannot be copied *after it is destroyed*. Never treat a newly generated genesis as continuation of the old chain.

**Deploy only after** original validator ID and latest block hash match the copied state. Persist private keys and chain data with secure volume, encrypted offsite backups and recovery drills. Keep a single writer/replica for the original JavaScript node. The private key must never appear in the explorer or logs.

If it is already impossible to retrieve original private state, continue running the existing experimental explorer without pretending it is durable; any new chain must use a new chain identity and a visible genesis migration notice.