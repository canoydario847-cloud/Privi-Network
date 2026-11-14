// Central policy registry: intended audiences/scopes, NOT a claim that services are integrated.
// A resource server must check the exact audience and required scopes for each route.
export const SERVICES = Object.freeze({
  gateway: { audience: 'privi-mcp-gateway', resource: 'https://privi-ai-21-gateway.onrender.com/mcp', scopes: ['privi:tools:execute'] },
  ledger: { audience: 'privi-ledger', scopes: ['privi:ledger:read', 'privi:ledger:write'] },
  life: { audience: 'privi-life', scopes: ['privi:life:read', 'privi:life:write'] },
  jose: { audience: 'privi-jose', scopes: ['privi:jose:invoke'] },
  mainnet: { audience: 'privi-mainnet', scopes: ['privi:chain:read'] }
});
export function servicePolicy(name) {
  if (!Object.hasOwn(SERVICES, name)) throw new Error('Unknown Privi service');
  return SERVICES[name];
}
export function requiredScopes(name, requested) {
  const allowed = new Set(servicePolicy(name).scopes);
  if (!Array.isArray(requested) || requested.some(scope => !allowed.has(scope))) {
    throw new Error('Unrecognized OAuth scope');
  }
  return requested;
}
