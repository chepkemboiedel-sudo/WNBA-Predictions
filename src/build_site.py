"""Generate a self-contained, Artifact-ready index.html for the WNBA forecast,
including an interactive, client-side bracket driven by the model's real
pairwise win-probability matrix."""
import base64, json, os, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "site"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd, joblib
import simulate as S
import app_features as UI
import availability as AV
import availability_ui as AVUI
import backtest_ui as BT
import live_ui as LIVE
import operations
from seasons import forecast_season
from app_data import append_snapshot, atomic_json, load_history, snapshot, slug, successful_health, team_profiles

def b64(p):
    with open(ROOT / "outputs" / p, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()

shap_img = b64("shap_summary.png")
calib_img = b64("calibration.png")

# --- export the model's pairwise probability matrix for client-side sim ----- #
games = pd.read_csv(ROOT / "data" / "all_games.csv", parse_dates=["date"])
season = forecast_season(games)
standings = S.compute_standings(games)
seeds = S.playoff_seeds(games)
model = joblib.load(ROOT / "data" / "models.joblib")["logistic"]
feats = S.current_team_features(games, seeds)
player_snapshot = AV.load_snapshot()
if player_snapshot.get("season") != season:
    player_snapshot = dict(player_snapshot,apply_adjustments=False,
                           message="Player feed season differs from the displayed forecast; adjustments disabled.")
Pmat = S.build_prob_matrix(model, feats, seeds, player_snapshot)
baseline_matrix = S.build_prob_matrix(model, feats, seeds)
PROB = {f"{x}|{y}|{1 if h else 0}": round(Pmat[(x, y, h)], 5)
        for key in Pmat if len(key)==3 for x,y,h in [key]}
BASE_PROB = {f"{x}|{y}|{1 if h else 0}":round(value,5) for (x,y,h),value in baseline_matrix.items()}
NEXT_PROB = {f"{key[0]}|{key[1]}|{1 if key[2] else 0}":round(value,5) for key,value in Pmat.items() if len(key)==4}
DATA = {"seeds": seeds, "conf": {t: S.CONFERENCE.get(t,"Unknown") for t in seeds}, "prob": BASE_PROB,
        "prob_base":BASE_PROB,"prob_availability":PROB,"prob_next":NEXT_PROB,
        "default_model":"score-only",
        "availability":{key:player_snapshot.get(key) for key in ("status","fetched_at","apply_adjustments","message","model","boxscore_coverage")}}
# All displayed figures come from the same run as the interactive probability matrix.
forecast = json.loads((ROOT / "outputs" / "forecast.json").read_text(encoding="utf-8"))
results = pd.read_csv(ROOT / "outputs" / "finals_probabilities.csv")
DATA["default_model"] = forecast["probability_model"]
DATA["prob"] = PROB if forecast["injury_adjustment_default"] else BASE_PROB
operations.update(ROOT,games,results,forecast,player_snapshot)
DATA["published_baseline"] = {"reach":dict(zip(results.team,results.p_reach_finals*100)),
                              "champ":dict(zip(results.team,results.p_champion*100))}
teams = [(r.team, r.seed, r.conference, r.win_pct,
          r.p_reach_finals * 100, r.p_champion * 100)
         for r in results.itertuples()]
matchups = [(m["teams"][0], m["teams"][1], m["probability"] * 100)
            for m in forecast["top_matchups"]]
odds = pd.read_csv(ROOT / "data" / "market_odds.csv")
comparison = results.merge(odds[["team", "market_novig"]], on="team", how="left")
market = [(r.team, r.p_champion * 100, r.market_novig * 100)
          for r in comparison.sort_values("p_champion", ascending=False).itertuples()
          if pd.notna(r.market_novig)]
REACH_SCALE = max(50.0, results.p_reach_finals.max() * 100)
CHAMP_SCALE = max(30.0, results.p_champion.max() * 100,
                  odds.market_novig.max() * 100)
DATA["reach_scale"] = REACH_SCALE
DATA["observed"] = forecast["observed_series"]
DATA["refresh"] = globals().get("REFRESH_META") or json.loads(
    (ROOT / "public" / "refresh_meta.json").read_text(encoding="utf-8"))
history_path = ROOT / "data" / "forecast_history.json"
DATA["history"] = append_snapshot(load_history(history_path), snapshot(results, forecast, DATA["refresh"]))
DATA["health"] = successful_health(games, forecast, DATA["refresh"])
DATA["backtest"] = BT.load_results()
BT.export_assets()
profiles = team_profiles(games, results, seeds, season=season)
data_json = json.dumps(DATA, ensure_ascii=False).replace("<", "\\u003c")
favorite = results.loc[results.p_champion.idxmax()]
data_date = datetime.strptime(forecast["data_through"], "%Y-%m-%d").strftime("%b %d, %Y")
conf = forecast["conferences"]
metrics = pd.read_csv(ROOT / "outputs" / "validation_metrics.csv")
metrics_html = "".join(
    f'<tr><td>{r.model}</td><td>{r.log_loss:.3f}</td><td>{r.brier:.3f}</td>'
    f'<td>{r.accuracy:.1%}</td></tr>' for r in metrics.itertuples())
playoff_status = f"{forecast['completed_playoff_games']} completed playoff games included."
if matchups[0][2] == 100:
    finalists = sorted(matchups[0][:2], key=seeds.index)
    score = DATA["observed"].get("|".join(finalists), {"hw": 0, "lw": 0})
    lead, trail = (finalists if score["hw"] >= score["lw"] else finalists[::-1])
    wins, losses = sorted((score["hw"], score["lw"]), reverse=True)
    playoff_status = (f"{lead} won the Finals {wins}–{losses}." if wins >= 4 else
                      f"Finals: {lead} and {trail} tied {wins}–{losses}." if wins == losses else
                      f"Finals: {lead} leads {trail} {wins}–{losses}.")
market_meta_path = ROOT / "data" / "market_meta.json"
market_meta = json.loads(market_meta_path.read_text(encoding="utf-8")) if market_meta_path.exists() else {}
market_note = (
    "Market odds retrieved during this refresh. Differences reflect information the score-only model cannot see."
    if market_meta.get("status") == "live" else
    "Live championship futures were unavailable. Market bars show a cached snapshot and may be out of date; model predictions use the refreshed game results."
)
if forecast["completed_playoff_games"] and (
    (comparison.p_champion == 0) & (comparison.market_novig > 0)
).any():
    market_note = "ESPN returned a futures snapshot that still assigns odds to eliminated teams. These market odds appear stale and are shown for historical reference only. The model uses the latest completed playoff games."
def cc(c): return "west" if c == "West" else "east"

rows = []
for i, (t, s, c, wp, rf, ch) in enumerate(teams):
    rows.append(f'''
      <div class="row" data-team="{t}" style="--i:{i}">
        <div class="teamcell">
          <span class="seed">{s}</span><a class="tname team-link" href="/teams/{slug(t)}/">{t} ↗</a>
          <span class="dot {cc(c)}"></span><span class="conf">{c}</span>
        </div>
        <div class="track">
          <div class="grid25"></div><div class="grid50"></div>
          <div class="bar reach {cc(c)}" style="--w:{min(rf/REACH_SCALE*100,100):.1f}%"></div>
          <div class="bar champ {cc(c)}" style="--w:{min(ch/REACH_SCALE*100,100):.1f}%"></div>
          <span class="val"><b>{rf:.0f}%</b><em>reach</em></span>
        </div>
        <div class="champcell"><b>{ch:.0f}%</b><span>title</span></div>
      </div>''')
rows_html = "".join(rows)

mm = []
for j, (a, b, p) in enumerate(matchups):
    top = " top" if j == 0 else ""
    mm.append(f'''<li class="mrow{top}"><span class="mteams">{a} <i>vs</i> {b}</span>
        <span class="mbarwrap"><span class="mbar" style="--w:{p/max(m[2] for m in matchups)*100:.0f}%"></span></span>
        <span class="mpct">{p:.1f}%</span></li>''')
matchups_html = "".join(mm)

vv = []
for t, mod, mk in market:
    diff = mod - mk
    sign = "pos" if diff > 0 else "neg"
    hl = " highlight" if t == "Golden State Valkyries" else ""
    vv.append(f'''<div class="vvrow{hl}"><span class="vvname">{t}</span>
        <span class="vvbars">
          <span class="vvbar model" style="--w:{mod/CHAMP_SCALE*100:.0f}%"><em>{mod:.0f}</em></span>
          <span class="vvbar market" style="--w:{mk/CHAMP_SCALE*100:.0f}%"><em>{mk:.0f}</em></span>
        </span><span class="vvdiff {sign}">{diff:+.0f}</span></div>''')
vv_html = "".join(vv)

# --- bracket scaffold (populated by JS) ------------------------------------ #
def match_card(node, pos):
    return f'''<div class="match {pos}" id="m-{node}">
      <div class="slot tbd" data-slot="0"><span class="s"></span><span class="t">—</span><span class="w"></span></div>
      <div class="slot tbd" data-slot="1"><span class="s"></span><span class="t">—</span><span class="w"></span></div>
      <button class="play" data-node="{node}" disabled>Play series</button>
    </div>'''
bracket_html = (
    match_card("r1-0", "pos-r1-0") + match_card("r1-1", "pos-r1-1") +
    match_card("r1-2", "pos-r1-2") + match_card("r1-3", "pos-r1-3") +
    match_card("semi-0", "pos-semi-0") + match_card("semi-1", "pos-semi-1") +
    match_card("finals", "pos-finals") +
    '''<div class="champ-card pos-champ" id="champ-card">
        <span class="lbl">Champion</span>
        <div class="trophy">🏆</div><div class="cname">—</div></div>'''
)

CSS = r"""
:root{
  --bg:#E9EDF2;--ink:#14213A;--muted:#5B6577;--card:#FFFFFF;--line:#D5DBE4;
  --west:#DD5F26;--west-soft:#f0c3ab;--east:#1B7E8B;--east-soft:#aed7dc;
  --pos:#2E8B63;--neg:#C2415B;--hair:rgba(20,33,58,.08);
  --shadow:0 1px 2px rgba(20,33,58,.06),0 8px 30px rgba(20,33,58,.07);
  --maxw:1060px;--sans:-apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,Roboto,Arial,sans-serif;
}
@media (prefers-color-scheme:dark){
  :root{--bg:#0D131F;--ink:#EAF0F8;--muted:#93A0B4;--card:#161E2C;--line:#273247;
    --west:#F0763B;--west-soft:#5a3421;--east:#37B0BE;--east-soft:#1c4249;
    --pos:#48B983;--neg:#E36080;--hair:rgba(255,255,255,.07);
    --shadow:0 1px 2px rgba(0,0,0,.3),0 10px 34px rgba(0,0,0,.35);}
}
:root[data-theme="dark"]{--bg:#0D131F;--ink:#EAF0F8;--muted:#93A0B4;--card:#161E2C;--line:#273247;
  --west:#F0763B;--west-soft:#5a3421;--east:#37B0BE;--east-soft:#1c4249;--pos:#48B983;--neg:#E36080;
  --hair:rgba(255,255,255,.07);--shadow:0 1px 2px rgba(0,0,0,.3),0 10px 34px rgba(0,0,0,.35);}
:root[data-theme="light"]{--bg:#E9EDF2;--ink:#14213A;--muted:#5B6577;--card:#FFFFFF;--line:#D5DBE4;
  --west:#DD5F26;--west-soft:#f0c3ab;--east:#1B7E8B;--east-soft:#aed7dc;--pos:#2E8B63;--neg:#C2415B;
  --hair:rgba(20,33,58,.08);--shadow:0 1px 2px rgba(20,33,58,.06),0 8px 30px rgba(20,33,58,.07);}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);line-height:1.6;
  -webkit-font-smoothing:antialiased;font-variant-numeric:tabular-nums}
.wrap{max-width:var(--maxw);margin:0 auto;padding:0 24px}
section{padding:56px 0;border-top:1px solid var(--hair)}
h2{font-size:clamp(1.35rem,3.2vw,1.9rem);font-weight:800;letter-spacing:-.02em;margin:0 0 6px;text-wrap:balance}
.eyebrow{font-size:.72rem;font-weight:700;letter-spacing:.18em;text-transform:uppercase;color:var(--west)}
.lead{color:var(--muted);max-width:62ch;margin:.2rem 0 28px}
b,strong{font-weight:800}
.hero{position:relative;overflow:hidden;border-top:none;
  background:linear-gradient(180deg,color-mix(in srgb,var(--card) 70%,var(--bg)),var(--bg))}
.hero .court{position:absolute;inset:0;pointer-events:none;opacity:.5}
.hero .court::before{content:"";position:absolute;right:-160px;top:50%;transform:translateY(-50%);
  width:520px;height:520px;border-radius:50%;border:2px solid var(--hair)}
.hero .court::after{content:"";position:absolute;right:-360px;top:50%;transform:translateY(-50%);
  width:360px;height:520px;border:2px solid var(--hair);border-radius:0 260px 260px 0}
.hero-inner{position:relative;padding:72px 0 60px}
.hero-grid{display:grid;grid-template-columns:1.25fr .75fr;gap:22px;align-items:start}
.hero h1{font-size:clamp(2rem,5.2vw,3.2rem);font-weight:800;letter-spacing:-.03em;line-height:1.05;
  margin:.5rem 0 0;max-width:16ch;text-wrap:balance}
.hero-copy,.status-card{background:color-mix(in srgb,var(--card) 82%,transparent);border:1px solid var(--line);border-radius:18px;box-shadow:var(--shadow)}
.hero-copy{padding:22px 24px}
.status-card{padding:18px 20px}
.status-card .label{font-size:.68rem;font-weight:800;letter-spacing:.14em;color:var(--muted);text-transform:uppercase}
.status-card .big{font-size:1.6rem;font-weight:800;letter-spacing:-.03em;margin-top:6px}
.status-card .meta{display:grid;gap:10px;margin-top:16px}
.status-card .meta div{display:flex;justify-content:space-between;gap:12px;padding-top:10px;border-top:1px solid var(--hair)}
.status-card .meta div:first-child{border-top:none;padding-top:0}
.status-card .meta span{color:var(--muted)}
.pickcard{display:flex;flex-wrap:wrap;align-items:flex-end;gap:8px 40px;padding:26px 30px;
  background:var(--card);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow);max-width:640px}
.pickcard .big{font-size:clamp(3.4rem,11vw,5.6rem);font-weight:800;line-height:.9;letter-spacing:-.04em;color:var(--west)}
.pickcard .who{font-size:1.5rem;font-weight:800;letter-spacing:-.02em}
.pickcard .sub{color:var(--muted);font-size:.95rem}
.pickcard .lbl{font-size:.7rem;letter-spacing:.16em;text-transform:uppercase;color:var(--muted);display:block;margin-bottom:2px}
.hero .foot{margin-top:16px;color:var(--muted);font-size:.85rem;max-width:60ch}
.refresh-badge{margin-top:18px;display:flex;flex-wrap:wrap;gap:10px;align-items:center;padding:10px 14px;border:1px solid var(--line);background:var(--card);border-radius:999px;box-shadow:var(--shadow);max-width:760px}
.live-dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:var(--pos);box-shadow:0 0 0 6px color-mix(in srgb,var(--pos) 20%,transparent);margin-right:4px}
.refresh-label{font-size:.72rem;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.refresh-item{display:inline-flex;align-items:center;gap:6px;font-size:.84rem;color:var(--ink);font-weight:700}
.refresh-item span{color:var(--muted);font-weight:600}
.summary-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px;margin:20px 0 18px}
.summary-card,.section-card{background:var(--card);border:1px solid var(--line);border-radius:14px;box-shadow:var(--shadow)}
.summary-card{padding:16px 18px}
.summary-card .label{font-size:.66rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:800}
.summary-card .value{font-size:1.1rem;font-weight:800;letter-spacing:-.02em;margin-top:8px}
.summary-card .sub{font-size:.82rem;color:var(--muted);margin-top:4px}
.mvp-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin:0 0 24px}
.mvp-card{display:flex;flex-direction:column;gap:4px;padding:12px 14px;background:var(--card);border:1px solid var(--line);border-radius:12px;box-shadow:var(--shadow)}
.mvp-card .team{font-size:.68rem;letter-spacing:.14em;text-transform:uppercase;color:var(--muted);font-weight:800}
.mvp-card .player{font-size:.96rem;font-weight:800;letter-spacing:-.02em}
.section-card{padding:18px}
.board{display:flex;flex-direction:column;gap:2px;background:var(--card);border:1px solid var(--line);
  border-radius:14px;overflow:hidden;box-shadow:var(--shadow)}
.row{display:grid;grid-template-columns:minmax(180px,1fr) 2.2fr auto;align-items:center;gap:18px;padding:13px 20px}
.row+.row{border-top:1px solid var(--hair)}
.row:hover{background:color-mix(in srgb,var(--west) 5%,transparent)}
.teamcell{display:flex;align-items:center;gap:9px;min-width:0}
.seed{flex:none;width:22px;height:22px;border-radius:6px;background:var(--ink);color:var(--bg);
  font-size:.72rem;font-weight:800;display:grid;place-items:center}
.tname{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.dot{width:8px;height:8px;border-radius:50%;flex:none;margin-left:2px}
.dot.west{background:var(--west)}.dot.east{background:var(--east)}
.conf{font-size:.7rem;color:var(--muted);letter-spacing:.04em}
.track{position:relative;height:26px;background:color-mix(in srgb,var(--ink) 6%,transparent);border-radius:7px;overflow:hidden}
.grid25,.grid50{position:absolute;top:0;bottom:0;width:1px;background:var(--hair)}
.grid25{left:50%}.grid50{left:100%}
.bar{position:absolute;left:0;top:0;bottom:0;border-radius:7px;width:0;
  animation:grow .9s cubic-bezier(.22,.61,.36,1) forwards;animation-delay:calc(var(--i)*70ms)}
.bar.reach.west{background:var(--west-soft)}.bar.reach.east{background:var(--east-soft)}
.bar.champ.west{background:var(--west)}.bar.champ.east{background:var(--east)}
.val{position:absolute;right:8px;top:50%;transform:translateY(-50%);font-size:.74rem;font-weight:700;color:var(--ink)}
.val em{font-style:normal;color:var(--muted);font-weight:600;margin-left:5px;font-size:.66rem;text-transform:uppercase;letter-spacing:.08em}
.champcell{text-align:right;min-width:52px}
.champcell b{font-size:1.15rem;font-weight:800}
.champcell span{display:block;font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}
@keyframes grow{to{width:var(--w)}}
.legend{display:flex;gap:18px;flex-wrap:wrap;margin-top:14px;font-size:.8rem;color:var(--muted)}
.legend i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
/* ---- interactive bracket ---- */
.controls{display:flex;flex-wrap:wrap;align-items:center;gap:10px;margin:0 0 8px}
.ctrl{font-family:inherit;font-size:.82rem;font-weight:700;padding:9px 15px;border-radius:9px;cursor:pointer;
  border:1px solid var(--line);background:var(--card);color:var(--ink);transition:transform .1s,background .15s}
.ctrl:hover{background:color-mix(in srgb,var(--west) 8%,var(--card))}
.ctrl:active{transform:translateY(1px)}
.ctrl.primary{background:var(--west);border-color:var(--west);color:#fff}
.ctrl.primary:hover{filter:brightness(1.06)}
.ctrl:focus-visible{outline:2px solid var(--west);outline-offset:2px}
.status{font-size:.82rem;color:var(--muted);margin:6px 0 22px;min-height:1.2em}
.status b{color:var(--ink)}
.bracket-wrap{overflow-x:auto;padding:4px 2px 10px}
.roundlbls,.bracket{display:grid;grid-template-columns:repeat(4,minmax(150px,1fr));gap:0 22px;min-width:730px}
.roundlbls{margin-bottom:10px}
.roundlbls span{font-size:.68rem;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--muted);text-align:center}
.bracket{grid-template-rows:repeat(8,auto);align-items:center;gap:14px 22px}
.pos-r1-0{grid-column:1;grid-row:1/3}.pos-r1-1{grid-column:1;grid-row:3/5}
.pos-r1-2{grid-column:1;grid-row:5/7}.pos-r1-3{grid-column:1;grid-row:7/9}
.pos-semi-0{grid-column:2;grid-row:2/4}.pos-semi-1{grid-column:2;grid-row:6/8}
.pos-finals{grid-column:3;grid-row:4/6}.pos-champ{grid-column:4;grid-row:4/6}
.match{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden;box-shadow:var(--shadow)}
.slot{display:flex;align-items:center;gap:8px;padding:9px 11px;font-size:.85rem}
.slot+.slot{border-top:1px solid var(--hair)}
.slot .s{width:18px;height:18px;border-radius:5px;background:var(--ink);color:var(--bg);font-size:.64rem;
  font-weight:800;display:grid;place-items:center;flex:none}
.slot.tbd .s{background:var(--line)}
.slot .t{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1}
.slot .w{font-weight:800;color:var(--muted);min-width:12px;text-align:right}
.slot.tbd .t{color:var(--muted);font-weight:500}
.slot.lose{opacity:.45}
.slot.win.cw{background:color-mix(in srgb,var(--west) 12%,transparent)}
.slot.win.cw .w{color:var(--west)}
.slot.win.ce{background:color-mix(in srgb,var(--east) 12%,transparent)}
.slot.win.ce .w{color:var(--east)}
.play{width:100%;border:none;border-top:1px solid var(--hair);background:transparent;color:var(--west);
  font-weight:700;font-size:.68rem;padding:7px;cursor:pointer;letter-spacing:.06em;text-transform:uppercase;font-family:inherit}
.play:hover:not(:disabled){background:color-mix(in srgb,var(--west) 9%,transparent)}
.play:disabled{color:var(--muted);cursor:default;opacity:.45}
.match.done .play{display:none}
.champ-card{align-self:center;text-align:center;padding:16px 14px;border:1px dashed var(--line);border-radius:12px;background:var(--card)}
.champ-card.set{border-style:solid;border-color:var(--west);box-shadow:0 0 0 1px var(--west),var(--shadow)}
.champ-card .lbl{font-size:.62rem;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.champ-card .trophy{font-size:1.8rem;line-height:1.3;filter:grayscale(1) opacity(.4)}
.champ-card.set .trophy{filter:none;animation:pop .5s ease}
.champ-card .cname{font-weight:800;font-size:.98rem;text-wrap:balance}
@keyframes pop{0%{transform:scale(.4);opacity:0}70%{transform:scale(1.15)}100%{transform:scale(1)}}
.reveal{animation:fade .45s ease}
@keyframes fade{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.matchups{list-style:none;padding:0;margin:0;display:flex;flex-direction:column;gap:8px}
.mrow{display:grid;grid-template-columns:minmax(0,1fr) 120px 54px;align-items:center;gap:16px;padding:12px 16px;
  background:var(--card);border:1px solid var(--line);border-radius:10px}
.mrow.top{border-color:var(--west);box-shadow:0 0 0 1px var(--west)}
.mteams{font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mteams i{font-style:normal;color:var(--muted);font-weight:500;padding:0 4px}
.mbarwrap{height:8px;background:color-mix(in srgb,var(--ink) 8%,transparent);border-radius:5px;overflow:hidden}
.mbar{display:block;height:100%;width:var(--w);background:var(--west);border-radius:5px}
.mpct{text-align:right;font-weight:800}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px}
.tile{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:22px 24px;box-shadow:var(--shadow)}
.tile .n{font-size:2.6rem;font-weight:800;letter-spacing:-.03em;line-height:1}
.tile .k{font-size:.9rem;color:var(--muted);margin-top:6px}
.tile.w .n{color:var(--west)}.tile.e .n{color:var(--east)}
.vv{display:flex;flex-direction:column;gap:9px}
.vvrow{display:grid;grid-template-columns:minmax(150px,1.1fr) 2fr 46px;align-items:center;gap:16px;padding:10px 16px;
  border:1px solid var(--line);border-radius:10px;background:var(--card)}
.vvrow.highlight{border-color:var(--west);background:color-mix(in srgb,var(--west) 7%,var(--card))}
.vvname{font-weight:700;font-size:.92rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.vvbars{display:flex;flex-direction:column;gap:4px}
.vvbar{height:15px;width:var(--w);border-radius:4px;min-width:20px;position:relative;display:flex;align-items:center}
.vvbar em{position:absolute;right:6px;font-style:normal;font-size:.66rem;font-weight:700;color:#fff}
.vvbar.model{background:var(--west)}
.vvbar.market{background:color-mix(in srgb,var(--ink) 42%,var(--bg))}
.vvbar.market em{color:var(--bg)}
.vvdiff{text-align:right;font-weight:800;font-size:.9rem}
.vvdiff.pos{color:var(--pos)}.vvdiff.neg{color:var(--neg)}
.vvkey{display:flex;gap:18px;flex-wrap:wrap;font-size:.8rem;color:var(--muted);margin:14px 0 20px}
.vvkey i{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.callout{margin-top:22px;padding:18px 22px;border-left:3px solid var(--west);
  background:color-mix(in srgb,var(--west) 8%,transparent);border-radius:0 10px 10px 0}
.callout b{color:var(--west)}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 26px}
.chip{font-size:.78rem;font-weight:600;padding:6px 12px;border:1px solid var(--line);border-radius:999px;background:var(--card);color:var(--muted)}
.tblwrap{overflow-x:auto;border:1px solid var(--line);border-radius:12px;background:var(--card)}
table{width:100%;border-collapse:collapse;font-size:.92rem;min-width:440px}
th,td{padding:12px 16px;text-align:right;border-top:1px solid var(--hair)}
th:first-child,td:first-child{text-align:left}
thead th{border-top:none;font-size:.72rem;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);font-weight:700}
tbody tr.best td{background:color-mix(in srgb,var(--pos) 9%,transparent);font-weight:700}
.best-tag{color:var(--pos);font-weight:700}
.grid2{display:grid;grid-template-columns:1fr;gap:26px}
@media(min-width:820px){.grid2{grid-template-columns:1fr 1fr}}
figure{margin:0;background:var(--card);border:1px solid var(--line);border-radius:14px;padding:16px;box-shadow:var(--shadow)}
figure img{width:100%;height:auto;border-radius:8px;display:block;background:#fff}
figcaption{color:var(--muted);font-size:.85rem;margin-top:12px}
.limits{list-style:none;padding:0;margin:0;display:grid;gap:12px}
.limits li{padding-left:26px;position:relative;color:var(--ink)}
.limits li::before{content:"";position:absolute;left:2px;top:.62em;width:8px;height:8px;border-radius:2px;
  background:var(--west);transform:rotate(45deg)}
footer{padding:40px 0 60px;color:var(--muted);font-size:.85rem;border-top:1px solid var(--hair)}
footer code{background:color-mix(in srgb,var(--ink) 8%,transparent);padding:2px 7px;border-radius:6px;font-size:.85em}
@media (prefers-reduced-motion:reduce){.bar,.reveal,.champ-card.set .trophy{animation:none;width:var(--w)}}
"""

JS = r"""
const D = window.__WNBA__;
const SEEDS = D.seeds, CONF = D.conf, PROB = D.prob;
const FMT = { R1:[1,0,1], SEMI:[1,1,0,0,1], FINALS:[1,1,0,0,1,0,1] }; // 1 = higher seed hosts
const reduce = matchMedia("(prefers-reduced-motion:reduce)").matches;
const seedIdx = t => SEEDS.indexOf(t);           // 0-based; smaller = higher seed
const pGame = (hi, lo, hiHome) => PROB[hi + "|" + lo + "|" + (hiHome ? 1 : 0)];
let applyAvailability = D.default_model === "injury-adjusted";
function gameProbability(hi,lo,home,next){
  const key=hi+'|'+lo+'|'+(home?1:0);
  if(!applyAvailability) return D.prob_base[key];
  return next && key in D.prob_next ? D.prob_next[key] : D.prob_availability[key];
}

// Simulate one best-of-N series game by game; returns winner + series score.
function simSeries(a, b, fmtKey){
  let hi = a, lo = b;
  if (seedIdx(a) > seedIdx(b)) { hi = b; lo = a; }
  const pat = FMT[fmtKey], need = (pat.length >> 1) + 1;
  const score = D.observed[hi + "|" + lo] || {hw:0,lw:0};
  let hw = score.hw, lw = score.lw;
  let firstUnplayed=true;
  for (const host of pat.slice(hw + lw)){
    if (hw >= need || lw >= need) break;
    if (Math.random() < gameProbability(hi, lo, host === 1, firstUnplayed)) hw++; else lw++;
    firstUnplayed=false;
    if (hw === need || lw === need) break;
  }
  const winner = hw === need ? hi : lo;
  return { winner, hi, lo, hw, lw };
}

// ---- aggregate Monte Carlo (pure, no DOM) ----
function simBracketOnce(){
  const w = [
    simSeries(SEEDS[0], SEEDS[7], "R1").winner,
    simSeries(SEEDS[3], SEEDS[4], "R1").winner,
    simSeries(SEEDS[1], SEEDS[6], "R1").winner,
    simSeries(SEEDS[2], SEEDS[5], "R1").winner,
  ];
  const fTop = simSeries(w[0], w[1], "SEMI").winner;
  const fBot = simSeries(w[2], w[3], "SEMI").winner;
  const champ = simSeries(fTop, fBot, "FINALS").winner;
  return { finalists: [fTop, fBot], champ };
}
function runMany(n){
  const reach = {}, champ = {};
  SEEDS.forEach(t => { reach[t] = 0; champ[t] = 0; });
  for (let i = 0; i < n; i++){
    const r = simBracketOnce();
    reach[r.finalists[0]]++; reach[r.finalists[1]]++; champ[r.champ]++;
  }
  SEEDS.forEach(t => { reach[t] = reach[t] / n * 100; champ[t] = champ[t] / n * 100; });
  return { reach, champ };
}
function updateLeaderboard(agg){
  document.querySelectorAll(".row[data-team]").forEach(row => {
    const t = row.dataset.team, rf = agg.reach[t], ch = agg.champ[t];
    const reachBar = row.querySelector(".bar.reach"), champBar = row.querySelector(".bar.champ");
    [reachBar, champBar].forEach(b => { b.style.animation = "none"; b.style.transition = "width .5s ease"; });
    reachBar.style.width = Math.min(rf / D.reach_scale * 100, 100) + "%";
    champBar.style.width = Math.min(ch / D.reach_scale * 100, 100) + "%";
    row.querySelector(".val b").textContent = Math.round(rf) + "%";
    row.querySelector(".champcell b").textContent = Math.round(ch) + "%";
  });
}

// ---- interactive single bracket ----
const R1 = [[SEEDS[0],SEEDS[7]],[SEEDS[3],SEEDS[4]],[SEEDS[1],SEEDS[6]],[SEEDS[2],SEEDS[5]]];
let st;
function fresh(){ st = { r1:[null,null,null,null], semi:[null,null], finals:null }; }
function teamsFor(node){
  if (node.startsWith("r1-")) return R1[+node.slice(3)];
  if (node === "semi-0") return (st.r1[0] && st.r1[1]) ? [st.r1[0].winner, st.r1[1].winner] : null;
  if (node === "semi-1") return (st.r1[2] && st.r1[3]) ? [st.r1[2].winner, st.r1[3].winner] : null;
  if (node === "finals") return (st.semi[0] && st.semi[1]) ? [st.semi[0].winner, st.semi[1].winner] : null;
}
function resFor(node){
  if (node.startsWith("r1-")) return st.r1[+node.slice(3)];
  if (node === "semi-0") return st.semi[0];
  if (node === "semi-1") return st.semi[1];
  if (node === "finals") return st.finals;
}
function store(node, res){
  if (node.startsWith("r1-")) st.r1[+node.slice(3)] = res;
  else if (node === "semi-0") st.semi[0] = res;
  else if (node === "semi-1") st.semi[1] = res;
  else if (node === "finals") st.finals = res;
}
function fmtFor(node){ return node.startsWith("r1-") ? "R1" : node === "finals" ? "FINALS" : "SEMI"; }
const ORDER = ["r1-0","r1-1","r1-2","r1-3","semi-0","semi-1","finals"];

function paintMatch(node){
  const el = document.getElementById("m-" + node);
  const teams = teamsFor(node), res = resFor(node);
  const slots = el.querySelectorAll(".slot");
  slots.forEach(s => s.className = "slot tbd");
  if (!teams){ slots.forEach((s,k)=>{ s.querySelector(".s").textContent=""; s.querySelector(".t").textContent="—"; s.querySelector(".w").textContent=""; }); }
  else {
    // higher seed on top
    const ordered = teams.slice().sort((a,b)=>seedIdx(a)-seedIdx(b));
    slots.forEach((s,k)=>{
      const tm = ordered[k];
      s.className = "slot";
      s.querySelector(".s").textContent = seedIdx(tm)+1;
      s.querySelector(".t").textContent = tm;
      if (res){
        const wins = tm === res.hi ? res.hw : res.lw;
        s.querySelector(".w").textContent = wins;
        if (tm === res.winner) s.classList.add("win", CONF[tm]==="West"?"cw":"ce");
        else s.classList.add("lose");
      } else {
        const [hi,lo] = ordered, score = D.observed[hi + "|" + lo];
        s.querySelector(".w").textContent = score ? (tm === hi ? score.hw : score.lw) : "";
      }
    });
  }
  const btn = el.querySelector(".play");
  el.classList.toggle("done", !!res);
  if (res){ /* hidden via .done */ }
  else { btn.disabled = !teams; btn.textContent = teams ? "Play series" : "Awaiting teams"; }
}
function paintAll(){ ORDER.forEach(paintMatch); paintChamp(); }
function paintChamp(){
  const card = document.getElementById("champ-card");
  const name = card.querySelector(".cname");
  if (st.finals){ card.classList.add("set"); name.textContent = st.finals.winner;
    card.querySelector(".trophy").classList.add("reveal"); }
  else { card.classList.remove("set"); name.textContent = "—"; }
}
function play(node){
  if (resFor(node)) return;
  const teams = teamsFor(node); if (!teams) return;
  store(node, simSeries(teams[0], teams[1], fmtFor(node)));
  const el = document.getElementById("m-"+node); if (!reduce) el.classList.add("reveal");
  paintAll();
  setStatus();
}
function nextReady(){ return ORDER.find(n => !resFor(n) && teamsFor(n)); }
function autoSim(){
  reset();
  if (reduce){ while (nextReady()) play(nextReady()); return; }
  const step = () => { const n = nextReady(); if (!n) return; play(n); setTimeout(step, 260); };
  step();
}
function reset(){
  fresh();
  for (const node of ORDER){
    const teams = teamsFor(node); if (!teams) continue;
    const [hi,lo] = teams.slice().sort((a,b)=>seedIdx(a)-seedIdx(b));
    const score = D.observed[hi+"|"+lo], need = (FMT[fmtFor(node)].length >> 1) + 1;
    if (score && (score.hw >= need || score.lw >= need)) {
      store(node, {hi,lo,hw:score.hw,lw:score.lw,winner:score.hw>=need?hi:lo});
    }
  }
  paintAll(); setStatus();
}
function setStatus(){
  const s = document.getElementById("bstatus");
  if (st.finals) s.innerHTML = "🏆 <b>" + st.finals.winner + "</b> wins this simulated bracket. Run it again — every play is a fresh draw from the model.";
  else { const n = nextReady(); s.innerHTML = n ? "Completed series are fixed. Click <b>Play series</b> to simulate the remaining games." : "…"; }
}

document.addEventListener("click", e => {
  const b = e.target.closest(".play");
  if (b) play(b.dataset.node);
});
document.getElementById("btn-auto").addEventListener("click", autoSim);
document.getElementById("btn-reset").addEventListener("click", reset);
document.getElementById("btn-many").addEventListener("click", () => {
  const out = document.getElementById("manystatus");
  out.textContent = "Simulating…";
  setTimeout(() => {
    const agg = runMany(10000);
    updateLeaderboard(agg);
    document.getElementById('board-model').textContent='Interactive simulation · '+(applyAvailability?'injury-adjusted (experimental)':'score-only');
    const best = SEEDS.slice().sort((a,b)=>agg.champ[b]-agg.champ[a])[0];
    out.innerHTML = "Updated the leaderboard above from a fresh <b>10,000-run</b> Monte Carlo — top title odds: <b>" +
      best + " " + Math.round(agg.champ[best]) + "%</b>. Model: "+(applyAvailability?'optional injury adjustment (experimental)':'score-only')+". Published forecasts and history stay unchanged.";
  }, 30);
});
reset();
const availabilityToggle=document.getElementById('use-availability');
availabilityToggle.checked=applyAvailability;
if(availabilityToggle) availabilityToggle.checked=applyAvailability;
availabilityToggle?.addEventListener('change',event=>{
  applyAvailability=event.target.checked && Boolean(D.availability.apply_adjustments);
  event.target.checked=applyAvailability;reset();
  updateLeaderboard(D.published_baseline);
  document.getElementById('board-model').textContent='Published '+(D.default_model||'score-only')+' forecast';
  document.getElementById('manystatus').textContent='Interactive games now use '+(applyAvailability?'the injury adjustment (experimental).':'score-only probabilities.')+' Run 10,000× to compare leaderboard odds. Published forecasts and history stay unchanged.';
});
"""

TITLE = f"<title>{season} WNBA Finals Forecast</title>"

BODY = f'''
<div class="hero"><div class="court"></div><div class="wrap hero-inner">
  <div class="hero-grid">
    <div class="hero-copy">
      <span class="eyebrow">{season} WNBA · Playoff Forecast</span>
      <h1>Who wins the title — from {forecast["n_sims"]:,} updated simulations.</h1>
      <div class="pickcard">
        <div><span class="lbl">{forecast["probability_model"]} champion pick</span><span class="big">{favorite.p_champion:.0%}</span></div>
        <div><span class="who">{favorite.team}</span><div class="sub">#{favorite.seed} seed · {favorite.p_reach_finals:.1%} to reach the Finals</div></div>
      </div>
      <p class="foot">Published model: {forecast["probability_model"]}. Score-model validation uses held-out seasons through {season-1}. Injury adjustments require prospective evidence before becoming default. Simulating the real 3-round bracket
        (best-of-3 → 5 → 7). Data through {data_date}. {playoff_status}</p>
    </div>
    <aside class="status-card">
      <div class="label">Automatic data refresh</div>
      <div class="big">{DATA['refresh'].get('schedule_label', 'Daily refresh')}</div>
      <p><a class="team-link" href="#refresh-health" aria-label="Refresh health details"><span class="health-pill" data-health-badge role="status">Checking refresh status</span></a></p>
      <p class="foot">{'Runs in the cloud, even when your computer is off.' if DATA['refresh'].get('scheduler') == 'github_actions' else 'Runs on this computer while Codex is open.'}</p>
      <div class="meta">
        <div><span>Last update</span><strong id="updated-at">--</strong></div>
        <div><span>Next refresh</span><strong id="countdown">24:00:00</strong></div>
        <div><span>Source</span><strong>ESPN public API</strong></div>
      </div>
    </aside>
  </div>
</div></div>

<section id="board"><div class="wrap">
  <span class="eyebrow">The field of eight</span>
  <h2>Probability of reaching the Finals</h2>
  <p class="lead">Each bracket half sends exactly one team to the Finals, so the pale bar is
    the chance a team gets there; the solid inner bar is its chance to win it all.</p>
  <div class="summary-strip">
    <div class="summary-card"><div class="label">Champion favorite</div>
      <div class="value">{favorite.team}</div><div class="sub">{favorite.p_champion:.1%} title probability</div></div>
    <div class="summary-card"><div class="label">Latest completed game</div>
      <div class="value">{data_date}</div><div class="sub">{forecast['completed_playoff_games']} completed playoff games included</div></div>
    <div class="summary-card"><div class="label">Finals pairing</div>
      <div class="value">{matchups[0][0]} vs. {matchups[0][1]}</div>
      <div class="sub">{matchups[0][2]:.1f}% of simulations</div></div>
    <div class="summary-card"><div class="label">Conference split</div>
      <div class="value">{conf['both_west']:.1%} all-West</div>
      <div class="sub">{conf['mixed']:.1%} mixed · {conf['both_east']:.1%} all-East</div></div>
  </div>
  <p class="feature-note" id="board-model" role="status">Published {forecast["probability_model"]} forecast</p>
  <p class="lead"><a class="team-link" href="#availability">View current roster and injury information, plus the optional injury comparison ↓</a></p>
  <div class="board">{rows_html}</div>
  <div class="legend">
    <span><i style="background:var(--west)"></i>West</span>
    <span><i style="background:var(--east)"></i>East</span>
    <span><i style="background:var(--west-soft)"></i>Reach Finals</span>
    <span><i style="background:var(--west)"></i>Win title</span>
    <span>Track = 0–{REACH_SCALE:.0f}%</span>
  </div>
</div></section>

<section id="play"><div class="wrap">
  <div class="section-card">
    <span class="eyebrow">Play it yourself</span>
    <h2>The interactive bracket</h2>
    <p class="lead">Completed playoff results are retained. Remaining games use the model's win
      probabilities — the same engine behind the numbers above. Play one series at a time,
      auto-simulate a full run, or re-run the whole Monte Carlo.</p>
    <div class="controls">
      <button class="ctrl primary" id="btn-auto">▶ Auto-simulate bracket</button>
      <button class="ctrl" id="btn-reset">↺ Reset</button>
      <button class="ctrl" id="btn-many">↻ Run 10,000× → update odds</button>
      <label class="ctrl"><input id="use-availability" type="checkbox" {'checked' if forecast["injury_adjustment_default"] else ''} {'' if player_snapshot.get('apply_adjustments') else 'disabled'}> Use injury adjustments (optional, experimental)</label>
    </div>
    <div class="status" id="bstatus"></div>
    <div class="bracket-wrap">
      <div class="roundlbls"><span>Round 1 · Bo3</span><span>Semifinals · Bo5</span><span>Finals · Bo7</span><span>Champion</span></div>
      <div class="bracket">{bracket_html}</div>
    </div>
    <div class="status" id="manystatus" style="margin-top:14px">Selected model: {forecast["probability_model"]}. Automatic selection follows the prospective evidence rule. This toggle applies to interactive simulations.</div>
  </div>
</div></section>

<section id="matchups"><div class="wrap">
  <span class="eyebrow">Most likely pairings</span>
  <h2>The Finals matchups the model sees most</h2>
  <p class="lead">Pairings reflect the latest standings and all completed playoff results.</p>
  <ul class="matchups">{matchups_html}</ul>
</div></section>

<section id="conf"><div class="wrap">
  <span class="eyebrow">Secondary cut · illustrative only</span>
  <h2>Which conference reaches the Finals?</h2>
  <p class="lead">Conference plays no role in seeding. These probabilities include completed playoff results.</p>
  <div class="tiles">
    <div class="tile w"><div class="n">{conf['both_west']:.1%}</div><div class="k">Both finalists from the West</div></div>
    <div class="tile"><div class="n">{conf['mixed']:.1%}</div><div class="k">Mixed — one West, one East</div></div>
    <div class="tile e"><div class="n">{conf['both_east']:.1%}</div><div class="k">Both finalists from the East</div></div>
  </div>
</div></section>

<section id="market"><div class="wrap">
  <div class="section-card">
    <span class="eyebrow">Sanity check</span>
    <h2>Model vs. the betting market</h2>
    <p class="lead">Championship probability from the refreshed simulation alongside the
      championship futures snapshot returned by ESPN. Check the source status below before comparing.</p>
    <div class="vvkey">
      <span><i style="background:var(--west)"></i>Model (simulation)</span>
      <span><i style="background:color-mix(in srgb,var(--ink) 42%,var(--bg))"></i>Market (ESPN BET)</span>
      <span>Bars scaled 0–{CHAMP_SCALE:.0f}%</span>
    </div>
    <div class="vv">{vv_html}</div>
    <div class="callout">{market_note}</div>
  </div>
</div></section>

<section id="how"><div class="wrap">
  <span class="eyebrow">Under the hood</span>
  <h2>Score-only baseline validation</h2>
  <p class="lead">Every form feature uses only games played <em>before</em> the game it
    describes, and validation splits by time — train on the past, test on the future — so the
    model never peeks ahead.</p>
  <div class="chips">
    <span class="chip">{len(games):,} games · 2016–{season}</span><span class="chip">ESPN public API</span>
    <span class="chip">Point differential</span><span class="chip">Pythagorean expectation</span>
    <span class="chip">Strength of schedule</span><span class="chip">Rest / home-away splits</span>
    <span class="chip">Logistic + gradient boosting</span><span class="chip">{forecast['n_sims']:,}-run Monte Carlo</span>
    <span class="chip">SHAP explanations</span>
  </div>
  <div class="tblwrap"><table>
    <thead><tr><th>Model (held-out {season-2}–{season-1})</th><th>Log-loss ↓</th><th>Brier ↓</th><th>Accuracy</th></tr></thead>
    <tbody>{metrics_html}</tbody></table></div>
  <p class="lead" style="margin-top:14px">Both models beat the "better record" baseline on the
    probability metrics that matter for simulation. The logistic model runs the sim — it's
    naturally symmetric and well-calibrated.</p>
  <div class="grid2" style="margin-top:30px">
    <figure><img src="{shap_img}" alt="SHAP summary of feature importance">
      <figcaption><b>What drives the score-only baseline.</b> The chart compares scoring-based strength,
        point differential, home court, and recent form. Correlated features
        share predictive signal; individual contributions need to be read together.</figcaption></figure>
    <figure><img src="{calib_img}" alt="Calibration plot">
      <figcaption><b>Are the probabilities honest?</b> On held-out seasons, when the model says
        70% the teams really win about 70% of the time — both models hug the diagonal.</figcaption></figure>
  </div>
</div></section>

<section id="limits"><div class="wrap">
  <span class="eyebrow">Reading it fairly</span>
  <h2>What the model can't see</h2>
  <ul class="limits">
    <li><b>Player effects are experimental.</b> Current rosters and reported absences are used conservatively; the availability layer has not been independently calibrated. Uncertain reports do not imply confirmed absences.</li>
    <li><b>Playoff rest is neutralized.</b> The sim doesn't model a team resting after a sweep or grinding through a decisive Game 3.</li>
    <li><b>Seeding tiebreakers are simplified</b> (win% then point differential), not the league's full head-to-head chain before the playoffs. Once available, actual first-round pairings resolve tied seeds.</li>
    <li><b>Completed results are fixed.</b> Only unplayed playoff games are simulated. {playoff_status}</li>
  </ul>
</div></section>

<footer><div class="wrap">
  Built with Python · pandas · scikit-learn · SHAP. Data: ESPN public API, through {forecast['data_through']}.
  Reproduce locally with <code>python run_all.py</code>. Probabilities are model estimates, not
  certainties — and not betting advice.
</div></footer>
'''

CSS += UI.CSS + AVUI.CSS + BT.CSS
BODY = UI.navigation() + BODY.replace('<section id="play">',
    AVUI.overview(player_snapshot,results,forecast["probability_model"]) + BT.section(DATA["backtest"]) + UI.history_section(DATA["history"], favorite.team) + UI.team_directory(profiles) + '<section id="play">')
BODY += LIVE.section(player_snapshot,forecast)
BODY += UI.health_section(DATA["health"])
scripts = ("\n<script>window.__WNBA__=" + data_json + ";</script><script>window.__PLAYER_CONTEXT__=" + LIVE.payload(player_snapshot) + ";</script>\n<script>" + JS + UI.JS + BT.JS + UI.POLL_JS + LIVE.JS + "</script>\n")

# (a) Artifact-format file: no <!doctype>/<html>/<head>/<body> — the Artifact
#     host wraps it in that skeleton itself.
artifact_html = TITLE + "\n<style>" + CSS + "</style>\n" + BODY + scripts
path = os.path.join(OUT, "index.html")
with open(path + ".tmp", "w", encoding="utf-8") as f:
    f.write(artifact_html)
os.replace(path + ".tmp", path)

# (b) Standalone full document for direct hosting (Vercel / any static host):
#     complete <html> shell with charset, mobile viewport, and social-preview
#     tags so the page renders correctly everywhere and previews on LinkedIn.
DESC = (f"Interactive {season} WNBA Finals forecast — a click-through playoff bracket, "
        "a live 10,000-run Monte Carlo, and how the model was built.")
head = (
    '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    f'<meta name="description" content="{DESC}">\n'
    '<meta property="og:type" content="website">\n'
    f'<meta property="og:title" content="{season} WNBA Finals Forecast">\n'
    f'<meta property="og:description" content="{DESC}">\n'
    + TITLE + "\n<style>" + CSS + "</style>\n</head>\n<body>\n"
)
standalone_html = head + BODY + scripts + "\n</body>\n</html>\n"
pub = os.path.join(ROOT, "public")
os.makedirs(pub, exist_ok=True)
pub_path = os.path.join(pub, "index.html")
with open(pub_path + ".tmp", "w", encoding="utf-8") as f:
    f.write(standalone_html)
os.replace(pub_path + ".tmp", pub_path)

print("wrote", path, f"({len(artifact_html)/1024:.0f} KB, Artifact format)")
print("wrote", pub_path, f"({len(standalone_html)/1024:.0f} KB, standalone for Vercel)")
print("prob entries:", len(PROB), "· seeds:", seeds[:3], "...")

summary_rows = "\n".join(
    f"| {r.seed} | {r.team} | {r.p_reach_finals:.1%} | {r.p_champion:.1%} |"
    for r in results.itertuples())
summary = f"""# {season} WNBA forecast — refreshed results

Data through **{data_date}**, retrieved from ESPN. {len(games):,} games across 2016–{season},
including {forecast['completed_playoff_games']} completed {season} playoff games.

**{playoff_status}**

The model gives **{favorite.team} a {favorite.p_champion:.1%} championship probability**.
These estimates retain completed playoff results and simulate only the games still to play,
using {forecast['n_sims']:,} brackets. Eliminated teams cannot advance.

| Seed | Team | Reach Finals | Champion |
|---:|---|---:|---:|
{summary_rows}

The actual first-round pairings resolve tied regular-season seeds once playoffs begin.
Game probabilities come from logistic regression fitted to 2016–{season-1} score-based team form;
validation trains through {season-3} and tests on {season-2}–{season-1}. Validation metrics are in
`outputs/validation_metrics.csv`. These metrics validate the score-only baseline.
Published model: {forecast["probability_model"]}. Automatic selection uses fixed prospective blocks, never the retrospective study.
The optional, experimental player-availability layer uses current ESPN rosters and verified absence
reports, with shrunken participation effects from {season-1}–{season} box scores. It has not been
independently calibrated and has not shown a clear improvement in the historical test.
The interactive toggle starts at the published model choice. Score-only title estimate for {favorite.team}:
{getattr(favorite, 'p_champion_baseline', favorite.p_champion):.1%}.
Player-data status: {player_snapshot.get('message', 'Unavailable; baseline used.')}
Regular-season team-strength features stay fixed during the playoff simulation and playoff
rest differences are neutralized.

Market source status: {market_note}

Run `python run_all.py` to refresh data, forecasts, charts, and the website together.
"""
(ROOT / "SUMMARY.md").write_text(summary, encoding="utf-8")

for folder in ("public", "site"):
    for team in profiles:
        target = ROOT / folder / "teams" / team["slug"] / "index.html"
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name("index.html.tmp")
        temporary.write_text(UI.team_page(team, DATA, CSS, script=UI.JS + UI.POLL_JS, availability=player_snapshot), encoding="utf-8")
        os.replace(temporary, target)
    atomic_json(ROOT / folder / "refresh_health.json", DATA["health"])
atomic_json(history_path, DATA["history"])
print(f"wrote {len(profiles)} team pages; retained {len(DATA['history']['snapshots'])} forecast snapshots")

