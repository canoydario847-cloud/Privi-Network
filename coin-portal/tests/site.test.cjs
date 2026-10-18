"use strict";
const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const root=path.resolve(__dirname,"..");
const html=fs.readFileSync(path.join(root,"index.html"),"utf8");
const js=fs.readFileSync(path.join(root,"app.js"),"utf8");
const css=fs.readFileSync(path.join(root,"styles.css"),"utf8");

test("purchase control is native-disabled and visibly says sale not open",()=>{
  assert.match(html,/<button class="purchase-button"[^>]*\bdisabled\b/);
  assert.match(html,/PRVI PURCHASES NOT OPEN/);
  assert.match(html,/NO PUBLIC TOKEN SALE IS OPEN/);
  assert.match(js,/const SALE_ENABLED = false;/);
});
test("no signing, payment, swap or token approval API is implemented",()=>{
  for(const method of ["eth_sendTransaction","eth_sendRawTransaction",
        "personal_sign","eth_sign","eth_signTypedData","eth_call","wallet_addEthereumChain",
        "wallet_switchEthereumChain","approve(","transfer("]) {
    assert.ok(!js.includes(method),"potentially financial method detected: "+method);
  }
  assert.match(js,/method:"eth_requestAccounts"/);
  assert.match(js,/method:"eth_chainId"/);
});
test("no tracking, external fonts, third party scripts or form submissions",()=>{
  assert.doesNotMatch(html,/<form\b/i);
  assert.doesNotMatch(html,/<script[^>]*src="https?:/i);
  assert.doesNotMatch(html,/<iframe\b/i);
  assert.doesNotMatch(css,/@import/i);
  assert.doesNotMatch(js,/\bfetch\s*\(/);
  assert.doesNotMatch(js,/\bXMLHttpRequest\b/);
  assert.doesNotMatch(js,/\blocalStorage\b/);
  assert.match(html,/Content-Security-Policy/);
  assert.match(html,/noindex, nofollow/);
});
test("local script and stylesheet paths resolve",()=>{
  for(const asset of ["styles.css","app.js"]) {
    assert.ok(html.includes('"./'+asset+'"'));
    assert.ok(fs.statSync(path.join(root,asset)).size>0);
  }
});
test("every local anchor target has a corresponding ID",()=>{
  const ids=new Set([...html.matchAll(/\bid="([a-zA-Z0-9-]+)"/g)].map(m=>m[1]));
  for(const match of html.matchAll(/\bhref="#([a-zA-Z0-9-]+)"/g)) {
    assert.ok(ids.has(match[1]),"missing local anchor "+match[1]);
  }
});
test("sale status and network differences are accurately disclosed",()=>{
  assert.match(html,/1,000,000,000/);
  assert.match(html,/not yet issued/i);
  assert.match(html,/NO FUNDS REQUESTED/);
  assert.match(html,/TEST \/ atest/);
  assert.match(html,/BNB PRIV/);
  assert.match(html,/not independently audited/i);
});
test("page uses accessible landmarks and responsive viewport",()=>{
  assert.match(html,/<html lang="en">/);
  assert.match(html,/<main id="main">/);
  assert.match(html,/<nav[^>]+aria-label="Main navigation"/);
  assert.match(html,/name="viewport"/);
  assert.match(html,/aria-live="polite"/);
  assert.match(css,/@media\(max-width:500px\)/);
  assert.match(css,/prefers-reduced-motion/);
});
