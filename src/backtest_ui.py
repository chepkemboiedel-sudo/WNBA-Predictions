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
    return result


def export_assets():
    for folder in ("public","site"):
        target = ROOT/folder/"backtest"
        target.mkdir(parents=True,exist_ok=True)
        for name in ("results.json","predictions.csv","REPORT.md"):
            shutil.copyfile(ROOT/"outputs/availability_backtest"/name,target/name)


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
    return f'''<section id="backtest"><div class="wrap">
      <span class="eyebrow">Evidence behind the model choice</span><h2>Score-only vs. injury-adjusted accuracy</h2>
      <p class="lead">Compare predictions made for past games using dated pregame reports and models fitted only on earlier games. Score-only remains the default; injury adjustments are experimental.</p>
      <p class="feature-note">Saved evaluation: {saved} · Games dated {result['date_range']['from']} to {result['date_range']['through']}. Current forecasts update independently of this saved test.</p>
      <div class="feature-toolbar"><label for="backtest-sample">Compare the same games<select id="backtest-sample">{options}</select></label>
        <a class="ctrl team-link" href="/backtest/predictions.csv" download>Download game-by-game CSV</a>
        <a class="team-link" href="/backtest/REPORT.md" download>Full methodology</a>
        <a class="team-link" href="/backtest/results.json" download>Results JSON</a></div>
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
      <details class="availability-notice"><summary>Coverage, method, and limits</summary>
        <p>{primary['n']} of {all_games} eligible games have explicit pregame reports for both teams. {result['report_files_verified']} of {result['report_files_requested']} report files passed validation. Coverage selects which games can be evaluated, so compare the two models within the same sample.</p>
        <p>The score-only model was trained on 2016–2025 games and evaluated on {result['test_season']}. Player effects were fitted at the start of each month using only preceding games. Only confirmed Out/Suspended statuses were used, with the existing participation discount and effect caps; no settings were tuned to these outcomes.</p>
        <p>Reports were selected at 09:00 ET for tips before 16:00 ET, otherwise 15:00 ET, at least an hour before tip. Missing or unsubmitted reports kept the baseline. An incomplete player archive disabled the affected team's adjustment in {result['incomplete_team_history_games']} covered games; {result['unmatched_out_records']} player-game Out records could not be uniquely matched and received no invented effect.</p>
        <p><strong>Only {result['groups']['playoffs']['n']} covered games were playoff games.</strong> This test does not validate series or championship probabilities. It tests the numerical adjustment with official archived reports, rather than recreating the complete historical ESPN injury and roster feed. Bootstrap intervals are approximate and do not guarantee performance in future seasons.</p>
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
  if(group.n<30) return 'Small sample: '+group.n+' games. This is too little evidence to establish an improvement.';
  const metrics=Object.values(group.metrics);
  if(metrics.every(m=>m.delta_ci95[0]<=0 && m.delta_ci95[1]>=0)) return 'No clear improvement established. All confidence intervals include no change.';
  return 'Results vary by metric. Read the changes and uncertainty intervals together; this sample does not validate championship forecasts.';
}
(function(){
  const select=document.getElementById('backtest-sample');
  if(!select) return;
  const data=window.__WNBA__.backtest;
  const text=(id,value)=>{document.getElementById(id).textContent=String(value);};
  function render(){
    const group=data.groups[select.value];
    if(!group || !group.n) return;
    text('backtest-n',group.n);text('backtest-changed',group.changed_games);
    text('backtest-picks',group.winner_changes.corrected+' / '+group.winner_changes.harmed);
    document.getElementById('backtest-metrics').innerHTML=btRows(group);
    text('backtest-finding',btFinding(group));
    for(const [suffix,key] of [['base','baseline'],['adj','adjusted']]){
      const percent=group.metrics.accuracy[key]*100;
      text('backtest-acc-'+suffix,percent.toFixed(2)+'%');
      document.getElementById('backtest-bar-'+suffix).style.width=percent.toFixed(2)+'%';
    }
    const notes={verified_report_games:'Primary comparison: both teams have verified pregame reports. Compare models within this same sample.',all_eligible_games:'Includes games with missing reports, where both models use the score-only fallback. Its overall accuracy should not be compared with the report-covered sample as if only the model changed.',changed_games:'Selected after identifying which probabilities changed. This is a diagnostic subset, not an independent validation sample.',regular_season:'Regular-season games with verified reports for both teams. These results do not validate playoff or championship odds.',playoffs:'Only '+group.n+' playoff games have both-team report coverage. This small sample cannot establish playoff or championship accuracy.'};
    text('backtest-context',notes[select.value]);
  }
  select.value='verified_report_games';
  select.addEventListener('change',render);
  render();
})();
"""
