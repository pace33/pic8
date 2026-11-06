import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const read = name => fs.readFileSync(new URL('../training/' + name, import.meta.url), 'utf8');
const source = read('data-api.js');
const primary = 'https://aiedue.ddns.net/db-pic8/api';
let count = 0;
const tick = () => new Promise(resolve => setImmediate(resolve));
function fixture(fetch) {
  const nodes = new Map();
  const get = id => {
    if (!nodes.has(id)) nodes.set(id, {value:'', hidden:false, disabled:false, textContent:'', listeners:{},
      addEventListener(type, fn){this.listeners[type]=fn;},
      classList:{toggle(){}}, setAttribute(){}, focus(){}, reset(){}, close(){}, showModal(){}});
    return nodes.get(id);
  };
  const document = {getElementById:get, querySelector:get, addEventListener(){}};
  const ctx = vm.createContext({window:{}, document, fetch, Headers, setInterval(){}, setTimeout, clearTimeout, AbortController});
  vm.runInContext(source,ctx);
  return {ctx,get};
}
{
  let calls=0;
  const {ctx}=fixture(async()=>{calls++;throw Error('offline');});
  const api=ctx.window.Pic8Api;
  const p=api.resolve();
  assert.equal(p,api.resolve());
  assert.deepEqual(await Promise.all(Array.from({length:8},()=>api.resolve())),Array(8).fill(primary));
  assert.equal(api.state.backend,'aiedue');
  assert.equal(calls,0);
  assert(Object.isFrozen(api) && Object.isFrozen(api.state));
  assert(!('legacy' in api));
  assert(!source.includes('chatgpt.site'));
  count++;
}
for (const scenario of ['active','inactive','string-true','http-503','network','bad-json']) {
  const requests=[];
  const {ctx,get}=fixture(async(url,options={})=>{
    requests.push({url,method:options.method||'GET'});
    if(scenario==='network')throw Error('offline');
    return {ok:scenario!=='http-503',json:async()=>{
      if(scenario==='bad-json')throw Error('invalid JSON');
      return {published:false,readyForCutover:scenario==='active'?true:scenario==='string-true'?'true':false};
    }};
  });
  vm.runInContext(read('app.js'),ctx);
  await tick();
  assert(requests.length>0);
  assert(requests.every(r=>r.url===primary+'/registrations' && r.method==='GET'));
  assert.equal(get('submit-button').disabled,scenario!=='active',scenario);
  if(scenario!=='active')assert.equal(get('intake-status').textContent,'접수 연결 확인 중');
  assert.equal(await ctx.window.Pic8Api.resolve(),primary);
  count++;
}
for (const mutationFailure of ['network','http-503']) {
  const requests=[];
  const {ctx,get}=fixture(async(url,options={})=>{
    requests.push({url,method:options.method||'GET'});
    if(options.method==='POST'){
      if(mutationFailure==='network')throw Error('offline');
      return {ok:false,json:async()=>({error:'temporary failure'})};
    }
    return {ok:true,json:async()=>({published:false,readyForCutover:true})};
  });
  vm.runInContext(read('app.js'),ctx);await tick();
  for(const [key,value] of Object.entries({region:'검증',school:'검증학교',name:'가상검증',pin:'0042'}))get(key).value=value;
  await get('training-form').listeners.submit({preventDefault(){}});
  await tick();
  assert.equal(requests.filter(r=>r.method==='POST').length,1,'no mutation replay');
  assert(requests.every(r=>r.url===primary+'/registrations'));
  assert.equal(get('form-message').hidden,false);
  assert.equal(get('submit-button').disabled,false,'busy flag released; no automatic retry');
  count++;
}
{
  const requests=[];
  const {ctx,get}=fixture(async(url,options={})=>{requests.push({url,method:options.method||'GET'});throw Error('offline');});
  vm.runInContext(read('admin.js'),ctx);
  get('admin-password').value='synthetic-fixture-not-a-real-password';
  await get('admin-login-form').listeners.submit({preventDefault(){}});
  assert.equal(requests.length,1);
  assert.equal(requests[0].url,primary+'/admin/login');
  assert.equal(requests[0].method,'POST');
  assert.equal(get('login-message').hidden,false);
  assert.equal(get('login-button').disabled,false);
  count++;
}
for(const [html,script,version] of [['index.html','app.js','20261106-status-v1'],['manage.html','admin.js','20261106-fresh-start-v2']]){
  assert(read(html).includes('data-api.js?v=aiedue-fresh-start-v2'));
  assert(read(html).includes(script+'?v='+version));
}
console.log(JSON.stringify({routingTestsPassed:count,aiedueOnly:true,noLegacyFallback:true,noMutationReplay:true,htmlVersionChain:true}));
