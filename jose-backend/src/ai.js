// Hey Jose — the live chat assistant. Calls the Anthropic Messages API with
// a Jose system prompt. Conversation history is kept by the browser and sent
// each turn (trimmed here), so the server stores no chat transcripts.
import { config } from './config.js';

const SYSTEM_PROMPT = `You are Jose ("Hey Jose"), a helpful assistant for people doing business and daily life between South America and China.

- Reply in the language the user writes in (Spanish, Portuguese, Chinese, or English) unless they ask for another.
- You are good at: reading and explaining trade, customs, shipping and invoice documents; translating messages between Spanish, Portuguese, Chinese and English while keeping the details that matter (dates, amounts, conditions); drafting replies to customers and suppliers; everyday help like menus, leases and messages from friends.
- When translating, give the translation first, then a short note on anything ambiguous.
- Be concise and practical. Use short paragraphs or short lists.
- You can explain what the JOSE token and the Jose marketplace are in general terms, but never give investment advice, price predictions, or tell anyone to buy, sell or hold crypto.
- If you are unsure about a legal, customs or tax rule, say so and suggest checking with a licensed customs broker, lawyer or the relevant authority.`;

const MAX_TURNS = 20;
const MAX_CHARS_PER_MESSAGE = 8000;

export function sanitizeHistory(messages) {
  if (!Array.isArray(messages)) return null;
  const cleaned = messages
    .filter((m) => m && (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string' && m.content.trim())
    .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_CHARS_PER_MESSAGE) }))
    .slice(-MAX_TURNS);
  // The API needs the conversation to start with a user turn and end with one.
  while (cleaned.length && cleaned[0].role !== 'user') cleaned.shift();
  if (!cleaned.length || cleaned[cleaned.length - 1].role !== 'user') return null;
  return cleaned;
}

export async function askJose(messages) {
  if (!config.anthropicApiKey) throw Object.assign(new Error('AI is not configured on this server.'), { status: 503 });
  const res = await fetch(`${config.anthropicBaseUrl}/v1/messages`, {
    method: 'POST',
    headers: {
      'content-type': 'application/json',
      'x-api-key': config.anthropicApiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: config.aiModel,
      max_tokens: config.aiMaxTokens,
      system: SYSTEM_PROMPT,
      messages,
    }),
    signal: AbortSignal.timeout(60000),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const msg = body?.error?.message || `AI request failed (${res.status}).`;
    throw Object.assign(new Error(msg), { status: 502 });
  }
  const text = (body.content || []).filter((b) => b.type === 'text').map((b) => b.text).join('\n').trim();
  return text || '…';
}
