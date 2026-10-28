/* Hourly cloud checks use Node only; no model refitting or local computer needed. */
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {reports}=require('../api/live.js');
const ROOT=path.resolve(__dirname,'..');
const read=(p,fallback)=>{try{return JSON.parse(fs.readFileSync(path.join(ROOT,p),'utf8'));}catch(e){if(e.code==='ENOENT')return fallback;throw e;}};
const write=(p,data)=>{fs.mkdirSync(path.dirname(path.join(ROOT,p)),{recursive:true});fs.writeFileSync(path.join(ROOT,p)+'.tmp',JSON.stringify(data,null,2)+'\n');fs.renameSync(path.join(ROOT,p)+'.tmp',path.join(ROOT,p));};
function material(p,now){return ['out','suspended'].includes(String(p.status).toLowerCase()) || /\b\d{1,2}[- ]minute (limit|restriction|cap)\b/i.test(p.comment||'');}
function changes(previous,current,nextGames,now=new Date()){
 if(!previous?.length)return [];
 const old=new Map((previous||[]).flatMap(t=>t.players.map(p=>[t.id+'|'+p.id,p]))),result=[];
 for(const t of current){const event=nextGames[t.id];if(!event)continue;const hours=(Date.parse(event.date)-now)/3600000;if(hours<=0||hours>24)continue;
  for(const p of t.players){const age=(now-Date.parse(p.date))/3600000;if(!Number.isFinite(age)||age<0||age>72)continue;
   if(!p.id)continue;
   const before=old.get(t.id+'|'+p.id)||{status:'No report',comment:''};
   if(before.status===p.status && before.comment===p.comment)continue;
   if(!material(p,now)&&!material(before,now))continue;
   const key=crypto.createHash('sha256').update(JSON.stringify([t.id,p.id,p.status,p.comment,event.id])).digest('hex').slice(0,24);
   result.push({key,title:`Availability update: ${p.name} — ${p.status}`,body:`${p.name}: ${before.status} → ${p.status}.\n\n${p.comment||p.detail||'No source detail.'}\n\nGame: ${event.name} (${event.date}). Report dated ${p.date}.\n\n[Source](https://www.espn.com/wnba/injuries) · [Live availability](https://wnba-predictions-4oai.vercel.app/#live)\n\nThis reports a source change, not a confirmed lineup or measured accuracy gain. Full forecasts rebuild daily.`,marker:'injury-'+key});
  }
 }return result;
}
async function json(url,options={}){const r=await fetch(url,{...options,signal:AbortSignal.timeout(20000)});if(!r.ok)throw Error('HTTP '+r.status+' from '+new URL(url).hostname);return r.json();}
async function notify(alert,repo,token,owner){
 const base='https://api.github.com/repos/'+repo,headers={Authorization:'Bearer '+token,Accept:'application/vnd.github+json','Content-Type':'application/json'};
 // The marker in the issue also survives a failed state-file commit or a rerun.
 for(let page=1;page<=20;page++){
  const issues=await json(base+'/issues?state=all&per_page=100&page='+page,{headers});
  if(issues.some(i=>(i.body||'').includes('<!-- wnba-alert:'+alert.marker+' -->')))return 'already-delivered';
  if(issues.length<100)break;if(page===20)throw Error('Issue deduplication limit reached; refusing duplicate alert');
 }
 const issue=await json(base+'/issues',{method:'POST',headers,body:JSON.stringify({title:alert.title,body:alert.body+'\n\n@'+owner+'\n\n<!-- wnba-alert:'+alert.marker+' -->',assignees:[owner]})});
 return issue.html_url;
}
async function main(){
 const now=new Date(),previous=read('data/cloud_monitor.json',{reports:[],delivered:[]}),repo=process.env.GITHUB_REPOSITORY,token=process.env.GITHUB_TOKEN,owner=process.env.ALERT_RECIPIENT||'chepkemboiedel-sudo';
 if(!repo||!token)throw Error('GitHub repository/token missing');
 const dry=process.argv.includes('--dry-run'),base='https://site.api.espn.com/apis/site/v2/sports/basketball/wnba';
 let current,schedule=[],error=null;
 try{
  const feed=await json(base+'/injuries?limit=1000');if(feed.status!=='success'||feed.season?.year!==now.getUTCFullYear())throw Error('Wrong-season or invalid injury feed');
  current=reports(feed);
  const day=d=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/New_York',year:'numeric',month:'2-digit',day:'2-digit'}).format(d).replaceAll('-','');
  const boards=await Promise.all([0,1].map(n=>json(base+'/scoreboard?dates='+day(new Date(+now+n*86400000))+'&limit=100')));
  schedule=boards.flatMap(b=>{if(!Array.isArray(b.events))throw Error('Invalid scoreboard');return b.events;});
 }catch(e){error=e.message;}
 const next={};for(const e of schedule){const c=e.competitions?.[0];if(c?.status?.type?.state!=='pre')continue;for(const t of c.competitors||[])if(!next[t.team.id]||Date.parse(e.date)<Date.parse(next[t.team.id].date))next[t.team.id]={id:e.id,date:e.date,name:e.name};}
 const alerts=current?changes(previous.reports,current,next,now):[];
 const evaluation=read('outputs/availability_backtest/auto_status.json',{});
 const checked=Date.parse(evaluation.last_success_at);
 if(evaluation.status!=='ok'||!Number.isFinite(checked)||+now-checked>36*3600000||checked>+now+3600000)
  error=error||'Backtest evaluation is failed, stale, or unverified; no improvement alert is permitted.';
 const policy=read('outputs/forecast.json',{}).promotion;
 if(!error && policy?.promoted && policy.season===now.getUTCFullYear() && +now-Date.parse(policy.checked_at)<=36*3600000)alerts.push({marker:'improvement-'+policy.model_version+'-'+policy.season+'-'+policy.evidence_id,
  title:'Injury adjustments passed the prospective improvement rule',body:'A fixed block of independently saved pregame predictions passed all model-selection checks.\n\n```json\n'+JSON.stringify(policy,null,2)+'\n```\n\n[Compare results and policy](https://wnba-predictions-4oai.vercel.app/#live). Evidence supports this sample; future performance and championship accuracy are not guaranteed.'});
 let failures=error?(previous.consecutive_failures||0)+1:0;
 if(failures===3)alerts.push({marker:'monitor-failed-'+(previous.failure_started_at||now.toISOString()).slice(0,10),title:'WNBA cloud monitoring needs attention',body:'Three consecutive hourly source or evaluation checks failed. Saved forecasts remain available.\n\n[Workflow](https://github.com/'+repo+'/actions/workflows/cloud-monitor.yml)\n\n'+error});
 const delivered=new Set(previous.delivered||[]),sent=[];
 for(const alert of alerts){if(delivered.has(alert.marker))continue;if(dry){sent.push({title:alert.title,dry_run:true});continue;}
  sent.push({title:alert.title,url:await notify(alert,repo,token,owner)});delivered.add(alert.marker);
 }
 if(!dry){const state={version:1,checked_at:now.toISOString(),status:error?'failed':'ok',error,reports:current||previous.reports,
  consecutive_failures:failures,failure_started_at:error?(previous.failure_started_at||now.toISOString()):null,delivered:[...delivered],last_alerts:sent};write('data/cloud_monitor.json',state);
  for(const dir of ['public','site'])write(dir+'/live_health.json',{version:1,checked_at:state.checked_at,status:state.status,error,consecutive_failures:failures,cadence:'hourly',channel:'GitHub issues assigned to '+owner});}
 console.log(JSON.stringify({dry_run:dry,source_status:error?'failed':'ok',alerts:sent,consecutive_failures:failures}));
}
module.exports={changes,notify,material};
if(require.main===module)main().catch(e=>{console.error(e.message);process.exitCode=1;});

