import test from 'node:test';
import assert from 'node:assert/strict';
import {
  shouldOfferReadTools, createJoseReadTools, JOSE_READ_TOOLS,
  runJoseToolRound, MAX_TOOL_CALLS
} from '../src/agent-tools.js';
import {completeJose,JoseProviderError} from '../src/agent-runner.js';

const wallet='0x'+'a'.repeat(40);
const hash='0x'+'b'.repeat(64);
function mockTools(){
 const called=[];
 const status={connected:true,observedEvmChainId:772626,financialMainnet:false,currency:'TEST (valueless)'};
 const devnet={
  check:async()=>{called.push('status');return status;},
  balance:async(address)=>{called.push('balance');return {address,chainId:772626,balanceWei:'1000000',asset:'TEST (valueless)'};},
  receipt:async(tx)=>{called.push('receipt');return {hash:tx,chainId:772626,status:'success',network:'Privi Devnet'};}
 };
 const monitor={getReport:()=>{called.push('health');return {fresh:true,score:85,monitoringScope:'APPLICATION_SERVICES_ONLY',financialMainnetActivated:false};}};
 return {tools:createJoseReadTools({devnet,monitor}),called};
}
function call(name,args,id='call_1'){return {id,type:'function',function:{name,arguments:JSON.stringify(args)}};}
test('read-only agent tool catalog exposes only fixed approved functions',()=>{
 assert.equal(JOSE_READ_TOOLS.length,5);
 for(const tool of JOSE_READ_TOOLS){
  assert.equal(tool.type,'function');
  assert.match(tool.function.name,/^(privi_|jose_)/);
  assert.equal(tool.function.parameters.additionalProperties,false);
  assert.doesNotMatch(tool.function.name,/send|write|mint|sign|deploy|gmail/i);
 }
});
test('tools selected only for relevant Privi questions, never app build',()=>{
 assert.equal(shouldOfferReadTools('Is Privi network healthy?'),true);
 assert.equal(shouldOfferReadTools('Get my wallet balance'),true);
 assert.equal(shouldOfferReadTools('Privi transaction receipt'),true);
 assert.equal(shouldOfferReadTools('What is Privi Devnet status?'),true);
 assert.equal(shouldOfferReadTools('How is the weather?'),false);
 assert.equal(shouldOfferReadTools('Write a business plan'),false);
 assert.equal(shouldOfferReadTools('Build Privi network health dashboard','build'),false);
});
test('read-only tool reads verified service monitor and devnet status',async()=>{
 const {tools,called}=mockTools();
 const a=await tools.execute('privi_service_health',{});
 const b=await tools.execute('privi_devnet_status',{});
 assert.equal(a.monitoringScope,'APPLICATION_SERVICES_ONLY');
 assert.equal(b.financialMainnet,false);
 assert.deepEqual(called,['health','status']);
});
test('wallet and receipts are strictly validated and cannot broadcast',async()=>{
 const {tools,called}=mockTools();
 assert.equal((await tools.execute('privi_devnet_balance',{address:wallet})).chainId,772626);
 assert.equal((await tools.execute('privi_devnet_receipt',{hash})).hash,hash);
 assert.deepEqual(called,['balance','receipt']);
 await assert.rejects(tools.execute('privi_devnet_balance',{address:'1',extra:'no'}),/valid public/);
 await assert.rejects(tools.execute('privi_devnet_receipt',{hash:'0x123'}),/valid public/);
 await assert.rejects(tools.execute('eth_sendTransaction',{}),/disallowed/);
 await assert.rejects(tools.execute('privi_service_health',{url:'http://localhost'}),/No arguments/);
});
test('malformed, oversized, duplicate and unapproved tool call batches fail closed',async()=>{
 const {tools,called}=mockTools();
 await assert.rejects(runJoseToolRound({calls:[call('write_email',{})],tools}),/Unsupported/);
 await assert.rejects(runJoseToolRound({calls:[call('privi_service_health',{}),call('privi_devnet_status',{}),call('jose_capabilities',{})],tools}),/more tool calls/);
 await assert.rejects(runJoseToolRound({calls:[call('privi_service_health',{},'x'),call('privi_devnet_status',{},'x')],tools}),/Duplicate/);
 await assert.rejects(runJoseToolRound({calls:[{id:'x',type:'function',function:{name:'privi_service_health',arguments:'{'}}],tools}),/Invalid tool/);
 await assert.rejects(runJoseToolRound({calls:[{id:'x',type:'function',function:{name:'privi_service_health',arguments:' '.repeat(801)}}],tools}),/exceed/);
 assert.equal(called.length,0);
 assert.equal(MAX_TOOL_CALLS,2);
});
test('one trusted read-only tool round then final answer, no recursive tools',async()=>{
 const {tools,called}=mockTools();
 const payloads=[];
 const fetchImpl=async(_url,opts)=>{
  const req=JSON.parse(opts.body);
  payloads.push(req);
  if(payloads.length===1)return {ok:true,status:200,json:async()=>({
   choices:[{message:{role:'assistant',content:null,tool_calls:[call('privi_service_health',{})]}}
  ]})};
  return {ok:true,status:200,json:async()=>({
   choices:[{message:{role:'assistant',content:'Verified service health reports A/B/C; this does not certify PRVI financial mainnet.'}}
  ]})};
 };
 const result=await completeJose({fetchImpl,apiKey:'test',model:'mock-model',mode:'chat',
  maxTokens:2500,messages:[{role:'user',content:'Is Privi network healthy?'}],
  userMessage:'Is Privi network healthy?',tools});
 assert.equal(result.toolsUsed[0],'privi_service_health');
 assert.equal(called.length,1);
 assert.equal(payloads.length,2);
 assert.equal(payloads[0].tool_choice,'auto');
 assert.equal(payloads[0].parallel_tool_calls,false);
 assert.equal(payloads[0].max_completion_tokens,1800);
 assert.equal(payloads[1].max_completion_tokens,2500);
 assert.equal(payloads[1].tools,undefined,'second response cannot request more tools');
 assert.ok(payloads[1].messages.some(m=>m.role==='tool'&&m.content.includes('APPLICATION_SERVICES_ONLY')));
 assert.match(result.answer,/does not certify/);
});
test('ordinary chat uses one model call, no tool overhead',async()=>{
 const {tools}=mockTools();
 let n=0,payload=null;
 const response=async(_url,opts)=>{n++;payload=JSON.parse(opts.body);return {ok:true,status:200,json:async()=>({choices:[{message:{content:'A simple answer.'}}]})};};
 const result=await completeJose({fetchImpl:response,apiKey:'test',model:'mock-model',mode:'chat',
   messages:[{role:'user',content:'Explain gravity'}],userMessage:'Explain gravity',tools});
 assert.equal(n,1);
 assert.deepEqual(result.toolsUsed,[]);
 assert.equal(payload.tools,undefined);
 assert.equal(result.answer,'A simple answer.');
});
test('model errors are explicit and do not get reported as verified facts',async()=>{
 const {tools}=mockTools();
 const bad=async()=>({ok:false,status:429});
 await assert.rejects(completeJose({fetchImpl:bad,apiKey:'test',model:'mock',messages:[],
   userMessage:'Privi network status',tools}),e=>e instanceof JoseProviderError&&e.status===429);
 const invalid=async()=>({ok:true,status:200,json:async()=>({choices:[{message:{content:null,tool_calls:[call('send_gmail',{})]}}]})});
 await assert.rejects(completeJose({fetchImpl:invalid,apiKey:'test',model:'mock',messages:[],
   userMessage:'Privi network status',tools}),/Unsupported agent tool request/);
});
