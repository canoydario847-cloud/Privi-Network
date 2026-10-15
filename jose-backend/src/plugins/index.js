import { whatsapp } from './whatsapp.js';
import { wechat } from './wechat.js';
import { mercadolibre } from './mercadolibre.js';

// The plugin registry. Adding a new app/plugin to Jose means writing one
// more file like whatsapp.js/wechat.js/mercadolibre.js (same shape: id,
// name, isConfigured, missingEnvVars, buildAuthorizeUrl, exchangeCode) and
// listing it here — the auth routes, connect/callback flow, encrypted
// token storage, and dashboard UI all pick it up automatically.
export const plugins = [whatsapp, wechat, mercadolibre];

export function getPlugin(id) {
  return plugins.find((p) => p.id === id) || null;
}
