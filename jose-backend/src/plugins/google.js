// Google (Gmail / Calendar / Drive) via Google OAuth2.
// Docs: https://developers.google.com/identity/protocols/oauth2/web-server
//
// Requires, from a Google Cloud project with the OAuth consent screen
// configured:
//   GOOGLE_CLIENT_ID
//   GOOGLE_CLIENT_SECRET
// Scopes below cover reading/sending mail, reading/writing calendar
// events, and basic Drive file access — narrow this list to only what
// Jose actually needs before submitting for Google's OAuth verification,
// since broader ("sensitive"/"restricted") scopes trigger a stricter
// review (and for some scopes, a paid third-party security assessment).

import { postForm } from '../http-client.js';

const SCOPES = [
  'https://www.googleapis.com/auth/gmail.readonly',
  'https://www.googleapis.com/auth/gmail.send',
  'https://www.googleapis.com/auth/calendar.events',
  'https://www.googleapis.com/auth/drive.file',
].join(' ');

export const google = {
  id: 'google',
  name: 'Google (Gmail, Calendar, Drive)',
  setup: {
    registerUrl: 'https://console.cloud.google.com/apis/credentials',
    envVars: [
      { key: 'GOOGLE_CLIENT_ID', label: 'OAuth Client ID del proyecto en Google Cloud' },
      { key: 'GOOGLE_CLIENT_SECRET', label: 'OAuth Client Secret del proyecto en Google Cloud' },
    ],
    steps: [
      'Crea un proyecto en Google Cloud Console y habilita las APIs de Gmail, Calendar y Drive.',
      'Configura la pantalla de consentimiento OAuth (OAuth consent screen) con el nombre "Jose", logo y política de privacidad.',
      'Crea credenciales OAuth 2.0 de tipo "Aplicación web" y agrega el Redirect URI de abajo.',
      'Copia el Client ID y el Client Secret.',
      'Para publicarlo en Google Workspace Marketplace: habilita la "Google Workspace Marketplace SDK", completa la ficha de la app (capturas, descripción, alcance de los permisos) y envíala a revisión — Google revisa manualmente cada permiso solicitado, lo cual puede tardar días o semanas.',
    ],
  },
  isConfigured() {
    return Boolean(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET);
  },
  missingEnvVars() {
    return ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'].filter((k) => !process.env[k]);
  },
  buildAuthorizeUrl(state, redirectUri) {
    const params = new URLSearchParams({
      client_id: process.env.GOOGLE_CLIENT_ID,
      redirect_uri: redirectUri,
      response_type: 'code',
      scope: SCOPES,
      access_type: 'offline',
      prompt: 'consent',
      state,
    });
    return `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
  },
  async exchangeCode(code, redirectUri) {
    const { status, body } = await postForm('https://oauth2.googleapis.com/token', {
      client_id: process.env.GOOGLE_CLIENT_ID,
      client_secret: process.env.GOOGLE_CLIENT_SECRET,
      redirect_uri: redirectUri,
      grant_type: 'authorization_code',
      code,
    });
    if (status !== 200 || !body.access_token) {
      throw new Error(`Google token exchange failed: ${JSON.stringify(body)}`);
    }
    return {
      accessToken: body.access_token,
      refreshToken: body.refresh_token || null,
      expiresInSeconds: body.expires_in || null,
      raw: body,
    };
  },
};
