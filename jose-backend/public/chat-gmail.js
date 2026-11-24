// Gmail UX lives INSIDE Jose's single chat. Gmail OAuth must run in a top-level
// browser context so session cookies work even if the main site uses an iframe.
(() => {
  const $=id=>document.getElementById(id);
  let connected=false,authenticated=false,configured=false,review=null;
  let lastReply='';
  const BACKEND='https://jose-backend-075d.onrender.com/chat.html';
  const message=t=>{$('gmailStatus').textContent=t;};
  function view(){
    $('gmailAuth').hidden=authenticated;
    $('gmailAccountActions').hidden=!authenticated;
    $('gmailConnect').hidden=connected;
    $('gmailInbox').hidden=!connected;
    $('gmailDisconnect').hidden=!connected;
    $('gmailCompose').hidden=!connected;
    $('gmailConnect').disabled=!configured;
  }
  async function api(path,options={}){
    const response=await fetch(path,{credentials:'same-origin',cache:'no-store',...options});
    const data=await response.json().catch(()=>({error:'Server returned an invalid response.'}));
    if(!response.ok)throw Error(data.error||('Request failed ('+response.status+')'));
    return data;
  }
  async function refresh(){
    const status=await api('/api/chat/status');
    configured=Boolean(status.gmailConfigured);
    const res=await fetch('/api/me',{credentials:'same-origin',cache:'no-store'});
    if(res.status===401){authenticated=false;connected=false;view();
      message('Sign in to a Jose account before connecting Gmail.'+(configured?'':' The Jose operator must also configure Google OAuth.'));return;}
    if(!res.ok)throw Error('Could not check Jose login.');
    const who=await res.json();authenticated=true;
    if(configured){
      const gmail=await api('/api/gmail/status');
      connected=Boolean(gmail.connected);
    }else connected=false;
    view();
    message(connected?'Gmail connected to Jose account '+who.email+'. Ask “show my inbox” or draft and review an email here.':
      configured?'Signed in as '+who.email+'. Choose Connect Gmail and approve access in Google.':
        'Signed in. Gmail unavailable until the site operator configures Google OAuth (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, APP_SECRET).');
  }
  function topLevel(){
    if(window.top!==window.self){
      // A user click is required: avoid third-party cookie blocking.
      window.top.location.assign(BACKEND+'?gmail=connect');
      return false;
    }
    return true;
  }
  $('gmailBtn').onclick=async()=>{
    if(!topLevel())return;
    $('gmailPanel').hidden=!$('gmailPanel').hidden;
    if(!$('gmailPanel').hidden)try{await refresh();}catch(e){message(e.message);}
  };
  async function authenticate(signup){
    const email=$('gmailEmail').value.trim(),password=$('gmailPassword').value;
    if(!email||password.length<8){message('Enter a valid email and a Jose account password of at least 8 characters.');return;}
    const button=$(signup?'gmailSignup':'gmailLogin');button.disabled=true;
    try{
      await api(signup?'/api/signup':'/api/login',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({email,password})
      });
      $('gmailPassword').value='';await refresh();
      window.dispatchEvent(new Event('jose-auth-changed'));
    }catch(e){message(e.message);}
    finally{button.disabled=false;}
  }
  $('gmailLogin').onclick=()=>authenticate(false);
  $('gmailSignup').onclick=()=>authenticate(true);
  $('gmailConnect').onclick=()=>{
    if(!topLevel())return;
    window.location.assign('/connect/google');
  };
  $('gmailInbox').onclick=()=>{
    $('gmailPanel').hidden=true;
    $('message').value='Show my latest Gmail';
    $('chat').requestSubmit();
  };
  $('gmailDisconnect').onclick=async()=>{
    if(!window.confirm('Disconnect Gmail from this Jose account?'))return;
    try{await api('/api/disconnect/google',{method:'POST'});review=null;await refresh();}
    catch(e){message(e.message);}
  };
  $('gmailUseReply').onclick=()=>{
    lastReply=String(window.joseAddons?.getLastReply?.()||'');
    if(!lastReply){message('Ask Jose to write the email first, then choose Use last Jose answer.');return;}
    $('gmailText').value=lastReply.slice(0,16000);
    review=null;$('gmailReview').hidden=true;
    message('Last Jose answer copied into the email body. Review it carefully before sending.');
  };
  $('gmailPrepare').onclick=async()=>{
    const to=$('gmailTo').value.trim(),subject=$('gmailSubject').value.trim(),text=$('gmailText').value.trim();
    review=null;$('gmailReview').hidden=true;
    try{
      const data=await api('/api/gmail/prepare',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({to,subject,text})
      });
      review=data;
      $('gmailReviewHeader').textContent='To: '+data.draft.to+' | Subject: '+data.draft.subject;
      $('gmailReviewText').textContent=data.draft.text;
      $('gmailReview').hidden=false;
      message('Ready to send ONLY after you explicitly confirm this exact draft.');
    }catch(e){message('Cannot prepare: '+e.message);}
  };
  // Editing any field invalidates a prior preview token; no silent send after edits.
  for(const id of ['gmailTo','gmailSubject','gmailText']){
    $(id).addEventListener('input',()=>{review=null;$('gmailReview').hidden=true;});
  }
  $('gmailCancel').onclick=()=>{review=null;$('gmailReview').hidden=true;message('Review canceled. You may edit the draft.');};
  $('gmailConfirm').onclick=async()=>{
    if(!review){message('Review the message again before sending.');return;}
    if(!window.confirm('Send this email to '+review.draft.to+' now?'))return;
    const token=review.reviewToken;review=null;
    $('gmailConfirm').disabled=true;
    try{
      const data=await api('/api/gmail/send',{
        method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({reviewToken:token,confirmSend:true})
      });
      $('gmailReview').hidden=true;
      message('Sent via your Gmail account. Message ID: '+data.id);
      $('gmailTo').value='';$('gmailSubject').value='';$('gmailText').value='';
    }catch(e){message('Send not confirmed: '+e.message+' Check Sent Mail before trying again.');}
    finally{$('gmailConfirm').disabled=false;}
  };
  if(new URLSearchParams(window.location.search).has('gmail')){
    $('gmailPanel').hidden=false;
    void refresh().catch(e=>message(e.message));
  }
})();
