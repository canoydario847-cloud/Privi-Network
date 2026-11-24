// Hey Jose conversation history contract. No provider/tool data is trusted.
// Server persistence requires Jose account login; guest history stays in browser.
export const MAX_CONVERSATIONS = 40;
export const MAX_MESSAGES = 80;
export const MAX_MESSAGE_CHARS = 12000;
export const MAX_TOTAL_CHARS = 100000;
export const MAX_TITLE_CHARS = 90;

export function normalizeTitle(value, fallback='New chat') {
  if (typeof value !== 'string') return fallback;
  const title=value.replace(/[\u0000-\u001f\u007f]/g,' ').replace(/\s+/g,' ').trim().slice(0,MAX_TITLE_CHARS);
  return title || fallback;
}

export function validateConversationMessages(value) {
  if (!Array.isArray(value) || value.length > MAX_MESSAGES)
    throw Object.assign(new Error('Save at most 80 messages per conversation.'),{status:400});
  let total=0;
  return value.map((entry)=>{
    if (!entry || typeof entry !== 'object' || Array.isArray(entry) ||
        !['user','assistant'].includes(entry.role) ||
        typeof entry.content !== 'string' || !entry.content.trim() ||
        entry.content.length > MAX_MESSAGE_CHARS)
      throw Object.assign(new Error('Conversation messages must be nonempty user or assistant text up to 12,000 characters.'),{status:400});
    total+=entry.content.length;
    if (total>MAX_TOTAL_CHARS)
      throw Object.assign(new Error('Conversation exceeds the 100,000-character storage limit.'),{status:400});
    return {role:entry.role,content:entry.content};
  });
}

export function conversationSummary(row){
  return {id:row.id,title:row.title,createdAt:row.createdAt,updatedAt:row.updatedAt,
    messageCount:row.messages.length,
    preview:row.messages.find(m=>m.role==='user')?.content.slice(0,120)||''};
}
