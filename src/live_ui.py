"""Near-live availability, projected rotations, and explicit injury scenarios."""
import json
from html import escape


def section(snapshot, forecast):
    teams=snapshot.get("teams",{})
    options=''.join(f'<option value="{escape(name)}">{escape(name)}</option>' for name in sorted(teams))
    policy=forecast.get("promotion",{})
    return f'''<section id="live"><div class="wrap"><span class="eyebrow">Between daily forecasts</span><h2>Live availability &amp; game context</h2>
      <p class="lead">Checks ESPN every minute while this page is visible. Cloud injury checks run hourly; full forecasts rebuild daily. Source reports can arrive late.</p>
      <p id="live-status" role="status">Checking live feeds…</p><div class="controls"><label class="ctrl">Team <select id="live-team">{options}</select></label>
      <label class="ctrl">Game <select id="live-game"><option value="">Today's scoreboard</option></select></label><button class="btn" id="live-retry">Refresh now</button></div>
      <div id="live-content" aria-live="polite"></div>
      <details class="availability-notice"><summary>Mid-game injury scenario (experimental)</summary><p>Select a player assumed unable to return. This estimates only lost remaining point-margin contribution, using the saved participation effect and current game clock. It is not a calibrated live win probability. No absence is inferred from minutes played.</p>
      <label class="ctrl">Player assumed out <select id="live-scenario"></select></label><p id="live-scenario-result"></p></details>
      <div class="availability-notice"><strong>Automatic model selection: {escape(forecast.get('probability_model','score-only'))}</strong><p>{escape(policy.get('reason','Collecting prospective evidence.'))} {policy.get('eligible_games',0)}/100 games in the current evidence stream.</p>
      <p>Only untouched predictions saved 5 minutes–24 hours before tip can qualify. Fixed, disjoint blocks need 100 games, 30 distinct game days, 30 changed forecasts, at least one percentage point higher winner accuracy, and improvement on probability scores and paired winner testing. Error allowances shrink at each checkpoint. Historical results cannot switch the default; new model versions start fresh.</p>
      <a class="team-link" href="/operations.json">Download model policy, coverage, and title evaluation ↗</a></div>
      <p class="feature-note" id="title-evidence">Championship validation is being collected separately: one first pre-playoff forecast per season, settled after the champion is known. Current Finals snapshots cannot establish independent season-level accuracy.</p>
      <p class="feature-note" id="cloud-monitor-health">Checking hourly cloud monitor health…</p>
      <p class="feature-note">Future seasons roll over when at least eight teams each have three completed regular-season games. {escape(forecast.get('season_context',{}).get('message',''))}</p>
      <p class="feature-note">Cloud alerts create GitHub issues assigned to chepkemboiedel-sudo for material upcoming injury changes or a qualifying prospective improvement. GitHub notification preferences control email and push delivery.</p>
      </div></section>'''


def payload(snapshot):
    return json.dumps({"teams":snapshot.get("teams",{}),"next_games":snapshot.get("next_games",{}),"fetched_at":snapshot.get("fetched_at")},ensure_ascii=False).replace('<','\\u003c')


