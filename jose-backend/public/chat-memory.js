// Hey Jose's user-controlled, browser-only memory; no automatic extraction.
// This file never sends notes to a service on its own. The chat sends enabled
// notes with user messages so the current model can use them as user context.
(() => {
  const NOTES_KEY='hey-jose-memory-notes-v1';
  const ENABLED_KEY='hey-jose-memory-enabled-v1';
  const MAX_NOTES=25, MAX_CHARS=180, MAX_CONTEXT=3600;
  const $=id=>document.getElementById(id);
  let available=true,notes=[],enabled=false;
  try{
    const parsed=JSON.parse(localStorage.getItem(NOTES_KEY)||'[]');
    if(Array.isArray(parsed))notes=parsed.filter(x=>typeof x==='string'&&x.length>0&&x.length<=MAX_CHARS).slice(0,MAX_NOTES);
    enabled=localStorage.getItem(ENABLED_KEY)==='true';
  }catch{available=false;}
  const unsafe=/(?:-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY-----|\b(?:password|passphrase|recovery phrase|secret key|private key|api key|access token)\s*[:=]\s*\S+|\b(?:sk-(?:proj-)?|gh[pousr]_)[A-Za-z0-9_-]{14,}\b|\b0x[a-fA-F0-9]{64}\b)/i;
  function valid(note){
    if(typeof note!=='string')throw Error('Memory must be plain text.');
    const clean=note.replace(/\s+/g,' ').trim();
    if(clean.length<3||clean.length>MAX_CHARS)throw Error('Write a memory between 3 and 180 characters.');
    if(unsafe.test(clean))throw Error('For safety, Jose will not store passwords, credentials or private keys.');
    return clean;
  }
  function persist(){
    if(!available)throw Error('Browser storage is unavailable. Enable site storage to save memories.');
    try{
      localStorage.setItem(NOTES_KEY,JSON.stringify(notes));
      localStorage.setItem(ENABLED_KEY,enabled?'true':'false');
    }catch{throw Error('Browser storage is blocked or full. Jose did not save this change.');}
  }
  function badge(){
    const b=$('memoryBtn');
    if(b){b.textContent='Memory '+(enabled?'on · ':'off · ')+notes.length;b.title=enabled?'Saved browser memories are included with new questions':'Memory is off; saved notes are not sent';}
  }
  function draw(){
    badge();
    const list=$('memoryList');
    if(!list)return;
    list.replaceChildren();
    if(!notes.length){
      const empty=document.createElement('p');empty.className='muted';
      empty.textContent='No saved memories. Tell Jose “Remember that I prefer short answers” or add one here.';
      list.append(empty);
    }
    notes.forEach((note,index)=>{
      const row=document.createElement('div');row.className='memory-row';
      const label=document.createElement('span');label.textContent=note;
      const del=document.createElement('button');del.type='button';del.textContent='Forget';
      del.setAttribute('aria-label','Forget memory '+(index+1));
      del.onclick=()=>{
        try{const old=notes;notes=old.filter((_,i)=>i!==index);persist();draw();}
        catch(error){notes.splice(index,0,note);draw();$('status').textContent=error.message;}
      };
      row.append(label,del);list.append(row);
    });
    const toggle=$('memoryToggle');
    if(toggle)toggle.checked=enabled;
  }
  function save(raw){
    const note=valid(raw);
    if(notes.some(x=>x.toLocaleLowerCase()===note.toLocaleLowerCase()))
      return 'I already have that memory saved in this browser.';
    if(notes.length>=MAX_NOTES)throw Error('Memory is full (25 entries). Forget an old note to make room.');
    const prev=notes,wasEnabled=enabled;
    notes=[...notes,note];enabled=true;
    try{persist();}catch(error){notes=prev;enabled=wasEnabled;throw error;}
    draw();
    return 'Saved in this browser: '+note+'\nJose will use it in future chats on this browser while Memory is on. It is not synced across devices.';
  }
  function forget(raw){
    const target=String(raw||'').trim().toLocaleLowerCase();
    if(!target)return 'Tell me which memory to forget, or say “show my memories”.';
    const match=notes.map((text,i)=>({text,i})).filter(x=>x.text.toLocaleLowerCase()===target);
    if(!match.length)return 'No exact saved memory matched. Say “show my memories” to see the exact wording.';
    const previous=notes;
    notes=notes.filter((_,i)=>i!==match[0].i);
    try{persist();}catch(error){notes=previous;throw error;}
    draw();return 'Forgot the selected browser memory.';
  }
  function clear(){
    if(!confirm('Delete ALL saved Hey Jose memories from this browser? This cannot be undone.'))return 'No memories were deleted.';
    const previous=notes;notes=[];
    try{persist();}catch(error){notes=previous;throw error;}
    draw();return 'All saved browser memories deleted.';
  }
  function listMemories(){
    return 'Jose browser memory is '+(enabled?'ON':'OFF')+'.\n'+(notes.length?
      notes.map((n,i)=>(i+1)+'. '+n).join('\n'):
      'Nothing is saved yet.')+
      '\nThese notes are stored only in this browser, not on Privi Devnet. Anyone using this browser profile may be able to see them. Do not store secrets.';
  }
  function message(text){
    const q=String(text||'').trim();
    const add=q.match(/^(?:\/remember\s+|remember\s+(?:that\s+)?|remember:\s*)([\s\S]+)$/i);
    if(add){try{return save(add[1]);}catch(e){return 'Memory not saved: '+e.message;}}
    if(/^(?:\/memories|show (?:me )?(?:my|your) memories|what do you remember(?: about me)?\??)$/i.test(q))return listMemories();
    if(/^(?:\/forget-all|forget (?:all|everything)(?: (?:you )?(?:remember|about me))?)$/i.test(q))return clear();
    const del=q.match(/^(?:\/forget\s+|forget(?: that|:)\s+)([\s\S]+)$/i);
    if(del){try{return forget(del[1]);}catch(e){return 'Memory not forgotten: '+e.message;}}
    if(/^(?:turn |switch )memory (?:off|on)$/i.test(q)){
      const next=/on$/i.test(q);
      if(!available)return 'Browser memory cannot be changed because storage is unavailable.';
      const previous=enabled;enabled=next;
      try{persist();draw();return next?'Memory is on. Saved notes will be included with future questions.':'Memory is off. Saved notes will not be included in questions, but remain in this browser.';}
      catch(e){enabled=previous;return e.message;}
    }
    return null;
  }
  function getNotes(){
    if(!available||!enabled)return [];
    let sum=0;
    return notes.filter(n=>(sum+=n.length)<=MAX_CONTEXT).slice();
  }
  function setup(){
    const button=$('memoryBtn');
    if(!button)return;
    button.onclick=()=>{const panel=$('memoryPanel');panel.hidden=!panel.hidden;draw();};
    const add=$('memoryAdd');
    if(add)add.onclick=()=>{
      const field=$('memoryInput');
      if(!field)return;
      try{$('status').textContent=save(field.value);field.value='';}
      catch(e){$('status').textContent=e.message;}
    };
    const toggle=$('memoryToggle');
    if(toggle)toggle.onchange=()=>{
      const before=enabled;enabled=toggle.checked;
      try{persist();draw();$('status').textContent=enabled?'Jose memory enabled.':'Jose memory paused.';}
      catch(e){enabled=before;draw();$('status').textContent=e.message;}
    };
    const clearButton=$('memoryClear');
    if(clearButton)clearButton.onclick=()=>{$('status').textContent=clear();};
    draw();
  }
  window.joseMemory={message,getNotes,setup,save,forget,list:listMemories};
})();
