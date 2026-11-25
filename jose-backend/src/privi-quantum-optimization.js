// Privi Quantum / Hey Jose: FREE exact classical QUBO baseline.
// Compatible with the convention x^T Q x + offset in quantum-server/src/privi_quantum/qaoa.py.
// Does NOT execute the separate CVaR-QAOA algorithm, spend credits or run on a QPU.
export const MAX_QUBO_VARIABLES=16;
export const MAX_QUBO_ABS_VALUE=10_000_000_000;
export class QuantumOptimizationError extends Error {
  constructor(message){super(message);this.name='QuantumOptimizationError';this.status=400;}
}
const fail=message=>{throw new QuantumOptimizationError(message);};
export function validateQubo(raw){
  if(!raw||typeof raw!=='object'||Array.isArray(raw))fail('Provide a JSON object with the Q matrix.');
  if(Object.keys(raw).some(key=>!['Q','offset','names'].includes(key)))
    fail('QUBO accepts only Q, offset, and names.');
  const Q=raw.Q;
  if(!Array.isArray(Q)||Q.length<1||Q.length>MAX_QUBO_VARIABLES)
    fail('Q must be a square 1–16-variable matrix.');
  const n=Q.length;
  for(const row of Q){
    if(!Array.isArray(row)||row.length!==n)fail('Q must have exactly '+n+' numbers per row.');
    for(const v of row){
      if(typeof v!=='number'||!Number.isFinite(v)||Math.abs(v)>MAX_QUBO_ABS_VALUE)
        fail('Q entries must be finite numbers with magnitude at most 10,000,000,000.');
    }
  }
  const offset=raw.offset===undefined?0:raw.offset;
  if(typeof offset!=='number'||!Number.isFinite(offset)||Math.abs(offset)>1_000_000_000_000)
    fail('offset must be a finite number with magnitude at most 1,000,000,000,000.');
  const names=raw.names===undefined?Array.from({length:n},(_,i)=>'x'+i):raw.names;
  if(!Array.isArray(names)||names.length!==n||
    names.some(name=>typeof name!=='string'||name.length>42||!name.trim()))
    fail('names must contain one nonempty short string for each variable.');
  if(new Set(names.map(x=>x.trim())).size!==n)fail('Variable names must be unique.');
  return {Q:Q.map(row=>row.slice()),offset,names:names.map(x=>x.trim()),variables:n};
}

