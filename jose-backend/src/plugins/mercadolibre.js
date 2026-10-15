// Mercado Libre OAuth2 (Authorization Code flow).
// Docs: https://developers.mercadolibre.com.ar/en_us/authentication-and-authorization
//
// Requires, from a Mercado Libre developer application tied to a seller
// account:
//   MERCADOLIBRE_CLIENT_ID
//   MERCADOLIBRE_CLIENT_SECRET
// Optional: MERCADOLIBRE_SITE (default "com.ar"; e.g. "com.br" for Brazil,
// "com.mx" for Mexico) — the authorize host differs per country site.

import { postForm } from '../http-client.js';

function authHost() {
  const site = process.env.MERCADOLIBRE_SITE || 'com.ar';
  return `https://auth.mercadolibre.${site}`;
}

export const mercadolibre = {
  id: 'mercadolibre',
  name: 'Mercado Libre',
  isConfigured() {
    return Boolean(process.env.MERCADOLIBRE_CLIENT_ID && process.env.MERCADOLIBRE_CLIENT_SECRET);
  },
  missingEnvVars() {
    return ['MERCADOLIBRE_CLIENT_ID', 'MERCADOLIBRE_CLIENT_SECRET'].filter((k) => !process.env[k]);
  },
  buildAuthorizeUrl(state, redirectUri) {
    const params = new URLSearchParams({
      response_type: 'code',
      client_id: process.env.MERCADOLIBRE_CLIENT_ID,
      redirect_uri: redirectUri,
      state,
    });
    return `${authHost()}/authorization?${params.toString()}`;
  },
  async exchangeCode(code, redirectUri) {
    const { status, body } = await postForm('https://api.mercadolibre.com/oauth/token', {
      grant_type: 'authorization_code',
      client_id: process.env.MERCADOLIBRE_CLIENT_ID,
      client_secret: process.env.MERCADOLIBRE_CLIENT_SECRET,
      code,
      redirect_uri: redirectUri,
    });
    if (status !== 200 || !body.access_token) {
      throw new Error(`Mercado Libre token exchange failed: ${JSON.stringify(body)}`);
    }
    return {
      accessToken: body.access_token,
      refreshToken: body.refresh_token,
      expiresInSeconds: body.expires_in || null,
      userId: body.user_id,
      raw: body,
    };
  },
};
