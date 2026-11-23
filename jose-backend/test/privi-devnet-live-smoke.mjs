// Manual / CI read-only remote check. No signing keys or transactions.
import { createDevnetClient } from '../src/privi-devnet.js';
const client=createDevnetClient({timeoutMs:15000});
const report=await client.check(true);
console.log(JSON.stringify(report,null,2));
if(!report.connected){
  console.error('Privi Devnet live read-only probe did not verify the node.');
  process.exitCode=1;
}else{
  console.log('PASS: Real Privi Devnet reports chain 772626 and a fresh block; Jose may use this RPC.');
}
