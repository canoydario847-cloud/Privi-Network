'use strict';
// Offline manifest comparison only: manifest must be independently approved.
const {auditBankSupply}=require('./audit_bank_supply.cjs');
const decimal=/^(0|[1-9][0-9]*)$/;
const UINT256_MAX=(1n<<256n)-1n;
const validUint256=value=>typeof value==='string' && decimal.test(value) && value.length<=78 && BigInt(value)<=UINT256_MAX;
function auditSupplyManifest(genesis,manifest){
 const errors=auditBankSupply(genesis);
 if(!manifest||typeof manifest!=='object'||Array.isArray(manifest))return [...errors,'missing approved supply manifest'];
 if(typeof manifest.denom!=='string'||!manifest.denom||/[\s\x00-\x1f\x7f]/u.test(manifest.denom))errors.push('invalid manifest denom');
 if(!validUint256(manifest.expectedSupply))errors.push('invalid manifest expectedSupply');
 if(!validUint256(manifest.maxSupply))errors.push('invalid manifest maxSupply');
 if(errors.length)return errors;
 const supply=genesis.app_state.bank.supply.find(x=>x.denom===manifest.denom);
 if(!supply){errors.push('manifest denomination missing from bank supply');return errors;}
 if(!validUint256(supply.amount)){errors.push('bank supply exceeds uint256 range');return errors;}
 const actual=BigInt(supply.amount),expected=BigInt(manifest.expectedSupply),cap=BigInt(manifest.maxSupply);
 if(actual!==expected)errors.push('bank supply differs from manifest');
 if(actual>cap)errors.push('bank supply exceeds manifest cap');
 if(expected>cap)errors.push('manifest expectedSupply exceeds cap');
 return errors;
}
module.exports={auditSupplyManifest};
