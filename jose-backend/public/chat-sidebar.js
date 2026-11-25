// Hey Jose: single-chat sidebar with real conversation history and quick actions.
// Guests save a bounded copy in THIS BROWSER ONLY. Signed-in users use
// account-isolated server endpoints (currently temporary Render file storage).
// Never save Gmail mailbox contents, passwords, attachments, or access tokens.
(() => {
  const $=id=>document.getElementById(id);
  const STORAGE_KEY='hey-jose-conversations-v1';
  const MAX_LOCAL=30;
  const MAX_MESSAGES=80;
  const MAX_TOTAL=100000;
  let chats=[],activeId=null,signedIn=false,ready=Promise.resolve();
  let saveQueue=Promise.resolve();
  const notice=text=>{$('sidebarStorage').textContent=text;};
  const flash=text=>{$('status').textContent=text;};
  const busy=()=>Boolean(window.joseChatBusy);
  const titleFor=text=>String(text||'New chat').replace(/\s+/g,' ').trim().slice(0,90)||'New chat';
  const stamp=()=>Date.now();
  const uuid=()=>window.crypto?.randomUUID?.()||('local-'+Date.now()+'-'+Math.random().toString(36).slice(2));
  const desktop=()=>window.matchMedia('(min-width:861px)').matches;
  function closeDrawer(){
    $('sidebar').classList.remove('expanded');
    $('sidebarShade').hidden=true;
    $('toggleSidebar').setAttribute('aria-expanded',String(desktop()&&!$('sidebar').classList.contains('collapsed')));
  }
  function toggleDrawer(){
    if(desktop()){
      const hidden=$('sidebar').classList.toggle('collapsed');
      $('toggleSidebar').setAttribute('aria-expanded',String(!hidden));
      if(!hidden)$('sidebarSearch').focus();
      return;
    }
    const open=!$('sidebar').classList.contains('expanded');
    $('sidebar').classList.toggle('expanded',open);
    $('sidebarShade').hidden=!open;
    $('toggleSidebar').setAttribute('aria-expanded',String(open));
    if(open)$('sidebarSearch').focus();
  }
  function readGuest(){
    try{
      const rows=JSON.parse(localStorage.getItem(STORAGE_KEY)||'[]');
      if(!Array.isArray(rows))return [];
      return rows.slice(0,MAX_LOCAL).filter(c=>c&&typeof c.id==='string'&&typeof c.title==='string'&&Array.isArray(c.messages))
        .map(c=>({id:c.id,title:titleFor(c.title),updatedAt:Number(c.updatedAt)||stamp(),
          createdAt:Number(c.createdAt)||stamp(),
          messages:c.messages.filter(m=>m&&['user','assistant'].includes(m.role)&&typeof m.content==='string'&&m.content.length<=12000).slice(-MAX_MESSAGES)}));
    }catch{return [];}
  }
  function persistGuest(){
    try{
      const rows=chats.slice(0,MAX_LOCAL).map(c=>({id:c.id,title:c.title,createdAt:c.createdAt,updatedAt:c.updatedAt,messages:c.messages||[]}));
      localStorage.setItem(STORAGE_KEY,JSON.stringify(rows));
      return true;
    }catch{
      notice('Browser storage is unavailable or full. Export chats to keep a copy.');
      return false;
    }
  }
  async function api(path,{method='GET',body}={}){
    const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',
      headers:body?{'Content-Type':'application/json'}:{},
      ...(body?{body:JSON.stringify(body)}:{})});
    const data=await response.json().catch(()=>({error:'Invalid server response.'}));
    if(!response.ok)throw Error(data.error||('Request failed ('+response.status+')'));
    return data;
  }
  function render(){
    const list=$('conversationList');
    list.replaceChildren();
    const search=$('sidebarSearch').value.toLowerCase().trim();
    const matching=chats.filter(c=>(c.title+' '+(c.preview||c.messages?.[0]?.content||'')).toLowerCase().includes(search))
      .sort((a,b)=>b.updatedAt-a.updatedAt);
    if(!matching.length){
      const empty=document.createElement('p');empty.className='sidebar-empty';
      empty.textContent=search?'No matching chats.':'Start a chat and it will appear here.';
      list.append(empty);
    }
    for(const c of matching){
      const row=document.createElement('div');
      row.className='sidebar-chat'+(activeId===c.id?' selected':'');
      const open=document.createElement('button');
      open.type='button';open.className='sidebar-chat-title';
      open.textContent=c.title;open.title=c.title;
      open.setAttribute('aria-label','Open '+c.title);
      open.onclick=()=>{void openChat(c.id);};
      const rename=document.createElement('button');
      rename.type='button';rename.className='sidebar-mini';rename.textContent='✎';
      rename.title='Rename';rename.setAttribute('aria-label','Rename '+c.title);
      rename.onclick=()=>{void renameChat(c);};
      const del=document.createElement('button');
      del.type='button';del.className='sidebar-mini';del.textContent='×';
      del.title='Delete';del.setAttribute('aria-label','Delete '+c.title);
      del.onclick=()=>{void deleteChat(c);};
      row.append(open,rename,del);list.append(row);
    }
    $('sidebarAccount').textContent=signedIn?'Account connected':'Sign in / sync chats';
  }
  async function load(){
    let account=false;
    try{
      const who=await fetch('/api/me',{credentials:'same-origin',cache:'no-store'});
      account=who.ok;
    }catch{}
    signedIn=account;
    activeId=null;
    if(signedIn){
      try{
        const data=await api('/api/conversations');
        chats=(data.conversations||[]).map(c=>({...c,messages:null}));
        notice('Signed-in history. Current Render storage is temporary: export important chats.');
      }catch(error){
        chats=[];
        notice('Unable to retrieve account history: '+error.message);
      }
    }else{
      chats=readGuest();
      notice('Guest chats stay in this browser. Sign in for account history; do not store secrets.');
    }
    render();
  }
  async function openChat(id){
    if(busy())return flash('Finish the current answer before changing chats.');
    let c=chats.find(row=>row.id===id);
    if(!c)return;
    if(signedIn&&!Array.isArray(c.messages)&&!c.draft){
      try{
        const detail=await api('/api/conversations/'+encodeURIComponent(c.id));
        c.messages=detail.messages;
      }catch(error){flash('Could not load this chat: '+error.message);return;}
    }
    activeId=c.id;
    window.joseRestoreConversation?.(c.messages||[]);
    render();closeDrawer();$('message').focus();
  }
  function newChat(){
    if(busy())return flash('Finish the current answer before starting another chat.');
    activeId=null;window.joseResetChat?.();window.joseAddons?.onSent?.('');render();closeDrawer();
    flash('New conversation. Ask Hey Jose anything.');
  }
  function enqueue(work){
    const next=saveQueue.then(work,work);
    saveQueue=next.catch(()=>{});
    return next;
  }
  async function save(c){
    if(!signedIn){persistGuest();return;}
    return enqueue(async()=>{
      if(c.draft){
        const created=await api('/api/conversations',{method:'POST',body:{title:c.title}});
        const previous=c.id;
        c.id=created.id;c.draft=false;
        if(activeId===previous)activeId=c.id;
      }
      await api('/api/conversations/'+encodeURIComponent(c.id),{
        method:'PUT',body:{messages:c.messages}
      });
      render();
    });
  }
  async function onTurn(user,answer,{gmailAction=null}={}){
    // Gmail replies must never be stored or replayed to the model.
    if(gmailAction)return;
    await ready;
    let c=chats.find(x=>x.id===activeId);
    if(!c){
      c={id:'draft-'+uuid(),draft:signedIn,title:titleFor(user),
        createdAt:stamp(),updatedAt:stamp(),messages:[]};
      chats.unshift(c);activeId=c.id;
    }
    if(!Array.isArray(c.messages))c.messages=[];
    c.messages.push({role:'user',content:String(user).slice(0,12000)},
      {role:'assistant',content:String(answer).slice(0,12000)});
    while(c.messages.length>MAX_MESSAGES||
       c.messages.reduce((n,m)=>n+m.content.length,0)>MAX_TOTAL)c.messages.splice(0,2);
    c.updatedAt=stamp();
    render();
    try{await save(c);}
    catch(error){flash('Jose answered, but chat history was not saved: '+error.message);}
  }
  async function renameChat(c){
    if(busy())return;
    const requested=window.prompt('Rename chat',c.title);
    if(requested===null)return;
    const next=titleFor(requested);
    if(next===c.title)return;
    if(signedIn&&!c.draft){
      try{await api('/api/conversations/'+encodeURIComponent(c.id),{method:'PATCH',body:{title:next}});}
      catch(error){flash('Rename failed: '+error.message);return;}
    }
    c.title=next;c.updatedAt=stamp();
    if(!signedIn)persistGuest();
    render();
  }
  async function deleteChat(c){
    if(busy())return;
    if(!window.confirm('Delete "'+c.title+'"? This cannot be undone.'))return;
    if(signedIn&&!c.draft){
      try{await api('/api/conversations/'+encodeURIComponent(c.id),{method:'DELETE'});}
      catch(error){flash('Deletion failed: '+error.message);return;}
    }
    chats=chats.filter(x=>x!==c);
    if(activeId===c.id){activeId=null;window.joseResetChat?.();}
    if(!signedIn)persistGuest();
    render();
  }
  $('toggleSidebar').onclick=toggleDrawer;
  $('closeSidebar').onclick=()=>{
    if(desktop()){$('sidebar').classList.add('collapsed');$('toggleSidebar').setAttribute('aria-expanded','false');}
    else closeDrawer();
  };
  $('sidebarShade').onclick=closeDrawer;
  $('sidebarNewChat').onclick=newChat;
  $('sidebarSearch').oninput=render;
  $('sidebarAccount').onclick=()=>{$('gmailBtn').click();closeDrawer();};
  $('sidebarTasks').addEventListener('click',event=>{
    const button=event.target.closest('[data-action]');
    if(!button||busy())return;
    const action=button.dataset.action;
    if(action==='powers'||action==='devnet'||action==='quantum'){
      $('message').value=action==='powers'?'/powers':action==='devnet'?'Privi Devnet status':'Simulate a 2-qubit Bell state with Privi Quantum';
      closeDrawer();$('chat').requestSubmit();
    }else if(action==='web3'){
      $('message').value='Help me build a safe Web3 smart contract for ';
      closeDrawer();$('message').focus();
    }else{
      const id={gmail:'gmailBtn',memory:'memoryBtn',voice:'priviVoiceBtn',export:'exportChat',attach:'attach'}[action];
      if(id)$(id).click();
      closeDrawer();
    }
  });
  window.addEventListener('keydown',event=>{if(event.key==='Escape')closeDrawer();});
  window.addEventListener('jose-auth-changed',()=>{
    if(busy())return;
    window.joseResetChat?.();
    ready=load();
  });
  window.joseSidebar={newChat,onTurn,openChat,getCurrentMessages:()=>{
    const row=chats.find(c=>c.id===activeId);
    return Array.isArray(row?.messages)?row.messages.slice():window.joseChatHistory?.slice()||[];
  }};
  $('toggleSidebar').setAttribute('aria-expanded',String(desktop()));
  ready=load();
})();
