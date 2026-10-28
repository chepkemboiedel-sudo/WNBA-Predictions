"""Display saved held-out results independently of live forecast refreshes."""
import csv
import json
from datetime import datetime
from html import escape
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = {
    "verified_report_games":"Verified pregame reports (primary comparison)",
    "all_eligible_games":"All eligible games (includes score-only fallbacks)",
    "changed_games":"Games whose probabilities changed",
    "regular_season":"Regular season with verified reports",
    "playoffs":"Playoffs with verified reports",
    "initial_study":"Frozen initial study (reference)",
    "newly_evaluated":"New historical games with verified reports",
    "prospective":"Prospective trial (recorded before tip)",
}
METRICS = {"accuracy":"Winner accuracy ↑", "log_loss":"Log-loss ↓", "brier":"Brier score ↓"}


def load_results():
    folder = ROOT/"outputs/availability_backtest"
    result = json.loads((folder/"results.json").read_text(encoding="utf-8"))
    with (folder/"predictions.csv").open(encoding="utf-8",newline="") as stream:
        dates = [row["local_date"] for row in csv.DictReader(stream)]
    if len(dates) != result["groups"]["all_eligible_games"]["n"]:
        raise ValueError("Saved backtest results and game-level coverage disagree")
    result["date_range"] = {"from":min(dates),"through":max(dates)}
    for key in ("initial_study","newly_evaluated","prospective"):
        result["groups"].setdefault(key,{"n":0})
    result["automation"]=json.loads((folder/"auto_status.json").read_text(encoding="utf-8")) if (folder/"auto_status.json").exists() else {"status":"not_started","message":"Automatic evaluation has not run yet."}
    result["progress"]=json.loads((folder/"progress.json").read_text(encoding="utf-8")) if (folder/"progress.json").exists() else {"checkpoints":[]}
    return result


def export_assets():
    for folder in ("public","site"):
        target = ROOT/folder/"backtest"
        target.mkdir(parents=True,exist_ok=True)
        for name in ("results.json","predictions.csv","REPORT.md","auto_status.json","progress.json","prospective.csv"):
            shutil.copyfile(ROOT/"outputs/availability_backtest"/name,target/name)
        for name in ("initial_results.json","initial_predictions.csv"):
            shutil.copyfile(ROOT/"data/backtests"/name,target/name)
        shutil.copyfile(ROOT/"data/backtests/prospective_predictions.json",target/"pregame_predictions.json")


def metric_rows(group):
    rows=[]
    for key,label in METRICS.items():
        m=group["metrics"][key]
        scale=100 if key=="accuracy" else 1
        values = [f"{m[v]:.2%}" if key=="accuracy" else f"{m[v]:.6f}" for v in ("baseline","adjusted")]
        digits=2 if key=="accuracy" else 6
        suffix=" pp" if key=="accuracy" else ""
        delta=f"{m['delta']*scale:+.{digits}f}{suffix}"
        lo,hi=m["delta_ci95"]
        interval=f"{lo*scale:+.{digits}f} to {hi*scale:+.{digits}f}{suffix}"
        rows.append(f'<tr><th scope="row">{label}</th><td>{values[0]}</td><td>{values[1]}</td><td>{delta}</td><td>{interval}</td></tr>')
    return ''.join(rows)


