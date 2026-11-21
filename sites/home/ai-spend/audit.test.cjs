const assert=require("node:assert/strict");const {estimate}=require("./audit.js");
const a=estimate(500,10,30,40);assert.equal(a.repeated,50);assert.equal(a.routed,54);assert.equal(a.savings,104);assert.equal(a.remaining,396);assert.equal(a.annual,1248);
assert.equal(estimate(500,100,100,100).savings,500);assert.equal(estimate(0,100,100,100).savings,0);assert.equal(estimate(100,0,0,0).remaining,100);
for(const x of [[-1,0,0,0],[100,101,0,0],[100,0,0,Infinity],[NaN,0,0,0]])assert.throws(()=>estimate(...x),RangeError);
console.log("Privi ONE scenario calculation tests passed");
