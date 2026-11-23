// Hey Jose's 20 local, deterministic, opt-in "powers" — never claim external access.
// No network calls, wallet signing, billing, automation or secret persistence.
// Ask /powers inside the same chat for usage. Copyright 2026 Privi World Corp.
import { createHash } from 'node:crypto';

export const JOSE_POWERS = Object.freeze([
  ['privacy','Privacy Mask','Redact common personal details from pasted text','/privacy Paste text'],
  ['secrets','Credential Alarm','Detect possible leaked credentials without displaying them','/secrets Paste text'],
  ['url-risk','URL Safety Lens','Check URL structure and phishing indicators offline','/url-risk https://example.org'],
  ['claims','Evidence Lens','List numerical or absolute claims needing source verification','/claims Paste statements'],
  ['fingerprint','Proof Fingerprint','Compute a SHA-256 hash of supplied text','/fingerprint Paste text'],
  ['verify-fingerprint','Proof Recheck','Compare text against a previously recorded SHA-256','/verify-fingerprint {"content":"hello","sha256":"..."}'],
  ['json-lint','Data Integrity','Parse JSON and report the structure without echoing values','/json-lint {"a":1}'],
  ['csv-stats','CSV Inspector','Profile CSV rows, missing cells and numeric fields','/csv-stats a,b\n1,2'],
  ['compare','Change Inspector','Show changed lines between two text versions','/compare old text\n--- VS ---\nnew text'],
  ['invoice-check','Invoice Math Auditor','Recalculate invoice line items, tax and totals','/invoice-check {"items":[{"qty":2,"unitPrice":15}],"taxRatePercent":6}'],
  ['runway','Survival Runway','Estimate months of runway from provided cash and burn','/runway {"cash":1200,"monthlyBurn":600,"monthlyRevenue":200}'],
  ['break-even','Break-even Calculator','Compute sales needed to cover fixed costs','/break-even {"fixedCost":1000,"price":35,"variableCost":5}'],
  ['unit-economics','Customer Margin Lens','Compute per-customer contribution and margin','/unit-economics {"revenue":1000,"variableCost":300,"customers":20}'],
  ['model-cost','AI Call Cost Guardian','Estimate inference spend from user-provided token prices','/model-cost {"inputTokens":10000,"outputTokens":4000,"inputPerMillion":1,"outputPerMillion":4}'],
  ['gas-cost','Gas Fee Guardian','Estimate on-chain gas spend from supplied assumptions','/gas-cost {"gasUnits":100000,"gwei":2,"nativePriceUsd":2000}'],
  ['token-units','Token Precision Guard','Convert whole tokens to exact EVM base units','/token-units {"tokens":"1000000","decimals":18}'],
  ['chain-guard','Network Identity Guard','Recognize known chain IDs and development-network cautions','/chain-guard {"chainId":772626}'],
  ['rpc-guard','Transaction Safety Gate','Check if an EVM JSON-RPC method is read-only','/rpc-guard {"method":"eth_chainId","params":[]}'],
  ['critical-path','Dependency Brain','Compute project order, blockers and longest path','/critical-path {"tasks":[{"id":"A","days":2},{"id":"B","days":3,"dependsOn":["A"]}]}'],
  ['launch-risk','Launch Risk Scanner','Review a launch plan for common missing safeguards','/launch-risk Paste a launch plan']
].map(([id,title,description,usage])=>Object.freeze({id,title,description,usage})));
const COMMANDS=new Map(JOSE_POWERS.map(p=>[p.id,p]));
const USAGE=Object.freeze(Object.fromEntries(JOSE_POWERS.map(p=>[p.id,p.usage])));
const MAX_TEXT=12000;
function requireText(raw){
  const text=String(raw??'').trim();
  if(!text||text.length>MAX_TEXT)throw Error('Provide 1–12,000 characters of content after the command.');
  return text;
}
function obj(raw){
  const text=requireText(raw);let value;
  try{value=JSON.parse(text);}catch{throw Error('Enter a valid JSON object; see the example below.');}
  if(!value||typeof value!=='object'||Array.isArray(value))throw Error('Expected a JSON object.');
  return value;
}
function number(value,name,{min=0,max=1e12,strict=false}={}){
  if(typeof value!=='number'||!Number.isFinite(value)||value<min||value>max||(strict&&value<=min))
    throw Error(name+' must be a finite numeric value from '+min+' to '+max+'.');
  return value;
}
function dollars(n){return '$'+Number(n).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:4});}
function cents(v,label){
  if((typeof v!=='number'&&typeof v!=='string')||! /^\d+(?:\.\d{1,2})?$/.test(String(v)))throw Error(label+' must be a nonnegative money amount with at most 2 decimals.');
  const [a,b='']=String(v).split('.');
  const result=BigInt(a)*100n+BigInt((b+'00').slice(0,2));
  if(result>1000000000000000n)throw Error('Amount is out of range.');
  return result;
}
function moneyCents(c){return '$'+(Number(c)/100).toFixed(2);}
function sha256(text){return createHash('sha256').update(text,'utf8').digest('hex');}
function summaryJSON(value){
  const type=Array.isArray(value)?'array':value===null?'null':typeof value;
  if(type==='array')return 'Top-level array: '+value.length+' entries. Sample entry types: '+Array.from(new Set(value.slice(0,20).map(x=>Array.isArray(x)?'array':x===null?'null':typeof x))).join(', ')+'.';
  if(type==='object'){
    const keys=Object.keys(value);
    return 'Top-level object: '+keys.length+' keys. Keys: '+keys.slice(0,40).map(x=>JSON.stringify(x)+' ('+(Array.isArray(value[x])?'array':value[x]===null?'null':typeof value[x])+')').join(', ')+(keys.length>40?' …':'')+'.';
  }
  return 'Top-level JSON type: '+type+'.';
}
function scanPrivacy(text){
  let out=text;const found=[];
  for(const [label,re,replacement] of [
    ['email',/\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b/gi,'[EMAIL]'],
    ['US Social Security number',/\b\d{3}-\d{2}-\d{4}\b/g,'[SSN]'],
    ['phone',/(?<!\d)(?:\+?1[-.\s]?)?\(?[2-9]\d{2}\)?[-.\s]?[2-9]\d{2}[-.\s]?\d{4}(?!\d)/g,'[PHONE]'],
    ['IPv4 address',/\b(?:\d{1,3}\.){3}\d{1,3}\b/g,'[IP]'],
    ['EVM private key',/\b0x[0-9a-fA-F]{64}\b/g,'[POTENTIAL_PRIVATE_KEY]'],
    ['credential assignment',/\b(?:api[_-]?key|secret|password|auth[_-]?token)\s*[:=]\s*["']?[A-Za-z0-9_\-\/+=]{8,}["']?/gi,'[POTENTIAL_SECRET]'],
  ]){
    const matches=out.match(re);
    if(matches){found.push(label+' ×'+matches.length);out=out.replace(re,replacement);}
  }
  return {out,found};
}
function csvParse(text){
  const rows=[];let row=[],cell='',quoted=false;
  for(let i=0;i<text.length;i++){
    const c=text[i];
    if(c==='"'){
      if(quoted&&text[i+1]==='"'){cell+='"';i++;}else if(quoted){quoted=false;}
      else if(cell===''){quoted=true;}else{cell+=c;}
    }else if(c===','&&!quoted){row.push(cell);cell='';}
    else if((c==='\n'||c==='\r')&&!quoted){
      if(c==='\r'&&text[i+1]==='\n')i++;
      row.push(cell);rows.push(row);row=[];cell='';
      if(rows.length>300)throw Error('CSV contains more than 300 rows. Provide a smaller sample.');
    }else cell+=c;
  }
  if(quoted)throw Error('Unclosed CSV quote.');
  if(cell||row.length){row.push(cell);rows.push(row);}
  if(!rows.length)throw Error('No CSV data supplied.');
  const columns=rows[0].length;
  if(columns>40)throw Error('CSV supports up to 40 columns.');
  if(rows.some(r=>r.length!==columns))throw Error('CSV rows have inconsistent column counts.');
  return rows;
}
function lines(text){return String(text).replace(/\r\n/g,'\n').split('\n');}
function run(id,raw,clock){
  const text=String(raw??'');
  let data;
  if(id==='privacy'){
    const r=scanPrivacy(requireText(text));
    return 'Privacy Mask\nDetected: '+(r.found.join(', ')||'No common patterns (not proof of anonymity)')+
      '\nRedacted content:\n'+r.out+'\nCheck manually before sharing; this does not detect every sensitive detail.';
  }
  if(id==='secrets'){
    const t=requireText(text),types=[];
    for(const [name,re] of [
      ['OpenAI-style API key',/\bsk-(?:proj-)?[A-Za-z0-9_-]{16,}\b/],
      ['GitHub personal access token',/\bgh[pousr]_[A-Za-z0-9_]{20,}\b/],
      ['Cloud/API credential assignment',/\b(?:api[_-]?key|secret|password|client_secret|access_token)\s*[:=]\s*\S{8,}/i],
      ['PEM private key',/-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/],
      ['JWT-like credential',/\beyJ[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b/],
    ])if(re.test(t))types.push(name);
    return 'Credential Alarm\n'+(types.length?'Possible exposures: '+types.join('; ')+'. Rotate compromised credentials; do not paste them again.':'No common credential patterns detected.')+
      '\nThis scan is heuristic and does not validate actual credentials.';
  }
  if(id==='url-risk'){
    const candidate=requireText(text).split(/\s/)[0];let u;
    try{u=new URL(candidate);}catch{throw Error('Provide a complete http:// or https:// URL.');}
    if(!['http:','https:'].includes(u.protocol))throw Error('Only HTTP or HTTPS URLs are supported.');
    const risks=[];
    if(u.protocol!=='https:')risks.push('unencrypted HTTP');
    if(u.username||u.password)risks.push('embedded URL credentials');
    if(u.hostname.includes('xn--'))risks.push('internationalized/punycode domain');
    if(/^\d{1,3}(?:\.\d{1,3}){3}$/.test(u.hostname))risks.push('IP-address hostname');
    if(/^(?:localhost|.+\.local)$/i.test(u.hostname))risks.push('local/private destination');
    if(['bit.ly','tinyurl.com','t.co','is.gd','cutt.ly'].includes(u.hostname))risks.push('URL shortener hides final destination');
    if(u.hostname.split('.').length>5)risks.push('many subdomain segments');
    return 'URL Safety Lens\nHost: '+u.hostname+'\nIndicators: '+(risks.join('; ')||'No listed structural warning signs')+
      '\nThis is not a malware scan, reputation check or proof of a safe site. No website was fetched.';
  }
  if(id==='claims'){
    const pieces=requireText(text).split(/(?<=[.!?])\s+|\n+/).map(x=>x.trim()).filter(Boolean);
    const claims=pieces.filter(x=>/\b(?:always|never|guaranteed|100%|first ever|most|best|all users|zero risk)\b/i.test(x)||/(?:\$|%|\b\d{2,}\b)/.test(x));
    const selected=claims.slice(0,12);
    return 'Evidence Lens\n'+(selected.length?selected.map((c,i)=>(i+1)+'. '+c.slice(0,190)+'\n   Source: '+(/https?:\/\/\S+/.test(c)?'link included, not verified':'no source included')).join('\n'):'No obvious numeric/absolute claims detected.')+
      '\nNo claims were fact-checked against external sources.';
  }
  if(id==='fingerprint'){
    const t=requireText(text);
    return 'Proof Fingerprint\nSHA-256: '+sha256(t)+'\nCharacters: '+t.length+'\nText is hashed as supplied after trimming leading/trailing whitespace. This receipt is not signed or recorded on a blockchain.';
  }
  if(id==='verify-fingerprint'){
    const v=obj(text);
    if(typeof v.content!=='string'||!v.content.trim()||v.content.length>MAX_TEXT)throw Error('Provide nonempty content (up to 12,000 characters).');
    if(typeof v.sha256!=='string'||!/^[0-9a-f]{64}$/i.test(v.sha256))throw Error('sha256 must be a 64-character hex digest.');
    const computed=sha256(v.content.trim());
    return 'Proof Recheck\n'+(computed===v.sha256.toLowerCase()?'MATCH — identical text fingerprint.':'MISMATCH — content differs from the claimed fingerprint.')+
      '\nComputed SHA-256: '+computed+'\nThis checks integrity only, not who created the text.';
  }
  if(id==='json-lint'){
    let v;try{v=JSON.parse(requireText(text));}catch(e){return 'Data Integrity\nINVALID JSON: '+String(e.message).slice(0,200);}
    return 'Data Integrity\nVALID JSON. '+summaryJSON(v)+'\nParsing validates syntax, not an external data schema.';
  }
  if(id==='csv-stats'){
    const rows=csvParse(requireText(text));
    const headers=rows[0],body=rows.slice(1);
    const report=headers.map((head,j)=>{
      const cells=body.map(r=>r[j].trim()),nonempty=cells.filter(Boolean);
      const numeric=nonempty.length>0&&nonempty.every(x=>/^-?\d+(?:\.\d+)?$/.test(x));
      return (j+1)+'. '+(head.trim()||'(unnamed)')+': '+(cells.length-nonempty.length)+' empty'+
        (numeric?', numeric, min '+Math.min(...nonempty.map(Number))+', max '+Math.max(...nonempty.map(Number)):'');
    });
    return 'CSV Inspector\nRows: '+body.length+'; columns: '+headers.length+'\n'+report.join('\n')+
      '\nThis is a bounded sample profile, not database validation.';
  }
  if(id==='compare'){
    const parts=requireText(text).split(/\n--- VS ---\n/);
    if(parts.length!==2)throw Error('Separate the two versions with a line containing exactly --- VS ---.');
    const a=lines(parts[0]),b=lines(parts[1]);
    const count=Math.max(a.length,b.length);
    const changed=[];for(let i=0;i<count;i++)if(a[i]!==b[i])changed.push('Line '+(i+1)+': '+(a[i]===undefined?'(missing)':a[i].slice(0,110))+' → '+(b[i]===undefined?'(missing)':b[i].slice(0,110)));
    return 'Change Inspector\n'+changed.length+' differing line positions.\n'+(changed.slice(0,30).join('\n')||'No changes detected.')+
      (changed.length>30?'\nAdditional changes omitted.':'')+'\nThis is a positional comparison, not a semantic code diff.';
  }
  if(id==='invoice-check'){
    const v=obj(text);
    if(!Array.isArray(v.items)||v.items.length<1||v.items.length>80)throw Error('Provide an items array of 1–80 {qty, unitPrice} entries.');
    let sub=0n;
    for(const row of v.items){
      if(!row||typeof row!=='object')throw Error('Invalid invoice line.');
      const qty=number(row.qty,'qty',{min:0,max:100000,strict:true});
      if(!Number.isInteger(qty))throw Error('Invoice qty must be a whole number.');
      sub+=BigInt(qty)*cents(row.unitPrice,'unitPrice');
    }
    const tax=number(v.taxRatePercent??0,'taxRatePercent',{min:0,max:100});
    const taxCents=BigInt(Math.round(Number(sub)*tax/100));
    const total=sub+taxCents;
    const comparison=v.claimedTotal===undefined?'not supplied':(cents(v.claimedTotal,'claimedTotal')===total?'MATCH':'MISMATCH');
    return 'Invoice Math Auditor\nSubtotal: '+moneyCents(sub)+'\nTax ('+tax+'%): '+moneyCents(taxCents)+
      '\nComputed total: '+moneyCents(total)+'\nClaimed total: '+comparison+'\nRecheck jurisdiction-specific tax rules independently.';
  }
  if(id==='runway'){
    const v=obj(text),cash=number(v.cash,'cash'),burn=number(v.monthlyBurn,'monthlyBurn'),revenue=number(v.monthlyRevenue??0,'monthlyRevenue');
    const net=burn-revenue;
    return 'Survival Runway\nCash: '+dollars(cash)+'; monthly net cash burn: '+dollars(net)+
      '\n'+(net<=0?'At these fixed assumptions, spending is covered by revenue (not a forecast).':
        'Estimated runway: '+(cash/net).toFixed(2)+' months.')+
      '\nAssumes constant cash flow and no debt, taxes, seasonality or one-time expenses.';
  }
  if(id==='break-even'){
    const v=obj(text),fixed=number(v.fixedCost,'fixedCost'),price=number(v.price,'price',{strict:true}),variable=number(v.variableCost,'variableCost');
    const contribution=price-variable;
    if(contribution<=0) return 'Break-even Calculator\nImpossible with supplied per-sale economics: price must exceed variable cost.';
    return 'Break-even Calculator\nContribution per sale: '+dollars(contribution)+'\nRequired sales: '+Math.ceil(fixed/contribution)+
      '\nRevenue at break-even: '+dollars(Math.ceil(fixed/contribution)*price)+
      '\nBefore taxes, refunds, time costs and other excluded expenses.';
  }
  if(id==='unit-economics'){
    const v=obj(text),revenue=number(v.revenue,'revenue'),variable=number(v.variableCost,'variableCost'),customers=number(v.customers,'customers',{strict:true});
    if(!Number.isInteger(customers))throw Error('customers must be an integer.');
    const profit=revenue-variable;
    return 'Customer Margin Lens\nPer-customer revenue: '+dollars(revenue/customers)+
      '\nPer-customer variable cost: '+dollars(variable/customers)+
      '\nContribution per customer: '+dollars(profit/customers)+
      '\nContribution margin: '+(revenue>0?((profit/revenue)*100).toFixed(2)+'%':'undefined (zero revenue)')+
      '\nFixed overhead and acquisition costs not included.';
  }
  if(id==='model-cost'){
    const v=obj(text),input=number(v.inputTokens,'inputTokens',{max:1e9}),output=number(v.outputTokens,'outputTokens',{max:1e9}),
      inputPrice=number(v.inputPerMillion,'inputPerMillion',{max:1e6}),outputPrice=number(v.outputPerMillion,'outputPerMillion',{max:1e6});
    return 'AI Call Cost Guardian\nInput: '+dollars(input*inputPrice/1e6)+
      '\nOutput: '+dollars(output*outputPrice/1e6)+'\nEstimated total: '+dollars((input*inputPrice+output*outputPrice)/1e6)+
      '\nPrices are user supplied, NOT fetched from a live provider; excludes cached/extra tool charges.';
  }
  if(id==='gas-cost'){
    const v=obj(text),gas=number(v.gasUnits,'gasUnits',{min:21000,max:1e8}),
      gwei=number(v.gwei,'gwei',{max:1e6}),rate=number(v.nativePriceUsd,'nativePriceUsd',{max:1e7});
    const native=gas*gwei/1e9;
    return 'Gas Fee Guardian\nEstimated native-token gas spend: '+native.toFixed(9)+
      '\nEstimated USD equivalent: '+dollars(native*rate)+
      '\nOnly user-supplied assumptions. Not a live gas quote or guarantee; no transaction sent.';
  }
  if(id==='token-units'){
    const v=obj(text);
    if(!/^\d{1,24}(?:\.\d{1,36})?$/.test(String(v.tokens??'')))throw Error('tokens must be a decimal string of up to 24 digits and optional fractional part.');
    if(!Number.isInteger(v.decimals)||v.decimals<0||v.decimals>36)throw Error('decimals must be a whole number from 0 to 36.');
    const [whole,frac='']=String(v.tokens).split('.');
    if(frac.length>v.decimals)throw Error('Token precision exceeds declared decimals; refusing to round.');
    const units=BigInt(whole)*10n**BigInt(v.decimals)+BigInt((frac+'0'.repeat(v.decimals)).slice(0,v.decimals)||'0');
    return 'Token Precision Guard\nBase units: '+units.toString()+'\nDecimals: '+v.decimals+
      '\nNo tokens were minted or sent. Check on-chain contract decimals independently.';
  }
  if(id==='chain-guard'){
    const v=obj(text);
    const id=Number(v.chainId);
    if(!Number.isSafeInteger(id)||id<1)throw Error('chainId must be a positive safe integer.');
    const known={
      772626:'Privi single-validator devnet; valueless TEST. Not financial mainnet.',
      262144:'Upstream Cosmos EVM developer reference, NOT Privi public devnet or approved mainnet.',
      84532:'Base Sepolia testnet.',
      11155111:'Ethereum Sepolia testnet.',
      8453:'Base mainnet; real asset/gas implications.',
      1:'Ethereum mainnet; real asset/gas implications.'
    };
    return 'Network Identity Guard\nChain ID: '+id+'\nKnown identity: '+(known[id]||'Unknown; do not infer network identity from an ID alone.')+
      '\nThis registry is static, not a live RPC verification. To check Privi devnet live, ask “What is the devnet status?”';
  }
  if(id==='rpc-guard'){
    const v=obj(text);
    if(typeof v.method!=='string'||v.method.length>80||!/^eth_[A-Za-z0-9]+$/.test(v.method))throw Error('Provide an EVM eth_* JSON-RPC method.');
    if(!Array.isArray(v.params)||v.params.length>8)throw Error('params must be an array of at most 8 items.');
    const readonly=new Set(['eth_chainId','eth_blockNumber','eth_getBalance','eth_getCode','eth_getStorageAt','eth_call','eth_estimateGas',
      'eth_getTransactionByHash','eth_getTransactionReceipt','eth_getBlockByNumber','eth_getLogs','eth_getTransactionCount']);
    return 'Transaction Safety Gate\nMethod: '+v.method+'\n'+
      (readonly.has(v.method)?'ALLOWLISTED AS READ-ONLY / SIMULATION (may reveal account data or use provider resources).':
        'NOT ALLOWLISTED — may be a state-changing, signing or unsupported RPC request.')+
      '\nNo network call or transaction was performed.';
  }
  if(id==='critical-path'){
    const v=obj(text);if(!Array.isArray(v.tasks)||v.tasks.length<1||v.tasks.length>40)throw Error('tasks must contain 1–40 {id, days, dependsOn?} objects.');
    const all=new Map();
    for(const task of v.tasks){
      if(!task||typeof task.id!=='string'||!/^[A-Za-z0-9_-]{1,32}$/.test(task.id)||all.has(task.id))throw Error('Task IDs must be unique, 1–32 letters/numbers/dashes.');
      number(task.days,'days',{max:365});
      const deps=task.dependsOn??[];
      if(!Array.isArray(deps)||deps.length>20||deps.some(x=>typeof x!=='string'||x===task.id))throw Error('Invalid dependency list for '+task.id);
      all.set(task.id,{id:task.id,days:task.days,dependsOn:deps});
    }
    for(const task of all.values())for(const dep of task.dependsOn)if(!all.has(dep))throw Error('Unknown dependency: '+dep);
    const done=new Set(),order=[];
    while(done.size<all.size){
      const ready=[...all.values()].filter(t=>!done.has(t.id)&&t.dependsOn.every(dep=>done.has(dep)));
      if(!ready.length)throw Error('Dependency cycle detected; cannot generate a plan.');
      for(const t of ready){done.add(t.id);order.push(t);}
    }
    const finish=new Map(),prior=new Map();
    for(const task of order){
      const maxDep=task.dependsOn.reduce((best,dep)=>finish.get(dep)> (best?.days??-1)?{id:dep,days:finish.get(dep)}:best,null);
      finish.set(task.id,(maxDep?.days||0)+task.days);prior.set(task.id,maxDep?.id||null);
    }
    const last=order.reduce((best,t)=>finish.get(t.id)>finish.get(best.id)?t:best,order[0]);
    const path=[];let at=last.id;while(at){path.unshift(at);at=prior.get(at);}
    return 'Dependency Brain\nExecution order: '+order.map(t=>t.id).join(' → ')+
      '\nEarliest finish: '+finish.get(last.id)+' working-day units\nLongest dependency path: '+path.join(' → ')+
      '\nAssumes unlimited parallel resources and supplied durations, not calendar scheduling.';
  }
  if(id==='launch-risk'){
    const t=requireText(text).toLowerCase();
    const checks=[
      ['security audit',/\b(?:audit|independent review)\b/],
      ['test or staging',/\b(?:testnet|staging|test suite|integration test)\b/],
      ['rollback/recovery plan',/\b(?:rollback|restore|recovery)\b/],
      ['monitoring and alerts',/\b(?:monitor|alert|observability)\b/],
      ['backups',/\b(?:backup|snapshot)\b/],
      ['access permissions',/\b(?:permission|least privilege|access control|multi-sig|multisig)\b/],
      ['incident response',/\b(?:incident|emergency stop|kill switch)\b/],
      ['cost or gas budget',/\b(?:budget|spend cap|cost ceiling|gas limit)\b/],
    ];
    const covered=checks.filter(([,re])=>re.test(t)).map(x=>x[0]);
    const missing=checks.filter(([,re])=>!re.test(t)).map(x=>x[0]);
    return 'Launch Risk Scanner\nSafeguards mentioned: '+(covered.join(', ')||'none')+
      '\nPotential omissions to review: '+(missing.join(', ')||'no listed omissions')+
      '\nPresence of keywords is not proof of effective safeguards. This is not a deployment audit or approval.';
  }
  throw Error('Unknown local power.');
}
export function listJosePowers(){
  return 'Hey Jose — 20 verified local tools. Everything runs inside this chat. Use a command below with your own content or numbers:\n\n'+
    JOSE_POWERS.map((p,i)=>(i+1)+'. '+p.title+' — '+p.description+'\n   '+p.usage).join('\n')+
    '\n\nThese tools require explicit commands. They do not browse the web, execute blockchain transactions, access accounts or promise financial outcomes.';
}
export function recognizePower(message){
  if(typeof message!=='string')return null;
  const t=message.trim();
  if(/^\/(?:powers|help-powers|jose-powers)\s*$/i.test(t)||
     /^(?:hey jose,?\s+)?(?:show|list|what are)\s+(?:me\s+)?(?:your\s+)?20\s+(?:powers|features|tools)\??$/i.test(t))
    return {id:'powers',input:''};
  const match=t.match(/^\/([a-z][a-z0-9-]{0,40})(?:\s+([\s\S]*))?$/i);
  if(match&&COMMANDS.has(match[1].toLowerCase()))
    return {id:match[1].toLowerCase(),input:match[2]||''};
  // A plain question can explicitly call any named power without opening a menu.
  const prompt=t.match(/^(?:hey jose,?\s*)?(?:run|use|do)\s+(?:the\s+)?(?:power\s+)?([a-z][a-z0-9-]{0,40})\s*:\s*([\s\S]+)$/i);
  if(prompt&&COMMANDS.has(prompt[1].toLowerCase()))
    return {id:prompt[1].toLowerCase(),input:prompt[2]};
  return null;
}
export async function runJosePower(message,clock=()=>new Date()){
  const request=recognizePower(message);
  if(!request)return null;
  if(request.id==='powers')return {power:'powers',answer:listJosePowers()};
  try{
    return {power:request.id,answer:run(request.id,request.input,clock)};
  }catch(err){
    return {power:request.id,answer:'The '+COMMANDS.get(request.id).title+' needs valid input.\n'+String(err.message).slice(0,240)+
      '\nExample: '+USAGE[request.id]};
  }
}
