import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync(new URL('../training/data-api.js',import.meta.url),'utf8');
let count=0;
async function scenario(response, expected, backend){
  let requests=0;
  const context={window:{},AbortController,setTimeout,clearTimeout,fetch:async()=>{requests++;if(response instanceof Error)throw response;return {ok:true,json:async()=>response};}};
  vm.runInNewContext(source,context);
  const api=context.window.Pic8Api;
  const results=await Promise.all(Array.from({length:8},()=>api.resolve()));
  assert(results.every(base=>base===api[expected]));
  assert.equal(api.state.backend,backend);
  assert.equal(requests,1);
  count++;
}
await scenario({ok:true,readyForCutover:false},'legacy','legacy-preserved');
await scenario({ok:true,readyForCutover:true},'primary','aiedue');
await scenario({ok:true,readyForCutover:'true'},'legacy','legacy-preserved');
await scenario(new Error('network unavailable'),'legacy','legacy-preserved');
console.log(JSON.stringify({routingTestsPassed:count,zeroMutatingRequests:true}));
