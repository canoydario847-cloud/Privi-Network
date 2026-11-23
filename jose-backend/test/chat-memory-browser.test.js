import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const code=readFileSync(new URL('../public/chat-memory.js',import.meta.url),'utf8');
function browser(saved=new Map(),canStore=true){
  const store={
    getItem:key=>saved.has(key)?saved.get(key):null,
    setItem:(key,value)=>{if(!canStore)throw Error('blocked');saved.set(key,String(value));}
  };
  const window={};
  const context={window,localStorage:store,document:{getElementById:()=>null},confirm:()=>true,console};
  runInNewContext(code,context);
  return {api:window.joseMemory,saved};
}
test('memories persist in the same browser across new chats or reloads',()=>{
 const saved=new Map(),a=browser(saved);
 assert.deepEqual(Array.from(a.api.getNotes()),[]);
 assert.match(a.api.message('Remember that I prefer short answers'),/Saved in this browser/);
 assert.deepEqual(Array.from(a.api.getNotes()),['I prefer short answers']);
 const second=browser(saved);
 assert.match(second.api.list(),/I prefer short answers/);
 assert.deepEqual(Array.from(second.api.getNotes()),['I prefer short answers']);
});
test('different browser profiles cannot access one another notes',()=>{
 const first=browser(new Map()),second=browser(new Map());
 first.api.save('My app is Hey Jose');
 assert.equal(second.api.getNotes().length,0);
 assert.doesNotMatch(second.api.list(),/My app is Hey Jose/);
});
test('memory is explicitly controlled, not automatically inferred from chat',()=>{
 const a=browser();
 assert.equal(a.api.message('What is Detroit?'),null);
 assert.equal(a.api.getNotes().length,0);
 assert.match(a.api.message('turn memory off'),/Memory is off/);
 a.api.save('I like simple answers');
 assert.match(a.api.message('turn memory off'),/Memory is off/);
 assert.equal(a.api.getNotes().length,0);
 assert.match(a.api.list(),/I like simple answers/);
 assert.match(a.api.message('turn memory on'),/Memory is on/);
 assert.equal(a.api.getNotes().length,1);
});
test('show, forget exactly and forget all operate with explicit requests',()=>{
 const a=browser();
 a.api.save('I prefer short replies');
 a.api.save('My project is Privi Network');
 assert.match(a.api.message('what do you remember about me?'),/Privi Network/);
 assert.match(a.api.message('forget that I prefer short replies'),/Forgot/);
 assert.equal(a.api.getNotes().length,1);
 assert.match(a.api.message('forget everything'),/deleted/);
 assert.equal(a.api.getNotes().length,0);
});
test('memory is bounded and rejects credential strings and duplicate notes',()=>{
 const a=browser();
 assert.throws(()=>a.api.save('API key: sk-proj-verylongsecretvalue123'),/not store passwords/);
 assert.throws(()=>a.api.save('x'.repeat(181)),/between 3 and 180/);
 a.api.save('I like clear explanations');
 assert.match(a.api.save('i like clear explanations'),/already/);
 for(let i=0;i<24;i++)a.api.save('Memory number '+i);
 assert.equal(a.api.getNotes().length,25);
 assert.throws(()=>a.api.save('Memory number 25'),/Memory is full/);
});
test('browser storage failures do not report successful saves',()=>{
 const a=browser(new Map(),false);
 assert.match(a.api.message('Remember that I prefer coffee'),/not saved/i);
 assert.equal(a.api.getNotes().length,0);
});
