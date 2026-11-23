// CI-only compile verification. This never deploys contracts or uses wallet keys.
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import solc from 'solc';
import {buildSource} from '../../jose-site/web3-core.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
function imports(imp){
  if(!imp.startsWith('@openzeppelin/contracts/'))return {error:'Unexpected import: '+imp};
  try{return {contents:readFileSync(path.join(root,'node_modules',imp),'utf8')};}
  catch{return {error:'Missing pinned OpenZeppelin source: '+imp};}
}
const samples=[
  buildSource('token',{name:'Test Token',symbol:'TEST',supply:'1000000'}),
  buildSource('nft',{name:'Test NFT',symbol:'TNFT'}),
  buildSource('contract',{name:'Jose Vault'}),
  buildSource('ledger-anchor'),
];
for(const file of samples){
 const input={language:'Solidity',sources:{[file.file]:{content:file.source}},settings:{
  optimizer:{enabled:true,runs:200},
  outputSelection:{'*':{'*':['abi','evm.bytecode.object']}}
 }};
 const output=JSON.parse(solc.compile(JSON.stringify(input),{import:imports}));
 const errors=(output.errors||[]).filter(e=>e.severity==='error');
 assert.equal(errors.length,0,file.file+' errors: '+errors.map(x=>x.formattedMessage).join('\n'));
 const result=output.contracts?.[file.file]?.[file.contract];
 assert.ok(result,file.contract+' artifact not found');
 assert.match(result.evm.bytecode.object,/^[0-9a-fA-F]+$/,file.contract+' has no usable creation bytecode');
 const constructor=result.abi.find(x=>x.type==='constructor');
 assert.equal(constructor?.inputs?.length||0,0,file.contract+' unexpectedly requires constructor arguments');
 console.log('Compiled '+file.file+' successfully ('+Math.ceil(result.evm.bytecode.object.length/2)+' bytes creation code)');
}