def section(result):
    primary=result["groups"]["verified_report_games"]
    all_games=result["groups"]["all_eligible_games"]["n"]
    options=''.join(f'<option value="{key}">{escape(label)} · {result["groups"][key]["n"]} games</option>' for key,label in SAMPLES.items())
    saved=datetime.fromisoformat(result["created_at"]).strftime("%b %d, %Y")
    changes=primary["winner_changes"]
    acc=primary["metrics"]["accuracy"]
    auto=result.get("automation",{})
    checked=datetime.fromisoformat(auto["last_checked_at"].replace("Z","+00:00")).strftime("%b %d, %Y %H:%M UTC") if auto.get("last_checked_at") else "Not checked"
    status="Automatic evaluation active" if auto.get("status")=="ok" else "Evaluation update failed — showing prior results" if auto.get("status")=="failed" else "Automatic evaluation not started"
    return f'''<section id="backtest"><div class="wrap">
      <span class="eyebrow">Evidence behind the model choice</span><h2>Score-only vs. injury-adjusted accuracy</h2>
      <p class="lead">Compare predictions made for past games using dated pregame reports and models fitted only on earlier games. The initial historical study has not established an injury-adjustment advantage. Automatic model selection uses the separate prospective rule.</p>
      <p class="feature-note">Evaluation results saved: {saved} · Games dated {result['date_range']['from']} to {result['date_range']['through']}. Past predictions are retained; new games are added once.</p>
      <div class="availability-notice" id="backtest-auto-status" role="status"><strong>{status}</strong><p>{escape(auto.get('message',''))}</p>
        <p class="feature-note">Daily at 7:00 a.m. Pacific · Last checked: {escape(checked)} · {auto.get('new_games_this_run',0)} new historical games this check · {auto.get('prospective_scored',0)} prospective results / {auto.get('prospective_pending',0)} pending</p></div>
      <div class="feature-toolbar"><label for="backtest-sample">Compare the same games<select id="backtest-sample">{options}</select></label>
        <a class="ctrl team-link" href="/backtest/predictions.csv" download>Download game-by-game CSV</a>
        <a class="team-link" href="/backtest/REPORT.md" download>Full methodology</a>
        <a class="team-link" href="/backtest/results.json" download>Results JSON</a>
        <a class="team-link" href="/backtest/prospective.csv" download>Prospective results CSV</a></div>
      <div class="profile-stats" aria-live="polite">
        <div class="metric-card"><div class="metric-label">Games in this comparison</div><div class="metric-value" id="backtest-n">{primary['n']}</div></div>
        <div class="metric-card"><div class="metric-label">Probabilities changed</div><div class="metric-value" id="backtest-changed">{primary['changed_games']}</div></div>
        <div class="metric-card"><div class="metric-label">Winner picks corrected / spoiled</div><div class="metric-value" id="backtest-picks">{changes['corrected']} / {changes['harmed']}</div></div>
      </div>
      <div class="backtest-bars" role="img" aria-label="Winner accuracy comparison on a zero to 100 percent scale">
        <div><span>Score-only</span><div class="backtest-track"><i id="backtest-bar-base" style="width:{acc['baseline']*100:.2f}%"></i></div><b id="backtest-acc-base">{acc['baseline']:.2%}</b></div>
        <div><span>Injury-adjusted</span><div class="backtest-track"><i class="backtest-optional" id="backtest-bar-adj" style="width:{acc['adjusted']*100:.2f}%"></i></div><b id="backtest-acc-adj">{acc['adjusted']:.2%}</b></div>
        <p class="feature-note">Both bars use the full 0–100% scale. Higher winner accuracy is better.</p>
      </div>
      <p class="availability-notice" id="backtest-finding" role="status">No clear improvement established. Both models picked the same number of winners correctly.</p>
      <div class="tblwrap"><table class="backtest-metrics"><caption>Paired comparison on the selected games; change means injury-adjusted minus score-only.</caption>
        <thead><tr><th>Metric</th><th>Score-only</th><th>Injury-adjusted</th><th>Change</th><th>95% interval for change</th></tr></thead><tbody id="backtest-metrics">{metric_rows(primary)}</tbody></table></div>
      <p class="feature-note">Lower log-loss and Brier score mean better probability predictions. Accuracy changes use percentage points (pp). An interval that includes zero is consistent with no change. Intervals use 10,000 paired bootstrap resamples of game days.</p>
      <p id="backtest-context" class="lead">The primary sample has verified reports for both teams. Games with missing reports are included only in the all-games sample, using the same score-only fallback for both models.</p>
      <div class="chart-shell"><h3>Accuracy difference over time</h3>
        <p class="feature-note">Injury-adjusted minus score-only accuracy, in percentage points. Above zero favors the injury adjustment. Each point is a cumulative evaluation checkpoint for the selected sample.</p>
        <svg id="backtest-progress" class="history-chart" viewBox="0 0 800 210" role="img" aria-label="Accuracy difference at recorded evaluation checkpoints"></svg>
        <p class="feature-note" id="backtest-progress-note">Checkpoints are added when scored evidence changes, not for unchanged daily checks.</p>
        <a class="team-link" href="/backtest/progress.json" download>Download progress checkpoints</a></div>
      <details class="availability-notice"><summary>Coverage, method, and limits</summary>
        <p>{primary['n']} of {all_games} eligible games have explicit pregame reports for both teams. {result['report_files_verified']} of {result['report_files_requested']} report files passed validation. Coverage selects which games can be evaluated, so compare the two models within the same sample.</p>
        <p>The score-only model was trained on 2016–2025 games and evaluated on {result['test_season']}. Player effects were fitted at the start of each month using only preceding games. Only confirmed Out/Suspended statuses were used, with the existing participation discount and effect caps; no settings were tuned to these outcomes.</p>
        <p>Reports were selected at 09:00 ET for tips before 16:00 ET, otherwise 15:00 ET, at least an hour before tip. Missing or unsubmitted reports kept the baseline. An incomplete player archive disabled the affected team's adjustment in {result['incomplete_team_history_games']} covered games; {result['unmatched_out_records']} player-game Out records could not be uniquely matched and received no invented effect.</p>
        <p><strong>Only {result['groups']['playoffs']['n']} covered games were playoff games.</strong> This test does not validate series or championship probabilities. It tests the numerical adjustment with official archived reports, rather than recreating the complete historical ESPN injury and roster feed. Bootstrap intervals are approximate and do not guarantee performance in future seasons.</p>
        <p><strong>Historical and prospective evidence stay separate.</strong> Existing historical rows are frozen. Newly evaluated historical games use archived pregame reports and monthly past-only fitting, but are evaluated after the game. The prospective trial records paired production game probabilities 5 minutes to 24 hours before scheduled tip, using a verified player snapshot fetched within two hours. It retains the original model hash and roster/injury evidence. Only recorded predictions are scored when the matching game finishes; missed captures are never backfilled.</p>
        <p>The prospective trial uses fixed regular-season form, while the historical test uses pregame running form. Daily sampling can miss early games or late injury updates. New cohorts start empty. Progress checkpoints are cumulative, not independent tests; repeated viewing does not establish significance or automatically enable injuries.</p>
        <p><a class="team-link" href="/backtest/initial_predictions.csv" download>Download the frozen initial study</a> · <a class="team-link" href="/backtest/pregame_predictions.json" download>Download the pregame prediction journal</a>. If an evaluation update fails, the last successful comparison stays available.</p>
        <p><a class="team-link" href="https://www.wnba.com/wnba-injury-report">Official WNBA injury-report source ↗</a>. Exact report URLs, prediction pairs, and model cutoffs are included in the downloadable game-level CSV.</p>
      </details></div></section>'''


