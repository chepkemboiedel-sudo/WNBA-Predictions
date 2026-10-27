"""Static pages and browser features for forecast history and refresh health."""
from html import escape
import json

from app_data import atomic_json, slug
import availability_ui

CSS = r"""
.app-nav{display:flex;gap:8px;flex-wrap:wrap;padding:18px 24px;margin:auto;max-width:1108px}
.app-nav a,.back-link{color:var(--ink);font-weight:700;text-decoration:none;padding:7px 12px;border-radius:8px}
.app-nav a:hover,.app-nav a:focus-visible{background:var(--card);outline:2px solid var(--west)}
.team-link{color:inherit;text-decoration:none}.team-link:hover,.team-link:focus-visible{text-decoration:underline}
.health-pill{display:inline-flex;gap:6px;align-items:center;padding:6px 11px;border-radius:99px;font-size:.8rem;font-weight:800;background:var(--line);color:var(--ink)}
.health-ok{color:var(--pos);background:color-mix(in srgb,var(--pos) 12%,var(--card))}
.health-failed,.health-overdue{color:var(--neg);background:color-mix(in srgb,var(--neg) 12%,var(--card))}
.health-grid,.profile-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:14px}
.metric-card{padding:18px;border:1px solid var(--line);border-radius:12px;background:var(--card);min-width:0}
.metric-label{font-size:.72rem;font-weight:750;color:var(--muted);text-transform:uppercase;letter-spacing:.08em}
.metric-value{font-size:1.4rem;font-weight:800;margin-top:7px;overflow-wrap:anywhere}
.metric-help{font-size:.8rem;color:var(--muted);margin-top:5px}
.feature-toolbar{display:flex;gap:16px;align-items:end;flex-wrap:wrap;margin-bottom:22px}
.feature-toolbar label{display:grid;gap:7px;font-weight:700;font-size:.85rem}
.feature-toolbar select,.feature-toolbar button{padding:11px 14px;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:8px;font:inherit;max-width:100%}
.feature-toolbar button{cursor:pointer}.feature-toolbar select:focus-visible,.feature-toolbar button:focus-visible{outline:2px solid var(--west)}
.history-chart{width:100%;height:auto;display:block;min-height:180px}.chart-shell{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin:20px 0}
.chart-key{display:flex;gap:24px;flex-wrap:wrap;color:var(--muted);font-size:.85rem}.chart-key b{display:inline-block;width:22px;height:3px;margin:0 8px 3px 0}
.team-directory{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:14px}
.team-card{padding:20px;background:var(--card);border:1px solid var(--line);border-radius:12px;text-decoration:none;color:var(--ink)}
.team-card:hover,.team-card:focus-visible{border-color:var(--west);box-shadow:var(--shadow);outline:2px solid var(--west)}
.team-card h3{font-size:1.02rem;margin:6px 0 10px}.team-card p{font-size:.84rem;margin:5px 0;color:var(--muted)}
.profile-hero{padding:35px 0}.profile-hero h1{font-size:clamp(2rem,5vw,3.3rem);letter-spacing:-.035em;line-height:1.1;margin:16px 0}
.profile-hero .lead{margin-bottom:18px}.profile-layout{display:grid;gap:22px}.game-win{font-weight:800;color:var(--pos)}.game-loss{font-weight:800;color:var(--neg)}
.feature-note{color:var(--muted);font-size:.85rem}.health-report-link{display:inline-block;margin-top:18px;color:var(--ink);font-weight:700}
.empty-chart{padding:35px;text-align:center;color:var(--muted)}
@media(max-width:760px){.hero-grid{grid-template-columns:1fr}.hero-inner{padding:30px 0}.feature-toolbar{align-items:stretch;flex-direction:column}.team-directory{grid-template-columns:1fr}.app-nav{padding:12px}.chart-shell{padding:8px}.history-chart{min-height:130px}}
"""


def navigation():
    return '<nav class="app-nav" aria-label="Main navigation"><a href="/">Forecast</a><a href="/#availability">Availability</a><a href="/#backtest">Backtest</a><a href="/#history">History</a><a href="/#teams">Teams</a><a href="/#refresh-health">Refresh health</a></nav>'


