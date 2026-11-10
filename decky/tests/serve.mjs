import { build } from 'esbuild';
import { createServer } from 'node:http';
import { resolve } from 'node:path';
const result=await build({entryPoints:['tests/harness.tsx'],bundle:true,write:false,format:'iife',jsx:'automatic',alias:{'@decky/api':resolve('tests/mock-decky-api.ts'),'@decky/ui':resolve('tests/mock-decky-ui.tsx')}});
const html='<!doctype html><html lang="en"><meta charset="utf-8"><title>DeckPilot UI tests</title><body style="margin:0;background:#101820;color:#edf4fa;font:16px system-ui"><div id="root"></div><script src="/app.js"></script></body></html>';
createServer((req,res)=>{
 if(req.url==='/app.js'){res.setHeader('Content-Type','text/javascript');res.end(result.outputFiles[0].contents);}
 else if(req.url==='/'){res.setHeader('Content-Type','text/html');res.end(html);}
 else {res.writeHead(404);res.end();}
}).listen(4173,'127.0.0.1');
