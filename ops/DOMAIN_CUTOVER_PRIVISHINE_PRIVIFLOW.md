# Privi custom-domain cutover to existing Render static sites

Status: DNS cutover NOT completed. 2026-11-12/13 verification found 14 Render static site homepages returned 200 HTML, but custom domains have not yet been confirmed on their Render service settings or verified with registrar DNS.

## Goals and known hosts

| Desired public hostname | Existing Render destination |
| --- | --- |
| privishine.info and www.privishine.info | privi-world.onrender.com |
| priviflow.us and www.priviflow.us (only if intentionally replacing the current IONOS site content with Privi World) | privi-world.onrender.com |
| fortress.privishine.info | privi-fortress.onrender.com |
| passport.privishine.info | privi-passport.onrender.com |
| kya.privishine.info | privi-kya.onrender.com |
| mandates.privishine.info | privi-mandates.onrender.com |
| gov.privishine.info | privi-gov.onrender.com |
| guard.privishine.info | privi-guard-814f.onrender.com |
| live.privishine.info | privi-live.onrender.com |
| hub.privishine.info | privi-hub.onrender.com |
| chainflow.privishine.info | privi-chainflow.onrender.com |
| developers.privishine.info | privi-developers.onrender.com |
| car.privishine.info (proposed; not a confirmed current hostname) | privi-car-trace.onrender.com |
| car-demo.privishine.info (proposed; not a confirmed current hostname) | privi-car-demo.onrender.com |
| jose.privishine.info (proposed; not a confirmed current hostname) | jose-site.onrender.com |

All targets already exist in original Render workspace tea-db83bk8n74is73dklo00. Do NOT redeploy or recreate these services in the empty alternate workspace without an explicit data/hosting migration plan.

## Migration checklist

1. Export existing DNS zones for both domains, especially MX, SPF/DKIM, DMARC, TXT verification and CAA records. Do not switch nameservers or overwrite email records.
2. In the **existing** Render static site's Settings > Custom Domains, add each desired hostname to its corresponding existing service. Render automatically pairs root/www in many cases; check actual service settings to avoid duplicate domain charges. Check plan's included custom-domain count and charges before adding optional hosts.
3. Set DNS at the **current authoritative DNS provider** for each domain:
   - For subdomains and `www`, CNAME to the exact Render host from the table, after removing conflicting A/AAAA/CNAME entries for that host only.
   - For apex `@`, use provider-supported ALIAS/ANAME to the Render hostname; if unavailable and not Cloudflare, Render currently documents A `216.24.57.1`. If Cloudflare, use a DNS-only flattened CNAME to the Render hostname. Verify instructions with the current Render dashboard before making changes.
   - Remove old IPv6 AAAA records for cutover web hosts, which Render does not serve. Preserve unrelated DNS records and email service.
4. In Render press **Verify** on each custom domain and wait for managed TLS issuance. Keep `*.onrender.com` fallback URLs enabled.
5. Independently check DNS, HTTPS status, HTML, product navigation, /start/, /car/, signup/payment flows and cookies. Do not claim a healthy API implies payment/authentication works.
6. For `priviflow.us`, current IONOS site content and HTTP 423 must be assessed/exported if the goal is to preserve that exact website. Pointing the domain to Privi World will intentionally replace the served site; it is not a byte-for-byte IONOS migration.

### Evidence

GitHub Actions workflow `.github/workflows/privi-static-pages-check.yml` verifies the public static homepages and prints current DNS resolution. Initial run: https://github.com/canoydario847-cloud/Privi-Network/actions/runs/43343049912 (all 14 existing Render static roots returned 200 HTML). That run reported missing DNS for www.privishine.info and product subdomains; privishine.info root and priviflow.us still resolved to non-Render endpoints.

## Not included in this change

No DNS registrar modifications, domain ownership transfers, Render custom-domain registration, wallets, ledger writes or mainnet launch are performed by this documentation. The connected Render app does not expose the Custom Domains write endpoint and does not provide registrar/DNS editing.
