"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {guardDeps,compileFixture}=require("./deploy_disposable_counter.cjs");

test("guards contract deployment to explicit disposable CI",()=>{
  assert.doesNotThrow(()=>guardDeps({
    CI:"true",PRIVI_EPHEMERAL_TRANSFER_TEST:"1",
    PRIVI_ETHERS_MODULE_PATH:"/tmp/privi-test-ethers/node_modules/ethers",
    PRIVI_SOLC_MODULE_PATH:"/tmp/privi-test-ethers/node_modules/solc"
  }));
});
test("refuses contract deployment outside CI",()=>{
  assert.throws(()=>guardDeps({
    CI:"false",PRIVI_EPHEMERAL_TRANSFER_TEST:"1",
    PRIVI_ETHERS_MODULE_PATH:"/tmp/privi-test-ethers/node_modules/ethers",
    PRIVI_SOLC_MODULE_PATH:"/tmp/privi-test-ethers/node_modules/solc"
  }),/CI-only/);
});
test("refuses missing compiler installation",()=>{
  assert.throws(()=>guardDeps({
    CI:"true",PRIVI_EPHEMERAL_TRANSFER_TEST:"1",
    PRIVI_ETHERS_MODULE_PATH:"/tmp/privi-test-ethers/node_modules/ethers"
  }),/solc/);
});
test("rejects accidental wrong Solidity compiler version",()=>{
  assert.throws(()=>compileFixture({version:()=>"0.7.6+commit"}, "contract PriviDevCounter{}"),
    /compiler/);
});
test("rejects malformed compiler output",()=>{
  assert.throws(()=>compileFixture({
    version:()=>"0.8.26+commit.foo",compile:()=>JSON.stringify({contracts:{}})
  },"contract PriviDevCounter{}"),/contract ABI/);
});
