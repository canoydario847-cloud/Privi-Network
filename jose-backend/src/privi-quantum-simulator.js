// Privi Quantum for Hey Jose: FREE, deterministic local exact-statevector
// simulations. Gate and bit ordering follow quantum-server/src/privi_quantum/hardware.py.
// This JS adapter does NOT invoke Privi Quantum's paid MCP tools or any QPU.
export const MAX_QUBITS=12;
export const MAX_RETURNED_STATES=64; // Keep 12-qubit uniform-state responses small.
export const MAX_GATES=80;
export const MAX_SHOTS=4096;
export class QuantumInputError extends Error{
  constructor(message){super(message);this.name='QuantumInputError';this.status=400;}
}
function invalid(message){throw new QuantumInputError(message);}
const validIndex=(v,n)=>Number.isInteger(v)&&v>=0&&v<n;
function gatesValidated(raw,n){
  if(!Array.isArray(raw)||raw.length>MAX_GATES)invalid('Provide a gates array with up to 80 entries.');
  return raw.map((value,index)=>{
    if(!value||typeof value!=='object'||Array.isArray(value))
      invalid('Gate '+(index+1)+' must be an object.');
    const gate=String(value.gate||'').toLowerCase();
    if(!['h','x','z','rx','rz','cx'].includes(gate))
      invalid('Unsupported gate '+gate+'. Allowed: h, x, z, rx, rz, cx.');
    if(!validIndex(value.target,n))invalid('Invalid target for gate '+(index+1)+'. Qubits start at 0.');
    const standard=['gate','target',...(gate==='cx'?['control']:['rx','rz'].includes(gate)?['angle']:[])];
    if(Object.keys(value).some(k=>!standard.includes(k)))invalid('Unknown parameter in gate '+(index+1)+'.');
    if(gate==='cx'){
      if(!validIndex(value.control,n)||value.control===value.target)
        invalid('CX needs distinct, valid control and target qubits.');
      return {gate,control:value.control,target:value.target};
    }
    if(gate==='rx'||gate==='rz'){
      if(typeof value.angle!=='number'||!Number.isFinite(value.angle)||Math.abs(value.angle)>1000)
        invalid('RX and RZ angles must be finite numbers in radians, magnitude ≤1000.');
      return {gate,target:value.target,angle:value.angle};
    }
    return {gate,target:value.target};
  });
}
export function validateCircuit(body){
  if(!body||typeof body!=='object'||Array.isArray(body))
    invalid('Provide a circuit object with qubits and gates.');
  const allowed=['qubits','gates','shots','seed'];
  if(Object.keys(body).some(k=>!allowed.includes(k)))invalid('Only qubits, gates, shots and seed are accepted.');
  const n=body.qubits;
  if(!Number.isInteger(n)||n<1||n>MAX_QUBITS)
    invalid('Hey Jose runs 1–12 qubits locally (the separate Privi Quantum server has different limits).');
  const shots=body.shots===undefined?1024:body.shots;
  if(!Number.isInteger(shots)||shots<1||shots>MAX_SHOTS)
    invalid('Shots must be an integer from 1 to 4096.');
  const seed=body.seed===undefined?1:body.seed;
  if(!Number.isInteger(seed)||seed<0||seed>0xffffffff)
    invalid('Seed must be an unsigned 32-bit integer.');
  return {qubits:n,gates:gatesValidated(body.gates,n),shots,seed};
}
function angleOf(expr){
  const clean=expr.replace(/\s+/g,'');
  if(/^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?$/i.test(clean))return Number(clean);
  const m=clean.match(/^([+-]?)(?:(\d+(?:\.\d+)?)\*)?pi(?:\/(\d+(?:\.\d+)?))?$/i);
  if(m){const sign=m[1]==='-'?-1:1;const scale=m[2]===undefined?1:Number(m[2]);const divisor=m[3]===undefined?1:Number(m[3]);if(divisor===0)invalid('Angle divisor cannot be zero.');return sign*scale*Math.PI/divisor;}
  invalid('Use numeric radians or pi/2, -pi/4, 2*pi in OpenQASM.');
}
export function parseQasm(source){
  if(typeof source!=='string'||source.length>5000)invalid('OpenQASM must be text under 5,000 characters.');
  const lines=source.replace(/\/\/[^\n]*/g,'').split(';').map(s=>s.trim()).filter(Boolean);
  if(lines.shift()!=='OPENQASM 2.0')invalid('Only a restricted OpenQASM 2.0 subset is supported.');
  let qubits=0,measured=false,cregSeen=false;
  const gates=[];
  for(const line of lines){
    if(/^include\s+"qelib1\.inc"$/i.test(line))continue;
    let m=line.match(/^qreg\s+q\[(\d+)\]$/);
    if(m){if(qubits)invalid('Only one quantum register q is supported.');qubits=Number(m[1]);continue;}
    m=line.match(/^creg\s+c\[(\d+)\]$/);
    if(m){cregSeen=true;continue;}
    if(/^barrier\s+q$/.test(line))continue;
    if(/^measure\s+q\[\d+\]\s*->\s*c\[\d+\]$/.test(line)){
      if(!cregSeen)invalid('A classical c register is required for measurement.');
      measured=true;continue;
    }
    if(measured)invalid('Mid-circuit measurement is not supported.');
    m=line.match(/^(h|x|z)\s+q\[(\d+)\]$/i);
    if(m){gates.push({gate:m[1].toLowerCase(),target:Number(m[2])});continue;}
    m=line.match(/^(rx|rz)\(([^)]{1,60})\)\s+q\[(\d+)\]$/i);
    if(m){gates.push({gate:m[1].toLowerCase(),target:Number(m[3]),angle:angleOf(m[2])});continue;}
    m=line.match(/^cx\s+q\[(\d+)\]\s*,\s*q\[(\d+)\]$/i);
    if(m){gates.push({gate:'cx',control:Number(m[1]),target:Number(m[2])});continue;}
    invalid('Unsupported OpenQASM statement: '+line.slice(0,60)+'.');
  }
  return validateCircuit({qubits,gates});
}
export const QUANTUM_HELP=
  'Privi Quantum is built into Hey Jose as a free, **classical exact-statevector qubit simulator** (1–12 qubits). Try:\n'+
  '• "Simulate a 2-qubit Bell state"\n'+
  '• "Simulate a 12-qubit GHZ state"\n'+
  '• "Privi Quantum project status" (live read-only service check)\n'+
  '• /quantum simulate {"qubits":2,"gates":[{"gate":"h","target":0},{"gate":"cx","control":0,"target":1}]}\n'+
  '• /quantum qasm OPENQASM 2.0; include "qelib1.inc"; qreg q[2]; h q[0]; cx q[0],q[1];\n'+
  'Allowed gates: H, X, Z, RX(angle), RZ(angle), CX. Input qubits use zero-based indices. No quantum hardware, paid API or on-chain write is used. The independent Privi Quantum project also has advanced optimization services; those are not silently called by this free chat simulator.';
