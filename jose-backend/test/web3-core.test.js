import test from 'node:test';
import assert from 'node:assert/strict';
import {buildSource,validateSupply,validateCreationBytecode,networkById,chainManifest,appendRecord,verifyRecords} from '../../jose-site/web3-core.mjs';
test('fixed-supply ERC20 escapes input and has no secondary mint',()=>{
 const x=buildSource('token',{name:'Sample Token',symbol:'SMPL',supply:'1000000'});
 assert.match(x.source,/_mint\(msg.sender/);
 assert.match(x.source,/uint256\(1000000\)/);
 assert.ok(!x.source.includes('function mint('));
 assert.deepEqual(x.constructorArgs,[]);
 assert.throws(()=>buildSource('token',{name:'Bad"; } contract Evil {',symbol:'E',supply:'1'}));
 assert.throws(()=>validateSupply('1e18'));
});
test('NFT owner-gated mint and metadata; no injected token names',()=>{
 const x=buildSource('nft',{name:'Jose Art',symbol:'ART'});
 assert.match(x.source,/onlyOwner/);
 assert.match(x.source,/ERC721URIStorage/);
 assert.throws(()=>buildSource('nft',{name:'A\nbreak',symbol:'NFT'}));
});
test('message vault and ledger anchor have zero-arg constructors',()=>{
 for(const kind of ['contract','ledger-anchor'])assert.deepEqual(buildSource(kind,{name:'Test Vault'}).constructorArgs,[]);
});
test('checks bytecode and network IDs',()=>{
 assert.equal(validateCreationBytecode('0x60016000'),'0x60016000');
 assert.throws(()=>validateCreationBytecode('0xzz'));
 assert.throws(()=>validateCreationBytecode('0xabc'));
 assert.equal(networkById(84532).testnet,true);
 assert.throws(()=>networkById(262144));
});
test('chain blueprint is not represented as a launched network',()=>{
 const m=chainManifest({name:'Demo Network',chainId:262144,validators:4});
 assert.equal(m.status,'DESIGN_ONLY_NOT_DEPLOYED');
 assert.throws(()=>chainManifest({name:'Demo Network',chainId:262144,validators:1}));
});
test('ledger detects altered records and broken links',async()=>{
 let r=await appendRecord([],'created');
 r=await appendRecord(r,'second');
 assert.equal(await verifyRecords(r),true);
 assert.equal(await verifyRecords([{...r[0],entry:'changed'},r[1]]),false);
 assert.equal(await verifyRecords([r[1],r[0]]),false);
 assert.equal(await verifyRecords([{...r[0],hash:'bad'}]),false);
});
