// Hey Jose Mission Control: explicit user-managed tasks, not autonomous agents.
// Tasks never imply remote work happened. "Completed" means user-reported,
// with an evidence note supplied by that user, not independent verification.
export const MAX_TASKS=30;
export const MAX_STEPS=12;
export const TASK_STATUSES=Object.freeze(['planned','in_progress','blocked','awaiting_approval','completed']);
export class TaskInputError extends Error{
  constructor(message,status=400){super(message);this.name='TaskInputError';this.status=status;}
}
const bad=(message,status=400)=>{throw new TaskInputError(message,status);};
const plain=(value,label,max,{minimum=1,optional=false}={})=>{
  if(optional&&(value===undefined||value===null||value===''))return '';
  if(typeof value!=='string')bad(label+' must be text.');
  const v=value.replace(/\s+/g,' ').trim();
  if(v.length<minimum||v.length>max)bad(label+' must be '+minimum+'–'+max+' characters.');
  return v;
};
function dueDate(value){
  if(value===undefined||value===null||value==='')return null;
  if(typeof value!=='string'||!/^20\d{2}-\d{2}-\d{2}$/.test(value)||
    Number.isNaN(Date.parse(value+'T00:00:00Z'))||
    new Date(value+'T00:00:00Z').toISOString().slice(0,10)!==value)
      bad('Use a valid YYYY-MM-DD due date or leave it empty.');
  return value;
}
export function validateNewTask(value){
  if(!value||typeof value!=='object'||Array.isArray(value))bad('Provide a task object.');
  if(Object.keys(value).some(k=>!['title','steps','dueDate'].includes(k)))
    bad('Only title, steps and dueDate are accepted when creating a task.');
  const title=plain(value.title,'Task title',160);
  const steps=value.steps===undefined?[]:value.steps;
  if(!Array.isArray(steps)||steps.length>MAX_STEPS)bad('Supply at most 12 checklist steps.');
  const cleaned=steps.map(x=>plain(x,'Checklist step',180));
  if(new Set(cleaned.map(x=>x.toLowerCase())).size!==cleaned.length)
    bad('Checklist steps must be unique.');
  return {title,steps:cleaned,dueDate:dueDate(value.dueDate)};
}
export function validateTaskChanges(changes,existing){
  if(!changes||typeof changes!=='object'||Array.isArray(changes)||
     Object.keys(changes).some(k=>!['title','status','dueDate','doneSteps','completionNote'].includes(k))||
     !Object.keys(changes).length)
    bad('Supply a task change (title, status, dueDate, doneSteps or completionNote).');
  const next={
    ...existing,
    steps:existing.steps.map(s=>({...s})),
  };
  if(Object.hasOwn(changes,'title'))next.title=plain(changes.title,'Task title',160);
  if(Object.hasOwn(changes,'status')){
    if(!TASK_STATUSES.includes(changes.status))bad('Invalid task status.');
    next.status=changes.status;
  }
  if(Object.hasOwn(changes,'dueDate'))next.dueDate=dueDate(changes.dueDate);
  if(Object.hasOwn(changes,'doneSteps')){
    const ids=changes.doneSteps;
    if(!Array.isArray(ids)||ids.length>MAX_STEPS||ids.some(id=>typeof id!=='string'))
      bad('doneSteps must be a list of checklist step IDs.');
    if(new Set(ids).size!==ids.length||ids.some(id=>!next.steps.some(step=>step.id===id)))
      bad('Unknown or duplicate checklist step ID.');
    const done=new Set(ids);
    next.steps=next.steps.map(step=>({...step,done:done.has(step.id)}));
  }
  if(Object.hasOwn(changes,'completionNote'))
    next.completionNote=plain(changes.completionNote,'Completion evidence note',800,{minimum:10,optional:true});
  if(next.status==='completed' && !next.completionNote)
    bad('To mark completed, add an evidence note explaining what was actually done (at least 10 characters).');
  if(next.status==='completed' && next.steps.some(step=>!step.done))
    bad('Finish each checklist step before marking the whole task completed.');
  // This field is always explicit: never claim a system-verified action.
  next.completionEvidenceType=next.completionNote?'USER_REPORTED_NOT_INDEPENDENTLY_VERIFIED':null;
  next.execution='MANUAL_USER_CONTROLLED';
  return next;
}
export function publicTask(row){
  if(!row)return null;
  return {
    id:row.id,title:row.title,status:row.status,dueDate:row.dueDate,
    steps:row.steps.map(s=>({...s})),createdAt:row.createdAt,updatedAt:row.updatedAt,
    completionNote:row.completionNote||'',
    completionEvidenceType:row.completionEvidenceType||null,
    execution:'MANUAL_USER_CONTROLLED',
    verification:'USER_MANAGED_NOT_AUTOMATICALLY_EXECUTED',
    events:(row.events||[]).map(e=>({...e})),
  };
}
