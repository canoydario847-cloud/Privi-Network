# Listing Jose on Google Workspace Marketplace

This is the part I can't do for you — only the Google account that owns
the Cloud project can create the listing, and Google's review of it is a
manual process on their end. Everything below is prepared so the actual
submission is mostly copy-paste.

## 1. Set up the Google Cloud project (you, in Google Cloud Console)

1. Create a project at https://console.cloud.google.com.
2. Enable the APIs Jose uses: Gmail API, Google Calendar API, Google Drive API.
3. Configure the OAuth consent screen:
   - App name: `Jose`
   - User support email: (yours)
   - App logo: (use the Jose wordmark/brand — ask me to export one if needed)
   - App domain / homepage: `https://jose-site.onrender.com`
   - Privacy policy URL: `https://jose-site.onrender.com/privacy.html` (needs to be written — see note below)
   - Authorized domains: `onrender.com`
   - Scopes: the four listed in `src/plugins/google.js` — narrow this list if Jose doesn't actually need all of them yet, since broader scopes mean a stricter review.
4. Create OAuth 2.0 credentials (type: Web application).
   - Authorized redirect URI: `https://jose-backend-vbuu.onrender.com/callback/google`
5. Copy the Client ID and Client Secret and send them to me — I'll set them as `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` on the backend and the "Connect" button goes live immediately.

## 2. Submit for OAuth verification (you, in Google Cloud Console)

Any app requesting Gmail/Calendar/Drive scopes beyond the most basic ones
needs Google's review before it works for anyone outside your own test
users. Google will ask for:
- A demo video showing the OAuth consent flow and what the scopes are used for.
- Justification for each scope (why Jose needs it).
- The privacy policy URL above.

This step is entirely manual on Google's side and commonly takes days to
a few weeks.

## 3. Create the Marketplace listing (you, in Workspace Marketplace SDK)

Once the OAuth app is verified:

1. Enable "Google Workspace Marketplace SDK" in the same Cloud project.
2. Fill in the listing. Suggested copy (edit freely):

   **App name:** Jose

   **Short description (ES):**
   Jose entiende español, portugués, chino e inglés, y ayuda a leer y responder mensajes y documentos entre Sudamérica y China — directamente en Gmail y Calendar.

   **Short description (EN):**
   Jose understands Spanish, Portuguese, Chinese, and English, helping you read and reply to messages and documents between South America and China — right inside Gmail and Calendar.

   **Category:** Productivity / Communication

   **Screenshots:** take these from the live dashboard at
   `https://jose-backend-vbuu.onrender.com/dashboard.html` once Google is
   connected and showing "Conectado."

3. Submit for Marketplace review (separate from the OAuth review above).

## Still missing before you can submit

- A real privacy policy at `/privacy.html` on the backend (the content-site
  has a placeholder one — it needs real, accurate text once Jose actually
  stores Google data, describing what's stored, for how long, and how to
  delete it).
- App icons in the sizes Google's listing form requires (128×128 minimum).
- The OAuth consent screen's demo video.

Tell me when you're ready for any of these and I'll draft them.
