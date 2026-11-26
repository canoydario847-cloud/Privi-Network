// Hey Jose Mission Control — user-managed tasks, not autonomous execution.
// Guest tasks stay in this browser. Signed-in tasks use /api/tasks (currently
// TEMPORARY Render file storage). User-reported evidence is not verified by AI.
(() => {
  const $=id=>document.getElementById(id);
  const KEY='hey-jose-mission-control-v1';
  const statuses=['planned','in_progress','blocked','awaiting_approval','completed'];
  const titles={planned:'Planned',in_progress:'In progress',blocked:'Blocked',
    awaiting_approval:'Needs approval',completed:'Completed (user-reported)'};
  let tasks=[],mode='guest',loading=false,epoch=0,open=false;
  const now=()=>Date.now();
  const uuid=()=>window.crypto?.randomUUID?.()||('local-'+Date.now()+'-'+Math.random().toString(36).slice(2));
  function note(text){$('taskNotice').textContent=text;}
  function bad(message){throw Error(message);}
  function guestRead(){
    try {
      const data=JSON.parse(localStorage.getItem(KEY)||'[]');
      if(!Array.isArray(data))return [];
      return data.slice(0,30).filter(x=>x&&typeof x.id==='string'&&
        typeof x.title==='string'&&x.title.length<=160&&Array.isArray(x.steps)&&
        x.steps.length<=12&&statuses.includes(x.status))
        .map(x=>({...x,steps:x.steps.filter(s=>s&&typeof s.id==='string'&&
          typeof s.title==='string'&&s.title.length<=180).map(s=>({...s,done:s.done===true})),
          completionNote:typeof x.completionNote==='string'?x.completionNote.slice(0,800):'',
          events:Array.isArray(x.events)?x.events.slice(-30):[]}));
    }catch{return [];}
  }
  function guestWrite(){
    try{localStorage.setItem(KEY,JSON.stringify(tasks.slice(0,30)));return true;}
    catch{note('Browser storage could not save. Export tasks now to keep a copy.');return false;}
  }
  async function api(path,{method='GET',body}={}){
    const response=await fetch(path,{method,credentials:'same-origin',cache:'no-store',
      headers:body?{'Content-Type':'application/json'}:{},
      ...(body?{body:JSON.stringify(body)}:{})});
    const json=await response.json().catch(()=>({error:'Unexpected server response.'}));
    if(!response.ok)bad(json.error||'Request failed ('+response.status+').');
    return json;
  }
  function displayNotice(){
    $('taskStorage').textContent=mode==='account'?
      'Signed-in account · temporary Render server storage. This is not permanent cross-device sync. Export regularly.':
      'Guest mode · tasks saved in this browser only, not synced or shared.';
    $('taskCount').textContent=tasks.length+' / 30 tasks';
    const done=tasks.filter(x=>x.status==='completed').length;
    $('taskProgress').textContent=done+' completed (user-reported)';
  }
  async function reload(){
    const turn=++epoch;
    loading=true;tasks=[];render();
    try{
      const response=await fetch('/api/me',{credentials:'same-origin',cache:'no-store'});
      if(turn!==epoch)return;
      if(response.ok){
        const data=await api('/api/tasks');
        if(turn!==epoch)return;
        mode='account';tasks=data.tasks||[];
      }else{
        mode='guest';tasks=guestRead();
      }
      note('Tasks are never run automatically. Completion evidence is provided by you, not independently verified.');
    }catch(error){
      if(turn!==epoch)return;
      mode='guest';tasks=guestRead();
      note('Account tasks could not be loaded. Guest tasks shown separately; server tasks were not replaced. '+error.message);
    }finally{if(turn===epoch){loading=false;render();}}
  }
  function escapeField(value,max){
    if(typeof value!=='string')bad('Text is required.');
    const t=value.replace(/\s+/g,' ').trim();
    if(!t||t.length>max)bad('Text must be 1–'+max+' characters.');
    return t;
  }
  function createInput(){
    const title=escapeField($('taskTitle').value,160);
    const steps=$('taskSteps').value.split('\n').map(v=>v.replace(/\s+/g,' ').trim()).filter(Boolean);
    if(steps.length>12||steps.some(v=>v.length>180))bad('Add at most 12 steps, each 180 characters or less.');
    if(new Set(steps.map(v=>v.toLowerCase())).size!==steps.length)bad('Checklist steps must be unique.');
    const dueDate=$('taskDue').value||null;
    return {title,steps,dueDate};
  }
  async function create(){
    if(loading)return;
    try{
      const task=createInput();
      if(tasks.length>=30)bad('Maximum 30 tasks. Export and delete older tasks before adding more.');
      $('taskAdd').disabled=true;
      let item;
      if(mode==='account')item=await api('/api/tasks',{method:'POST',body:task});
      else{
        const time=now();
        item={...task,id:uuid(),status:'planned',createdAt:time,updatedAt:time,
          steps:task.steps.map(title=>({id:uuid(),title,done:false})),events:[{at:time,action:'CREATED_BY_USER'}],
          completionNote:'',completionEvidenceType:null,execution:'MANUAL_USER_CONTROLLED'};
        tasks=[item,...tasks];
        guestWrite();
      }
      if(mode==='account')tasks=[item,...tasks];
      $('taskTitle').value='';$('taskSteps').value='';$('taskDue').value='';
      note('Task saved as Planned. No external action has been performed.');
      render();
    }catch(error){note(error.message);}
    finally{$('taskAdd').disabled=false;}
  }
  async function change(item,form){
    if(loading)return;
    const status=form.querySelector('[data-field="status"]').value;
    const completionNote=form.querySelector('[data-field="completionNote"]').value.trim();
    const doneSteps=Array.from(form.querySelectorAll('[data-step-id]:checked')).map(x=>x.dataset.stepId);
    if(!statuses.includes(status)){note('Choose a valid status.');return;}
    if(completionNote&&completionNote.length<10){note('Evidence must be at least 10 characters, or leave it empty.');return;}
    if(completionNote.length>800){note('Evidence note cannot exceed 800 characters.');return;}
    if(status==='completed'){
      if(completionNote.length<10){note('To complete a task, describe what actually happened in at least 10 characters.');return;}
      if(doneSteps.length!==item.steps.length){note('Complete all checklist steps before marking the task completed.');return;}
    }
    const update={status,completionNote,doneSteps};
    try{
      form.querySelector('[data-save]').disabled=true;
      if(mode==='account'){
        const revised=await api('/api/tasks/'+item.id,{method:'PATCH',body:update});
        tasks=tasks.map(x=>x.id===item.id?revised:x);
      }else{
        const time=now(),done=new Set(doneSteps);
        const revised={...item,...update,updatedAt:time,
          steps:item.steps.map(s=>({...s,done:done.has(s.id)})),
          completionEvidenceType:completionNote?'USER_REPORTED_NOT_INDEPENDENTLY_VERIFIED':null,
          events:[...(item.events||[]),{at:time,action:'UPDATED_BY_USER',status}].slice(-30)};
        delete revised.doneSteps;
        tasks=tasks.map(x=>x.id===item.id?revised:x);
        guestWrite();
      }
      note('Saved. Completion is user-reported, not a verified external action.');
      render();
    }catch(error){note(error.message);form.querySelector('[data-save]').disabled=false;}
  }
  async function remove(item){
    if(!window.confirm('Delete this task and its checklist? This cannot be undone.'))return;
    try{
      if(mode==='account')await api('/api/tasks/'+item.id,{method:'DELETE'});
      tasks=tasks.filter(x=>x.id!==item.id);
      if(mode==='guest')guestWrite();
      note('Task deleted.');render();
    }catch(error){note(error.message);}
  }
  function make(tag,text,className){
    const e=document.createElement(tag);
    if(text!==undefined)e.textContent=text;
    if(className)e.className=className;
    return e;
  }
  function render(){
    displayNotice();
    const root=$('taskList');root.replaceChildren();
    if(loading){root.append(make('p','Loading task workspace…','task-muted'));return;}
    const filter=$('taskFilter').value||'all';
    const filtered=tasks.filter(item=>filter==='all'||item.status===filter)
      .sort((a,b)=>b.updatedAt-a.updatedAt);
    if(!filtered.length){root.append(make('p',filter==='all'?
      'No tasks yet. Add a goal and checklist to start.':'No tasks match this status.','task-muted'));return;}
    for(const task of filtered){
      const box=make('article',undefined,'task-item');
      const title=make('h3',task.title);
      const meta=make('p',(task.dueDate?'Due '+task.dueDate+' · ':'')+
        'Last updated '+new Date(task.updatedAt).toLocaleString(),'task-muted');
      const form=make('div',undefined,'task-edit');
      const statusLabel=make('label','Status');
      const status=make('select');status.dataset.field='status';
      for(const key of statuses){
        const option=make('option',titles[key]);option.value=key;
        status.append(option);
      }
      status.value=task.status;statusLabel.append(status);
      form.append(statusLabel);
      const stepBox=make('div',undefined,'task-checklist');
      for(const step of task.steps){
        const label=make('label');
        const input=make('input');input.type='checkbox';input.checked=step.done===true;
        input.dataset.stepId=step.id;
        label.append(input,document.createTextNode(' '+step.title));
        stepBox.append(label);
      }
      if(task.steps.length)form.append(stepBox);
      const evidenceLabel=make('label','Completion evidence (user-provided, not verified)');
      const evidence=make('textarea');evidence.rows=2;evidence.maxLength=800;
      evidence.placeholder='What was done? Paste an actual link or specific result; never a password or private key.';
      evidence.value=task.completionNote||'';
      evidence.dataset.field='completionNote';
      evidenceLabel.append(evidence);form.append(evidenceLabel);
      const controls=make('div',undefined,'task-row');
      const save=make('button','Save progress');save.type='button';save.dataset.save='true';
      save.onclick=()=>change(task,form);
      const chat=make('button','Discuss in chat');chat.type='button';
      chat.onclick=()=>{
        $('message').value='Help me work on this task: '+task.title+
          '. Make a clear next-action plan. Do not claim a tool ran or the task was completed without evidence.';
        close();$('message').focus();
      };
      const del=make('button','Delete');del.type='button';del.className='task-delete';
      del.onclick=()=>remove(task);
      controls.append(save,chat,del);form.append(controls);
      const disclosure=make('details');
      const summary=make('summary','Activity history ('+(task.events||[]).length+')');
      disclosure.append(summary);
      for(const event of (task.events||[]).slice().reverse().slice(0,12)){
        disclosure.append(make('p',new Date(event.at).toLocaleString()+
          ' · '+String(event.action||'USER_EVENT').replaceAll('_',' ')+
          (event.status?' · '+titles[event.status]||event.status:''),'task-muted'));
      }
      box.append(title,meta,form,disclosure);root.append(box);
    }
  }
  function openPanel(){
    open=true;$('taskPanel').hidden=false;
    $('taskToggle').setAttribute('aria-expanded','true');
    $('taskTitle').focus();
    void reload();
  }
  function close(){
    open=false;$('taskPanel').hidden=true;
    $('taskToggle').setAttribute('aria-expanded','false');
  }
  function suggest(){
    try{
      const title=escapeField($('taskTitle').value,160).toLowerCase();
      let steps=['Define a measurable result','Check dependencies and permissions',
        'Perform a user-approved action','Check the result and record evidence'];
      if(/\b(?:code|build|app|api|website|backend|deploy|github)\b/i.test(title))
        steps=['Write acceptance criteria','Implement in a reviewed branch',
          'Run automated tests','Deploy after review and verify live behavior'];
      else if(/\b(?:email|market|sales|post|publish|customers|campaign)\b/i.test(title))
        steps=['Define audience and permission to contact','Prepare accurate campaign content',
          'Review and approve publication','Publish through a connected account and record the live link'];
      else if(/\b(?:privi|chain|web3|token|mainnet|contract|quantum)\b/i.test(title))
        steps=['Define scope, test environment and safety gates',
          'Implement and test the change','Review security and independent verification',
          'Approve release and record deployment evidence'];
      $('taskSteps').value=steps.join('\n');
      note('Starter checklist suggested. Edit it before saving; no actions have been executed.');
    }catch(error){note(error.message);}
  }
  function exportTasks(){
    const data={product:'Hey Jose Mission Control',exportedAt:new Date().toISOString(),
      storage:mode==='guest'?'GUEST_BROWSER_ONLY':'TEMPORARY_RENDER_SERVER',
      verification:'ALL_COMPLETION_EVIDENCE_IS_USER_REPORTED',tasks};
    const link=document.createElement('a');
    const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));
    link.href=url;link.download='hey-jose-mission-control.json';document.body.append(link);
    link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    note('Exported task records. Keep the JSON in a safe location.');
  }
  $('taskToggle').onclick=()=>{
    if(open)close();else openPanel();
  };
  $('taskClose').onclick=close;
  $('taskSuggest').onclick=suggest;
  $('taskAdd').onclick=()=>void create();
  $('taskExport').onclick=exportTasks;
  $('taskFilter').onchange=render;
  window.addEventListener('jose-auth-changed',()=>{if(open)void reload();else{++epoch;tasks=[];}});
  window.joseTasks=Object.freeze({open:openPanel,close,reload});
})();