JS=r"""
(()=>{
const root=document.getElementById('live-content');if(!root)return;
const ctx=window.__PLAYER_CONTEXT__,team=document.getElementById('live-team'),games=document.getElementById('live-game');
const status=document.getElementById('live-status'),scenario=document.getElementById('live-scenario');let live=null,busy=false;
const el=(tag,text)=>{const n=document.createElement(tag);n.textContent=text;return n;};
function render(){
 root.replaceChildren();const saved=ctx.teams[team.value]||{},feed=(live?.injuries||[]).find(t=>t.id===saved.id);
 const rotation=saved.rotation||{};root.append(el('h3','Projected rotation · recent usage'));
 root.append(el('p',(rotation.players||[]).map(p=>p.name+' ('+p.recent_minutes+' recent MPG)').join(' · ')||'Recent rotation unavailable.'));
 root.append(el('p',rotation.note||'Starting lineup unconfirmed.'));
 const group=feed?.players;root.append(el('h3','Current source reports'));
 if(!group?.length)root.append(el('p',live?'No report listed for this team. Availability and starting lineup remain unconfirmed.':'Live source unavailable. Use the dated roster snapshot on the team page.'));
 (group||[]).forEach(p=>root.append(el('p',p.name+' — '+p.status+' · '+(p.date||'Timestamp missing')+' · '+(p.comment||p.detail||'No detail'))));
 const selected=live?.selected;
 if(selected){root.append(el('h3',selected.name||'Selected game'));root.append(el('p',(selected.detail||'Status unconfirmed')+' · '+selected.teams.map(t=>t.name+' '+(t.score??'')).join(' / ')));
  const lineup=selected.lineups?.find(t=>t.team===team.value),starters=lineup?.players.filter(p=>p.starter)||[];
  root.append(el('p',starters.length===5?'Source-listed starters: '+starters.map(p=>p.name).join(', '):'Confirmed starting lineup unavailable.'));
  if(selected.state==='in')root.append(el('p','Live minutes: '+(lineup?.players||[]).map(p=>p.name+' '+(p.minutes??'—')).join(' · ')));
 }
 const old=scenario.value;scenario.replaceChildren(el('option','Choose a player'));scenario.options[0].value='';
 (saved.players||[]).forEach(p=>{const o=el('option',p.name);o.value=p.id;scenario.append(o);});scenario.value=old;renderScenario();
}
function renderScenario(){
 const saved=ctx.teams[team.value]||{},p=(saved.players||[]).find(p=>p.id===scenario.value),g=live?.selected;
 let message='Select an in-progress game and a player.';
 if(p&&g?.state==='in'){
  const m=/^(\d{1,2}):(\d{2})$/.exec(g.clock||''),quarter=Number(g.period);
  if(!m||!Number.isInteger(quarter)||quarter<1||quarter>4||Number(m[1])>10||Number(m[2])>59)message='Remaining regulation time cannot be verified; no scenario estimate.';
  else if(!saved.adjustment_ready||!p.effect_points||Date.now()-Date.parse(ctx.fetched_at)>36*3600000)message='A fresh, usable player effect is unavailable; no invented estimate.';
  else {const left=(4-quarter)*10+Number(m[1])+Number(m[2])/60;const loss=p.effect_points*(p.baseline_participation||0)*Math.min(40,left)/40;
   message=p.name+' assumed unable to return: −'+loss.toFixed(2)+' points of remaining regulation margin in this illustrative scenario. Saved player model: '+new Date(ctx.fetched_at).toLocaleString()+'. Published pregame forecasts stay unchanged.';}
 }
 document.getElementById('live-scenario-result').textContent=message;
}
function updateOptions(){
 const before=games.value,seen=new Set();const items=[...(live?.games||[]),...Object.values(ctx.next_games||{}).map(e=>({id:e.event_id,name:e.opponent+' · '+e.date}))];
 games.replaceChildren(el('option',"Today's scoreboard"));games.options[0].value='';items.forEach(g=>{if(seen.has(g.id))return;seen.add(g.id);const o=el('option',g.name||g.id);o.value=g.id;games.append(o);});games.value=before;
}
async function poll(){if(busy||document.hidden)return;busy=true;
 try{const r=await fetch('/api/live'+(games.value?'?event='+encodeURIComponent(games.value):''),{cache:'no-store'});if(!r.ok)throw Error();live=await r.json();
 status.textContent='Live feed checked '+new Date(live.fetched_at).toLocaleString()+'. Full prediction refresh is separate.';updateOptions();render();}
 catch{live=null;status.textContent='Live feed unavailable. Showing saved rotation; current injury status is unconfirmed.';render();}finally{busy=false;}}
async function health(){try{const r=await fetch('/live_health.json',{cache:'no-store'});if(!r.ok)throw Error();const h=await r.json();const stale=Date.now()-Date.parse(h.checked_at)>3*3600000;document.getElementById('cloud-monitor-health').textContent='Hourly cloud monitor: '+(stale?'overdue':h.status)+' · last check '+new Date(h.checked_at).toLocaleString()+'. Alerts use GitHub notifications.';}catch{document.getElementById('cloud-monitor-health').textContent='Hourly cloud monitor status not available yet; no successful check is confirmed.';}}
 team.addEventListener('change',render);games.addEventListener('change',poll);scenario.addEventListener('change',renderScenario);document.getElementById('live-retry').addEventListener('click',poll);
 document.addEventListener('visibilitychange',()=>{if(!document.hidden){poll();health();}});updateOptions();render();poll();health();setInterval(()=>{if(!document.hidden){poll();health();}},60000);
})();
"""