def health_section(health):
    coverage = health.get("coverage", {})
    run_url = health.get("run_url")
    return f'''<section id="refresh-health"><div class="wrap">
      <span class="eyebrow">Data you can check</span><h2>Refresh health</h2>
      <p><span class="health-pill" data-health-badge role="status">Checking refresh status</span></p>
      <p id="health-summary" class="lead">The last published forecast stays available if a refresh fails.</p>
      <div class="health-grid">
        <div class="metric-card"><div class="metric-label">Last successful refresh</div><div class="metric-value" id="health-last-success">—</div><div class="metric-help">Shown in your local time</div></div>
        <div class="metric-card"><div class="metric-label">Latest attempt</div><div class="metric-value" id="health-last-attempt">—</div><div class="metric-help">Includes reported failures</div></div>
        <div class="metric-card"><div class="metric-label">Latest completed game</div><div class="metric-value">{escape(health.get('data_through', 'Unknown'))}</div><div class="metric-help">An off day does not mean data is missing</div></div>
        <div class="metric-card"><div class="metric-label">2026 coverage</div><div class="metric-value">{coverage.get('season_games', '—')} games</div><div class="metric-help">{coverage.get('regular_games', '—')} regular season · {coverage.get('playoff_games', '—')} playoff</div></div>
      </div>
      <p class="feature-note">ESPN completed results · published forecasts are checked for consistency. A refresh is marked overdue after a two-hour scheduling grace period. Cloud start times may vary.</p>
      <a id="health-run-link" class="health-report-link" href="{escape(run_url or '#')}" {'hidden' if not run_url else ''}>View the latest cloud run ↗</a>
    </div></section>'''


def history_section(history, default_team, *, fixed=False):
    names = sorted({team["team"] for entry in history["snapshots"] for team in entry["teams"]})
    options = ''.join(f'<option value="{escape(team)}" {"selected" if team == default_team else ""}>{escape(team)}</option>' for team in names)
    controls = (f'<span id="history-fixed-team">{escape(default_team)}</span>' if fixed else
                f'<label for="history-team">Choose a team<select id="history-team">{options}</select></label>')
    return f'''<section id="history"><div class="wrap">
      <span class="eyebrow">How the outlook changes</span><h2>Forecast history</h2>
      <p class="lead">{len(history['snapshots'])} saved forecasts. New successful refreshes add observations; archived forecasts are labeled. No values are invented for days without a saved forecast.</p>
      <div class="feature-toolbar">{controls}<button id="history-download" type="button">Download team history CSV</button></div>
      <div class="profile-stats"><div class="metric-card"><div class="metric-label">Latest title probability</div><div class="metric-value" id="history-title">—</div></div>
        <div class="metric-card"><div class="metric-label">Latest Finals probability</div><div class="metric-value" id="history-finals">—</div></div>
        <div class="metric-card"><div class="metric-label">Title change</div><div class="metric-value" id="history-change">—</div><div class="metric-help">Percentage points since the previous saved forecast</div></div></div>
      <div class="chart-shell"><svg id="history-chart" class="history-chart" viewBox="0 0 800 300" role="img" aria-label="Saved championship and Finals probabilities"></svg>
        <div class="chart-key"><span><b style="background:var(--west)"></b>Win championship</span><span><b style="background:var(--east)"></b>Reach Finals</span></div></div>
      <p class="feature-note">Lines connect saved observations across gaps. Model versions and confirmed results can change between snapshots. Archived points use their data date when the save time is unknown. The chart uses a 0–100% scale.</p>
      <div class="tblwrap"><table><thead><tr><th>Forecast saved</th><th>Data through</th><th>Reach Finals</th><th>Title</th><th>Model</th></tr></thead><tbody id="history-table"></tbody></table></div>
    </div></section>'''


