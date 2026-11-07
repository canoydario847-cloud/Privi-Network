# Privi RealCheck for Android

A Trusted Web Activity (TWA) that opens Privi RealCheck (`https://privi-quantum.onrender.com/real`) full screen in
Chrome. Passkeys (Face ID / fingerprint / screen lock) work inside it the same as in Chrome.

- Package: `us.priviflow.realcheck`
- Origin: `https://privi-quantum.onrender.com` (the Quantum server serves `/.well-known/assetlinks.json` for it)
- Built by `.github/workflows/android-realcheck.yml` (unsigned unless signing secrets are set)

## Release steps (owner only)

1. **Upload key.** On your computer: `keytool -genkeypair -v -keystore realcheck-upload.jks -alias upload -keyalg RSA -keysize 2048 -validity 10000`.
   Keep the file and password safe and off GitHub. Optionally add GitHub secrets `REALCHECK_KEYSTORE_B64`
   (base64 of the .jks) and `REALCHECK_KEYSTORE_PASSWORD` so the workflow signs the bundle for you.
2. **Build.** GitHub → Actions → "Privi RealCheck Android app" → Run workflow. Download the `.aab` from the run.
3. **Play Console** (account PriviKing1) → Create app → "Privi RealCheck", App, Free to download (the service itself
   is a paid company subscription bought on the web, which is allowed for B2B services) → upload the .aab to
   **Internal testing**.
4. **App signing fingerprint.** Play Console → Test and release → App integrity → copy the **App signing key
   SHA-256**. In Render, set `REALCHECK_ANDROID_SHA256` on privi-quantum to that value (comma-separate if you add
   the upload-key SHA-256 too). This makes the app open without a browser bar.
5. **Store listing, Data safety, content rating, privacy policy URL** (`https://privi-world.onrender.com/privacy.html`),
   then roll out. Personal developer accounts must run a **closed test with at least 12 testers for 14 days**
   before Google allows a production release.

## Suggested listing

**Title:** Privi RealCheck
**Short description:** Stop deepfake and voice-clone requests for money. Confirm it's really them.
**Full description:** Someone calls, texts or emails pretending to be your boss and asks for a wire, gift cards or a
password reset. With Privi RealCheck your company sends a check to the real person's own phone, and only their
Face ID, fingerprint or screen lock can answer "Yes, that was me" or "No, that's not me". Every answer comes back as
a signed receipt you can keep. For companies with a Privi RealCheck subscription ($49/month for up to 25 people at
privi-hub.onrender.com/pay). Privi stores only a passkey's public key, never your face or fingerprint.
