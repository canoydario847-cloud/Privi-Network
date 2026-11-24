import { readFileSync } from 'node:fs';

const resourceUri = 'ui://privi-voice/player.html';
const html = readFileSync(new URL('./privi-voice-player.html', import.meta.url), 'utf8');
const protocolVersions = ['2025-11-25', '2025-06-18', '2025-03-26'];
const maxText = 10000;

const tool = {
  name: 'open_voice_player',
  title: 'Open Privi Voice',
  description: 'Open a player to read text aloud only when the user explicitly requests Privi Voice. Pass the specific reply or excerpt requested, or omit text to open an empty player for manual paste. Do not include unrelated conversation text.',
  inputSchema: {
    type: 'object',
    properties: { text: { type: 'string', maxLength: maxText, description: 'Only the text the user asked to hear.' } },
    additionalProperties: false,
  },
  annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false },
  _meta: {
    securitySchemes: [{ type: 'noauth' }],
    ui: { resourceUri },
    'openai/outputTemplate': resourceUri,
    'openai/toolInvocation/invoking': 'Opening Privi Voice',
    'openai/toolInvocation/invoked': 'Privi Voice is ready',
  },
};

const resource = { uri: resourceUri, name: 'Privi Voice player', mimeType: 'text/html;profile=mcp-app' };

function send(res, status, body) {
  res.writeHead(status, { 'Cache-Control': 'no-store', 'Content-Type': 'application/json; charset=utf-8' });
  res.end(body === undefined ? undefined : JSON.stringify(body));
}

export async function handleVoiceMcp(req, res, requestOrigin, readBody) {
  const origin = req.headers.origin;
  if (origin && ![requestOrigin, 'https://chatgpt.com', 'https://chat.openai.com'].includes(origin)) {
    return send(res, 403, { error: 'Unsupported origin.' });
  }
  if (req.method !== 'POST') {
    res.setHeader('Allow', 'POST');
    return send(res, 405, { error: 'Use POST.' });
  }
  const version = req.headers['mcp-protocol-version'];
  if (version && !protocolVersions.includes(version)) return send(res, 400, { error: 'Unsupported MCP version.' });

  let msg;
  try {
    msg = await readBody(req, 70000);
  } catch (error) {
    return send(res, error instanceof RangeError ? 413 : 400, {
      jsonrpc: '2.0', id: null, error: { code: -32700, message: 'Unable to read request.' },
    });
  }
  const validId = typeof msg?.id === 'string' || Number.isInteger(msg?.id);
  const id = validId ? msg.id : null;
  const ok = result => send(res, 200, { jsonrpc: '2.0', id, result });
  const fail = (code, message, status = 200) =>
    send(res, status, { jsonrpc: '2.0', id, error: { code, message } });

  if (msg?.jsonrpc !== '2.0' || typeof msg.method !== 'string') return fail(-32600, 'Invalid request.', 400);
  if (!validId) {
    if (msg.id !== undefined) return fail(-32600, 'Invalid request ID.', 400);
    return send(res, 202);
  }
  switch (msg.method) {
    case 'initialize':
      return ok({
        protocolVersion: protocolVersions.includes(msg.params?.protocolVersion) ? msg.params.protocolVersion : protocolVersions[0],
        capabilities: { tools: {}, resources: {} },
        serverInfo: { name: 'privi-voice', title: 'Privi Voice', version: '1.0.0' },
      });
    case 'ping':
      return ok({});
    case 'tools/list':
      return ok({ tools: [tool] });
    case 'resources/list':
      return ok({ resources: [resource] });
    case 'resources/templates/list':
      return ok({ resourceTemplates: [] });
    case 'resources/read':
      if (msg.params?.uri !== resourceUri) return fail(-32002, 'Resource not found.');
      return ok({ contents: [{
        uri: resourceUri, mimeType: resource.mimeType, text: html,
        _meta: { ui: { csp: { connectDomains: [], resourceDomains: [] } } },
      }] });
    case 'tools/call': {
      if (msg.params?.name !== tool.name) return fail(-32602, 'Unknown tool.');
      const args = msg.params.arguments === undefined ? {} : msg.params.arguments;
      if (!args || typeof args !== 'object' || Array.isArray(args) ||
          Object.keys(args).some(key => key !== 'text') ||
          ('text' in args && (typeof args.text !== 'string' || args.text.length > maxText))) {
        return fail(-32602, 'Provide text up to 10,000 characters or open an empty player.');
      }
      return ok({
        content: [{ type: 'text', text: 'Privi Voice is ready. In the player, choose a voice and speed, then select Play. If there is no player, try ChatGPT on desktop web.' }],
        _meta: { text: args.text?.trim() || '' },
      });
    }
    default:
      return fail(-32601, 'Method not found.');
  }
}
