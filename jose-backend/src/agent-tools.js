// Jose read-only agent tools: no arbitrary HTTP requests, code execution,
// email, wallet signing, state mutation, or paid third-party actions.
// Tool calls do not implicitly authenticate a user or grant account access.
export const JOSE_READ_TOOLS = Object.freeze([
  {
    type:'function',
    function:{
      name:'privi_service_health',
      description:'Read the latest monitored Privi application service health report. This is NOT blockchain consensus health or financial mainnet certification.',
      parameters:{type:'object',properties:{},additionalProperties:false}
    }
  },
  {
    type:'function',
    function:{
      name:'privi_devnet_status',
      description:'Verify the live valueless Privi Devnet RPC and EVM chain ID 772626. Never represent this as the production financial PRVI mainnet.',
      parameters:{type:'object',properties:{},additionalProperties:false}
    }
  },
  {
    type:'function',
    function:{
      name:'privi_devnet_balance',
      description:'Read a public EVM wallet TEST balance on verified Privi Devnet only. No wallet signing or sending.',
      parameters:{type:'object',properties:{address:{type:'string',description:'Public EVM address, starting with 0x and containing exactly 40 hex digits'}},required:['address'],additionalProperties:false}
    }
  },
  {
    type:'function',
    function:{
      name:'privi_devnet_receipt',
      description:'Read an existing transaction receipt by its public transaction hash from the valueless Privi Devnet. Never broadcast.',
      parameters:{type:'object',properties:{hash:{type:'string',description:'0x followed by exactly 64 hex characters'}},required:['hash'],additionalProperties:false}
    }
  },
  {
    type:'function',
    function:{
      name:'jose_capabilities',
      description:'Describe the existing deterministic local tools and connection limitations. This is a static capability inventory, not proof of connected accounts.',
      parameters:{type:'object',properties:{},additionalProperties:false}
    }
  },
]);
const ALLOWED = new Set(JOSE_READ_TOOLS.map(x=>x.function.name));
export const MAX_TOOL_CALLS = 2;
export const MAX_TOOL_ARGUMENT_CHARS = 800;
export function shouldOfferReadTools(message,mode='chat'){
  if(mode==='build'||typeof message!=='string')return false;
  const q=message.toLowerCase();
  // Limit provider overhead to relevant questions instead of charging
  // a tool-selection token premium on every everyday conversation.
  return (/\b(?:privi|devnet|jose|wallet|transaction|tx|on.chain|blockchain)\b/i.test(q)
    && /\b(?:health|status|grade|down|up|online|working|availability|connected|balance|funds|receipt|transaction|tx|latest|block|network|chain\s*id|capabilit|tools|services)\b/i.test(q));
}
export function createJoseReadTools({devnet,monitor}){
  if(!devnet||!monitor)throw TypeError('Trusted devnet and monitor required');
  async function execute(name,args){
    if(!ALLOWED.has(name))throw Error('Unrecognized or disallowed read-only tool.');
    if(!args||typeof args!=='object'||Array.isArray(args))throw Error('Tool arguments must be an object.');
    if(name==='privi_service_health'){
      if(Object.keys(args).length)throw Error('No arguments accepted.');
      // The monitor is already actively sampling: avoid user-triggered external fan-out.
      return monitor.getReport();
    }
    if(name==='privi_devnet_status'){
      if(Object.keys(args).length)throw Error('No arguments accepted.');
      return await devnet.check();
    }
    if(name==='privi_devnet_balance'){
      if(Object.keys(args).length!==1||typeof args.address!=='string'||!/^0x[a-fA-F0-9]{40}$/.test(args.address))
        throw Error('A valid public EVM address is required.');
      return await devnet.balance(args.address);
    }
    if(name==='privi_devnet_receipt'){
      if(Object.keys(args).length!==1||typeof args.hash!=='string'||!/^0x[a-fA-F0-9]{64}$/.test(args.hash))
        throw Error('A valid public transaction hash is required.');
      return await devnet.receipt(args.hash);
    }
    if(name==='jose_capabilities'){
      if(Object.keys(args).length)throw Error('No arguments accepted.');
      return {assistant:'Hey Jose',localPowers:20,readOnlyAgentTools:JOSE_READ_TOOLS.map(x=>x.function.name),
        permissions:'READ_ONLY_VERIFIED_PUBLIC_DATA',gmail:'REQUIRES_OPERATOR_OAUTH_AND_USER_CONSENT',
        financialMainnet:false,autonomousTransactions:false};
    }
  }
  return Object.freeze({definitions:JOSE_READ_TOOLS,execute});
}
function safeArguments(value){
  if(typeof value!=='string'||value.length>MAX_TOOL_ARGUMENT_CHARS)throw Error('Tool arguments exceed allowed size.');
  let data;
  try{data=JSON.parse(value);}catch{throw Error('Invalid tool arguments JSON.');}
  if(!data||typeof data!=='object'||Array.isArray(data))throw Error('Tool arguments must be an object.');
  return data;
}
export async function runJoseToolRound({calls,tools}){
  if(!Array.isArray(calls)||calls.length<1||calls.length>MAX_TOOL_CALLS)
    throw Error('Model requested more tool calls than the safe per-response limit.');
  if(new Set(calls.map(x=>x.id)).size!==calls.length)
    throw Error('Duplicate tool call identifiers.');
  // Validate entire batch before invoking any read-only action.
  const validated=calls.map(call=>{
    if(call?.type!=='function'||typeof call.id!=='string'||call.id.length>96||call.id.length<1||
       !ALLOWED.has(call.function?.name))throw Error('Unsupported agent tool request.');
    return {id:call.id,name:call.function.name,args:safeArguments(call.function.arguments)};
  });
  const outputs=[];
  for(const call of validated){
    let content;
    try{
      const result=await tools.execute(call.name,call.args);
      content=JSON.stringify({ok:true,data:result}).slice(0,9500);
    }catch(error){
      content=JSON.stringify({ok:false,error:String(error?.message||'Tool unavailable').slice(0,170)});
    }
    outputs.push({role:'tool',tool_call_id:call.id,content});
  }
  return {outputs,toolsUsed:validated.map(x=>x.name)};
}
