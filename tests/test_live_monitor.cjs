const assert=require('node:assert/strict');
const handler=require('../api/live.js');
const {changes,notify}=require('../scripts/cloud-monitor.cjs');
const now=new Date('2026-10-28T18:00Z'),next={'1':{id:'12345678',date:'2026-10-29T16:00Z',name:'A vs B'}};
const p={id:'p',name:'Player',status:'Questionable',date:now.toISOString(),comment:''};
const old=[{id:'1',players:[p]}],fresh=[{id:'1',players:[{...p,status:'Out'}]}];
assert.equal(changes([],fresh,next,now).length,0,'first poll must not send old statuses as new alerts');
assert.equal(changes(old,fresh,next,now).length,1);
assert.equal(changes(fresh,fresh,next,now).length,0);
assert.equal(changes(old,fresh,{},now).length,0);
assert.equal(changes(old,fresh,next,new Date('2026-11-01')).length,0);
function response(){return {statusCode:200,headers:{},setHeader(k,v){this.headers[k]=v;},end(s){this.body=s;}};}
(async()=>{
 const original=global.fetch;let calls=0;
 try{
  global.fetch=async()=>{calls++;throw Error('Must not fetch');};
  for(const query of [{event:'https://bad.test'},{url:'https://bad.test'},{event:'../12345678'}]){const res=response();await handler({method:'GET',query},res);assert.equal(res.statusCode,400);}
  assert.equal(calls,0,'invalid queries must not reach the network');
  global.fetch=async()=>({ok:true,json:async()=>({status:'success',season:{year:new Date().getUTCFullYear()},injuries:[],events:[]})});
  const good=response();await handler({method:'GET',query:{}},good);assert.equal(good.statusCode,200);assert.deepEqual(JSON.parse(good.body).games,[]);
  global.fetch=async()=>{throw Error('Source down');};const failed=response();await handler({method:'GET',query:{}},failed);assert.equal(failed.statusCode,503);
  let posts=0;
  global.fetch=async(url,options)=>{if(options.method==='POST')posts++;return {ok:true,json:async()=>[{body:'<!-- wnba-alert:existing -->'}]};};
  assert.equal(await notify({marker:'existing'},'owner/repo','fake-token','owner'),'already-delivered');assert.equal(posts,0,'retry must not create duplicate issue');
 }finally{global.fetch=original;}
 console.log('Live API validation, unavailable-feed fallback, material alerts, and GitHub deduplication passed.');
})().catch(e=>{console.error(e);process.exitCode=1;});

