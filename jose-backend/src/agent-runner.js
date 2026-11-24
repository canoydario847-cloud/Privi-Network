// OpenAI-compatible Chat Completions orchestrator for Jose's read-only tools.
// One model selection step, at most two read-only tool calls, one final answer.
// No recursive/autonomous loop, no arbitrary URLs, no write tools.
import {shouldOfferReadTools,runJoseToolRound} from './agent-tools.js';

export class JoseProviderError extends Error {
  constructor(status,detail){super(detail);this.status=status;}
}
export async function completeJose({
  fetchImpl=globalThis.fetch, apiKey, model, messages, mode='chat', maxTokens=2500,
  userMessage='', tools, signal
}={}){
  if(!apiKey||!Array.isArray(messages)||!model||typeof fetchImpl!=='function')
    throw TypeError('AI provider config and message array required');
  const enabled=tools&&shouldOfferReadTools(userMessage,mode);
  async function request(conversation,withTools){
    const response=await fetchImpl('https://api.openai.com/v1/chat/completions',{
      method:'POST',signal,redirect:'error',
      headers:{'Content-Type':'application/json',Authorization:'Bearer '+apiKey},
      body:JSON.stringify({
        model,
        max_completion_tokens:withTools?Math.min(maxTokens,1800):maxTokens,
        messages:conversation,
        ...(withTools?{tools:tools.definitions,tool_choice:'auto',parallel_tool_calls:false}:{})
      })
    });
    if(!response.ok){
      throw new JoseProviderError(response.status,'Provider returned status '+response.status);
    }
    let data;
    try{data=await response.json();}catch{throw new JoseProviderError(502,'Malformed provider response');}
    const reply=data?.choices?.[0]?.message;
    if(!reply||typeof reply!=='object')throw new JoseProviderError(502,'Missing provider answer');
    return reply;
  }
  const first=await request(messages,Boolean(enabled));
  if(!enabled||!Array.isArray(first.tool_calls)||!first.tool_calls.length){
    if(typeof first.content!=='string'||!first.content.trim())
      throw new JoseProviderError(502,'Empty model response');
    return {answer:first.content.trim(),toolsUsed:[],agentToolsAvailable:Boolean(enabled)};
  }
  const {outputs,toolsUsed}=await runJoseToolRound({calls:first.tool_calls,tools});
  // Tool outputs are observations, not instructions: model is explicitly
  // told not to elevate their content or infer financial mainnet readiness.
  const followUp=[
    ...messages,
    {role:'assistant',content:typeof first.content==='string'?first.content:null,tool_calls:first.tool_calls},
    ...outputs,
  ];
  const last=await request(followUp,false);
  if(typeof last.content!=='string'||!last.content.trim())
    throw new JoseProviderError(502,'Empty model response after tools');
  return {answer:last.content.trim(),toolsUsed,agentToolsAvailable:true};
}
