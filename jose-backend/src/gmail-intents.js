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
// Explicitly explain live connection readiness instead of a generic AI refusal.
// Only non-secret configuration KEY NAMES are exposed, never OAuth values.
export function gmailConnectionGuide({configured=false,authenticated=false,connected=false,missingEnvVars=[]}={}){
 const setupUrl='https://jose-backend-075d.onrender.com/chat.html?gmail=connect';
 const missing=Array.isArray(missingEnvVars)
   ?missingEnvVars.filter(name=>['GOOGLE_CLIENT_ID','GOOGLE_CLIENT_SECRET','APP_SECRET'].includes(name))
   :[];
 let gmailStatus,answer;
 if(!configured){
   gmailStatus='operator_setup';
   answer='Hey Jose has Gmail reading, search and reviewed sending built into its backend, but this deployment cannot connect to Gmail yet. '+
     'The operator must configure '+(missing.length?missing.join(' and '):'Google OAuth credentials')+
     ' in the jose-backend Render environment, enable the Gmail API, and register the Google OAuth redirect URI https://jose-backend-075d.onrender.com/callback/google. '+
     'Until Google OAuth is configured and you authorize your own account, I cannot read or send Gmail. Click Gmail in the chat header to view the connection status.';
 }else if(!authenticated){
   gmailStatus='sign_in';
   answer='Hey Jose supports Gmail. First open Gmail in the chat header and sign in or create a Jose account. '+
     'Then select Connect Gmail and approve Google permissions. I will not ask for your Google password.';
 }else if(!connected){
   gmailStatus='authorize';
   answer='Hey Jose is ready for Gmail access, but your Gmail account has not been connected to this Jose account. '+
     'Click Gmail in the chat header and choose Connect Gmail using Google, then approve read and send permissions. '+
     'I cannot read your inbox until you authorize access.';
 }else{
   gmailStatus='connected';
   answer='Your Gmail account is connected to Hey Jose. You can say "show my latest Gmail", '+
     '"show my unread emails", "search my email for invoices", or use "/gmail read MESSAGE_ID". '+
     'You can also draft a message using Gmail in this chat. Every send requires your review and explicit confirmation.';
 }
 return {answer,mode:'chat',gmailAction:'connect',gmailStatus,gmailSetupUrl:setupUrl};
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
