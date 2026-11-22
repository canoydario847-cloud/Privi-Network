const get = id => document.getElementById(id);
let catalog = [];
let busy = false;
async function gateway(method, params, key) {
  const headers = {"Content-Type": "application/json"};
  if (key) headers.Authorization = "Bearer " + key;
  const res = await fetch("https://privi-ai-21-gateway.onrender.com/mcp", {
    method:"POST", headers, credentials:"omit", redirect:"error", cache:"no-store",
    signal:AbortSignal.timeout(45000),
    body:JSON.stringify({jsonrpc:"2.0",id:1,method,params})
  });
  if (!res.ok) throw Error("Gateway returned HTTP " + res.status);
  const data = await res.json();
  if (data.error) throw Error(data.error.message);
  return data.result;
}
function selectTool() {
  const tool = catalog.find(t => t.name === get("tool").value);
  get("description").textContent = tool?.description || "No matching tools";
  get("schema").textContent = JSON.stringify(tool?.inputSchema || {}, null, 2);
  get("run").disabled = !tool || busy;
}
function filterTools() {
  const q = get("query").value.trim().toLowerCase();
  const matches = catalog.filter(t => [t.name,t.title,t.description].join(" ").toLowerCase().includes(q));
  get("tool").replaceChildren(...matches.map(t => new Option(t.title || t.name,t.name)));
  selectTool();
}
async function discover() {
  get("load").disabled = true;
  get("status").textContent = "Connecting to Privi…";
  try {
    const data = await gateway("tools/list",{});
    if (!Array.isArray(data.tools)) throw Error("Unexpected catalog response");
    catalog = data.tools;
    filterTools();
    get("status").textContent = catalog.length + " tools available in the gateway catalog";
  } catch(e) { get("status").textContent = "Catalog unavailable. " + e.message; }
  finally { get("load").disabled = false; }
}
get("query").oninput = filterTools;
get("tool").onchange = selectTool;
get("load").onclick = discover;
get("runner").onsubmit = async event => {
  event.preventDefault();
  if (busy) return;
  let args;
  try {
    args = JSON.parse(get("args").value);
    if (!args || typeof args !== "object" || Array.isArray(args)) throw Error();
  } catch { get("output").textContent = "Enter a JSON object for the tool inputs."; return; }
  const name = get("tool").value;
  if (!catalog.some(t=>t.name===name)) return;
  busy = true;
  selectTool();
  get("output").textContent = "Running " + name + "…";
  try {
    const result = await gateway("tools/call",{name,arguments:args},get("key").value.trim());
    get("output").textContent = (result.isError ? "Tool declined the request\n" : "") +
      JSON.stringify(result.structuredContent ?? result.content,null,2);
  } catch(e) { get("output").textContent = e.message + ". Outcome unknown. Check your account before retrying."; }
  finally { busy = false; selectTool(); }
};
discover();