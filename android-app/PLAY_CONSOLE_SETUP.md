# Privi Android — Google Play Console handoff

**Status:** source-code preflight only. Not evidence of a verified developer account, a published store listing, signed app bundle, valid live Digital Asset Links, or Play review approval.

## Known project identifiers

- App name: **Privi**
- Android application ID / package: `us.priviflow.privi`
- Android launcher and requested origin: `https://privi-world.onrender.com/?source=app`
- Website origin in `android-app/app/src/main/res/values/strings.xml`: `privi-world.onrender.com`
- Site files in this repository: `sites/home/`
- Candidate privacy-policy location: `https://privi-world.onrender.com/privacy.html` (**unverified online**)
- Developer/support email in the site's privacy-policy source: `dariocanoy@priviflow.us`

**IMPORTANT:** The home site's source also uses `https://priviflow.us` as a canonical URL. Do not assume the two domains serve identical content. The Android TWA requires `/.well-known/assetlinks.json` to be reachable **on the exact launcher origin** `https://privi-world.onrender.com`. If changing the launcher to a custom domain, update its host, URL, and `assetStatements` together; verify Digital Asset Links on the new origin before release. Do not silently substitute another host.

## Work completed in source

- Gradle project under `android-app/` uses Android browser helper as a Trusted Web Activity; current `targetSdk` is 36.
- Web app manifest, app icons, privacy-policy source, and `assetlinks.json` are checked in under `sites/home/`.
- A GitHub Actions workflow builds an **unsigned** `.aab`; the private upload key is not in GitHub.
- Run `python3 android-app/scripts/play_preflight.py` and `python3 -m unittest discover -s android-app/tests -v`. These **offline** tests validate internal project consistency, not deployed behavior or Google review.

## Actions inside the developer's own Play Console

1. Open <https://play.google.com/console/>. Confirm that the correct developer account is verified and that this package ID is not already assigned to a different app.
2. Create a **free app** named `Privi` (not a game), or select the already-created Privi listing. Supply the developer contact address and accept applicable Google declarations. Play Console account creation/verification and any registration fee require the account owner.
3. In **Store presence**, supply app category, contact details, accurate store description, app icon, feature graphic, phone screenshots, and the public privacy-policy URL. Do not claim that a protected service or coin sale is active if it is not.
4. Complete **App content**: Data safety disclosures, access instructions for reviewers, content rating, ads declaration, target audience and age, and other relevant sections. Independently audit real site APIs, cookies, hosting, connected services, analytics, and payments before answering. The checked-in privacy policy is a draft source and is not a substitute for this audit.
5. Under **App integrity / Play App Signing**, obtain the actual **app-signing certificate SHA-256**, which may differ from the upload-key SHA. Compare against `sites/home/.well-known/assetlinks.json`; add/replace only the independently verified fingerprint. Keep every signing private key in secure offline/secret storage, never GitHub.
6. Verify from a real network and Chrome-compatible Android device that these URLs respond correctly, without redirecting to a different host: `https://privi-world.onrender.com/`, `https://privi-world.onrender.com/manifest.webmanifest`, `https://privi-world.onrender.com/.well-known/assetlinks.json`, `https://privi-world.onrender.com/privacy.html`. The asset-links file must use `application/json`; validate `delegate_permission/common.handle_all_urls`, package and Play signing fingerprint on-device.
7. Download the unsigned `.aab` GitHub Actions artifact. Sign the release bundle with **your upload key** in an approved build environment, without sharing keys in ChatGPT or GitHub. Verify that the `versionCode` increases for each release.
8. Upload the signed bundle to **Internal testing**, review Play Console pre-launch and policy results, and fix errors. When applicable, meet Google's closed-test enrollment/duration and production-access process before requesting a public release. Do not consider an internal test a public launch.

## Suggested Play listing text (review for accuracy)

**Title:** Privi

**Short description:** Explore AI agent audit records, verification tools and trust credentials.

**Full description:**

Privi connects people and developers to tools for recording and verifying AI agent activity. Explore product information and discover resources for audit records, signed proofs, trust credentials, manufacturing verification and developer integrations.

The Privi Android app opens the Privi website in a full-screen browser experience. Availability and access requirements differ between services. Some linked features are for developers or remain in testing. This app does not guarantee that all Privi network features, token markets, or payments are available.

**Support email:** `dariocanoy@priviflow.us` (verify mailbox ownership before submitting).

## Official references

- Create app: <https://support.google.com/googleplay/android-developer/answer/9859152>
- App testing and production access: <https://support.google.com/googleplay/android-developer/answer/14151465>
- Play App Signing: <https://support.google.com/googleplay/android-developer/answer/9842756>
- Trusted Web Activity and Digital Asset Links: <https://developer.chrome.com/docs/android/trusted-web-activity/android-for-web-devs>

**Do not enable:** PRVI / BNB PRIV / USDC deposits or other financial functionality just to satisfy app review. LIFE remains staging-only until reviewed separately.