export function quantumRequest(message){
  if(typeof message!=='string')return null;
  const q=message.trim();
  if(!q)return null;
  // Exact status intents make a bounded read-only call to the EXISTING Quantum service.
  if(/^(?:(?:check|show)\\s+)?(?:privi\\s+)?quantum(?:\\s+(?:project|server|service|cloud))?\\s+status[!?.]*$/i.test(q)||
      /^(?:is\\s+)?privi\\s+quantum(?:\\s+(?:project|server|service))?\\s+online\\??$/i.test(q))
    return {type:'project_status'};
  const structured=q.match(/^\/?quantum\s+(?:simulate\s+)?(\{[\s\S]*\})$/i);
  if(structured){
    try{return {type:'simulate',circuit:validateCircuit(JSON.parse(structured[1]))};}
    catch(error){if(error instanceof SyntaxError)invalid('The quantum circuit JSON is invalid.');throw error;}
  }
  const qasm=q.match(/^\/?quantum\s+qasm\s+([\s\S]+)$/i);
  if(qasm)return {type:'simulate',circuit:parseQasm(qasm[1])};
  if(!/\b(?:quantum|qubit|qubits|bell\s+state|ghz\s+state)\b/i.test(q)&&!/^\/quantum\b/i.test(q))return null;
  const requestsSimulation=/\b(?:simulate|simulation|run|execute|measure|bell\s+state|ghz\s+state)\b/i.test(q)||/^\/quantum\b/i.test(q);
  if(!requestsSimulation)return null;  // "what is quantum computing" goes to the regular AI.
  if(/\bbell(?:\s+state)?\b/i.test(q)){
    return {type:'simulate',circuit:validateCircuit({qubits:2,gates:[{gate:'h',target:0},{gate:'cx',control:0,target:1}]})};
  }
  if(/\bghz(?:\s+state)?\b/i.test(q)){
    const number=q.match(/(\d{1,2})\s*[- ]?\s*qubits?/i)||q.match(/ghz\s+(\d{1,2})/i);
    const n=number?Number(number[1]):3;
    if(!Number.isInteger(n)||n<2||n>MAX_QUBITS)invalid('GHZ simulations require 2–12 qubits.');
    return {type:'simulate',circuit:validateCircuit({qubits:n,gates:[{gate:'h',target:0},...Array.from({length:n-1},(_,i)=>({gate:'cx',control:i,target:i+1}))]})};
  }
  return {type:'help'};
}
function complexPair(state,k,g,a,b,c,d){
  const x=state[2*k],y=state[2*k+1],z=state[2*g],w=state[2*g+1];
  // complex matrix entries a..d are [re,im] arrays
  state[2*k]=a[0]*x-a[1]*y+b[0]*z-b[1]*w;
  state[2*k+1]=a[0]*y+a[1]*x+b[0]*w+b[1]*z;
  state[2*g]=c[0]*x-c[1]*y+d[0]*z-d[1]*w;
  state[2*g+1]=c[0]*y+c[1]*x+d[0]*w+d[1]*z;
}
function applyGate(state,n,gate){
  const mask=1<<gate.target,dim=1<<n;
  if(gate.gate==='cx'){
    const controlMask=1<<gate.control;
    for(let i=0;i<dim;i++)if((i&controlMask)&&!(i&mask)){
      const partner=i|mask;
      for(let k=0;k<2;k++){const tmp=state[2*i+k];state[2*i+k]=state[2*partner+k];state[2*partner+k]=tmp;}
    }
    return;
  }
  let a,b,c,d;
  if(gate.gate==='h'){
    const r=1/Math.sqrt(2);a=[r,0];b=[r,0];c=[r,0];d=[-r,0];
  }else if(gate.gate==='x'){
    a=[0,0];b=[1,0];c=[1,0];d=[0,0];
  }else if(gate.gate==='z'){
    a=[1,0];b=[0,0];c=[0,0];d=[-1,0];
  }else if(gate.gate==='rx'){
    const co=Math.cos(gate.angle/2),si=Math.sin(gate.angle/2);
    a=[co,0];b=[0,-si];c=[0,-si];d=[co,0];
  }else if(gate.gate==='rz'){
    const co=Math.cos(gate.angle/2),si=Math.sin(gate.angle/2);
    a=[co,-si];b=[0,0];c=[0,0];d=[co,si];
  }
  for(let i=0;i<dim;i++)if(!(i&mask))complexPair(state,i,i|mask,a,b,c,d);
}
function rngSeeded(seed){
  let a=(seed>>>0)||0x9e3779b9;
  return ()=>{a^=a<<13;a^=a>>>17;a^=a<<5;return (a>>>0)/4294967296;};
}
export function simulateCircuit(input){
  const circuit=validateCircuit(input);
  const n=circuit.qubits,dim=2**n,state=new Float64Array(dim*2);
  state[0]=1;
  for(const gate of circuit.gates)applyGate(state,n,gate);
  const probabilities=new Float64Array(dim);
  let total=0;
  for(let i=0;i<dim;i++){probabilities[i]=state[2*i]**2+state[2*i+1]**2;total+=probabilities[i];}
  if(!Number.isFinite(total)||total<=0)throw Error('Invalid simulation norm.');
  const thresholds=new Float64Array(dim);let cumulative=0;
  for(let i=0;i<dim;i++){probabilities[i]/=total;cumulative+=probabilities[i];thresholds[i]=cumulative;}
  thresholds[dim-1]=1;
  const rng=rngSeeded(circuit.seed);
  const counts=new Uint32Array(dim);
  for(let j=0;j<circuit.shots;j++){
    const r=rng();
    let lo=0,hi=dim-1;
    while(lo<hi){const mid=(lo+hi)>>1;if(r<thresholds[mid])hi=mid;else lo=mid+1;}
    counts[lo]++;
  }
  const bitstring=i=>i.toString(2).padStart(n,'0');
  // The full statevector remains on the server. For large superpositions,
  // return a bounded high-probability / most-sampled subset rather than up
  // to 4096 amplitudes in an HTTP response.
  const active=Array.from({length:dim},(_,i)=>i)
    .filter(i=>probabilities[i]>1e-12||counts[i]>0);
  let visible=active;
  if(active.length>MAX_RETURNED_STATES){
    const byProbability=[...active].sort((a,b)=>
      probabilities[b]-probabilities[a]||counts[b]-counts[a]||a-b).slice(0,32);
    const bySamples=[...active].sort((a,b)=>
      counts[b]-counts[a]||probabilities[b]-probabilities[a]||a-b).slice(0,32);
    visible=[...new Set([...byProbability,...bySamples])].slice(0,MAX_RETURNED_STATES).sort((a,b)=>a-b);
  }
  let retainedProbability=0,shownShots=0;
  for(const i of visible){retainedProbability+=probabilities[i];shownShots+=counts[i];}
  const truncated=active.length>visible.length;
  const probabilitiesOut=[],countsOut={},amplitudes=[];
  for(const i of visible){
    const p=probabilities[i];
    if(p>1e-12)probabilitiesOut.push({state:bitstring(i),probability:Number(p.toFixed(12))});
    if(counts[i]>0)countsOut[bitstring(i)]=counts[i];
    if(n<=4&&(Math.abs(state[2*i])>1e-11||Math.abs(state[2*i+1])>1e-11))
      amplitudes.push({state:bitstring(i),re:Number(state[2*i].toFixed(10)),im:Number(state[2*i+1].toFixed(10))});
  }
  return {engine:'Privi Quantum / Hey Jose local simulator',
    method:'classical_exact_statevector',physicalQpu:false,quantumAdvantageClaimed:false,
    paymentRequired:false,networkWrites:false,
    bitOrder:'q0 is least-significant (rightmost) bit',
    qubits:n,gates:circuit.gates,shots:circuit.shots,seed:circuit.seed,
    probabilities:probabilitiesOut,counts:countsOut,amplitudes:n<=4?amplitudes:undefined,
    basisStatesWithProbability:active.length,returnedStates:visible.length,
    distributionTruncated:truncated,probabilityMassReturned:Number(retainedProbability.toFixed(12)),
    countsTotal:circuit.shots,countsShown:shownShots,
    totalProbability:total};
}
export function formatQuantumAnswer(result){
  const top=[...result.probabilities].sort((a,b)=>b.probability-a.probability).slice(0,12);
  const probabilities=top.map(row=>'- |'+row.state+'⟩: '+(100*row.probability).toFixed(3)+'% (sampled '+(result.counts[row.state]||0)+'/'+result.shots+' shots)').join('\n');
  return 'Privi Quantum — '+result.qubits+'-qubit circuit simulation\n\n'+
    'Ran '+result.gates.length+' gates using a **classical exact-statevector simulator**. '+result.shots+' seeded simulated measurement shots.\n\n'+probabilities+
    (result.distributionTruncated?
      '\n- Partial distribution: '+(result.basisStatesWithProbability-result.returnedStates)+
      ' nonzero/observed states omitted; '+(result.shots-result.countsShown)+
      ' shots not shown. Calculated probabilities are exact to floating-point precision.':
      result.probabilities.length>top.length?'\n- ... '+(result.probabilities.length-top.length)+' other nonzero states available in the structured result.':'')+
    '\n\nGate convention: q0 is the rightmost bit. No physical quantum processor, charges, tokens, wallet transactions, QPU advantage, or on-chain receipts were involved.';
}