CSS = r"""
.backtest-bars{margin:24px 0;padding:20px;background:var(--card);border:1px solid var(--line);border-radius:12px}
.backtest-bars>div{display:grid;grid-template-columns:145px minmax(60px,1fr) 75px;gap:14px;align-items:center;margin:15px 0;font-size:.9rem}.backtest-bars b{text-align:right}
.backtest-track{height:15px;border-radius:8px;background:var(--line);overflow:hidden}.backtest-track i{display:block;height:100%;background:var(--ink);border-radius:8px}.backtest-track .backtest-optional{background:var(--west)}
.backtest-metrics caption{padding:14px 16px;text-align:left;color:var(--muted);font-size:.85rem}.backtest-metrics th[scope=row]{text-align:left;font-size:.85rem;letter-spacing:0;text-transform:none;color:var(--ink)}
@media(max-width:520px){.backtest-bars{padding:12px}.backtest-bars>div{grid-template-columns:95px minmax(40px,1fr) 64px;gap:8px;font-size:.8rem}}
"""


JS = r"""
function btRows(group){
  return [['accuracy','Winner accuracy ↑'],['log_loss','Log-loss ↓'],['brier','Brier score ↓']].map(([key,label])=>{
    const m=group.metrics[key],accuracy=key==='accuracy',scale=accuracy?100:1,digits=accuracy?2:6,suffix=accuracy?' pp':'';
    const number=value=>(value*scale).toFixed(digits);
    const signed=value=>(value>=0?'+':'')+number(value);
    return '<tr><th scope="row">'+label+'</th><td>'+number(m.baseline)+(accuracy?'%':'')+'</td><td>'+number(m.adjusted)+(accuracy?'%':'')+'</td><td>'+signed(m.delta)+suffix+'</td><td>'+signed(m.delta_ci95[0])+' to '+signed(m.delta_ci95[1])+suffix+'</td></tr>';
  }).join('');
}
function btFinding(group){
  if(!group.n) return 'No completed games in this cohort yet. Waiting for new evidence; no result is inferred.';
  if(group.n<30) return 'Small sample: '+group.n+' games. This is too little evidence to establish an improvement.';
  const metrics=Object.values(group.metrics);
  if(metrics.every(m=>m.delta_ci95[0]<=0 && m.delta_ci95[1]>=0)) return 'No clear improvement established. All confidence intervals include no change.';
  return 'Results vary by metric. Read the changes and uncertainty intervals together; this sample does not validate championship forecasts.';
}
function btTrend(progress,key){
  const points=(progress.checkpoints||[]).filter(p=>p.groups[key]?.n>0).map(p=>({at:p.at,n:p.groups[key].n,value:p.groups[key].accuracy_delta*100}));
  if(!points.length) return '<text x="400" y="105" text-anchor="middle" fill="currentColor">Awaiting scored games for this cohort.</text>';
  const low=Math.min(-1,...points.map(p=>p.value)),high=Math.max(1,...points.map(p=>p.value));
  const start=Date.parse(points[0].at),end=Date.parse(points[points.length-1].at);
  const x=p=>end===start?425:65+(Date.parse(p.at)-start)/(end-start)*680;
  const y=v=>155-(v-low)/(high-low)*125;
  const label=p=>new Date(p.at).toISOString().slice(0,10);
  return '<line x1="65" x2="745" y1="'+y(0)+'" y2="'+y(0)+'" stroke="currentColor" stroke-dasharray="5 5" opacity=".4"/>'+
    '<text x="55" y="'+(y(high)+4)+'" text-anchor="end" fill="currentColor">+'+high.toFixed(2)+'</text><text x="55" y="'+(y(low)+4)+'" text-anchor="end" fill="currentColor">'+low.toFixed(2)+'</text>'+
    (points.length>1?'<polyline points="'+points.map(p=>x(p)+','+y(p.value)).join(' ')+'" fill="none" stroke="var(--west)" stroke-width="3"/>':'')+
    points.map(p=>'<circle cx="'+x(p)+'" cy="'+y(p.value)+'" r="5" fill="var(--west)"><title>'+label(p)+' · '+p.n+' games · '+p.value.toFixed(2)+' pp</title></circle>').join('')+
    '<text x="65" y="190" fill="currentColor">'+label(points[0])+'</text>'+(points.length>1?'<text x="745" y="190" text-anchor="end" fill="currentColor">'+label(points[points.length-1])+'</text>':'');
}
(function(){
  const select=document.getElementById('backtest-sample');
  if(!select) return;
  const data=window.__WNBA__.backtest;
  const text=(id,value)=>{document.getElementById(id).textContent=String(value);};
  function render(){
    const group=data.groups[select.value];
    if(!group) return;
    text('backtest-n',group.n);text('backtest-changed',group.changed_games||0);
    text('backtest-picks',group.n?group.winner_changes.corrected+' / '+group.winner_changes.harmed:'—');
    document.getElementById('backtest-metrics').innerHTML=group.n?btRows(group):'<tr><td colspan="5">No completed games in this cohort yet.</td></tr>';
    text('backtest-finding',btFinding(group));
    for(const [suffix,key] of [['base','baseline'],['adj','adjusted']]){
      const percent=group.n?group.metrics.accuracy[key]*100:0;
      text('backtest-acc-'+suffix,group.n?percent.toFixed(2)+'%':'—');
      document.getElementById('backtest-bar-'+suffix).style.width=percent.toFixed(2)+'%';
    }
    const notes={verified_report_games:'Primary historical comparison: both teams have verified pregame reports. Includes the original study and newly evaluated games; compare models within this same sample.',all_eligible_games:'Includes games with missing reports, where both models use the score-only fallback. Its overall accuracy should not be compared with the report-covered sample as if only the model changed.',changed_games:'Selected after identifying which probabilities changed. This is a diagnostic subset, not an independent validation sample.',regular_season:'Regular-season games with verified reports for both teams. These results do not validate playoff or championship odds.',playoffs:'Only '+group.n+' playoff games have both-team report coverage. This small sample cannot establish playoff or championship accuracy.',initial_study:'Frozen reference: the initial study is preserved and never rewritten by daily checks.',newly_evaluated:'Historical walk-forward results for new games since monitoring began, with verified archived reports. These predictions were reconstructed after the game, so they are separate from the prospective trial.',prospective:'Only paired predictions actually recorded before tip-off are scored here. No missing pregame prediction is filled in afterward. This production trial remains separate from the historical study.'};
    text('backtest-context',notes[select.value]);
    document.getElementById('backtest-progress').innerHTML=btTrend(data.progress||{},select.value);
    const count=(data.progress?.checkpoints||[]).filter(p=>p.groups[select.value]?.n>0).length;
    text('backtest-progress-note',count===1?'One starting checkpoint. A trend will appear as new scored evidence arrives.':count?count+' checkpoints. Lines connect saved cumulative results; unchanged daily checks add no observations.':'No scored evidence yet for this cohort.');
  }
  select.value='verified_report_games';
  select.addEventListener('change',render);
  render();
})();
"""

