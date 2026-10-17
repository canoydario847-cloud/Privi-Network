"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const {localGate}=require("./send_disposable_test_transfer.cjs");

test("only explicit CI local opt-in permits invoking transfer",()=>{
  assert.doesNotThrow(()=>localGate({CI:"true",PRIVI_EPHEMERAL_TRANSFER_TEST:"1"},
    "http://127.0.0.1:8545"));
});
test("refuses out-of-CI key export/transfer",()=>{
  assert.throws(()=>localGate({CI:"false",PRIVI_EPHEMERAL_TRANSFER_TEST:"1"},
    "http://127.0.0.1:8545"),/CI-only/);
});
test("refuses missing explicit opt-in",()=>{
  assert.throws(()=>localGate({CI:"true"},
    "http://127.0.0.1:8545"),/CI-only/);
});
test("refuses remote JSON-RPC destination",()=>{
  assert.throws(()=>localGate({CI:"true",PRIVI_EPHEMERAL_TRANSFER_TEST:"1"},
    "https://example.com"),/localhost/);
});
