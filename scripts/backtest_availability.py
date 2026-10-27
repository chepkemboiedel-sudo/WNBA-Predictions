"""Walk-forward evaluation of the existing absence adjustment, without tuning it.

Uses archived, fixed-time official reports, never today's ESPN injury snapshot.
Models and participation rates use earlier games only. One observation per game.
"""
from __future__ import annotations

import json
import math
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import availability as A
from features import FEATURE_COLS, build_matchup_table
from model import make_logistic

ET=ZoneInfo("America/New_York")
OUT=ROOT/"outputs/availability_backtest"
ABBREVIATIONS={"GS":"GSV","NY":"NYL","LV":"LVA","WSH":"WAS","LA":"LAS","PHO":"PHX","POR":"PDX"}


def normalized(value):
    value=unicodedata.normalize("NFKD",value).encode("ascii","ignore").decode().lower()
    return re.sub(r"[^a-z0-9]","",value)


def name_key(value):
    if "," in value:
        last,first=value.split(",",1)
        value=first+last
    return normalized(value)


def matchup_code(home_abbr,away_abbr):
    return ABBREVIATIONS.get(away_abbr,away_abbr)+"@"+ABBREVIATIONS.get(home_abbr,home_abbr)


def report_for(tip,reports):
    local=tip.astimezone(ET)
    hour=9 if local.hour<16 else 15
    selected=local.replace(hour=hour,minute=0,second=0,microsecond=0)
    if tip-selected<timedelta(hours=1):
        return None
    report=reports.get(selected.isoformat())
    if report and datetime.fromisoformat(report["published_at"])>tip-timedelta(hours=1):
        raise AssertionError("Report was not available at the prediction cutoff")
    return report


def team_penalty(team,report,game,prior_games,prior_boxes,effects):
    """Only uniquely matched reported Out players contribute; no future roster."""
    played=prior_boxes[(prior_boxes.team==team)&~prior_boxes.is_playoff&(prior_boxes.season==2026)&(prior_boxes.minutes>0)]
    expected=prior_games[(prior_games.season==2026)&~prior_games.is_playoff&((prior_games.home_team==team)|(prior_games.away_team==team))]
    team_boxes=prior_boxes[(prior_boxes.team==team)&(prior_boxes.season==2026)&~prior_boxes.is_playoff]
    complete=set(expected.game_id.astype(str)).issubset(set(team_boxes.game_id))
    known={}
    for player in prior_boxes[["player_id","player"]].drop_duplicates().itertuples():
        known.setdefault(name_key(player.player),set()).add(player.player_id)
    game_date=game["local_date"]
    matchup=game["matchup"]
    records=[p for p in report["players"] if p["date"]==game_date and p["matchup"]==matchup and normalized(p["team"])==normalized(team)]
    penalty=0.0
    details=[]
    for player in records:
        if player["status"] not in ("Out","Suspended"):
            continue
        matches=known.get(name_key(player["player"]),set())
        aid=next(iter(matches)) if len(matches)==1 else None
        fraction=played[played.player_id==aid].game_id.nunique()/len(expected) if len(expected) else 0
        effect=effects.get(aid,0)
        amount=A.absence_penalty(effect,fraction) if complete else 0.0
        penalty+=amount
        details.append({"name":player["player"],"id":aid,"effect":effect,"prior_participation":fraction,"penalty":amount})
    return -min(A.MAX_TEAM_POINTS,penalty),details,complete


def history_before(games,boxes,cutoff):
    """Strict date cutoff: current-day and future outcomes cannot affect inputs."""
    cutoff=pd.Timestamp(cutoff)
    return games[games.date<cutoff].copy(),boxes[boxes.date<cutoff].copy()


def losses(y,p):
    p=np.clip(np.asarray(p,float),1e-12,1-1e-12)
    y=np.asarray(y,int)
    return {"log_loss":-(y*np.log(p)+(1-y)*np.log1p(-p)),"brier":(p-y)**2,"accuracy":((p>=.5)==y).astype(float)}


