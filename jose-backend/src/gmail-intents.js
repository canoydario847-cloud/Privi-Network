// Only explicit Gmail intents trigger mailbox access. Other questions remain normal AI chat.
export function gmailIntent(message){
 if(typeof message!=='string')return null;
 const q=message.trim();
 if(!q||q.length>500)return null;
 if(/^(?:\/gmail\s+(?:inbox|latest|unread)|(?:show|check|list|read)\s+(?:me\s+)?(?:my\s+)?(?:latest\s+|recent\s+|unread\s+)?(?:gmail|emails?|inbox)(?:\s+(?:messages?|emails?))?\??)$/i.test(q))
   return {action:'inbox',query:/unread/i.test(q)?'is:unread in:inbox':''};
 const search=q.match(/^(?:\/gmail\s+search\s+|(?:search|find)\s+(?:my\s+)?(?:gmail|email|inbox)\s+(?:for|about)\s+)(.{1,180})$/i);
 if(search)return {action:'inbox',query:search[1].trim()};
 const read=q.match(/^(?:\/gmail\s+read\s+|read\s+(?:my\s+)?(?:gmail\s+)?(?:email|message)\s+(?:id\s+)?)([a-z0-9]{8,50})$/i);
 if(read)return {action:'read',id:read[1]};
 if(/^(?:\/gmail(?:\s+help)?|how (?:do|can) i connect (?:my\s+)?gmail\??)$/i.test(q))
   return {action:'help'};
 if(/^(?:compose|write|send)\s+(?:an?\s+)?(?:gmail\s+)?email(?:\s+for me)?[.!]?$/i.test(q))
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
