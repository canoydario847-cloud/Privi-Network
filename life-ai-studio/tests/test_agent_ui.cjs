"use strict";
const test=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");

function loadUI(){
  const source=fs.readFileSync(path.join(__dirname,"../public/app.js"),"utf8");
  const prepared=source.replace(/start\(\);\s*\}\)\(\);\s*$/,
    "globalThis.__lifeUITest={state,teamControls,teamTabs,agentResults,bindResultTabs};\n})();");
  assert.notEqual(prepared,source,"UI test entrypoint must be isolated from live startup");
  const dom={
    getElementById:()=>({}),
    querySelectorAll:()=>[]
  };
  const sandbox={document:dom};
  vm.runInNewContext(prepared,sandbox,{filename:"life-ui.js"});
  return {hooks:sandbox.__lifeUITest,dom};
}
function toggle(id,key){
  const attrs={};
  return {
    dataset:{[key]:id},attrs,
    classList:{toggle(name,active){attrs[name]=active;}},
    setAttribute(name,value){attrs[name]=value;},
    onclick:null
  };
}

test("Team Up exposes a separate tab and selectable lane for each configured agent",()=>{
  const {hooks}=loadUI();
  hooks.state.catalog={agents:[
    {id:"chatgpt",name:"ChatGPT",ready:true},
    {id:"claude",name:"Claude",ready:true},
    {id:"grok",name:"<Grok>",ready:false}
  ]};
  const html=hooks.teamControls();
  for(const id of ["chatgpt","claude","grok"]){
    assert.ok(html.includes('data-team-tab="'+id+'"'));
    assert.ok(html.includes('data-agent-pane="'+id+'"'));
  }
  assert.ok(html.includes("&lt;Grok&gt;"),"Provider names must be HTML escaped");
  assert.ok(html.includes('name="selected-agent"'),"Existing run-team submission inputs retained");
  assert.ok(html.includes("Provider not configured"),"Missing providers must not appear operational");
});

test("Selecting an agent lane preserves all team selections",()=>{
  const {hooks,dom}=loadUI();
  const tabs=[toggle("all","teamTab"),toggle("claude","teamTab")];
  const lanes=[{dataset:{agentPane:"chatgpt"},hidden:false},{dataset:{agentPane:"claude"},hidden:false}];
  const boxes=[
    {checked:true,addEventListener(name,fn){this.notify=fn;}},
    {checked:true,addEventListener(name,fn){this.notify=fn;}}
  ];
  const summary={textContent:""};
  dom.getElementById=id=>id==="teamselection"?summary:{};
  dom.querySelectorAll=selector=>{
    if(selector==="[data-team-tab]")return tabs;
    if(selector==="[data-agent-pane]")return lanes;
    if(selector==='input[name="selected-agent"]')return boxes;
    if(selector==='input[name="selected-agent"]:checked')return boxes.filter(box=>box.checked);
    return [];
  };
  hooks.teamTabs();
  assert.ok(summary.textContent.includes("2 agents selected"));
  tabs[1].onclick();
  assert.equal(lanes[0].hidden,true);
  assert.equal(lanes[1].hidden,false);
  assert.equal(tabs[1].attrs["aria-pressed"],"true");
  assert.equal(boxes[0].checked,true,"Hidden agent must remain selected");
  tabs[0].onclick();
  assert.equal(lanes[0].hidden,false);
  assert.equal(lanes[1].hidden,false);
});

test("Agent results show individually filtered outputs without deleting results",()=>{
  const {hooks,dom}=loadUI();
  const html=hooks.agentResults([
    {agent:"ChatGPT",status:"done",task:"Frontend",output:"UI"},
    {agent:"Claude",status:"done",task:"Backend",output:"API"}
  ]);
  assert.ok(html.includes('data-result-tab="ChatGPT"'));
  assert.ok(html.includes('data-result-tab="Claude"'));
  const tabs=[toggle("all","resultTab"),toggle("Claude","resultTab")];
  const outputs=[{dataset:{resultPane:"ChatGPT"},hidden:false},{dataset:{resultPane:"Claude"},hidden:false}];
  dom.querySelectorAll=selector=>selector==="[data-result-tab]"?tabs:selector==="[data-result-pane]"?outputs:[];
  hooks.bindResultTabs();
  tabs[1].onclick();
  assert.equal(outputs[0].hidden,true);
  assert.equal(outputs[1].hidden,false);
  tabs[0].onclick();
  assert.equal(outputs[0].hidden,false);
  assert.equal(outputs[1].hidden,false);
});