def score(rows,bootstrap=10000):
    if rows.empty:
        return {"n":0}
    baseline=losses(rows.home_win,rows.p_baseline)
    adjusted=losses(rows.home_win,rows.p_adjusted)
    result={"n":len(rows),"days":rows.local_date.nunique(),"changed_games":int((abs(rows.p_adjusted-rows.p_baseline)>1e-10).sum()),"metrics":{}}
    improved=int(((adjusted["accuracy"]==1)&(baseline["accuracy"]==0)).sum())
    worsened=int(((adjusted["accuracy"]==0)&(baseline["accuracy"]==1)).sum())
    discordant=improved+worsened
    pvalue=min(1.0,2*sum(math.comb(discordant,k) for k in range(min(improved,worsened)+1))/2**discordant) if discordant else 1.0
    result["winner_changes"]={"corrected":improved,"harmed":worsened,"mcnemar_exact_p":pvalue}
    days=sorted(rows.local_date.unique())
    day_idx={day:i for i,day in enumerate(days)}
    clusters=np.array([day_idx[day] for day in rows.local_date])
    counts=np.bincount(clusters,minlength=len(days))
    draws=np.random.default_rng(20261027).integers(0,len(days),size=(bootstrap,len(days)))
    for metric in baseline:
        differences=adjusted[metric]-baseline[metric]
        totals=np.bincount(clusters,weights=differences,minlength=len(days))
        sample=totals[draws].sum(axis=1)/counts[draws].sum(axis=1)
        result["metrics"][metric]={"baseline":float(baseline[metric].mean()),"adjusted":float(adjusted[metric].mean()),"delta":float(differences.mean()),"delta_ci95":[float(v) for v in np.quantile(sample,[.025,.975])]}
    return result


