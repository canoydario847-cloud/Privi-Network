#!/usr/bin/env node
// OFFLINE ONLY. Stop the original service first; never post validator.pem.
'use strict';
const fs=require('node:fs'), crypto=require('node:crypto'), path=require('node:path'), assert=require('node:assert/strict');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
const pub=k=>crypto.createPublicKey(k);
const address=k=>'prv_'+sha(pub(k).export({format:'der',type:'spki'})).slice(0,40);
const core=b=>({index:b.index,chainId:b.chainId,timestamp:b.timestamp,previousHash:b.previousHash,merkleRoot:b.merkleRoot,validator:b.validator,transactions:b.transactions});
function inspect(source){
  const chain=JSON.parse(fs.readFileSync(path.join(source,'chain.json'),'utf8'));
  const key=crypto.createPrivateKey(fs.readFileSync(path.join(source,'validator.pem')));
  const validator=address(key);
  assert(Array.isArray(chain)&&chain.length,'Empty chain');
  for(let i=0;i<chain.length;i++){
    const block=chain[i];
    assert(block.index===i&&block.chainId==='privi-dev-1','Wrong chain/block');
    assert(block.hash===sha(JSON.stringify(core(block))),'Block hash mismatch');
    if(!i)assert(block.validator==='GENESIS'&&block.previousHash==='0'.repeat(64),'Invalid genesis');
    else{
      assert(block.previousHash===chain[i-1].hash&&block.validator===validator,'Wrong validator/previous block');
      assert(crypto.verify(null,Buffer.from(block.hash,'hex'),pub(key),Buffer.from(block.signature,'base64')),'Bad validator signature');
    }
  }
  return {height:chain.length-1,headHash:chain.at(-1).hash,validator};
}
function copy(source,dest){
  source=path.resolve(source);dest=path.resolve(dest);
  assert(dest!==source&&!dest.startsWith(source+path.sep),'Unsafe target directory');
  assert(!fs.existsSync(dest),'Destination exists: will not overwrite');
  const files=['chain.json','validator.pem'];
  if(fs.existsSync(path.join(source,'user-wallet.pem')))files.push('user-wallet.pem');
  for(const file of files){
    const st=fs.lstatSync(path.join(source,file));
    assert(st.isFile()&&!st.isSymbolicLink(),'Unsafe source file: '+file);
  }
  const before=inspect(source),parent=path.dirname(dest);
  fs.mkdirSync(parent,{recursive:true,mode:0o700});
  const tmp=fs.mkdtempSync(path.join(parent,'.privi-copy-'));
  try{
    fs.chmodSync(tmp,0o700);
    for(const file of files){
      fs.copyFileSync(path.join(source,file),path.join(tmp,file),fs.constants.COPYFILE_EXCL);
      fs.chmodSync(path.join(tmp,file),0o600);
      assert(sha(fs.readFileSync(path.join(source,file)))===sha(fs.readFileSync(path.join(tmp,file))),'Copy mismatch: '+file);
    }
    const after=inspect(tmp);assert.deepEqual(before,after,'State changed mid-backup');
    fs.writeFileSync(path.join(tmp,'backup-manifest.json'),JSON.stringify({type:'OFFLINE_VALIDATOR_STATE',snapshot:after,files},null,2)+'\n',{mode:0o600,flag:'wx'});
    fs.renameSync(tmp,dest);
    return after;
  }catch(e){fs.rmSync(tmp,{recursive:true,force:true});throw e}
}
if(require.main===module){
  try{
    if(process.argv.length!==4)throw Error('Usage: node legacy_state_copy.js <STOPPED_SOURCE_DIR> <NEW_DEST_DIR>');
    console.log('State copy verified:',JSON.stringify(copy(process.argv[2],process.argv[3])));
    console.log('Keys copied privately with mode 0600. Do not commit them.');
  }catch(e){console.error('Copy refused:',e.message);process.exitCode=1;}
}
module.exports={inspect,copy};
