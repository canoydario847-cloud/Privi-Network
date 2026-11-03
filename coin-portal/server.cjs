"use strict";
// Dependency-free, prelaunch informational portal. No purchase, crypto custody,
// HTTP API, user databases, analytics or payment backend.
const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");

const ROOT = __dirname;
const ALLOWED = Object.freeze({
  "/": ["index.html", "text/html; charset=utf-8"],
  "/index.html": ["index.html", "text/html; charset=utf-8"],
  "/styles.css": ["styles.css", "text/css; charset=utf-8"],
  "/app.js": ["app.js", "application/javascript; charset=utf-8"],
  "/robots.txt": ["robots.txt", "text/plain; charset=utf-8"]
});
const SECURITY_HEADERS = Object.freeze({
  "X-Content-Type-Options": "nosniff",
  "Referrer-Policy": "no-referrer",
  "X-Frame-Options": "DENY",
  "X-Robots-Tag": "noindex, nofollow, noarchive",
  "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=(), clipboard-read=(), clipboard-write=()",
  "Content-Security-Policy": "default-src 'self'; base-uri 'self'; object-src 'none'; frame-ancestors 'none'; connect-src 'none'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; form-action 'none'; upgrade-insecure-requests",
  "Cache-Control": "no-store"
});

function makeServer() {
  return http.createServer((req, res) => {
    const headers = { ...SECURITY_HEADERS };
    const method = req.method || "";
    if (method !== "GET" && method !== "HEAD") {
      res.writeHead(405, {...headers, Allow:"GET, HEAD", "Content-Type":"text/plain; charset=utf-8"});
      return res.end("Method not allowed");
    }
    let pathname;
    try {
      const u=new URL(req.url || "/", "http://localhost");
      pathname=u.pathname;
      if(u.search && !/^\/health$/.test(pathname)){
        res.writeHead(404,{...headers,"Content-Type":"text/plain; charset=utf-8"});
        return res.end("Not found");
      }
    } catch (_) {
      res.writeHead(400,{...headers,"Content-Type":"text/plain; charset=utf-8"});
      return res.end("Bad request");
    }
    if (pathname === "/health") {
      res.writeHead(200, {...headers, "Content-Type":"text/plain; charset=utf-8"});
      return res.end(method==="HEAD"?"":"ok");
    }
    const item = Object.prototype.hasOwnProperty.call(ALLOWED,pathname)
      ? ALLOWED[pathname] : null;
    if(!item){
      res.writeHead(404,{...headers,"Content-Type":"text/plain; charset=utf-8"});
      return res.end("Not found");
    }
    // Only hardcoded public files can be read. Never expose repo, dotfiles,
    // CI secrets, env variables, test keys or config via HTTP.
    const filepath=path.join(ROOT,item[0]);
    fs.readFile(filepath,(err,bytes)=>{
      if(err){
        res.writeHead(500,{...headers,"Content-Type":"text/plain; charset=utf-8"});
        return res.end("Unavailable");
      }
      res.writeHead(200,{...headers,"Content-Type":item[1],"Content-Length":bytes.length});
      return res.end(method==="HEAD"?undefined:bytes);
    });
  });
}

if(require.main===module){
  const rawPort = process.env.PORT || "3000";
  const port=Number(rawPort);
  if(!Number.isInteger(port)||port<=0||port>65535){
    console.error("Invalid PORT");process.exitCode=1;
  }else{
    const server=makeServer();
    server.listen(port,"0.0.0.0",()=>console.log("Privi preview static server listening on port "+port));
    server.on("error",()=>{console.error("Preview HTTP server failed");process.exitCode=1;});
  }
}
module.exports={makeServer};
