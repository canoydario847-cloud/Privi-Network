// WhatsApp Business (via Meta's Facebook Login for Business OAuth).
// Docs: https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow
//       https://developers.facebook.com/docs/whatsapp/embedded-signup (recommended path for
//       WhatsApp specifically — this classic OAuth flow is the general-purpose fallback)
//
// Requires, from a Meta developer account with a Business app set up:
//   WHATSAPP_CLIENT_ID      — the app's App ID
//   WHATSAPP_CLIENT_SECRET  — the app's App Secret
// The app must have the WhatsApp product added and request the
// `whatsapp_business_messaging` and `whatsapp_business_management` permissions
// (these require App Review from Meta before they work for real users, not
// just the app's own test users).

import { postForm } from '../http-client.js';

const GRAPH_VERSION = 'v19.0';

export const whatsapp = {
  id: 'whatsapp',
  name: 'WhatsApp Business',
  setup: {
    registerUrl: 'https://developers.facebook.com/apps/',
    envVars: [
      { key: 'WHATSAPP_CLIENT_ID', label: 'App ID de tu app de Meta' },
      { key: 'WHATSAPP_CLIENT_SECRET', label: 'App Secret de tu app de Meta' },
    ],
    steps: [
      'Crea una cuenta de Meta for Developers y una app de tipo "Business".',
      'Dentro de la app, agrega el producto "WhatsApp".',
      'En Configuración básica, copia el App ID y el App Secret.',
      'Pide a Meta la revisión de los permisos whatsapp_business_messaging y whatsapp_business_management — sin esta revisión, solo funciona con usuarios de prueba de tu propia app.',
    ],
  },
  isConfigured() {
    return Boolean(process.env.WHATSAPP_CLIENT_ID && process.env.WHATSAPP_CLIENT_SECRET);
  },
  missingEnvVars() {
    return ['WHATSAPP_CLIENT_ID', 'WHATSAPP_CLIENT_SECRET'].filter((k) => !process.env[k]);
  },
  buildAuthorizeUrl(state, redirectUri) {
    const params = new URLSearchParams({
      client_id: process.env.WHATSAPP_CLIENT_ID,
      redirect_uri: redirectUri,
      state,
      response_type: 'code',
      scope: 'whatsapp_business_messaging,whatsapp_business_management',
    });
    return `https://www.facebook.com/${GRAPH_VERSION}/dialog/oauth?${params.toString()}`;
  },
  async exchangeCode(code, redirectUri) {
    const { status, body } = await postForm(
      `https://graph.facebook.com/${GRAPH_VERSION}/oauth/access_token`,
      {
        client_id: process.env.WHATSAPP_CLIENT_ID,
        client_secret: process.env.WHATSAPP_CLIENT_SECRET,
        redirect_uri: redirectUri,
        code,
      }
    );
    if (status !== 200 || !body.access_token) {
      throw new Error(`WhatsApp token exchange failed: ${JSON.stringify(body)}`);
    }
    return {
      accessToken: body.access_token,
      expiresInSeconds: body.expires_in || null,
      raw: body,
    };
  },
};
