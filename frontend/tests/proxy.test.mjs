import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {readFileSync} from 'node:fs';

test('Node development proxy strips forged identity and preserves API status/body/query', {timeout:10000}, async()=>{
  const upstream=http.createServer(async(req,res)=>{
    let body='';for await(const chunk of req)body+=chunk;
    res.writeHead(409,{'Content-Type':'application/json'});
    res.end(JSON.stringify({headers:req.headers,path:req.url,body:JSON.parse(body)}));
  });
  upstream.listen(0,'127.0.0.1');await once(upstream,'listening');
  const child=spawn(process.execPath,['server.mjs'],{cwd:new URL('../',import.meta.url),env:{...process.env,PORT:'0',MCP_API_URL:`http://127.0.0.1:${upstream.address().port}`},stdio:['ignore','pipe','pipe']});
  try {
    const address=await new Promise((resolve,reject)=>{
      child.stdout.on('data',chunk=>{const match=String(chunk).match(/http:\/\/localhost:(\d+)/);if(match)resolve(`http://127.0.0.1:${match[1]}`);});
      child.once('error',reject);child.once('exit',code=>reject(new Error(`server exited ${code}`)));
    });
    const response=await fetch(address+'/api/runs?limit=2',{method:'POST',headers:{Authorization:'Bearer user-session','X-Internal-Token':'forged','X-User-Id':'forged','X-User-Roles':'REQUESTER'},body:JSON.stringify({test_id:'PA01'})});
    assert.equal(response.status,409);const data=await response.json();
    assert.equal(data.path,'/api/runs?limit=2');assert.deepEqual(data.body,{test_id:'PA01'});
    assert.equal(data.headers.authorization,'Bearer user-session');
    for(const key of ['x-internal-token','x-user-id','x-user-roles'])assert.equal(data.headers[key],undefined);
  } finally {child.kill();await once(child,'exit');await new Promise(resolve=>upstream.close(resolve));}
});


test('entry and first-party module imports use the same release to bypass old browser caches',()=>{
  const index=readFileSync(new URL('../dist/index.html',import.meta.url),'utf8');
  const entry=index.match(/src="\.\/app\.js\?v=([^"\s]+)"/);
  assert.ok(entry);
  for(const file of ['app.js','live.js','registry.js','registration.js','scene.js']) {
    const source=readFileSync(new URL('../dist/'+file,import.meta.url),'utf8');
    for(const match of source.matchAll(/from ['"]\.\/([\w-]+\.js)([^'"]*)['"]/g)) {
      assert.equal(match[2],'?v='+entry[1],file+' → '+match[1]);
    }
  }
});
