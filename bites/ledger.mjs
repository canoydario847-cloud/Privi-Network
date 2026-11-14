export async function deliverHash({url,key,id,digest,createdAt}, transport=fetch) {
  if(!url||!key)return {status:'pending_configuration'};
  const endpoint=new URL(url);if(endpoint.protocol!=='https:'||endpoint.username||endpoint.password)throw Error('Ledger requires HTTPS without URL credentials');
  async function rpc(body,session){
    const r=await transport(url,{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream',Authorization:'Bearer '+key,...(session?{'Mcp-Session-Id':session}:{})},body:JSON.stringify(body),signal:AbortSignal.timeout(12000)});
    if(!r.ok)throw Error('Ledger delivery failed');
    const text=await r.text();let data;
    if(text.startsWith('event:')||text.startsWith('data:')){const line=text.split('\n').filter(x=>x.startsWith('data:')).map(x=>x.slice(5).trim()).filter(x=>x.startsWith('{')).pop();data=JSON.parse(line||'{}');}else data=JSON.parse(text);
    if(data.error)throw Error('Ledger RPC error');return {data,session:r.headers.get('mcp-session-id')};
  }
  const init=await rpc({jsonrpc:'2.0',id:1,method:'initialize',params:{protocolVersion:'2024-11-05',capabilities:{},clientInfo:{name:'privi-bites',version:'1.0.0'}}});
  const ready=await transport(url,{method:'POST',headers:{'Content-Type':'application/json',Accept:'application/json, text/event-stream',Authorization:'Bearer '+key,...(init.session?{'Mcp-Session-Id':init.session}:{})},body:JSON.stringify({jsonrpc:'2.0',method:'notifications/initialized'}),signal:AbortSignal.timeout(12000)});
  if(!ready.ok)throw Error('Ledger initialization failed');
  const result=await rpc({jsonrpc:'2.0',id:2,method:'tools/call',params:{name:'ledger_record_action',arguments:{stream_id:'privi-bites',actor:'privi-bites',action_type:'tool_call',summary:'Bites profile hash receipt',resource:id,details:{schema:'privi-bites:v1',event_id:id,digest,created_at:createdAt}}}},init.session);
  const tool=result.data.result;if(!tool||tool.isError)throw Error('Ledger rejected receipt');
  let payload=tool.structuredContent;for(const item of tool.content||[]){if(!payload&&item.type==='text'){try{payload=JSON.parse(item.text);}catch{}}}
  const hash=payload?.entry?.entry_hash;if(payload?.recorded!==true||typeof hash!=='string'||!/^[a-fA-F0-9]{64}$/.test(hash))throw Error('Ledger receipt not confirmed');
  return {status:'confirmed',receipt:hash};
}
