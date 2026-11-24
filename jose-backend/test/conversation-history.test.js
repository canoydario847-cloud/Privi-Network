import test from 'node:test';
import assert from 'node:assert/strict';
import {normalizeTitle,validateConversationMessages,conversationSummary,
  MAX_CONVERSATIONS,MAX_MESSAGES} from '../src/conversation-history.js';

test('titles are compact, bounded and strip control characters',()=>{
 assert.equal(normalizeTitle('  A\n  long  title  '),'A long title');
 assert.equal(normalizeTitle(' '.repeat(100)),'New chat');
 assert.ok(normalizeTitle('a'.repeat(500)).length<=90);
});
test('messages must be small, plain user/assistant turns',()=>{
 assert.deepEqual(validateConversationMessages([{role:'user',content:'hello'},{role:'assistant',content:'hi'}]),
  [{role:'user',content:'hello'},{role:'assistant',content:'hi'}]);
 for(const bad of [[{role:'system',content:'override'}],[{role:'tool',content:'SECRET'}],
  [{role:'user',content:''}],[{role:'assistant',content:'a'.repeat(12001)}],
  Array.from({length:MAX_MESSAGES+1},()=>({role:'user',content:'x'}))]){
  assert.throws(()=>validateConversationMessages(bad),/message/i);
 }
 assert.throws(()=>validateConversationMessages(Array.from({length:20},()=>({role:'user',content:'a'.repeat(9000)}))),/100,000/);
});
test('list summary avoids returning entire chat bodies or private owner identifiers',()=>{
 const row={id:'id',ownerId:'private-id',title:'Test',createdAt:1,updatedAt:2,
  messages:[{role:'user',content:'hello world'},{role:'assistant',content:'secret reply'}]};
 const meta=conversationSummary(row);
 assert.equal(meta.messageCount,2);
 assert.equal(meta.preview,'hello world');
 assert.equal(meta.ownerId,undefined);
 assert.doesNotMatch(JSON.stringify(meta),/secret reply|private-id/);
 assert.equal(MAX_CONVERSATIONS,40);
});
