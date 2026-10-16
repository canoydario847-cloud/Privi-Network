'use strict';
const {test}=require('node:test'), assert=require('node:assert/strict'),
 fs=require('node:fs'),os=require('node:os'),path=require('node:path'),crypto=require('node:crypto');
const {inspect,copy}=require('./legacy_state_copy');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
function fixture(){
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'privi-backup-'));
 const src=path.join(root,'source');fs.mkdirSync(src);
 const key=crypto.generateKeyPairSync('ed25519').privateKey;
 fs.writeFileSync(path.join(src,'validator.pem'),key.export({format:'pem',type:'pkcs8'}));
 let g={index:0,chainId:'privi-dev-1',timestamp:0,previousHash:'0'.repeat(64),merkleRoot:sha(''),validator:'GENESIS',transactions:[]};
 g.hash=sha(JSON.stringify(g));g.signature='';
 const v='prv_'+sha(crypto.createPublicKey(key).export({format:'der',type:'spki'})).slice(0,40);
 let b={index:1,chainId:'privi-dev-1',timestamp:1,previousHash:g.hash,merkleRoot:sha(''),validator:v,transactions:[]};
 b.hash=sha(JSON.stringify(b));
 b.signature=crypto.sign(null,Buffer.from(b.hash,'hex'),key).toString('base64');
 fs.writeFileSync(path.join(src,'chain.json'),JSON.stringify([g,b]));
 return {root,src};
}
test('offline backup verified with private key permissions',()=>{
 const {root,src}=fixture();try{
   const dest=path.join(root,'dest');
   assert.equal(copy(src,dest).height,1);
   assert.equal(inspect(dest).height,1);
   assert.equal(fs.statSync(path.join(dest,'validator.pem')).mode&0o777,0o600);
   assert.throws(()=>copy(src,dest),/Destination exists/);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
test('tampered chain aborts',()=>{
 const {root,src}=fixture();try{
   const file=path.join(src,'chain.json'),chain=JSON.parse(fs.readFileSync(file));
   chain[1].timestamp=55;fs.writeFileSync(file,JSON.stringify(chain));
   assert.throws(()=>copy(src,path.join(root,'dest')),/Block hash mismatch/);
 }finally{fs.rmSync(root,{recursive:true,force:true})}
});
