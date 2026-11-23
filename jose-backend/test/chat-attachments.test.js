import test from 'node:test';
import assert from 'node:assert/strict';
import {validateAttachments,userContentWithAttachments} from '../src/chat-attachments.js';
const image='data:image/png;base64,'+Buffer.from('89504e470d0a1a0a','hex').toString('base64');
test('empty attachments preserve simple text content',()=>{
 assert.equal(userContentWithAttachments('Hi',[]),'Hi');
 assert.equal(userContentWithAttachments('Hi',undefined),'Hi');
});
test('a validated image is passed as a vision input',()=>{
 const p=userContentWithAttachments('What is this?',[{kind:'image',name:'test.png',dataUrl:image}]);
 assert.equal(p[0].text,'What is this?');
 assert.equal(p[2].type,'image_url');
 assert.equal(p[2].image_url.url,image);
});
test('attached text is marked as untrusted context',()=>{
 const p=userContentWithAttachments('Summarize',[{kind:'text',name:'sample.csv',content:'a,b\n1,2'}]);
 assert.match(p[1].text,/UNTRUSTED TEXT ATTACHMENT/);
 assert.match(p[1].text,/1,2/);
});
test('rejected image MIME and broken base64 do not reach provider',()=>{
 assert.throws(()=>validateAttachments([{kind:'image',name:'x.png',dataUrl:'data:image/svg+xml;base64,YQ=='}]));
 assert.throws(()=>validateAttachments([{kind:'image',name:'x.png',dataUrl:'data:image/png;base64,SGVsbG8='}]));
 assert.throws(()=>validateAttachments([{kind:'image',name:'x.png',dataUrl:'data:image/png;base64,ABCD&'}]));
});
test('rejects oversized, exotic and excessive attachments',()=>{
 assert.throws(()=>validateAttachments([{kind:'text',name:'file.exe',content:'a'}]));
 assert.throws(()=>validateAttachments([{kind:'text',name:'x.md',content:'a'.repeat(12001)}]));
 assert.throws(()=>validateAttachments(Array.from({length:3},(_,i)=>({kind:'text',name:'f'+i+'.txt',content:'hi'}))));
 assert.throws(()=>validateAttachments('nonsense'));
});
