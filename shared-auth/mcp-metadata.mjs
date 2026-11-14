// RFC 9728 protected-resource metadata and OAuth discovery challenge for MCP.
// Mount at /.well-known/oauth-protected-resource/mcp on the gateway host.
export function protectedResourceMetadata({ resource, authorizationServers, scopesSupported = [] }) {
  if (!resource?.startsWith('https://') || !Array.isArray(authorizationServers) || !authorizationServers.length ||
      authorizationServers.some(x => typeof x !== 'string' || !x.startsWith('https://'))) {
    throw new Error('HTTPS resource and authorization servers required');
  }
  return {
    resource,
    authorization_servers: authorizationServers,
    scopes_supported: scopesSupported,
    bearer_methods_supported: ['header']
  };
}
export function oauthChallenge({ resourceMetadataUrl, scope }) {
  if (!resourceMetadataUrl?.startsWith('https://')) throw new Error('HTTPS resource metadata URL required');
  return 'Bearer resource_metadata="' + resourceMetadataUrl + '"' + (scope ? ', scope="' + scope + '"' : '');
}
export function sendProtectedResourceMetadata(res, metadata) {
  res.writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' });
  res.end(JSON.stringify(metadata));
}