def run(*, append_only=False, destination=None):
    output=Path(destination) if destination is not None else OUT
    old_summary=json.loads((output/"results.json").read_text(encoding="utf-8")) if append_only and (output/"results.json").exists() else {}
    retained=pd.read_csv(output/"predictions.csv",dtype={"game_id":str},float_precision="round_trip") if old_summary else pd.DataFrame()
    if not retained.empty:
        retained["player_details"]=retained.player_details.map(json.loads)
        retained["fallback_reason"]=retained.fallback_reason.fillna("")
    games=pd.read_csv(ROOT/"data/all_games.csv",dtype={"game_id":str},parse_dates=["date"])
    boxes=pd.read_csv(ROOT/"data/player_game_stats.csv",dtype={"game_id":str,"player_id":str},parse_dates=["date"])
    manifest=json.loads((ROOT/"data/backtests/injury_report_manifest.json").read_text(encoding="utf-8"))
    reports={r["published_at"]:r for r in manifest["reports"] if r["status"]==200}
    matchups=build_matchup_table(games)
    training=matchups[matchups.season<=2025]
    test=matchups[(matchups.season==2026)&(matchups.home==1)].copy().sort_values(["date","game_id"])
    if not retained.empty:
        test=test[~test.game_id.astype(str).isin(set(retained.game_id))]
    if test.empty and old_summary:
        return old_summary,retained
    baseline=make_logistic().fit(training[FEATURE_COLS],training.target)
    test["p_baseline"]=baseline.predict_proba(test[FEATURE_COLS])[:,1]
    tips=boxes.drop_duplicates("game_id").set_index("game_id").started_at.to_dict()
    originals=games.set_index("game_id")
    models={}
    predictions=retained.to_dict("records") if not retained.empty else []
    for row in test.itertuples():
        tip=datetime.fromisoformat(tips[row.game_id].replace("Z","+00:00")) if row.game_id in tips else None
        month=pd.Timestamp(row.date).to_period("M").start_time
        if month not in models:
            earlier_games,earlier_boxes=history_before(games,boxes,month)
            effects,model=A.fit_effects(earlier_games,earlier_boxes)
            models[month]=(effects,model)
            print(f"Player fit before {month.date()}: {model['training_games']} earlier regular-season games",flush=True)
        effects,model=models[month]
        actual=originals.loc[row.game_id]
        matchup=matchup_code(actual.home_abbr,actual.away_abbr)
        report=report_for(tip,reports) if tip else None
        local_date=tip.astimezone(ET).date().isoformat() if tip else str(row.date)[:10]
        result={"game_id":row.game_id,"date":str(row.date)[:10],"local_date":local_date,"home":row.team,"away":row.opp,"is_playoff":row.is_playoff,"home_win":row.target,"p_baseline":row.p_baseline,"p_adjusted":row.p_baseline,"report_covered":False,"fallback_reason":"No verified fixed-time report" if tip else "Game start time unavailable","report_url":report["url"] if report else None,"report_published_at":report["published_at"] if report else None,"tip":tip.isoformat() if tip else None,"player_fit_before":str(month.date()),"player_training_games":model["training_games"],"home_penalty":0.0,"away_penalty":0.0,"out_count":0,"unmatched_out":0,"player_details":[]}
        if report:
            submitted={normalized(t["team"]) for t in report["teams"] if t["date"]==local_date and t["matchup"]==matchup and t["submitted"]}
            if {normalized(row.team),normalized(row.opp)}.issubset(submitted):
                # Date-only game logs: exclude the entire report's UTC date.
                # This conservatively omits any earlier game on that UTC date.
                cutoff=pd.Timestamp(datetime.fromisoformat(report["published_at"]).astimezone(ZoneInfo("UTC")).date())
                prior_games,prior_boxes=history_before(games,boxes,cutoff)
                context={"local_date":local_date,"matchup":matchup}
                hs,hd,hc=team_penalty(row.team,report,context,prior_games,prior_boxes,effects)
                aws,ad,ac=team_penalty(row.opp,report,context,prior_games,prior_boxes,effects)
                details=hd+ad
                result.update(report_covered=True,fallback_reason="" if hc and ac else "Incomplete prior team player archive; affected side keeps baseline strength",home_penalty=hs,away_penalty=aws,out_count=len(details),unmatched_out=sum(p["id"] is None for p in details),player_details=details)
                result["p_adjusted"]=A.adjust_probability(row.p_baseline,hs,aws,model["margin_logit_coefficient"])
            else:
                result["fallback_reason"]="Both teams not explicitly submitted in the selected report"
        predictions.append(result)
    frame=pd.DataFrame(predictions)
    if frame.game_id.duplicated().any():
        raise AssertionError("A held-out game was counted more than once")
    groups={"all_eligible_games":frame,"verified_report_games":frame[frame.report_covered],"verified_reports_with_out":frame[frame.report_covered&(frame.out_count>0)],"changed_games":frame[abs(frame.p_adjusted-frame.p_baseline)>1e-10],"regular_season":frame[frame.report_covered&~frame.is_playoff],"playoffs":frame[frame.report_covered&frame.is_playoff]}
    results={name:score(rows) for name,rows in groups.items()}
    summary={"version":1,"created_at":datetime.now(ZoneInfo("UTC")).isoformat(),"primary_comparison":"verified_report_games","test_season":2026,"baseline_train_seasons":[2016,2025],"player_fits":[{"before":str(k.date()),**v[1]} for k,v in models.items()],"report_policy":manifest["policy"],"report_files_requested":len(manifest["reports"]),"report_files_verified":len(reports),"report_failures":[r for r in manifest["reports"] if r["status"]!=200],"fallback_counts":dict(Counter(frame.loc[~frame.report_covered,"fallback_reason"])),"out_records":int(frame.out_count.sum()),"unmatched_out_records":int(frame.unmatched_out.sum()),"incomplete_team_history_games":int((frame.report_covered&(frame.fallback_reason!="")).sum()),"groups":results,"by_month":{str(month):score(rows,bootstrap=2000) for month,rows in frame[frame.report_covered].groupby(frame.date.str[:7])}}
    if old_summary:
        fits={f["before"]:f for f in old_summary.get("player_fits",[])}
        fits.update({f["before"]:f for f in summary["player_fits"]})
        summary["player_fits"]=list(fits.values())
    output.mkdir(parents=True,exist_ok=True)
    (output/"results.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    frame.assign(player_details=frame.player_details.map(json.dumps)).to_csv(output/"predictions.csv",index=False)
    for name,result in results.items():
        print(name,json.dumps(result),flush=True)
    write_report(summary,frame,destination=output)
    return summary,frame


def write_report(summary,frame,*,destination=None):
    output=Path(destination) if destination is not None else OUT
    primary=summary["groups"]["verified_report_games"]
    probability_scores=[primary["metrics"][name] for name in ("log_loss","brier")]
    clear_improvement=all(m["delta_ci95"][1]<0 for m in probability_scores)
    conclusion="The probability scores show an improvement in this sample; broader prospective validation is still required." if clear_improvement else "The test does not establish an improvement in prediction quality."
    description=f"Winner accuracy changed by {primary['metrics']['accuracy']['delta']*100:+.2f} percentage points. Log-loss changed by {probability_scores[0]['delta']:+.6f} and Brier score by {probability_scores[1]['delta']:+.6f}."
    if all(m["delta_ci95"][0]<=0<=m["delta_ci95"][1] for m in probability_scores):
        description+=" Both probability-score uncertainty intervals include zero."
    lines=["# Historical injury-adjustment test","",conclusion+" "+description,"", "## Results", "",f"Primary comparison: {primary['n']} held-out 2026 games with an explicitly submitted report for both teams. Lower log-loss and Brier score are better; higher winner accuracy is better.","", "| Metric | Score-only | With absence adjustment | Change (adjusted minus baseline) | 95% interval for change |", "|---|---:|---:|---:|---:|"]
    for name,metric in primary["metrics"].items():
        lo,hi=metric["delta_ci95"]
        if name=="accuracy":
            values=[f"{metric['baseline']:.2%}",f"{metric['adjusted']:.2%}",f"{metric['delta']*100:+.2f} pp",f"{lo*100:+.2f} to {hi*100:+.2f} pp"]
        else:
            values=[f"{metric['baseline']:.6f}",f"{metric['adjusted']:.6f}",f"{metric['delta']:+.6f}",f"{lo:+.6f} to {hi:+.6f}"]
        lines.append("| "+name.replace("_"," ")+" | "+" | ".join(values)+" |")
    changes=primary["winner_changes"]
    lines += ["",f"The adjustment corrected {changes['corrected']} winner picks and harmed {changes['harmed']}; two-sided exact McNemar p = {changes['mcnemar_exact_p']:.3f}. Intervals use 10,000 paired bootstrap resamples of game days, keeping games played on the same day together. They are approximate, conditional on the fitted models, and do not establish generalization to future seasons.","", "## Additional comparisons","", "| Sample | Games | Changed probabilities | Baseline accuracy | Adjusted accuracy | Log-loss change | Brier change |", "|---|---:|---:|---:|---:|---:|---:|"]
    for name,result in summary["groups"].items():
        if not result["n"]:
            continue
        m=result["metrics"]
        lines.append(f"| {name.replace('_',' ')} | {result['n']} | {result['changed_games']} | {m['accuracy']['baseline']:.2%} | {m['accuracy']['adjusted']:.2%} | {m['log_loss']['delta']:+.6f} | {m['brier']['delta']:+.6f} |")
    lines += ["", "## Method and safeguards","", "- Score-only logistic regression is fitted on 2016-2025 games. Held-out games are in 2026; early games lacking the existing feature minimum are excluded. Each game contributes once, from the home team's perspective.","- Player effects are refitted at the start of each month using only preceding games, including 2025 box scores and earlier 2026 regular-season games. The existing ridge penalty, positive-effect clipping, participation discount, probability mapping, and player/team caps are retained without tuning to these results.","- Official report selection is fixed before scoring: 09:00 ET for games tipping before 16:00 ET, otherwise 15:00 ET, with at least one hour before tip. Eastern dates are derived from recorded scheduled game timestamps, not UTC game-log dates.","- Both teams must be explicitly submitted for the exact date and matchup. Missing, unsubmitted, malformed, or wrong-league reports produce the score-only fallback. An omitted team is not inferred to be healthy. This conservative rule makes the covered subset unrepresentative of the whole league.","- Only Out/Suspended records trigger an absence. Doubtful, Questionable, Probable, and Available do not. Each game uses its own report; no report is carried into subsequent games.","- Report names are normalized and matched uniquely to athlete IDs seen in earlier box scores. Current rosters, today's ESPN statuses, future aliases, future participation, and the test game's box-score statistics are not prediction inputs. The scheduled start timestamp is the only field taken from the held-out game's box-score record.","- Prior participation and team archive completeness use games strictly before the report's UTC calendar date, conservatively omitting earlier games on that date. Incomplete prior player history disables that team's penalty. Training folds exclude the entire test month and all later dates.","", "## Coverage and limits","",f"- {summary['report_files_verified']} of {summary['report_files_requested']} fixed-time report files passed validation. Five URLs returned documents containing non-WNBA teams; two returned HTTP 403.",f"- Of {summary['groups']['all_eligible_games']['n']} eligible 2026 games, {primary['n']} had both-team report coverage. The remaining games use the same baseline in both comparisons. Only {summary['groups']['playoffs']['n']} covered games are playoff games, which is too small to validate championship forecasts.",f"- {summary['out_records']} Out/Suspended player-game records were considered; {summary['unmatched_out_records']} could not be matched to a unique previously seen athlete and received no invented effect. {summary['incomplete_team_history_games']} covered games had an incomplete prior archive for at least one side; that side retained baseline strength.","- This tests the existing numerical adjustment with independently archived official statuses. It does not recreate historical ESPN fetches, roster snapshots, feed delays, return-date fields, or the full season-long-report propagation logic. Those were not archived. It therefore does not certify the complete live injury pipeline.","- Historical game probabilities use the model's pregame running-form features, which include earlier playoff games. Production bracket simulations use a fixed regular-season form snapshot and neutral rest. These are not a direct backtest of series or championship probabilities.","- Test outcomes influenced neither report-time selection nor hyperparameter selection. The model was not retuned or promoted after viewing these results. The report-covered subset is selected by data availability, so its accuracy must not be compared directly with the all-games accuracy as if model quality changed.","", "## Reproduce","", "1. Use the bundled PDF Python runtime (pdfplumber required) to run `python scripts/collect_historical_injuries.py`. It downloads archived PDFs into `tmp/pdfs/historical_injuries/` and writes dated, hashed records plus the manifest under `data/backtests/`.","2. Run `.venv/Scripts/python.exe -X utf8 scripts/backtest_availability.py`. It uses the manifest and existing game/player caches; no network access or live forecast rebuild is required.","3. Inspect `predictions.csv` for every game, selected report URL/timestamp, model cutoff, fallback reason, probability pair, and per-player treatment. `results.json` includes monthly fits, subgroups, and uncertainty intervals.","", "Sources: [Official WNBA injury reporting rules](https://www.wnba.com/wnba-injury-report). Every downloaded report's exact source URL and SHA-256 are recorded in `data/backtests/injury_report_manifest.json`.","", "Recommendation: retain the experimental label. These results do not justify claiming better accuracy. Collect prospective ESPN report/roster snapshots and evaluate a larger untouched sample before promoting or retuning the live adjustment.",""]
    (output/"REPORT.md").write_text("\n".join(lines),encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4.5))
    for ax,name,title in zip(axes,["log_loss","brier"],["Log-loss change","Brier score change"]):
        labels=["All eligible games","Verified reports","Changed probabilities"]
        keys=["all_eligible_games","verified_report_games","changed_games"]
        for i,key in enumerate(keys):
            m=summary["groups"][key]["metrics"][name]
            lo,hi=m["delta_ci95"]
            ax.errorbar(m["delta"],i,xerr=[[m["delta"]-lo],[hi-m["delta"]]],fmt="o",color="#d45a24",capsize=4)
        ax.axvline(0,color="#34465a",linestyle="--",linewidth=1)
        ax.set_yticks(range(3),labels)
        ax.invert_yaxis()
        ax.set_title(title)
        ax.set_xlabel("Adjusted minus baseline (left is better)")
        ax.grid(axis="x",alpha=.18)
    fig.suptitle("Historical injury-adjustment test" if clear_improvement else "No clear improvement from the injury adjustment",fontweight="bold")
    fig.text(.5,.015,"2026 held-out games; 95% paired game-day bootstrap intervals. Negative changes favor the adjustment.",ha="center",fontsize=9)
    fig.tight_layout(rect=(0,.05,1,.93))
    fig.savefig(output/"comparison.png",dpi=160)
    plt.close(fig)


if __name__=="__main__":
    run()

