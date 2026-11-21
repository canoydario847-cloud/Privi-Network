"use strict";
(function(){
function estimate(spend, repeat, route, discount){
 if (![spend,repeat,route,discount].every(Number.isFinite) || spend<0 || spend>1e8 || [repeat,route,discount].some(x=>x<0||x>100)) throw new RangeError("Use valid nonnegative amounts and percentages from 0 to 100.");
 const repeated=spend*repeat/100;
 const routed=(spend-repeated)*route/100*discount/100;
 const savings=repeated+routed;
 return {spend,repeat,route,discount,repeated,routed,savings,remaining:Math.max(0,spend-savings),annual:savings*12};
}
if(typeof module==="object"&&module.exports){module.exports={estimate};return;}
const el=id=>document.getElementById(id), usd=n=>new Intl.NumberFormat("en-US",{style:"currency",currency:"USD"}).format(n);
let current=null;
function update(){
 try{
  current=estimate(...["spend","repeat","route","discount"].map(id=>el(id).valueAsNumber));
  const r=current;
  for(const [id,value] of Object.entries({monthly:r.savings,repeatResult:r.repeated,routeResult:r.routed,remaining:r.remaining,annual:r.annual}))el(id).textContent=usd(value);
  el("payback").textContent=r.savings>0 ? "For comparison, a $35 one-time purchase equals about "+(35/r.savings).toLocaleString("en-US",{maximumFractionDigits:2})+" months of modeled savings, not a promised return." : "No savings estimated with these assumptions.";
  el("error").textContent="";el("download").disabled=false;
 }catch(e){current=null;el("error").textContent=e.message;el("download").disabled=true;for(const id of ["monthly","repeatResult","routeResult","remaining","annual"])el(id).textContent="—";el("payback").textContent="";}
}
el("audit").addEventListener("submit",e=>{e.preventDefault();update();});
el("audit").addEventListener("input",update);
el("download").addEventListener("click",()=>{
 if(!current)return;
 const r=current, lines=["PRIVI ONE — AI SPEND ESTIMATE","Made by Dario Canoy","Monthly spend: "+usd(r.spend),"Avoidable repeat share: "+r.repeat+"%","Eligible routing share: "+r.route+"%","Routing reduction: "+r.discount+"%","Monthly modeled savings: "+usd(r.savings),"Projected spend: "+usd(r.remaining),"Annualized estimate: "+usd(r.annual),"Scenario only; no savings guaranteed. No actual usage analyzed."];
 const url=URL.createObjectURL(new Blob([lines.join("\n")],{type:"text/plain;charset=utf-8"}));const a=document.createElement("a");a.href=url;a.download="privi-one-spend-estimate.txt";a.click();URL.revokeObjectURL(url);
});
update();
})();