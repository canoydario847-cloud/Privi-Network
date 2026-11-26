import test from 'node:test';
import assert from 'node:assert/strict';
import {
  MAX_TASKS,MAX_STEPS,TASK_STATUSES,TaskInputError,
  validateNewTask,validateTaskChanges,publicTask
} from '../src/task-center.js';

const sample={
 id:'00000000-0000-4000-8000-000000000001',ownerId:'private-account-id',
 title:'Publish Hey Jose demo',status:'planned',dueDate:null,
 steps:[{id:'step-a',title:'Record real demo',done:false},
        {id:'step-b',title:'Review product claims',done:false}],
 completionNote:'',createdAt:1000,updatedAt:1000,
 events:[{at:1000,action:'CREATED_BY_USER'}]
};
test('tasks are bounded and require nonempty, unique checklist steps',()=>{
  assert.equal(MAX_TASKS,30);assert.equal(MAX_STEPS,12);
  assert.deepEqual(TASK_STATUSES,['planned','in_progress','blocked','awaiting_approval','completed']);
  const x=validateNewTask({title:'  Launch   Jose  ',steps:[' Prepare  demo ',' Publish '],dueDate:'2026-12-01'});
  assert.deepEqual(x,{title:'Launch Jose',steps:['Prepare demo','Publish'],dueDate:'2026-12-01'});
  for(const input of [null,[],{title:''},{title:'x'.repeat(161)},
    {title:'A',steps:[1]},{title:'A',steps:['One',' one ']},
    {title:'A',steps:new Array(13).fill('Step')},
    {title:'A',dueDate:'2026-02-30'},
    {title:'A',attachments:['wallet.key']}]){
    assert.throws(()=>validateNewTask(input),TaskInputError);
  }
});
test('unverified actions can never be auto-marked completed',()=>{
  assert.throws(()=>validateTaskChanges({status:'completed'},sample),/evidence note/);
  assert.throws(()=>validateTaskChanges({
    status:'completed',completionNote:'I think it is done'
  },sample),/Finish each checklist step/);
  assert.throws(()=>validateTaskChanges({
    status:'completed',completionNote:'short'
  },sample),/at least|10–800/);
  const done=validateTaskChanges({
    status:'completed',
    doneSteps:['step-a','step-b'],
    completionNote:'Screenshot and test run reviewed manually'
  },sample);
  assert.equal(done.status,'completed');
  assert.equal(done.steps.every(x=>x.done),true);
  assert.equal(done.execution,'MANUAL_USER_CONTROLLED');
  assert.equal(done.completionEvidenceType,'USER_REPORTED_NOT_INDEPENDENTLY_VERIFIED');
  assert.equal(sample.status,'planned','validation must not mutate original data');
});
test('task step ID ownership is validated before modifying state',()=>{
  for(const input of [
    {doneSteps:['other-account-step']},{doneSteps:['step-a','step-a']},
    {status:'running'},{admin:true},{status:'done'},{dueDate:'2026-13-01'},
    {completionNote:5},[],{}
  ])assert.throws(()=>validateTaskChanges(input,sample),TaskInputError);
  const updated=validateTaskChanges({status:'awaiting_approval',doneSteps:['step-a']},sample);
  assert.equal(updated.steps[0].done,true);
  assert.equal(updated.steps[1].done,false);
  assert.equal(updated.status,'awaiting_approval');
});
test('public task summary never exposes ownerId or claims independent verification',()=>{
  const item=publicTask(sample);
  assert.equal(item.ownerId,undefined);
  assert.equal(item.verification,'USER_MANAGED_NOT_AUTOMATICALLY_EXECUTED');
  assert.equal(item.execution,'MANUAL_USER_CONTROLLED');
  assert.equal(item.events.length,1);
  item.steps[0].title='modified';
  assert.equal(sample.steps[0].title,'Record real demo');
});
