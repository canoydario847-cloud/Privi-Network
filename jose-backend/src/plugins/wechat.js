// WeChat (Official Account platform) OAuth2 web login.
// Docs: https://developers.weixin.qq.com/doc/offiaccount/OA_Web_Apps/Wechat_webpage_authorization.html
//
// Requires, from a verified WeChat Official Account (generally requires a
// China-registered business entity to complete verification):
//   WECHAT_APP_ID      — the Official Account's AppID
//   WECHAT_APP_SECRET  — the Official Account's AppSecret

import { getJson } from '../http-client.js';

export const wechat = {
  id: 'wechat',
  name: 'WeChat',
  isConfigured() {
    return Boolean(process.env.WECHAT_APP_ID && process.env.WECHAT_APP_SECRET);
  },
  missingEnvVars() {
    return ['WECHAT_APP_ID', 'WECHAT_APP_SECRET'].filter((k) => !process.env[k]);
  },
  buildAuthorizeUrl(state, redirectUri) {
    const params = new URLSearchParams({
      appid: process.env.WECHAT_APP_ID,
      redirect_uri: redirectUri,
      response_type: 'code',
      scope: 'snsapi_userinfo',
      state,
    });
    return `https://open.weixin.qq.com/connect/oauth2/authorize?${params.toString()}#wechat_redirect`;
  },
  async exchangeCode(code) {
    // WeChat's token endpoint takes query params, not a POST body.
    const params = new URLSearchParams({
      appid: process.env.WECHAT_APP_ID,
      secret: process.env.WECHAT_APP_SECRET,
      code,
      grant_type: 'authorization_code',
    });
    const { status, body } = await getJson(
      `https://api.weixin.qq.com/sns/oauth2/access_token?${params.toString()}`
    );
    if (status !== 200 || body.errcode || !body.access_token) {
      throw new Error(`WeChat token exchange failed: ${JSON.stringify(body)}`);
    }
    return {
      accessToken: body.access_token,
      refreshToken: body.refresh_token,
      expiresInSeconds: body.expires_in || null,
      openId: body.openid,
      raw: body,
    };
  },
};
