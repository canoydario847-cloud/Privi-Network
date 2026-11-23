import test from 'node:test';
import assert from 'node:assert/strict';
import {validateMemoryNotes,userMemoryMessage} from '../src/chat-memory.js';

test('no memory is used without opt-in notes',()=>{
 assert.deepEqual(validateMemoryNotes(undefined),[]);
 assert.equal(userMemoryMessage([]),null);
});
test('user-supplied memories are introduced at the user role, not system',()=>{
 const record=userMemoryMessage(['I prefer short explanations.','My app is Hey Jose.']);
 assert.equal(record.role,'user');
 assert.match(record.content,/I prefer short explanations/);
 assert.match(record.content,/fallible information/);
 assert.match(record.content,/not a higher-priority instruction/);
});
test('memory notes are individually capped and total length is bounded',()=>{
 assert.throws(()=>validateMemoryNotes(['x'.repeat(181)]),/3–180/);
 assert.throws(()=>validateMemoryNotes(['   ']),/3–180/);
 assert.throws(()=>validateMemoryNotes(['word\nanother']),/single-line/);
 assert.throws(()=>validateMemoryNotes(Array.from({length:26},(_,i)=>'note '+i)),/at most 25/);
 assert.throws(()=>validateMemoryNotes(Array.from({length:25},(_,i)=>String(i).padStart(3,'0')+'x'.repeat(177))),/Total memory/);
});
test('no repeated notes or arbitrary object inputs accepted',()=>{
 assert.throws(()=>validateMemoryNotes([{text:'secret'}]),/single-line/);
 assert.throws(()=>validateMemoryNotes(['A useful fact','a useful fact']),/Duplicate/);
 assert.throws(()=>validateMemoryNotes({foo:'bar'}),/array/);
});