def team_directory(profiles):
    cards = []
    for team in profiles:
        record = team["regular"]
        seed = f'Playoff seed #{team["seed"]}' if team["seed"] else 'Outside the eight-team bracket'
        odds = f'{team["probabilities"]["champion"]:.1%} title probability' if team["probabilities"] else 'No current bracket forecast'
        cards.append(f'''<a class="team-card" href="/teams/{team['slug']}/"><span class="eyebrow">{seed}</span>
          <h3>{escape(team['team'])} ↗</h3><p>{record['wins']}–{record['losses']} regular season · {team['point_diff']:+.1f} point differential</p><p>{odds}</p></a>''')
    return f'<section id="teams"><div class="wrap"><span class="eyebrow">Explore the league</span><h2>Team detail pages</h2><p class="lead">Records, recent games, head-to-head results, and saved forecasts for all {len(profiles)} teams in the 2026 data.</p><div class="team-directory">' + ''.join(cards) + '</div></div></section>'


def team_page(team, data, css, *, script, availability=None):
    def rec(value):
        return f"{value['wins']}–{value['losses']}"

    probability = team["probabilities"]
    odds = f"{probability['champion']:.1%}" if probability else 'Not modeled'
    seed = f"Playoff seed #{team['seed']}" if team["seed"] else 'Outside the current eight-team bracket'
    metrics = [("Regular-season record", rec(team['regular'])), ("Score-only title probability", odds),
               ("Home / away record", rec(team['home']) + " / " + rec(team['away'])),
               ("Last 10 regular-season games", rec(team['last10'])),
               ("Points scored / allowed", f"{team['points_for']:.1f} / {team['points_against']:.1f}"),
               ("Point differential", f"{team['point_diff']:+.1f} per game"),
               ("Playoff record", rec(team['playoffs'])), ("Streak, including playoffs", team['streak'])]
    cards = ''.join(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>' for label, value in metrics)
    recent = ''.join(f'''<tr><td>{row['date']}</td><td><a class="team-link" href="/teams/{row['opponent_slug']}/">{escape(row['opponent'])}</a></td><td>{'Home' if row['home'] else 'Away'}</td><td>{'Playoff' if row['playoff'] else 'Regular'}</td><td class="{'game-win' if row['won'] else 'game-loss'}">{'W' if row['won'] else 'L'} {row['pf']}–{row['pa']}</td></tr>''' for row in team['recent'])
    h2h = ''.join(f'''<tr><td><a class="team-link" href="/teams/{row['slug']}/">{escape(row['team'])}</a></td><td>{row['wins']}–{row['losses']}</td><td>{row['margin']:+.1f}</td></tr>''' for row in team['head_to_head'])
    body = navigation() + f'''<header class="profile-hero"><div class="wrap"><a class="back-link" href="/#teams">← All teams</a>
      <p class="eyebrow">2026 team profile · {seed}</p><h1>{escape(team['team'])}</h1>
      <p class="lead">Results through {data['health']['data_through']}. Scoring averages and venue records use regular-season games.</p>
      <a class="team-link" href="#refresh-health" aria-label="Refresh health details"><span class="health-pill" data-health-badge role="status">Checking refresh status</span></a>
      <div class="profile-stats" style="margin-top:22px">{cards}</div></div></header>
      <section><div class="wrap"><span class="eyebrow">Latest performances</span><h2>Last 10 completed games</h2><p class="lead">Most recent first. Playoff games are labeled separately.</p>
        <div class="tblwrap"><table><thead><tr><th>Date</th><th>Opponent</th><th>Venue</th><th>Phase</th><th>Result</th></tr></thead><tbody>{recent}</tbody></table></div></div></section>'''
    body += availability_ui.roster_section(team['team'],availability or {})
    body += history_section(data['history'], team['team'], fixed=True)
    body += f'''<section><div class="wrap"><span class="eyebrow">Season matchups</span><h2>Head-to-head records</h2><p class="lead">Regular season only. Point differential is per game from {escape(team['team'])}'s perspective.</p>
      <div class="tblwrap"><table><thead><tr><th>Opponent</th><th>Record</th><th>Avg. point differential</th></tr></thead><tbody>{h2h}</tbody></table></div></div></section>'''
    body += health_section(data['health'])
    payload = {"refresh": data['refresh'], "history": data['history'], "health": data['health'], "profile": team['team']}
    serialized = json.dumps(payload, ensure_ascii=False).replace('<', '\\u003c')
    return f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{escape(team['team'])} | WNBA forecast</title><style>{css}</style></head><body>{body}<footer><div class="wrap"><a class="team-link" href="/">← Back to the WNBA forecast</a></div></footer><script>window.__WNBA__={serialized};</script><script>{script}</script></body></html>'''


JS = r"""
const APP = window.__WNBA__;
const htmlEscape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const percent = value => (value * 100).toFixed(1) + '%';
const dateOnly = value => new Date(value + 'T12:00:00Z').toLocaleDateString([], {month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
const timestamp = value => value ? new Date(value).toLocaleString([], {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : 'Not recorded';
let health = APP.health || {};
function healthState(report, now=Date.now()){
  if (report.status === 'failed') return {state:'failed',label:'Refresh failed',message:report.message};
  if (!Number.isFinite(Date.parse(report.last_success_at))) return {state:'unknown',label:'Status unavailable',message:'No successful refresh has been recorded yet.'};
  if (Number.isFinite(Date.parse(report.next_refresh_at)) && now > Date.parse(report.next_refresh_at) + 2*60*60*1000) {
    return {state:'overdue',label:'Refresh overdue',message:'The next scheduled refresh is overdue. Showing the last successful forecast; the cloud run may be delayed or missed.'};
  }
  if(report.availability && report.availability.status!=='live') return {state:'partial',label:'Partial player data',message:report.availability.message || 'Score results are current, but some player data could not be verified.'};
  return {state:'ok',label:'Refresh healthy',message:'The latest recorded forecast refresh completed successfully. Predictions include completed games through ' + report.data_through + '.'};
}
function updateHealth(report){
  if (report) health = report;
  const state = healthState(health);
  document.querySelectorAll('[data-health-badge]').forEach(el=>{el.className='health-pill health-'+state.state;el.textContent=state.label;});
  const summary=document.getElementById('health-summary'); if(summary) summary.textContent=state.message;
  for (const [id,key] of [['health-last-success','last_success_at'],['health-last-attempt','last_attempt_at']]) {
    const el=document.getElementById(id); if(el) el.textContent=timestamp(health[key]);
  }
  const link=document.getElementById('health-run-link');
  if(link){link.hidden=!health.run_url;if(health.run_url) link.href=health.run_url;}
}
function refreshClock(){
  const el=document.getElementById('updated-at'),cd=document.getElementById('countdown');
  if(el) el.textContent=timestamp(APP.refresh.last_updated);
  const seconds=Math.max(0,Math.floor((Date.parse(APP.refresh.next_refresh_at)-Date.now())/1000));
  if(cd) cd.textContent=!Number.isFinite(seconds)?'Not scheduled':seconds===0?'Awaiting next run':[Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(n=>String(n).padStart(2,'0')).join(':');
}
function selectedHistoryTeam(){const select=document.getElementById('history-team');return APP.profile || (select && select.value);}
function historyPoints(team){return (APP.history.snapshots || []).flatMap(entry=>{const row=entry.teams.find(t=>t.team===team);return row?[{...row,entry}]:[];});}
function renderHistory(){
  const chart=document.getElementById('history-chart'); if(!chart) return;
  const team=selectedHistoryTeam(),points=historyPoints(team),latest=points.at(-1),previous=points.at(-2);
  document.getElementById('history-title').textContent=latest?percent(latest.champion):'Not modeled';
  document.getElementById('history-finals').textContent=latest?percent(latest.reach_finals):'Not modeled';
  document.getElementById('history-change').textContent=previous?((latest.champion-previous.champion)>=0?'+':'')+((latest.champion-previous.champion)*100).toFixed(1)+' pp':'No earlier snapshot';
  const table=document.getElementById('history-table');
  table.innerHTML=points.slice().reverse().map(p=>'<tr><td>'+htmlEscape(p.entry.generated_at?timestamp(p.entry.generated_at):'Archived · save time unknown')+'</td><td>'+htmlEscape(p.entry.data_through)+'</td><td>'+percent(p.reach_finals)+'</td><td>'+percent(p.champion)+'</td><td>'+(p.entry.probability_model==='availability-experimental'?'Availability (experimental)':'Score-only')+'</td></tr>').join('');
  if(!points.length){chart.innerHTML='<text x="400" y="145" text-anchor="middle" fill="currentColor">No saved forecast for this team yet.</text>';table.innerHTML='<tr><td colspan="5">This team is outside the saved eight-team forecasts.</td></tr>';return;}
  const dates=points.map(p=>Date.parse(p.entry.generated_at || p.entry.data_through+'T12:00:00Z'));
  const first=Math.min(...dates),last=Math.max(...dates);
  const x=i=>last===first?420:65+(dates[i]-first)/(last-first)*700, y=p=>250-p*220;
  let svg='<title>'+htmlEscape(team)+' saved forecast history</title>';
  for(const value of [0,.25,.5,.75,1]) svg+='<line x1="65" y1="'+y(value)+'" x2="765" y2="'+y(value)+'" stroke="var(--line)"/><text x="53" y="'+(y(value)+4)+'" text-anchor="end" fill="var(--muted)" font-size="12">'+value*100+'%</text>';
  for(const [key,color] of [['reach_finals','var(--east)'],['champion','var(--west)']]){
    svg+='<polyline fill="none" stroke="'+color+'" stroke-width="3" points="'+points.map((p,i)=>x(i)+','+y(p[key])).join(' ')+'"/>';
    points.forEach((p,i)=>{svg+='<circle cx="'+x(i)+'" cy="'+y(p[key])+'" r="5" fill="'+color+'"><title>'+htmlEscape(p.entry.data_through+': '+percent(p[key]))+'</title></circle>';});
  }
  for(const index of [...new Set([0,points.length-1])]) svg+='<text x="'+x(index)+'" y="282" text-anchor="'+(index===0?'start':'end')+'" fill="var(--muted)" font-size="12">'+htmlEscape(dateOnly(points[index].entry.data_through))+'</text>';
  chart.innerHTML=svg;
}
document.getElementById('history-team')?.addEventListener('change',renderHistory);
document.getElementById('history-download')?.addEventListener('click',()=>{
  const team=selectedHistoryTeam(),points=historyPoints(team);
  const rows=[['Team','Forecast saved UTC','Data through','Reach Finals percent','Title percent'],...points.map(p=>[team,p.entry.generated_at || 'Archived date only',p.entry.data_through,(p.reach_finals*100).toFixed(3),(p.champion*100).toFixed(3)])];
  const csv=rows.map(row=>row.map(value=>'"'+String(value).replaceAll('"','""')+'"').join(',')).join('\r\n');
  const link=document.createElement('a');link.href='data:text/csv;charset=utf-8,'+encodeURIComponent(csv);link.download=team.toLowerCase().replaceAll(' ','-')+'-forecast-history.csv';link.click();
});
window.WNBAFeatures={updateHealth,healthState};
renderHistory();updateHealth();refreshClock();setInterval(refreshClock,1000);setInterval(()=>updateHealth(),60000);
"""

POLL_JS = r"""
let checkingForUpdates = false;
async function checkForUpdates(){
  if(checkingForUpdates || document.hidden) return;
  checkingForUpdates=true;
  try {
    const get=async path=>{const response=await fetch(path,{cache:'no-store'});if(!response.ok)throw new Error('Refresh check unavailable');return response.json();};
    const [meta,report]=await Promise.allSettled([get('/refresh_meta.json'),get('/refresh_health.json')]);
    if(report.status==='fulfilled') window.WNBAFeatures.updateHealth(report.value);
    if(meta.status==='fulfilled' && meta.value.last_updated && meta.value.last_updated!==window.__WNBA__.refresh.last_updated) window.location.reload();
  } catch {
    // A connection failure never replaces the forecast with empty data.
  } finally {checkingForUpdates=false;}
}
setInterval(checkForUpdates,60000);
document.addEventListener('visibilitychange',checkForUpdates);
window.addEventListener('focus',checkForUpdates);
checkForUpdates();
"""
