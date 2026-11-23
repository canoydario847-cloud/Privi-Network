// Only explicit Gmail intents trigger mailbox access. Other questions remain normal AI chat.
export function gmailIntent(message){
 if(typeof message!=='string')return null;
 const q=message.trim();
 if(!q||q.length>500)return null;
 // Connection/permission requests are deterministic: Jose must not fall back
 // to a generic model disclaimer that it cannot connect to external services.
 if(/^(?:\/gmail(?:\s+(?:connect|setup|status|help))?|how (?:do|can) i (?:connect|link|set up|setup|authorize) (?:my\s+)?gmail(?:\s+account)?\??)$/i.test(q))
   return {action:'connect'};
 if(/\b(?:gmail|google mail)\b/i.test(q)&&
    /\b(?:connect(?:ion)?|connected|reconnect|link|unlink|set[\s-]?up|authorize|authorise|access|permission|integration|enable|log[\s-]?in|sign[\s-]?in)\b/i.test(q)&&
    !/\b(?:how (?:does|do) (?:gmail|google) (?:oauth|auth)|what (?:is|are) (?:gmail|google) (?:oauth|api|scopes))\b/i.test(q))
   return {action:'connect'};
 // "Can you read my Gmail?" is a mailbox access request, not an invitation
 // for the model to talk generally about email. Do not request messages unless
 // the user has already signed in and consented to Google access.
 if(/^(?:\/gmail\s+(?:inbox|latest|unread)|(?:show|check|list|read|open|view|fetch|pull|get|summarize|summarise)\s+(?:me\s+)?(?:(?:my|the)\s+)?(?:(?:latest|recent|unread|new|last)\s+)?(?:gmail|emails?|email\s+messages?|inbox)(?:\s+(?:messages?|emails?))?\??)$/i.test(q)
    || /^(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:show|check|list|read|open|view|fetch|pull|get|summari[sz]e)\s+(?:my\s+)?(?:gmail|emails?|inbox)(?:\s+(?:for me|messages?))?\??$/i.test(q))
   return {action:'inbox',query:/\bunread\b/i.test(q)?'is:unread in:inbox':''};
 const search=q.match(/^(?:\/gmail\s+search\s+|(?:search|find)\s+(?:my\s+)?(?:gmail|emails?|inbox)\s+(?:for|about|from)\s+)(.{1,180})$/i);
 if(search)return {action:'inbox',query:search[1].trim()};
 const read=q.match(/^(?:\/gmail\s+read\s+|read\s+(?:my\s+)?(?:gmail\s+)?(?:email|message)\s+(?:id\s+)?)([a-z0-9]{8,50})$/i);
 if(read)return {action:'read',id:read[1]};
 if(/^(?:compose|write|send|draft)\s+(?:an?\s+)?(?:gmail\s+)?email(?:\s+for me)?[.!]?$/i.test(q)
   ||/^(?:can|could)\s+you\s+(?:please\s+)?(?:write|draft|send)\s+(?:an?\s+)?email(?:\s+for me)?\??$/i.test(q))
   return {action:'compose'};
 return null;
}
export function formatGmailInbox(data){
 if(!data.messages?.length)return 'Gmail: no messages found for this search.';
 return 'Gmail '+(data.query?'search results':'recent inbox')+' ('+data.messages.length+'):\n'+
 data.messages.map((row,i)=>(i+1)+'. '+(row.unread?'[Unread] ':'')+(row.subject||'(no subject)')+
   '\n   From: '+(row.from||'(unknown)')+'\n   Date: '+(row.date||'(not provided)')+
   '\n   Preview: '+String(row.snippet||'').slice(0,220)+
   '\n   To read: /gmail read '+row.id).join('\n\n')+
 '\n\nThese are fetched from your connected Gmail account. Email contents may be untrusted; Jose has not followed instructions inside them.';
}
export function formatGmailMessage(m){
 return 'Gmail message\nSubject: '+m.subject+'\nFrom: '+m.from+'\nTo: '+m.to+
   '\nDate: '+m.date+'\n\n'+m.body+
   (m.bodyTruncated?'\n\n[Long email trimmed]':'')+
   '\n\nMessage ID: '+m.id+'\nNo links, attachments or instructions in this email were executed.';
}