function bitArray(mask,n){return Array.from({length:n},(_,i)=>(mask>>i)&1);}
function costOf(mask,Q,offset){
  let score=offset,n=Q.length;
  for(let i=0;i<n;i++)if(mask&(1<<i)){
    score+=Q[i][i];
    for(let j=i+1;j<n;j++)if(mask&(1<<j))score+=Q[i][j]+Q[j][i];
  }
  return score;
}
export function solveExactQubo(input){
  const {Q,offset,names,variables:n}=validateQubo(input);
  const states=2**n;
  let min=Infinity,max=-Infinity,bestMask=0,worstMask=0,degenerate=0,mean=0;
  // n<=16: at most 65,536 configurations; a deterministic, bounded classical baseline.
  for(let mask=0;mask<states;mask++){
    const score=costOf(mask,Q,offset);
    mean+=score/states;
    if(score<min-1e-9){
      min=score;bestMask=mask;degenerate=1;
    }else if(Math.abs(score-min)<=1e-9)degenerate++;
    if(score>max){max=score;worstMask=mask;}
  }
  return {
    method:'classical_exhaustive_qubo',algorithm:'exact_binary_enumeration',
    sourceConvention:'Privi Quantum qaoa.py — x^T Q x + offset',
    variables:n,configurationsEvaluated:states,
    optimalBits:bitArray(bestMask,n),optimalBitstring:bestMask.toString(2).padStart(n,'0'),
    optimalAssignments:Object.fromEntries(names.map((name,i)=>[name,(bestMask>>i)&1])),
    optimumCost:Number(min.toPrecision(14)),degenerateOptima:degenerate,
    worstCost:Number(max.toPrecision(14)),meanCost:Number(mean.toPrecision(14)),
    names,offset,
    quantumHardware:false,qaoaExecuted:false,quantumAdvantageClaimed:false,
    paymentRequired:false,remoteJobsSubmitted:false,
    note:'Proven classical reference optimum, not a QAOA or physical quantum processor result.',
  };
}
export function validateBalanceLines(raw){
  if(!raw||typeof raw!=='object'||Array.isArray(raw)||Object.keys(raw).some(k=>k!=='jobs'))
    fail('Line balancing requires a jobs array.');
  const jobs=raw.jobs;
  if(!Array.isArray(jobs)||jobs.length<2||jobs.length>MAX_QUBO_VARIABLES)
    fail('Supply 2–16 jobs to balance across two lines.');
  const seen=new Set();
  return jobs.map((job,i)=>{
    if(!job||typeof job!=='object'||Array.isArray(job)||
       Object.keys(job).some(k=>!['name','minutes'].includes(k))||
       typeof job.name!=='string'||!job.name.trim()||job.name.length>42||
       typeof job.minutes!=='number'||!Number.isFinite(job.minutes)||
       job.minutes<=0||job.minutes>10000)
      fail('Each job needs a short name and positive minutes (up to 10,000).');
    const name=job.name.trim();
    if(seen.has(name))fail('Job names must be unique.');seen.add(name);
    return {name,minutes:job.minutes};
  });
}
export function optimizeBalanceLines(input){
  const jobs=validateBalanceLines(input),n=jobs.length;
  const total=jobs.reduce((v,j)=>v+j.minutes,0);
  const Q=Array.from({length:n},(_,i)=>Array.from({length:n},(_,j)=>
    i===j?4*jobs[i].minutes**2-4*total*jobs[i].minutes:
      4*jobs[i].minutes*jobs[j].minutes));
  // (minutes_A - minutes_B)^2 = (2 * sum(x_i d_i) - total)^2
  const base=solveExactQubo({Q,offset:total**2,names:jobs.map(j=>j.name)});
  const lineA=jobs.filter((_,i)=>base.optimalBits[i]===1);
  const lineB=jobs.filter((_,i)=>base.optimalBits[i]===0);
  const lineAMinutes=lineA.reduce((v,j)=>v+j.minutes,0);
  const lineBMinutes=lineB.reduce((v,j)=>v+j.minutes,0);
  return {...base,problem:'balance_lines',lineA,lineB,lineAMinutes,lineBMinutes,
    differenceMinutes:Math.abs(lineAMinutes-lineBMinutes),
    objective:'minimize squared difference in total minutes between two lines',
    note:'Exact classical optimum for this bounded two-line allocation. QAOA has not been run.'};
}
export function optimizationRequest(message){
  if(typeof message!=='string')return null;
  const q=message.trim();
  if(/^(?:\/quantum\s+optimize|\/qubo)\s+/i.test(q)){
    const json=q.replace(/^(?:\/quantum\s+optimize|\/qubo)\s+/i,'');
    let input;
    try{input=JSON.parse(json);}catch{fail('Use valid JSON: /quantum optimize {"Q":[[1,-2],[-2,1]]}');}
    return {type:'qubo',input:validateQubo(input)};
  }
  if(/^\/quantum\s+balance\s+/i.test(q)){
    let input;
    try{input=JSON.parse(q.replace(/^\/quantum\s+balance\s+/i,''));}
    catch{fail('Use valid JSON: /quantum balance {"jobs":[{"name":"A","minutes":30},{"name":"B","minutes":20}]}');}
    return {type:'balance',input:{jobs:validateBalanceLines(input)}};
  }
  if(/^(?:\/quantum\s+optimize|\/qubo|\/quantum\s+balance)\s*$/i.test(q)||
     /\b(?:privi\s+)?quantum\b.*\b(?:optimization|optimisation|qubo|balance\s+lines)\b/i.test(q)){
    return {type:'help'};
  }
  return null;
}
export const OPTIMIZATION_HELP=
  'Privi Quantum optimization in Hey Jose runs a **free, exact classical QUBO baseline** for up to 16 binary variables. It does not run the separate QAOA engine or any paid quantum hardware.\n\n'+
  'Try:\n'+
  '• /quantum optimize {"Q":[[1,-2],[-2,1]],"names":["a","b"]}\n'+
  '• /quantum balance {"jobs":[{"name":"A","minutes":42},{"name":"B","minutes":17},{"name":"C","minutes":33}]}\n\n'+
  'The output is a proven minimum over up to 65,536 assignments, suitable as a reference for comparing later QAOA runs. The existing Privi Quantum CVaR-QAOA server remains a separate, potentially paid tool.';
export function formatOptimizationResult(result){
  if(result.problem==='balance_lines')
    return 'Privi Quantum — **classical exact line-balancing result**\n\n'+
      'Line A: '+result.lineA.map(j=>j.name+' ('+j.minutes+' min)').join(', ')+
      '\nLine B: '+result.lineB.map(j=>j.name+' ('+j.minutes+' min)').join(', ')+
      '\nTotals: '+result.lineAMinutes+' versus '+result.lineBMinutes+' minutes; difference **'+
      result.differenceMinutes+' minutes**.\n\nChecked '+result.configurationsEvaluated+
      ' binary assignments for a mathematically exact classical optimum. No QAOA or physical qubits were used.';
  return 'Privi Quantum — **classical exact QUBO baseline**\n\n'+
    'Best assignment: '+result.optimalBitstring+' (q0/rightmost bit is x0)\n'+
    Object.entries(result.optimalAssignments).map(([k,v])=>'- '+k+': '+v).join('\n')+
    '\nMinimum objective: **'+result.optimumCost+'**; '+result.degenerateOptima+' optimal assignment(s).\n'+
    'Checked '+result.configurationsEvaluated+' configurations for '+result.variables+
    ' binary variables. This is a reference result, **not QAOA, physical qubit hardware or quantum advantage**.';
}
