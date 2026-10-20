"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const {makeServer}=require("../server.cjs");

async function withServer(work){
  const server=makeServer();
  await new Promise((resolve,reject)=>{server.once("error",reject);server.listen(0,"127.0.0.1",resolve)});
  try {
    const base="http://127.0.0.1:"+server.address().port;
    await work(base);
  } finally {await new Promise(resolve=>server.close(resolve));}
}
test("serves prelaunch HTML and required security headers",async()=>{
  await withServer(async(base)=>{
    const res=await fetch(base+"/");
    assert.equal(res.status,200);
    assert.match(await res.text(),/PRVI PURCHASES NOT OPEN/);
    assert.match(res.headers.get("content-security-policy"),/connect-src 'none'/);
    assert.equal(res.headers.get("x-robots-tag"),"noindex, nofollow, noarchive");
    assert.equal(res.headers.get("x-frame-options"),"DENY");
  });
});
test("serves only explicitly allowed public assets",async()=>{
  await withServer(async(base)=>{
    for(const asset of ["/app.js","/styles.css","/robots.txt","/health"]){
      const res=await fetch(base+asset);
      assert.equal(res.status,200,asset);
    }
    for(const asset of ["/package.json","/README.md","/server.cjs","/.env",
      "/tests/site.test.cjs","/..%2fserver.cjs","/some-other-file"]){
      const res=await fetch(base+asset);
      assert.equal(res.status,404,asset);
    }
  });
});
test("rejects body-bearing HTTP writes; never accepts payment requests",async()=>{
  await withServer(async(base)=>{
    const response=await fetch(base+"/",{method:"POST",body:"not a payment"});
    assert.equal(response.status,405);
    assert.equal(response.headers.get("allow"),"GET, HEAD");
  });
});
test("HEAD returns a status with no body",async()=>{
  await withServer(async(base)=>{
    const res=await fetch(base+"/", {method:"HEAD"});
    assert.equal(res.status,200);
    assert.equal(await res.text(),"");
  });
});
