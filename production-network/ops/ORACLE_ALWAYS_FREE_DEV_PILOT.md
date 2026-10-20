# Free-first Privi developer pilot — Oracle Always Free (October 2026)

**Status:** PLAN AND STATIC CI POLICY ONLY; **0 cloud machines provisioned**, **0 production validators**. No financial PRVI issued. Keep TEST/`atest` permanently valueless.

## Decision and current official limits

Oracle Cloud Infrastructure **Always Free** in the tenancy **home region** (not the $300/30-day Free Trial credits). Current official docs revised **June 2026** allow:
- Ampere A1 Arm64 Compute: **2 OCPUs and 12 GB RAM TOTAL across up to two A1 instances** (1,500 OCPU-hours and 9,000 GB-hours/month allowance).
- 200 GB total Always Free block volume across boot and data volumes; each VM uses a boot disk of **at least approximately 50 GB**.
- Oracle's tiny AMD E2 Micro allowance is separate but provides just **1GB RAM and 1/8 OCPU per VM**; these are not adequate dedicated production Cosmos EVM validators.
- Always Free compute must be in the tenancy's **home region**; lack of free capacity can prevent provisioning and idle resources may be reclaimed.

**Sources:** [Oracle Always Free current limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm), [Oracle Free Tier terms](https://docs.oracle.com/iaas/Content/FreeTier/freetier.htm). Old posts claiming 4 A1 OCPU / 24GB Always Free are **OUTDATED**. The limits were cut during June 2026. Pricing and eligibility must be verified in the OCI console before any transaction.

## Phase 0: already available for no hosting subscription

The GitHub Actions disposable four-container Cosmos EVM developer cluster is the current reproducible CI baseline; CI allowance may be subject to GitHub plan limits. It has one runner/one failure domain, upstream `evmd` and `atest`, and does **NOT** count as four independent physical hosts or production PRVI validators.

## Phase 1: proposed single-host Always Free pilot

[Candidate configuration](oracle-always-free-pilot.candidate.json) is deliberately non-deployable and contains **no OCI account identifiers or credentials**.

| Setting | Intended configuration |
| --- | --- |
| Provider/tier | OCI **Always Free** only; avoid upgrades and use of trial-credit-only compute |
| VM | One `VM.Standard.A1.Flex` / Ubuntu Arm64, **2 OCPU, 12 GB RAM, 100 GB boot disk** |
| Network | Home region private VCN; outbound traffic may need reviewed egress; disable public RPC, publicly accessible validator management and public SSH by default |
| Binary | Tested cross-compiled Arm64 **developer** build in a valueless sandbox, after reviewing resource consumption and network behavior |
| Authentication | OCI Console owner-controlled MFA; SSH keys and privileged configuration **NEVER** pasted into GitHub/chat |
| Token/network | `atest` only and **never** `aprvi` financial genesis, mint, treasury, production signer or token transfer |
| Spend controls | No Pay As You Go upgrade; review each OCI resource's Always Free eligibility; cost alert and tenancy quotas are useful but **not a hard guarantee of zero charges** |

This machine is for compile/smoke/RPC compatibility, not the final four-owner-host consensus topology. OCI Arm capacity may be unavailable and the service may reclaim idle machines; nothing is provisioned until owner account setup and explicit confirmation.

## Phase 2: still Always Free, if available

**Instead of one large A1 instance**, redistribute the same allowance across **two A1 VMs at 1 OCPU, 6 GB RAM, ~50 GB boot each**, in available separate availability domains (if supported in the same home region). Test two-host networking and valueless chains. It still is not the required **four hardened production validator hosts** and has limited memory/disk performance.

## Phase 3: four owner-operated production hosts (later)

After test performance and an independently assessed security report, upgrade to **four sufficiently resourced and physically separated hosts**, one operator Privi World Corp, four independent consensus keys/hosts/sentries. The owner-operated architecture remains **centrally administered and permissioned**, not four independent operator organizations. Obtain actual priced quotes and explicit billing authorization before ordering.

## Free-tier guard and local acceptance check

```sh
python3 production-network/ops/oracle_free_pilot_preflight.py \
  production-network/ops/oracle-always-free-pilot.candidate.json
python3 -m unittest discover -s production-network/ops -p 'test_oracle_free_pilot_preflight.py' -v
```

The first tool is **static only** and intentionally prevents provisioning, real PRVI issuance, paid tiers or access-control deviations. It checks published resource ceilings; it cannot guarantee account-specific free eligibility, physical hardware separation, cloud capacity, or bill amounts.

## What the account owner must do before hosting starts

1. Visit [Oracle Cloud Free Tier](https://www.oracle.com/cloud/free/), create or select a **Free Tier** tenancy with company-controlled sign-in and MFA. Oracle may require **phone and payment-card verification**; official policy says the card is not charged unless you upgrade the account. Do **not** share your payment details or credentials in chat.
2. Choose your home region carefully: Always Free A1 compute and storage have to be in **that** region. Confirm account eligibility and Arm capacity, and do not select non-free shape, premium image, GPU, premium storage or public paid extras.
3. Only when the intended machine clearly shows **Always Free Eligible** and its full configuration shows no billable extras should you authorize VM provisioning. The model/chat environment does **not** currently have a connected Oracle OCI Compute account or the ability to create this VM.
4. Once OCI tenancy is available, update just the **non-secret** host attestation/evidence. Install only the reviewed valueless development binary. Never publish validator signing keys or use the four-node production manifest on the free pilot.

**Financial PRVI mainnet remains NO-GO.** Required gates include fully guarded issuance, custom app genesis/upgrade/IBC/VM tests, third-party security audit, four independently hosted but same-owner validators and signed release/genesis.
